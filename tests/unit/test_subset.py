from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from bench.subset import SubsetError, load_subset


def _write(tmp_path: Path, body: str) -> str:
    p = tmp_path / "subset.yaml"
    p.write_text(textwrap.dedent(body))
    return str(p)


def test_loads_valid_entry(tmp_path):
    path = _write(tmp_path, """
        - intent_id: sec-001
          text: Block RAN mgmt from core billing
          domain: security
          criticality: high
          klass: isolation
          topology: linear3
          endpoints:
            ran_mgmt: {host: h1, mac: "00:00:00:00:00:01"}
            core_billing: {host: h3, mac: "00:00:00:00:00:03"}
          ground_truth: {check: ping_fail, src: ran_mgmt, dst: core_billing}
    """)
    entries = load_subset(path)
    assert entries[0].intent_id == "sec-001"
    assert entries[0].endpoints["ran_mgmt"].host == "h1"
    assert entries[0].ground_truth.check == "ping_fail"


def test_rejects_ground_truth_unknown_endpoint(tmp_path):
    path = _write(tmp_path, """
        - intent_id: bad-001
          text: x
          domain: security
          criticality: low
          klass: isolation
          topology: linear3
          endpoints:
            a: {host: h1, mac: "00:00:00:00:00:01"}
          ground_truth: {check: ping_fail, src: a, dst: ghost}
    """)
    with pytest.raises(SubsetError):
        load_subset(path)
