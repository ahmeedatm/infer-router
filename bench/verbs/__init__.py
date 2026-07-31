"""Verb registry: one module per verb family, dispatched by ``op.verb``.

Adding a verb means adding a module and one entry here. Nothing else in the
bench needs to change.
"""
from __future__ import annotations

from types import ModuleType

from bench.subset import EndpointRef
from bench.verbs import allow_block
from bench.verbs.base import OvsCommand, VerbError

REGISTRY: dict[str, ModuleType] = {
    "allow": allow_block,
    "block": allow_block,
}


def commands_for(op, endpoints: dict[str, EndpointRef]) -> tuple[OvsCommand, ...]:
    """Map one operation to its OVS commands via the registry."""
    module = REGISTRY.get(op.verb)
    if module is None:
        raise VerbError(f"no verb module for {op.verb!r}")
    return module.to_commands(op, endpoints)
