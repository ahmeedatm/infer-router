"""Mininet topology + a runner that applies FlowSpecs and measures the data plane.

No SDN controller: switches run in OVS standalone mode (L2 learning), and the
runner realises actions directly via ovs-ofctl (drops) / ovs-vsctl (policing).
Imported only inside the Lima VM (needs mininet). Never import from unit tests.
"""
from __future__ import annotations

import time

from mininet.net import Mininet
from mininet.node import OVSSwitch
from mininet.topo import Topo

from bench.translator import FlowSpec

# Settle delay after starting a controller-less topology, so OVS standalone MAC
# learning is ready before the first probe (avoids transient first-ping loss).
_SETTLE_S = 1.5


class TopologyError(ValueError):
    """Raised when an unknown topology name is requested."""


class _Linear3(Topo):
    """h1-s1-s2-h3 with h2 on s1 (no loop; safe without a controller/STP)."""

    def build(self):
        h1 = self.addHost("h1", mac="00:00:00:00:00:01")
        h2 = self.addHost("h2", mac="00:00:00:00:00:02")
        h3 = self.addHost("h3", mac="00:00:00:00:00:03")
        s1, s2 = self.addSwitch("s1"), self.addSwitch("s2")
        self.addLink(h1, s1)
        self.addLink(s1, s2)
        self.addLink(h2, s1)
        self.addLink(h3, s2)


_TOPOS = {"linear3": _Linear3}


def build_topology(name: str) -> Mininet:
    """Start a controller-less Mininet with OVS switches in standalone mode."""
    if name not in _TOPOS:
        raise TopologyError(f"unknown topology {name!r}")
    net = Mininet(topo=_TOPOS[name](), switch=OVSSwitch, controller=None,
                  waitConnected=False)
    net.start()
    for sw in net.switches:
        sw.cmd(f"ovs-vsctl set-fail-mode {sw.name} standalone")
    time.sleep(_SETTLE_S)
    return net


class MininetRunner:
    """Applies a FlowSpec on the running network and runs ping/iperf probes."""

    def __init__(self, net: Mininet) -> None:
        self._net = net

    def warmup(self) -> None:
        self._net.pingAll()

    def apply(self, spec: FlowSpec) -> None:
        if spec.kind == "allow":
            return
        if spec.kind == "block":
            for sw in self._net.switches:
                for dl_src, dl_dst in spec.drop_pairs:
                    sw.cmd(
                        f"ovs-ofctl add-flow {sw.name} "
                        f"'priority=200,dl_src={dl_src},dl_dst={dl_dst},actions=drop'"
                    )
            return
        # qos: ingress policing on the switch port facing the source host
        host = self._net.get(spec.policing_host)
        intf = host.defaultIntf()
        link = intf.link
        sw_intf = link.intf2 if link.intf1 is intf else link.intf1
        rate = spec.policing_kbps or 0
        burst = max(rate // 10, 1)
        sw_intf.node.cmd(
            f"ovs-vsctl set interface {sw_intf.name} "
            f"ingress_policing_rate={rate} ingress_policing_burst={burst}"
        )

    def ping(self, src_host: str, dst_host: str) -> str:
        src, dst = self._net.get(src_host), self._net.get(dst_host)
        return src.cmd(f"ping -c 3 -W 1 {dst.IP()}")

    def iperf(self, src_host: str, dst_host: str, seconds: int = 5) -> str:
        server, client = self._net.get(dst_host), self._net.get(src_host)
        server.cmd("iperf -s -D")
        out = client.cmd(f"iperf -c {server.IP()} -t {seconds}")
        server.cmd("kill %iperf")
        return out

    def stop(self) -> None:
        self._net.stop()
