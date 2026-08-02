"""Mininet diamond topology + a runner that applies OVS commands and probes.

No SDN controller. The diamond holds a loop, so switches run in secure mode and
the bench installs the base forwarding rules itself, pinning the default path
through s2. Static ARP removes broadcast entirely, which makes the data plane
deterministic and removes the MAC-learning settle delay the linear topology
needed.

The switches run the staged pipeline defined in :mod:`bench.verbs.base`: a
marking table, a queueing table, then the forwarding table this module
populates. The two upstream stages get a priority-0 ``resubmit`` here, without
which an empty table would drop everything in secure mode.

Imported only inside the Lima VM (needs mininet). Never import from unit tests.
"""
from __future__ import annotations

import itertools
import re
from typing import Optional

from mininet.link import TCLink
from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo

from bench.apply_result import ApplyError, raise_if_failed  # noqa: F401
from bench.verbs.base import (  # noqa: F401
    PIPELINE_DEFAULT_PRIORITY,
    PRIORITY_BASE_FLOW,
    PRIORITY_PAIR_FLOW,
    TABLE_FORWARD,
    TABLE_MARK,
    TABLE_QUEUE,
    OvsCommand,
)

# The pipeline scheme (tables and priority tiers) lives in ``bench.verbs.base``
# so the verb modules and the topology read the same one. Two names are used
# here:
#   PRIORITY_BASE_FLOW  forwarding by destination MAC, the floor of the
#                       forwarding table.
#   PRIORITY_PAIR_FLOW  per-pair flows on the transit switches, just above
#                       that floor. They forward identically; they exist so
#                       traversal is countable. ``flow_packets`` needs dl_src
#                       and dl_dst on one line, which a dl_dst-only table
#                       never provides, so without them ``path_used`` could
#                       never be true. The catch-all stays underneath, so
#                       connectivity never depends on this table being
#                       exhaustive.
_TRANSIT_SWITCHES = ("s2", "s3")

# iperf's default control port. Passed explicitly so the server can be killed
# by an exact pattern instead of a shell job spec (see ``iperf``).
DEFAULT_IPERF_PORT = 5001

# Traffic the mirror checks generate. Short interval, so the burst fits inside
# one capture window; enough packets that a working mirror clears min_packets
# with margin even if the first one is lost to tcpdump's startup.
MIRROR_PING_COUNT = 6
MIRROR_PING_INTERVAL = 0.2

# How long to wait for tcpdump to report "listening" before generating the
# traffic it is supposed to capture.
CAPTURE_READY_TIMEOUT_S = 5

# How long to wait for an iperf server to release, then bind, its port.
IPERF_PORT_TIMEOUT_S = 5

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


_ROUTES = {
    "s1": {"h1": "h1", "h2": "h2", "h4": "h4", "h3": "s2"},
    "s2": {"h1": "s1", "h2": "s1", "h4": "s1", "h3": "s4"},
    "s3": {"h1": "s1", "h2": "s1", "h4": "s1", "h3": "s4"},
    "s4": {"h1": "s2", "h2": "s2", "h4": "s2", "h3": "h3"},
}


def _install_pipeline_defaults(net) -> None:
    """Carry a packet no verb touched through the marking and queueing stages.

    Without these the two upstream stages are empty tables, and in secure mode
    an empty table drops. Every stage therefore ends in a priority-0
    ``resubmit`` to the next one, and only the forwarding table decides
    anything. See the scheme in :mod:`bench.verbs.base`.
    """
    for stage, nxt in ((TABLE_MARK, TABLE_QUEUE), (TABLE_QUEUE, TABLE_FORWARD)):
        for sw in net.switches:
            command = (
                f"ovs-ofctl add-flow {sw.name} "
                f"'table={stage},priority={PIPELINE_DEFAULT_PRIORITY},"
                f"actions=resubmit(,{nxt})'"
            )
            raise_if_failed(sw.name, command, sw.cmd(command))


def _install_base_flows(net) -> None:
    """Unicast forwarding by destination MAC, default path through s2.

    Everything installed here lives in the pipeline's forwarding table, below
    every verb tier, so a verb can override a route without the base table
    having to be edited or removed.

    A rejection here breaks every case at once and is invisible without
    reading the output, so it raises like any other rejected command.
    """
    for switch, table in _ROUTES.items():
        sw = net.get(switch)
        for host, nexthop in table.items():
            port = _port_to(net, switch, nexthop)
            command = (
                f"ovs-ofctl add-flow {switch} "
                f"'table={TABLE_FORWARD},priority={PRIORITY_BASE_FLOW},"
                f"dl_dst={_HOSTS[host]},actions=output:{port}'"
            )
            raise_if_failed(switch, command, sw.cmd(command))

    for switch in _TRANSIT_SWITCHES:
        sw = net.get(switch)
        table = _ROUTES[switch]
        for src, dst in itertools.permutations(_HOSTS, 2):
            port = _port_to(net, switch, table[dst])
            command = (
                f"ovs-ofctl add-flow {switch} "
                f"'table={TABLE_FORWARD},priority={PRIORITY_PAIR_FLOW},"
                f"dl_src={_HOSTS[src]},"
                f"dl_dst={_HOSTS[dst]},actions=output:{port}'"
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
    _install_pipeline_defaults(net)
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
        self._invalidate_datapath_cache()

    def _invalidate_datapath_cache(self) -> None:
        """Drop cached datapath flows so the next packet is re-classified.

        The warmup runs before the plan and populates the kernel megaflow
        cache with action lists derived from the pre-plan configuration.
        OVS's revalidator re-derives them on its own schedule, not on the
        change, so a check probing immediately after ``apply`` can be served
        entirely from stale entries and measure the network as it was.

        Measured on the mirror case: with the warmup, 0 mirrored packets
        immediately after applying the mirror, 10 after sleeping 15 s, 10
        immediately after this flush. Sleeping would work; it would also add
        a quarter of an hour to the campaign and leave the race in place.
        The cache is datapath-wide, so one flush covers every bridge.
        """
        if self._net.switches:
            self._net.switches[0].cmd("ovs-appctl dpctl/del-flows 2>/dev/null")

    # --- probes ----------------------------------------------------------

    def ping(self, src_host: str, dst_host: str, count: int = 3,
             interval: Optional[float] = None) -> str:
        src, dst = self._net.get(src_host), self._net.get(dst_host)
        pace = f"-i {interval} " if interval is not None else ""
        return src.cmd(f"ping -c {count} -W 1 {pace}{dst.IP()}")

    def iperf(self, src_host: str, dst_host: str, port=None, seconds: int = 5) -> str:
        """Measure throughput; a refused port must read as 0, not as a stall.

        The client carries a ``timeout`` because a correctly blocked port
        leaves iperf retrying the TCP SYN for roughly two minutes. That is a
        successful block, so it must cost one measurement window, not the
        campaign's schedule.

        The port is always explicit, even when it is iperf's own default,
        because that is what makes the server killable. ``-D`` detaches the
        server from the shell that started it, so the previous ``kill %iperf``
        was a job spec matching nothing: servers accumulated for the whole
        campaign, each one holding its case's network namespace open long
        after ``net.stop()``. A pattern carrying the exact port kills this
        server without touching the contention flow's server on another port.
        """
        server, client = self._net.get(dst_host), self._net.get(src_host)
        port = DEFAULT_IPERF_PORT if port is None else port
        self._start_iperf_server(server, port)
        out = client.cmd(f"timeout {seconds + IPERF_GRACE_S} "
                         f"iperf -c {server.IP()} -t {seconds} -p {port}")
        server.cmd(f"pkill -f 'iperf -s -D -p {port}'")
        return out

    def _start_iperf_server(self, server, port: int) -> str:
        """Leave exactly one server listening on ``port``, and prove it.

        Both waits are load-bearing. Killing the previous server and starting
        the next one immediately is a race: the dying process still holds the
        socket, the new one fails to bind, and the client's connection is
        reset a few milliseconds in. iperf still prints a bandwidth for that
        sliver -- "0.0000-0.0177 sec 99.0 KBytes 45.9 Mbits/sec" -- which is
        an entirely fictitious number that parses cleanly. Measured on
        consecutive calls, every second one came back like that, so any case
        running two throughput checks had a coin-flip on the second.

        Waiting for the port to appear in the listen table then removes the
        opposite race, where the client connects before the server is up.
        """
        attempts = int(IPERF_PORT_TIMEOUT_S * 10)
        server.cmd(f"pkill -f 'iperf -s -D -p {port}'")
        server.cmd(f"for _ in $(seq 1 {attempts}); do "
                   f"pgrep -f 'iperf -s -D -p {port}' >/dev/null || break; "
                   f"sleep 0.1; done")
        server.cmd(f"iperf -s -D -p {port}")
        return server.cmd(f"for _ in $(seq 1 {attempts}); do "
                          f"ss -ltn 2>/dev/null | grep -q ':{port} ' && break; "
                          f"sleep 0.1; done")

    def iperf_contended(self, src_host, dst_host, contender_src, contender_dst,
                        seconds: int = 5) -> str:
        """Measure the protected flow while a competing flow saturates the core.

        The noise flow deliberately outlives the measurement window, so it has
        to be killed here: left running, it keeps loading the core link during
        the next check of the same case and corrupts that measurement too.
        """
        noise_srv = self._net.get(contender_dst)
        noise_cli = self._net.get(contender_src)
        self._start_iperf_server(noise_srv, NOISE_PORT)
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
                       seconds: int = 15, tag: str = "case") -> int:
        """Count mirrored packets on the probe while src pings dst.

        Only the traffic the mirror is supposed to duplicate is counted: ICMP
        between the two mirrored endpoints. Counting everything on the probe's
        interface counted the wrong thing entirely. A freshly started Linux
        interface emits its own IPv6 autoconfiguration burst (multicast
        listener reports, neighbour and router solicitations), measured at 8
        to 10 packets in the first seconds, against a ``min_packets`` of 3.
        So the check passed with no mirror installed, and passed or failed
        depending only on how far into the case it ran: 8 packets at t=0, 0 at
        t=8s, which is why it scored 1/1 on the mirror intent and 0 on the
        one where it ran fourth.

        The capture is also synchronised with the traffic rather than raced
        against it. tcpdump needs a moment to open its socket, and the ping
        used to start immediately, so the first packets were lost before the
        capture existed. Here the ping waits for tcpdump to report that it is
        listening, and the capture is stopped as soon as the ping is done
        rather than sitting out its full timeout.

        The file name carries the case's tag because Mininet hosts share
        ``/tmp`` with the VM, so a fixed path lets one case read the previous
        case's packets.
        """
        probe = self._net.get(probe_host)
        stem = f"/tmp/mirror-{_UNSAFE_TAG.sub('_', tag)}-{next(self._capture_seq)}"
        pcap, log = f"{stem}.pcap", f"{stem}.log"
        expected = (f"icmp and host {self._net.get(src_host).IP()} "
                    f"and host {self._net.get(dst_host).IP()}")

        probe.cmd(f"rm -f {pcap} {log}")
        probe.cmd(f"timeout {seconds} tcpdump -i {probe.defaultIntf().name} "
                  f"-U -c 200 -w {pcap} 2>{log} &")
        probe.cmd(f"for _ in $(seq 1 {int(CAPTURE_READY_TIMEOUT_S * 10)}); do "
                  f"grep -q listening {log} && break; sleep 0.1; done")

        self.ping(src_host, dst_host, count=MIRROR_PING_COUNT,
                  interval=MIRROR_PING_INTERVAL)

        # -U flushes each packet as it arrives, so stopping the writer early
        # loses nothing and saves the rest of the timeout window.
        probe.cmd(f"pkill -f 'tcpdump -i .* -w {pcap}'")
        probe.cmd("wait")
        out = probe.cmd(f"tcpdump -r {pcap} -n '{expected}' 2>/dev/null | wc -l")
        try:
            return int(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            return 0

    def flow_packets(self, switch: str, dl_src: str, dl_dst: str) -> int:
        """Packets forwarded by flows matching this ordered MAC pair.

        The field names are part of the match. A bare substring test counted
        ``dl_src=B,dl_dst=A`` for the pair (A, B) as well, so the two
        directions of a flow were summed together and a reroute that only
        moved one of them read as if it had moved both.

        Only the forwarding table is dumped. The marking stage matches on the
        same MAC pair and its counters would otherwise be added to the
        forwarding counters, so a marked flow would be counted twice on the
        path it took. ``path_used`` compares two paths and survives a uniform
        factor, but the number would stop meaning "packets forwarded here".
        """
        sw = self._net.get(switch)
        out = sw.cmd(f"ovs-ofctl dump-flows {switch} table={TABLE_FORWARD}")
        total = 0
        for line in out.splitlines():
            if f"dl_src={dl_src}" in line and f"dl_dst={dl_dst}" in line:
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
        """Tear the case down, including anything that outlived its shell.

        ``iperf -s -D`` detaches, so it survives both the shell that started
        it and ``net.stop()``. A surviving server keeps its case's network
        namespace alive; a campaign's worth of them accumulates (19 were found
        in the VM, some carrying ports from a previous run). They are swept
        here rather than only per call, so a case that raises mid-check still
        cleans up after itself.
        """
        if self._net.hosts:
            self._net.hosts[0].cmd("pkill -f 'iperf -s -D' 2>/dev/null")
        self._net.stop()
