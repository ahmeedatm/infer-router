"""Tests for the CLI entry point: argument mapping and failure handling."""
from __future__ import annotations

import pytest

from app import config
from app.cli import __main__ as cli
from app.cli.pipeline import PipelineError
from app.cli.trace import ComplexityStage, DecisionStage, Trace
from app.llm.schema import Intent


def _trace() -> Trace:
    return Trace(
        intent=Intent(
            id="CLI",
            text="text",
            domain="core",
            expected_complexity="simple",
            criticality="med",
        ),
        complexity=ComplexityStage(label="simple", features={}, elapsed_ms=1.0),
        decision=DecisionStage(
            q_min=0.5,
            q_min_forced=False,
            l_max=1e9,
            c_max=1e9,
            candidates=(),
            chosen_model_id="light-model",
            rationale="rationale",
            admissible_count=0,
        ),
    )


def test_defaults_are_local_and_full_pipeline():
    args = cli.build_parser().parse_args(["an intent"])
    options = cli._options(args)
    assert options.provider == "local"
    assert options.stage == "judge"
    assert options.pool == "generic"


def test_unset_budget_flags_keep_the_module_defaults():
    options = cli._options(cli.build_parser().parse_args(["an intent"]))
    assert options.l_max == config.BENCH_L_MAX_MS
    assert options.max_tokens == config.RESPONSE_MAX_TOKENS


def test_budget_flags_override_the_defaults():
    args = cli.build_parser().parse_args(["an intent", "--l-max", "5000", "--c-max", "0.01"])
    options = cli._options(args)
    assert options.l_max == 5000.0
    assert options.c_max == 0.01


def test_an_invalid_domain_is_rejected_by_the_parser():
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["an intent", "--domain", "transport"])


def test_main_prints_the_report_and_exits_zero(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda text, options: _trace())
    assert cli.main(["an intent"]) == 0
    assert "InferRouter-LLM" in capsys.readouterr().out


def test_json_flag_emits_the_raw_trace(monkeypatch, capsys):
    monkeypatch.setattr(cli, "run", lambda text, options: _trace())
    assert cli.main(["an intent", "--json"]) == 0
    assert '"chosen_model_id": "light-model"' in capsys.readouterr().out


def test_a_pipeline_failure_is_reported_on_stderr(monkeypatch, capsys):
    def boom(text, options):
        raise PipelineError("estimator missing")

    monkeypatch.setattr(cli, "run", boom)
    assert cli.main(["an intent"]) == 1
    assert "estimator missing" in capsys.readouterr().err
