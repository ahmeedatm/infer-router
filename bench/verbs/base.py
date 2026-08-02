"""Shared primitives for verb modules.

A verb module is pure: it maps one Operation to OVS commands and never touches
Mininet. Switch and port names are unknown at this stage, so a command may
carry markers the runner substitutes at apply time:

    {switch}              the switch the command currently runs on
    {swport:<host>}       switch-side interface name facing that host
    {swport_to:<switch>}  OpenFlow port number towards that switch
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from bench.subset import EndpointRef

# --- OpenFlow pipeline ---------------------------------------------------
#
# THE scheme. Every module that installs a flow reads its table and priority
# from here; nothing hardcodes either.
#
# Two verbs must be able to act on the same packet. One table cannot do that:
# a packet matches exactly one flow entry, so ``reroute`` (output to a chosen
# path) and ``priority`` (rewrite the ToS byte) sitting at the same priority
# on the same MAC pair simply raced, and whichever OVS happened to prefer
# decided which of ``path_used`` / ``tos_marked`` could hold. Never both. That
# is what c-003 measured.
#
# So the pipeline is staged by concern, and each stage hands the packet on
# with ``resubmit`` instead of consuming it. Only the last stage forwards:
#
#   table 0  MARK     ``priority``      mod_nw_tos      -> resubmit(,1)
#   table 1  QUEUE    ``bandwidth_min`` set_queue       -> resubmit(,2)
#   table 2  FORWARD  ``allow``/``block``/``reroute`` + the base flows the
#                     topology installs -> output / drop / normal
#
# Tables 0 and 1 each carry a priority-0 catch-all that resubmits, installed
# by ``bench.topology``, so a packet no verb touched still reaches table 2.
#
# Priorities are only ever compared inside one table. The forwarding tiers,
# highest first:
#
#   300  allow/block narrowed by an L4 selector
#   200  block on a whole MAC pair (drop)
#   150  reroute
#   110  per-pair transit flows, forwarding identically to the base flows but
#        naming both endpoints so ``path_used`` has a counter to read
#   100  base forwarding by destination MAC
#
# ``bandwidth_max`` appears nowhere above: it is port-level ingress policing,
# not a flow entry. ``mirror`` likewise is a bridge-level SPAN.
TABLE_MARK = 0
TABLE_QUEUE = 1
TABLE_FORWARD = 2

#: Catch-all that carries an untouched packet to the next stage.
PIPELINE_DEFAULT_PRIORITY = 0

PRIORITY_MARK = 150
PRIORITY_QUEUE = 150

PRIORITY_SELECTED = 300
PRIORITY_PAIR_DROP = 200
PRIORITY_REROUTE = 150
PRIORITY_PAIR_FLOW = 110
PRIORITY_BASE_FLOW = 100


class VerbError(ValueError):
    """Raised when an operation cannot be mapped to OVS commands."""


class OvsCommand(BaseModel):
    """One shell command to run on a bench node.

    Attributes:
        target: Switch name (``s1``) or ``all`` to run it on every switch.
        command: Shell line, possibly containing ``{swport:<host>}`` markers.
    """

    model_config = ConfigDict(frozen=True)

    target: str
    command: str


def resolve(endpoints: dict[str, EndpointRef], key: str) -> EndpointRef:
    """Return the endpoint named ``key``, or raise ``VerbError``."""
    if key not in endpoints:
        raise VerbError(f"unknown endpoint {key!r}")
    return endpoints[key]
