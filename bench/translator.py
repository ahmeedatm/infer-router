"""Pure mapping: action/plan + endpoint table -> OVS realisation.

No SDN controller: actions and operations are realised directly on Open
vSwitch. This module stays pure (no execution); the runner applies the result
via ovs-ofctl / ovs-vsctl.

Two paths coexist during the verb-vocabulary migration:

- Legacy: ``translate`` maps one ``SdnAction`` (allow/block/bandwidth) to a
  single ``FlowSpec``, one field per mechanism. This shape forced every
  realisable intent to touch exactly two endpoints under one constraint, and
  so made every bench intent structurally simple. It is removed once every
  consumer has migrated to the plan path (see the cleanup task in the SDD
  plan); until then it stays untouched here.
- Plan: ``translate_plan`` maps an ``IntentPlan`` (an ordered sequence of
  operations covering all seven verbs) to a flat tuple of ``OvsCommand``,
  delegating each operation to ``bench.verbs.commands_for``. All verb
  knowledge lives in ``bench.verbs``, so adding a verb never touches this
  module.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from app.llm.intent_plan import IntentPlan
from app.llm.sdn_action import SdnAction
from bench.subset import EndpointRef
from bench.verbs import commands_for
from bench.verbs.base import OvsCommand, VerbError


class TranslateError(ValueError):
    """Raised when an action or plan cannot be mapped to an OVS realisation."""


class FlowSpec(BaseModel):
    """Immutable OVS realisation of a network action."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["allow", "block", "qos"]
    # (dl_src, dl_dst) MAC pairs to drop (both directions for isolation).
    drop_pairs: tuple[tuple[str, str], ...] = ()
    # Ingress policing rate applied to policing_host's switch port.
    policing_kbps: Optional[int] = None
    policing_host: Optional[str] = None


def _resolve(endpoints: dict[str, EndpointRef], key: str) -> EndpointRef:
    if key not in endpoints:
        raise TranslateError(f"unknown endpoint {key!r}")
    return endpoints[key]


def translate(action: SdnAction, endpoints: dict[str, EndpointRef]) -> FlowSpec:
    src = _resolve(endpoints, action.src)
    dst = _resolve(endpoints, action.dst)

    if action.action == "allow":
        return FlowSpec(kind="allow")
    if action.action == "block":
        return FlowSpec(
            kind="block",
            drop_pairs=((src.mac, dst.mac), (dst.mac, src.mac)),
        )
    # bandwidth -> ingress policing cap on the source host
    if action.bw_mbps is None:
        raise TranslateError("bandwidth action requires bw_mbps")
    return FlowSpec(
        kind="qos",
        policing_kbps=int(action.bw_mbps * 1000),
        policing_host=src.host,
    )


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
