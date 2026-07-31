"""Curated realizable intents + ground truth for the OVS bench.

Ground truth describes the expected network state, never the expected
operations: a model reaching that state by another route is not penalised, and
an omitted operation fails its check on its own.

``GroundTruth``/``klass`` are the legacy single-check schema, still consumed
by :mod:`bench.verifier` and :mod:`bench.orchestrator`. ``checks`` (plural,
Task 9) supersedes them for new entries; the two coexist until the
consumers migrate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

_DEFAULT_PATH = Path(__file__).with_name("subset.yaml")

Complexity = Literal["simple", "medium", "complex"]


class SubsetError(RuntimeError):
    """Raised on a malformed or internally inconsistent subset file."""


class EndpointRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str
    mac: str
    ip: Optional[str] = None


class GroundTruth(BaseModel):
    """Legacy single-check ground truth (pre-Task 9)."""

    model_config = ConfigDict(frozen=True)
    check: Literal["ping_ok", "ping_fail", "throughput_min", "throughput_max"]
    src: str
    dst: str
    min_mbps: Optional[float] = None
    max_mbps: Optional[float] = None


class _BaseCheck(BaseModel):
    model_config = ConfigDict(frozen=True)


class PingOk(_BaseCheck):
    check: Literal["ping_ok"]
    src: str
    dst: str


class PingFail(_BaseCheck):
    check: Literal["ping_fail"]
    src: str
    dst: str


class ThroughputMax(_BaseCheck):
    check: Literal["throughput_max"]
    src: str
    dst: str
    max_mbps: float = Field(gt=0)


class ThroughputMin(_BaseCheck):
    check: Literal["throughput_min"]
    src: str
    dst: str
    min_mbps: float = Field(gt=0)
    contender_src: str
    contender_dst: str


class PortBlocked(_BaseCheck):
    check: Literal["port_blocked"]
    src: str
    dst: str
    port: int = Field(ge=1, le=65535)
    proto: Literal["tcp", "udp"]


class MirrorSeen(_BaseCheck):
    check: Literal["mirror_seen"]
    src: str
    dst: str
    probe_host: str
    min_packets: int = Field(ge=1)


class PathUsed(_BaseCheck):
    check: Literal["path_used"]
    src: str
    dst: str
    via: str
    not_via: str


class TosMarked(_BaseCheck):
    check: Literal["tos_marked"]
    src: str
    dst: str
    tos: int = Field(ge=0, le=255)


Check = Annotated[
    Union[PingOk, PingFail, ThroughputMax, ThroughputMin,
          PortBlocked, MirrorSeen, PathUsed, TosMarked],
    Field(discriminator="check"),
]


class SubsetEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_id: str
    text: str
    domain: str
    criticality: str
    expected_complexity: Complexity
    topology: str
    endpoints: dict[str, EndpointRef]
    checks: tuple[Check, ...] = Field(min_length=1)
    # Legacy fields (pre-Task 9), optional so both schemas coexist until
    # bench.verifier/bench.orchestrator migrate to `checks` in Tasks 10-11.
    klass: Optional[Literal["reachability", "isolation", "qos"]] = None
    ground_truth: Optional[GroundTruth] = None


_ENDPOINT_FIELDS = ("src", "dst", "contender_src", "contender_dst")


def _validate_refs(entry: SubsetEntry) -> None:
    """Every endpoint a check (or the legacy ground_truth) names must exist
    in the entry's endpoint table.

    ``mirror_seen.probe_host`` is a Mininet host name, not a logical
    endpoint key, so it is deliberately excluded from this check.
    """
    for check in entry.checks:
        for field in _ENDPOINT_FIELDS:
            who = getattr(check, field, None)
            if who is not None and who not in entry.endpoints:
                raise SubsetError(
                    f"{entry.intent_id}: check {check.check} references "
                    f"unknown endpoint {who!r}"
                )
    if entry.ground_truth is not None:
        for who in (entry.ground_truth.src, entry.ground_truth.dst):
            if who not in entry.endpoints:
                raise SubsetError(
                    f"{entry.intent_id}: ground_truth references unknown "
                    f"endpoint {who!r}"
                )


def load_subset(path: Optional[str] = None) -> tuple[SubsetEntry, ...]:
    """Load and validate the curated subset; fail fast on inconsistency."""
    target = Path(path) if path is not None else _DEFAULT_PATH
    try:
        raw = yaml.safe_load(target.read_text())
    except (OSError, yaml.YAMLError) as exc:
        raise SubsetError(f"cannot read subset {target}: {exc}") from exc
    if not isinstance(raw, list):
        raise SubsetError(f"subset {target} must be a YAML list")
    entries = []
    for i, item in enumerate(raw):
        try:
            entry = SubsetEntry(**item)
        except (ValidationError, TypeError) as exc:
            raise SubsetError(f"entry {i} invalid: {exc}") from exc
        _validate_refs(entry)
        entries.append(entry)
    return tuple(entries)
