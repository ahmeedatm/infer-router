"""Pure mapping: intent plan + endpoint table -> OVS realisation.

No SDN controller: operations are realised directly on Open vSwitch. This
module stays pure (no execution); the runner applies the result via
ovs-ofctl / ovs-vsctl.

``translate_plan`` maps an ``IntentPlan`` (an ordered sequence of operations
covering all seven verbs) to a flat tuple of ``OvsCommand``, delegating each
operation to ``bench.verbs.commands_for``. All verb knowledge lives in
``bench.verbs``, so adding a verb never touches this module.
"""
from __future__ import annotations

from app.llm.intent_plan import IntentPlan
from bench.subset import EndpointRef
from bench.verbs import commands_for
from bench.verbs.base import OvsCommand, VerbError


class TranslateError(ValueError):
    """Raised when a plan cannot be mapped to an OVS realisation."""


def translate_plan(
    plan: IntentPlan,
    endpoints: dict[str, EndpointRef],
) -> tuple[OvsCommand, ...]:
    """Flatten a plan into the ordered commands that realise it."""
    commands: list[OvsCommand] = []
    for op in plan.operations:
        try:
            commands.extend(commands_for(op, endpoints))
        except VerbError as exc:
            raise TranslateError(f"{plan.intent_id}: {exc}") from exc
    return tuple(commands)
