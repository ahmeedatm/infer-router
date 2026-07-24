"""Curated realizable intents + ground truth for the OVS bench."""
from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

_DEFAULT_PATH = Path(__file__).with_name("subset.yaml")


class SubsetError(RuntimeError):
    """Raised on a malformed or internally inconsistent subset file."""


class EndpointRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    host: str
    mac: str
    ip: Optional[str] = None


class GroundTruth(BaseModel):
    model_config = ConfigDict(frozen=True)
    check: Literal["ping_ok", "ping_fail", "throughput_min", "throughput_max"]
    src: str
    dst: str
    min_mbps: Optional[float] = None
    max_mbps: Optional[float] = None


class SubsetEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    intent_id: str
    text: str
    domain: str
    criticality: str
    klass: Literal["reachability", "isolation", "qos"]
    topology: str
    endpoints: dict[str, EndpointRef]
    ground_truth: GroundTruth


def _validate_refs(entry: SubsetEntry) -> None:
    for who in (entry.ground_truth.src, entry.ground_truth.dst):
        if who not in entry.endpoints:
            raise SubsetError(
                f"{entry.intent_id}: ground_truth references unknown endpoint {who!r}"
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
