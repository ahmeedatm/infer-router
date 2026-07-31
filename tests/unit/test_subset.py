from __future__ import annotations

import textwrap

import pytest

from bench.subset import SubsetError, load_subset

_VALID = textwrap.dedent("""
- intent_id: cx-001
  text: "Isolate a from b and cap a to c at 10 Mbps."
  domain: security
  criticality: high
  expected_complexity: complex
  topology: diamond4
  endpoints:
    a: {host: h1, mac: "00:00:00:00:00:01"}
    b: {host: h3, mac: "00:00:00:00:00:03"}
    c: {host: h2, mac: "00:00:00:00:00:02"}
  checks:
    - {check: ping_fail, src: a, dst: b}
    - {check: throughput_max, src: a, dst: c, max_mbps: 10.0}
""")


_WITH_LEGACY_GROUND_TRUTH = textwrap.dedent("""
- intent_id: legacy-001
  text: "Block a from b."
  domain: security
  criticality: high
  klass: isolation
  expected_complexity: simple
  topology: linear3
  endpoints:
    a: {host: h1, mac: "00:00:00:00:00:01"}
    b: {host: h3, mac: "00:00:00:00:00:03"}
  ground_truth: {check: ping_fail, src: a, dst: b}
  checks:
    - {check: ping_fail, src: a, dst: b}
""")


def _write(tmp_path, body: str) -> str:
    path = tmp_path / "subset.yaml"
    path.write_text(body)
    return str(path)


def test_loads_an_entry_with_several_checks(tmp_path):
    entries = load_subset(_write(tmp_path, _VALID))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.expected_complexity == "complex"
    assert len(entry.checks) == 2
    assert entry.checks[0].check == "ping_fail"
    assert entry.checks[1].max_mbps == 10.0


def test_rejects_a_check_referencing_an_unknown_endpoint(tmp_path):
    body = _VALID.replace("{check: ping_fail, src: a, dst: b}",
                          "{check: ping_fail, src: a, dst: ghost}")
    with pytest.raises(SubsetError):
        load_subset(_write(tmp_path, body))


def test_rejects_an_entry_without_checks(tmp_path):
    body = _VALID.split("  checks:")[0] + "  checks: []\n"
    with pytest.raises(SubsetError):
        load_subset(_write(tmp_path, body))


def test_rejects_an_unknown_complexity_label(tmp_path):
    with pytest.raises(SubsetError):
        load_subset(_write(tmp_path, _VALID.replace("complex", "trivial")))


def test_rejects_a_throughput_max_without_a_cap(tmp_path):
    body = _VALID.replace(", max_mbps: 10.0", "")
    with pytest.raises(SubsetError):
        load_subset(_write(tmp_path, body))


def test_rejects_a_legacy_ground_truth_referencing_an_unknown_endpoint(tmp_path):
    body = _WITH_LEGACY_GROUND_TRUTH.replace(
        "ground_truth: {check: ping_fail, src: a, dst: b}",
        "ground_truth: {check: ping_fail, src: a, dst: ghost}",
    )
    with pytest.raises(SubsetError):
        load_subset(_write(tmp_path, body))


def test_loads_a_valid_legacy_ground_truth_alongside_checks(tmp_path):
    entries = load_subset(_write(tmp_path, _WITH_LEGACY_GROUND_TRUTH))
    assert len(entries) == 1
    entry = entries[0]
    assert entry.ground_truth.check == "ping_fail"
    assert entry.ground_truth.src == "a"
    assert entry.ground_truth.dst == "b"
