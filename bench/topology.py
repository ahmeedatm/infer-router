"""Mininet diamond topology + a runner that applies OVS commands and probes.

No SDN controller. The diamond holds a loop, so switches run in secure mode and
the bench installs the base forwarding rules itself, pinning the default path
through s2. Static ARP removes broadcast entirely, which makes the data plane
deterministic and removes the MAC-learning settle delay the linear topology
needed.

Imported only inside the Lima VM (needs mininet). Never import from unit tests.
"""
from __future__ import annotations

import itertools
import re

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo

from bench.apply_result import ApplyError, raise_if_failed  # noqa: F401
from bench.verbs.base import OvsCommand

BASE_FLOW_PRIORITY = 100

# Seconds of slack on top of an iperf run before the client is killed. Without
# it a correctly blocked port stalls the whole run on TCP SYN retries (~127 s
# per call, ~30 minutes across the campaign) instead of reading as 0 Mbps.
IPERF_GRACE_S = 5

# Port and overrun of the competing flow in ``iperf_contended``. The noise must
# outlive the measurement window it is meant to contend with, and must then be
# killed, or it bleeds into the next check of the same case.
NOISE_PORT = 5002
NOISE_OVERRUN_S = 2

_UNSAFE_TAG = re.compile(r"[^A-Za-z0-9_.-]")

# Capacity cap on the core link, so bandwidth_min has contention to survive.
_CORE_MBPS = 10

_HOSTS = {
    "h1": "00:00:00:00:00:01",
    "h2": "00:00:00:00:00:02",
    "h3": "00:00:00:00:00:03",
    "h4": "00:00:00:00:00:04",
}

# Which edge switch each host hangs off, and the far-side edge for the others.
# h4 is the mirror probe host: it sits on s1 alongside h1/h2, the natural
# mirror sources, because an OVS mirror is bridge-scoped -- the selected
# source port and the output port must live on the same switch.
_HOST_SWITCH = {"h1": "s1", "h2": "s1", "h4": "s1", "h3": "s4"}


class TopologyError(ValueError):
    """Raised when an unknown topology name is requested."""


class _Diamond4(Topo):
    """h1,h2,h4-s1 = s2/s3 = s4-h3. Two paths, so reroute is observable."""

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
    """Unicast forwarding by destination MAC, default path through s2.

    A rejection here breaks every case at once and is invisible without
    reading the output, so it raises like any other rejected command.
    """
    routes = {
        "s1": {"h1": "h1", "h2": "h2", "h4": "h4", "h3": "s2"},
        "s2": {"h1": "s1", "h2": "s1", "h4": "s1", "h3": "s4"},
        "s3": {"h1": "s1", "h2": "s1", "h4": "s1", "h3": "s4"},
        "s4": {"h1": "s2", "h2": "s2", "h4": "s2", "h3": "h3"},
    }
    for switch, table in routes.items():
        sw = net.get(switch)
        for host, nexthop in table.items():
            port = _port_to(net, switch, nexthop)
            command = (
                f"ovs-ofctl add-flow {switch} "
                f"'priority={BASE_FLOW_PRIORITY},dl_dst={_HOSTS[host]},"
                f"actions=output:{port}'"
            )
            raise_if_failed(switch, command, sw.cmd(command))


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
        self._applied: list[tuple[str, str]] = []
        self._capture_seq = itertools.count(1)

    @property
    def applied(self) -> tuple[tuple[str, str], ...]:
        """Every (switch, expanded command) this runner has issued, in order.

        A failed case is otherwise undiagnosable: the plan says what was
        asked for, this says what actually reached the switches.
        """
        return tuple(self._applied)

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
        """Run each command on its target switch, raising on any rejection.

        ``Node.cmd`` has no exit status, so the combined output is inspected
        instead (see :mod:`bench.apply_result`). Silently discarding it made
        every rejected rule look like a model that simply did not ask for the
        behaviour: the rule was never installed, the check failed, and the
        model was charged for a bench problem.
        """
        for cmd in commands:
            targets = ([s.name for s in self._net.switches]
                       if cmd.target == "all" else [cmd.target])
            for switch in targets:
                expanded = self._expand(cmd.command, switch)
                self._applied.append((switch, expanded))
                raise_if_failed(switch, expanded,
                                self._net.get(switch).cmd(expanded))

    # --- probes ----------------------------------------------------------

    def ping(self, src_host: str, dst_host: str) -> str:
        src, dst = self._net.get(src_host), self._net.get(dst_host)
        return src.cmd(f"ping -c 3 -W 1 {dst.IP()}")

    def iperf(self, src_host: str, dst_host: str, port=None, seconds: int = 5) -> str:
        """Measure throughput; a refused port must read as 0, not as a stall.

        The client carries a ``timeout`` because a correctly blocked port
        leaves iperf retrying the TCP SYN for roughly two minutes. That is a
        successful block, so it must cost one measurement window, not the
        campaign's schedule.
        """
        server, client = self._net.get(dst_host), self._net.get(src_host)
        flag = f"-p {port}" if port is not None else ""
        server.cmd(f"iperf -s -D {flag}")
        out = client.cmd(f"timeout {seconds + IPERF_GRACE_S} "
                         f"iperf -c {server.IP()} -t {seconds} {flag}")
        server.cmd("kill %iperf")
        return out

    def iperf_contended(self, src_host, dst_host, contender_src, contender_dst,
                        seconds: int = 5) -> str:
        """Measure the protected flow while a competing flow saturates the core.

        The noise flow deliberately outlives the measurement window, so it has
        to be killed here: left running, it keeps loading the core link during
        the next check of the same case and corrupts that measurement too.
        """
        noise_srv = self._net.get(contender_dst)
        noise_cli = self._net.get(contender_src)
        noise_srv.cmd(f"iperf -s -D -p {NOISE_PORT}")
        noise_cli.cmd(
            f"timeout {seconds + NOISE_OVERRUN_S + IPERF_GRACE_S} "
            f"iperf -c {noise_srv.IP()} -p {NOISE_PORT} "
            f"-t {seconds + NOISE_OVERRUN_S} &"
        )
        try:
            return self.iperf(src_host, dst_host, seconds=seconds)
        finally:
            # Matched on the noise port, which the protected flow never uses.
            noise_cli.cmd(f"pkill -f 'iperf -c .* -p {NOISE_PORT}'")
            noise_srv.cmd(f"pkill -f 'iperf -s -D -p {NOISE_PORT}'")

    def tcpdump_count(self, probe_host: str, src_host: str, dst_host: str,
                       seconds: int = 3, tag: str = "case") -> int:
        """Count packets seen on the probe while ``src_host`` pings ``dst_host``.

        The traffic generated must be the traffic the mirror actually taps,
        so the caller supplies the intent's own endpoints rather than a
        hardcoded pair.

        Two details decide whether this measures anything. ``-U`` makes
        tcpdump flush each packet instead of block-buffering, and the capture
        window is waited out before the file is read: read while the writer
        still holds it, a mirror that worked can count 0. The file name
        carries the case's tag because Mininet hosts share ``/tmp`` with the
        VM, so a fixed path lets one case read the previous case's packets.
        """
        probe = self._net.get(probe_host)
        pcap = (f"/tmp/mirror-{_UNSAFE_TAG.sub('_', tag)}-"
                f"{next(self._capture_seq)}.pcap")
        probe.cmd(f"rm -f {pcap}")
        probe.cmd(f"timeout {seconds} tcpdump -i {probe.defaultIntf().name} "
                  f"-U -c 100 -w {pcap} 2>/dev/null &")
        self.ping(src_host, dst_host)
        probe.cmd("wait")
        out = probe.cmd(f"tcpdump -r {pcap} 2>/dev/null | wc -l")
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
