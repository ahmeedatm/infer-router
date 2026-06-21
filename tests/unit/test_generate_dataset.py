"""Tests des fonctions pures du pipeline de génération du dataset (Plan 3 / ADR-007).

La génération par cellule (domaine x complexité) appelle un LLM fort via
OpenRouter. Ces tests ne touchent jamais le réseau : ils exercent uniquement les
fonctions pures (construction de prompt, parsing, déduplication, couverture).
Le runner réseau (`main`) n'est pas exercé ici.
"""
from __future__ import annotations

import pytest

from app.llm.schema import Intent
from scripts.generate_dataset import (
    GenerationError,
    build_generation_prompt,
    coverage_report,
    dedup_intents,
    parse_generated_intents,
    sample_length_targets,
)

SEED_EXAMPLES: tuple[Intent, ...] = (
    Intent(
        id="ran-read-throughput",
        text="What is the current downlink throughput on cell gNB-042?",
        domain="ran",
        expected_complexity="simple",
        criticality="low",
        slice_type=None,
    ),
    Intent(
        id="ran-read-prb",
        text="Show me the PRB utilization for sector 2 of gNB-118 right now.",
        domain="ran",
        expected_complexity="simple",
        criticality="low",
        slice_type=None,
    ),
)


# ───────────────────────────── build_generation_prompt ──────────────────────


def test_prompt_contains_domain_complexity_and_count():
    prompt = build_generation_prompt("ran", "simple", 21, SEED_EXAMPLES)
    assert "ran" in prompt
    assert "simple" in prompt
    assert "21" in prompt


def test_prompt_embeds_seed_examples_text():
    prompt = build_generation_prompt("ran", "simple", 5, SEED_EXAMPLES)
    for seed in SEED_EXAMPLES:
        assert seed.text in prompt


def test_prompt_states_required_yaml_fields():
    prompt = build_generation_prompt("core", "complex", 5, SEED_EXAMPLES)
    for field in ("id", "text", "domain", "expected_complexity",
                  "criticality", "slice_type"):
        assert field in prompt


def test_prompt_complexity_guidance_differs_simple_vs_complex():
    simple = build_generation_prompt("ran", "simple", 5, SEED_EXAMPLES)
    complex_ = build_generation_prompt("ran", "complex", 5, SEED_EXAMPLES)
    assert simple != complex_


def test_prompt_default_has_no_length_constraint():
    # Non-regression of the v1 mode: the length band must NOT appear by default.
    prompt = build_generation_prompt("ran", "simple", 5, SEED_EXAMPLES)
    assert "45 to 65 words" not in prompt
    assert "regardless of complexity" not in prompt.lower()


def test_prompt_length_controlled_injects_band_constraint():
    prompt = build_generation_prompt(
        "ran", "simple", 5, SEED_EXAMPLES, length_controlled=True
    )
    assert "45 to 65 words" in prompt
    assert "regardless of complexity" in prompt.lower()


def test_prompt_length_controlled_keeps_complexity_guidance():
    # The length constraint ADDS to the existing complexity guidance, it does
    # not replace it: simple vs complex must still diverge under length control.
    simple = build_generation_prompt(
        "ran", "simple", 5, SEED_EXAMPLES, length_controlled=True
    )
    complex_ = build_generation_prompt(
        "ran", "complex", 5, SEED_EXAMPLES, length_controlled=True
    )
    assert simple != complex_
    assert "45 to 65 words" in simple
    assert "45 to 65 words" in complex_


# ───────────────────────────── sample_length_targets ───────────────────────


def test_sample_length_targets_is_deterministic_for_same_seed():
    a = sample_length_targets(10, seed=42)
    b = sample_length_targets(10, seed=42)
    assert a == b


def test_sample_length_targets_differs_for_different_seed():
    a = sample_length_targets(10, seed=1)
    b = sample_length_targets(10, seed=2)
    assert a != b


def test_sample_length_targets_returns_n_values():
    assert len(sample_length_targets(7, seed=0)) == 7
    assert len(sample_length_targets(1, seed=0)) == 1
    assert sample_length_targets(0, seed=0) == ()


def test_sample_length_targets_stays_in_bounds():
    targets = sample_length_targets(200, seed=3, lo=15, hi=70)
    assert all(15 <= t <= 70 for t in targets)


def test_sample_length_targets_respects_custom_bounds():
    targets = sample_length_targets(50, seed=9, lo=20, hi=30)
    assert all(20 <= t <= 30 for t in targets)


# ───────────────────────────── build_generation_prompt (decorrelated) ───────


def test_prompt_default_has_no_length_targets_block():
    # Non-regression v1/v2: without length_targets the decorrelated block is absent.
    prompt = build_generation_prompt("ran", "simple", 5, SEED_EXAMPLES)
    assert "target word counts" not in prompt.lower()
    assert "independent of complexity" not in prompt.lower()


def test_prompt_length_controlled_has_no_length_targets_block():
    # v2 (band) and v3 (per-intent targets) are distinct: v2 must not emit v3 block.
    prompt = build_generation_prompt(
        "ran", "simple", 5, SEED_EXAMPLES, length_controlled=True
    )
    assert "target word counts" not in prompt.lower()
    assert "independent of complexity" not in prompt.lower()


def test_prompt_decorrelated_injects_targets_and_instruction():
    prompt = build_generation_prompt(
        "ran", "simple", 3, SEED_EXAMPLES, length_targets=(20, 55, 18)
    )
    assert "[20, 55, 18]" in prompt
    assert "independent of complexity" in prompt.lower()
    assert "target word counts" in prompt.lower()


def test_prompt_decorrelated_keeps_complexity_guidance():
    # The decorrelated targets ADD to complexity guidance; simple != complex.
    simple = build_generation_prompt(
        "ran", "simple", 3, SEED_EXAMPLES, length_targets=(20, 55, 18)
    )
    complex_ = build_generation_prompt(
        "ran", "complex", 3, SEED_EXAMPLES, length_targets=(20, 55, 18)
    )
    assert simple != complex_
    assert "[20, 55, 18]" in simple
    assert "[20, 55, 18]" in complex_


# ───────────────────────────── parse_generated_intents ──────────────────────


def _yaml_block(entries: str) -> str:
    return "intents:\n" + entries


VALID_YAML = """intents:
  - id: ran-read-rsrp
    text: "What is the RSRP on cell gNB-201 right now?"
    domain: ran
    expected_complexity: simple
    criticality: low
    slice_type: null
  - id: ran-read-cqi
    text: "Report the average CQI on sector 1 of gNB-077."
    domain: ran
    expected_complexity: simple
    criticality: low
    slice_type: null
"""


def test_parse_valid_yaml_returns_intents():
    intents = parse_generated_intents(VALID_YAML, "ran", "simple")
    assert len(intents) == 2
    assert all(isinstance(i, Intent) for i in intents)


def test_parse_forces_cell_domain_and_complexity():
    # The LLM drifted on domain/complexity; the parser must override both.
    drifting = """intents:
  - id: x-1
    text: "Read the current AMF registration count."
    domain: slice
    expected_complexity: complex
    criticality: low
    slice_type: null
"""
    intents = parse_generated_intents(drifting, "core", "simple")
    assert len(intents) == 1
    assert intents[0].domain == "core"
    assert intents[0].expected_complexity == "simple"


def test_parse_ignores_malformed_entries_keeps_valid():
    mixed = """intents:
  - id: ok-1
    text: "Read throughput on gNB-001."
    domain: ran
    expected_complexity: simple
    criticality: low
    slice_type: null
  - id: bad-1
    text: "Missing criticality and bad slice."
    criticality: NOT_A_LEVEL
    slice_type: weird
  - "not a mapping"
"""
    intents = parse_generated_intents(mixed, "ran", "simple")
    assert len(intents) == 1
    assert intents[0].id == "ok-1"


def test_parse_tolerates_markdown_code_fences():
    fenced = "```yaml\n" + VALID_YAML + "```"
    intents = parse_generated_intents(fenced, "ran", "simple")
    assert len(intents) == 2


def test_parse_zero_intents_raises():
    with pytest.raises(GenerationError):
        parse_generated_intents("intents:\n  - 123\n", "ran", "simple")


def test_parse_unparseable_yaml_raises():
    with pytest.raises(GenerationError):
        parse_generated_intents("::: not yaml :::\n  - [unbalanced", "ran", "simple")


# ───────────────────────────── dedup_intents ────────────────────────────────


def _intent(id_: str, text: str) -> Intent:
    return Intent(
        id=id_,
        text=text,
        domain="ran",
        expected_complexity="simple",
        criticality="low",
        slice_type=None,
    )


def test_dedup_removes_normalized_duplicates():
    a = _intent("a", "What is the throughput on gNB-042?")
    b = _intent("b", "  what is the   THROUGHPUT on   gNB-042?  ")
    c = _intent("c", "Show PRB utilization on gNB-118.")
    out = dedup_intents((a, b, c))
    assert len(out) == 2
    assert out[0].id == "a"  # first occurrence kept
    assert out[1].id == "c"


def test_dedup_is_pure_does_not_mutate_input():
    a = _intent("a", "Read throughput.")
    b = _intent("b", "read   THROUGHPUT.")
    original = (a, b)
    out = dedup_intents(original)
    assert original == (a, b)
    assert len(out) == 1


def test_dedup_empty_returns_empty():
    assert dedup_intents(()) == ()


# ───────────────────────────── coverage_report ──────────────────────────────


def test_coverage_report_counts_per_cell():
    intents = (
        _intent("a", "one"),
        _intent("b", "two"),
        Intent(id="c", text="three", domain="core",
               expected_complexity="complex", criticality="high",
               slice_type="urllc"),
    )
    report = coverage_report(intents)
    assert report["total"] == 3
    assert report["matrix"]["ran"]["simple"] == 2
    assert report["matrix"]["core"]["complex"] == 1
    assert report["matrix"]["slice"]["medium"] == 0


def test_coverage_report_counts_criticality_and_slice():
    intents = (
        _intent("a", "one"),  # criticality low, slice None
        Intent(id="c", text="three", domain="core",
               expected_complexity="complex", criticality="high",
               slice_type="urllc"),
    )
    report = coverage_report(intents)
    assert report["criticality"]["low"] == 1
    assert report["criticality"]["high"] == 1
    assert report["slice_type"]["urllc"] == 1
    assert report["slice_type"]["none"] == 1
