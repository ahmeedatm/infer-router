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
