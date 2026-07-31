"""Mininet diamond topology + a runner that applies OVS commands and probes.

No SDN controller. The diamond holds a loop, so switches run in secure mode and
the bench installs the base forwarding rules itself, pinning the default path
through s2. Static ARP removes broadcast entirely, which makes the data plane
deterministic and removes the MAC-learning settle delay the linear topology
needed.

Imported only inside the Lima VM (needs mininet). Never import from unit tests.
"""
from __future__ import annotations

import re

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo

from bench.verbs.base import OvsCommand

BASE_FLOW_PRIORITY = 100

# Capacity cap on the core link, so bandwidth_min has contention to survive.
_CORE_MBPS = 10

_HOSTS = {
    "h1": "00:00:00:00:00:01",
    "h2": "00:00:00:00:00:02",
    "h3": "00:00:00:00:00:03",
    "h4": "00:00:00:00:00:04",
}

# Which edge switch each host hangs off, and the far-side edge for the others.
_HOST_SWITCH = {"h1": "s1", "h2": "s1", "h3": "s4", "h4": "s4"}


class TopologyError(ValueError):
    """Raised when an unknown topology name is requested."""


class _Diamond4(Topo):
    """h1,h2-s1 = s2/s3 = s4-h3,h4. Two paths, so reroute is observable."""

    def build(self):
        s1, s2, s3, s4 = (self.addSwitch(n) for n in ("s1", "s2", "s3", "s4"))
        for name, mac in _HOSTS.items():
            host = self.addHost(name, mac=mac)
            self.addLink(host, _HOST_SWITCH[name])
        self.addLink(s1, s2)
        self.addLink(s2, s4, cls=TCLink, bw=_CORE_MBPS)
        self.addLink(s1, s3)
        self.addLink(s3, s4)


_TOPOS = {"diamond4": _Diamond4}


def _port_to(net, switch: str, peer: str) -> int:
    """OpenFlow port number on ``switch`` facing node ``peer``."""
    sw = net.get(switch)
    for intf in sw.intfList():
        if intf.link is None:
            continue
        other = (intf.link.intf2 if intf.link.intf1 is intf else intf.link.intf1)
        if other.node.name == peer:
            return sw.ports[intf]
    raise TopologyError(f"no link between {switch} and {peer}")


def _install_base_flows(net) -> None:
    """Unicast forwarding by destination MAC, default path through s2."""
    routes = {
        "s1": {"h1": "h1", "h2": "h2", "h3": "s2", "h4": "s2"},
        "s2": {"h1": "s1", "h2": "s1", "h3": "s4", "h4": "s4"},
        "s3": {"h1": "s1", "h2": "s1", "h3": "s4", "h4": "s4"},
        "s4": {"h1": "s2", "h2": "s2", "h3": "h3", "h4": "h4"},
    }
    for switch, table in routes.items():
        sw = net.get(switch)
        for host, nexthop in table.items():
            port = _port_to(net, switch, nexthop)
            sw.cmd(
                f"ovs-ofctl add-flow {switch} "
                f"'priority={BASE_FLOW_PRIORITY},dl_dst={_HOSTS[host]},"
                f"actions=output:{port}'"
            )


def build_topology(name: str) -> Mininet:
    """Start a controller-less Mininet in secure mode with base flows."""
    if name not in _TOPOS:
        raise TopologyError(f"unknown topology {name!r}")
    net = Mininet(topo=_TOPOS[name](), switch=OVSSwitch, controller=None,
                  link=TCLink, waitConnected=False)
    net.start()
    for sw in net.switches:
        sw.cmd(f"ovs-vsctl set-fail-mode {sw.name} secure")
    net.staticArp()
    _install_base_flows(net)
    return net


class MininetRunner:
    """Applies OvsCommands on the running network and probes the data plane."""

    def __init__(self, net: Mininet) -> None:
        self._net = net

    # --- realisation -----------------------------------------------------

    def _expand(self, command: str, switch: str) -> str:
        """Substitute {switch}, {swport:<host>} and {swport_to:<switch>}."""
        out = command.replace("{switch}", switch)
        for host in re.findall(r"\{swport:(\w+)\}", out):
            intf = self._net.get(host).defaultIntf()
            link = intf.link
            sw_intf = link.intf2 if link.intf1 is intf else link.intf1
            out = out.replace(f"{{swport:{host}}}", sw_intf.name)
        for peer in re.findall(r"\{swport_to:(\w+)\}", out):
            out = out.replace(f"{{swport_to:{peer}}}", str(_port_to(self._net, switch, peer)))
        return out

    def warmup(self) -> None:
        self._net.pingAll()

    def apply(self, commands) -> None:
        for cmd in commands:
            targets = ([s.name for s in self._net.switches]
                       if cmd.target == "all" else [cmd.target])
            for switch in targets:
                self._net.get(switch).cmd(self._expand(cmd.command, switch))

    # --- probes ----------------------------------------------------------

    def ping(self, src_host: str, dst_host: str) -> str:
        src, dst = self._net.get(src_host), self._net.get(dst_host)
        return src.cmd(f"ping -c 3 -W 1 {dst.IP()}")

    def iperf(self, src_host: str, dst_host: str, port=None, seconds: int = 5) -> str:
        server, client = self._net.get(dst_host), self._net.get(src_host)
        flag = f"-p {port}" if port is not None else ""
        server.cmd(f"iperf -s -D {flag}")
        out = client.cmd(f"iperf -c {server.IP()} -t {seconds} {flag}")
        server.cmd("kill %iperf")
        return out

    def iperf_contended(self, src_host, dst_host, contender_src, contender_dst,
                        seconds: int = 5) -> str:
        """Measure the protected flow while a competing flow saturates the core."""
        noise_srv = self._net.get(contender_dst)
        noise_cli = self._net.get(contender_src)
        noise_srv.cmd("iperf -s -D -p 5002")
        noise_cli.cmd(f"iperf -c {noise_srv.IP()} -p 5002 -t {seconds + 2} &")
        out = self.iperf(src_host, dst_host, seconds=seconds)
        noise_srv.cmd("kill %iperf")
        return out

    def tcpdump_count(self, probe_host: str, seconds: int = 3) -> int:
        probe = self._net.get(probe_host)
        probe.cmd(f"timeout {seconds} tcpdump -i {probe.defaultIntf().name} "
                  f"-c 100 -w /tmp/mirror.pcap &")
        self.ping("h1", "h3")
        out = probe.cmd("tcpdump -r /tmp/mirror.pcap 2>/dev/null | wc -l")
        try:
            return int(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 0

    def flow_packets(self, switch: str, dl_src: str, dl_dst: str) -> int:
        sw = self._net.get(switch)
        out = sw.cmd(f"ovs-ofctl dump-flows {switch}")
        total = 0
        for line in out.splitlines():
            if dl_src in line and dl_dst in line:
                m = re.search(r"n_packets=(\d+)", line)
                if m:
                    total += int(m.group(1))
        return total

    def tos_of(self, src_host: str, dst_host: str) -> int:
        dst = self._net.get(dst_host)
        dst.cmd(f"timeout 4 tcpdump -i {dst.defaultIntf().name} -v -c 1 icmp "
                f"> /tmp/tos.txt 2>&1 &")
        self.ping(src_host, dst_host)
        out = dst.cmd("cat /tmp/tos.txt")
        m = re.search(r"tos 0x([0-9a-fA-F]+)", out)
        return int(m.group(1), 16) if m else 0

    def stop(self) -> None:
        self._net.stop()
