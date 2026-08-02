"""Turns a :class:`~app.cli.trace.Trace` into readable terminal output.

Pure formatting: every function takes a trace (or one of its stages) and
returns lines, so the rendering is unit-testable without running the pipeline.
Labels are in French because this output is read during the defence; the code
itself stays in English, per project conventions.
"""
from __future__ import annotations

from typing import Optional

from app.cli.trace import DecisionStage, Trace

_WIDTH = 78
_RULE = "═" * _WIDTH
_THIN = "─" * _WIDTH

# Human labels for the length-independent attributes the estimator reads.
_FEATURE_LABELS = {
    "n_entities": "entités (n)",
    "n_constraints": "contraintes (p)",
    "n_domains": "domaines (|δ|)",
    "n_numbers": "valeurs numériques",
    "n_tokens": "tokens",
    "n_sentences": "phrases",
}


def _field(label: str, value: str) -> str:
    """One aligned ``label : value`` line."""
    return f"  {label:<16}: {value}"


def _section(number: int, title: str) -> list[str]:
    """Section header with its ordinal."""
    return ["", f"▸ {number}. {title}", ""]


def _budget(value: float) -> str:
    """Format an SLA budget, marking the effectively unbounded default."""
    return "illimité" if value >= 1e9 else f"{value:,.6g}".replace(",", " ")


def render_intent(trace: Trace, number: int = 1) -> list[str]:
    """The intent as submitted, with the operator metadata that came with it."""
    return _section(number, "INTENT") + [
        _field("texte", trace.intent.text),
        _field("domaine", f"{trace.intent.domain}  (métadonnée opérateur)"),
        _field("criticité", trace.intent.criticality),
    ]


def render_complexity(trace: Trace, number: int = 2) -> list[str]:
    """Attributes read by the estimator, the class it predicted, and its cost."""
    stage = trace.complexity
    attributes = "  ".join(
        f"{_FEATURE_LABELS.get(name, name)}={value:g}"
        for name, value in stage.features.items()
    )
    return _section(number, "ESTIMATION DE COMPLEXITÉ") + [
        _field("attributs", attributes),
        _field("classe prédite", stage.label),
        _field("temps", f"{stage.elapsed_ms:.1f} ms"),
    ]


def _candidate_row(row) -> str:
    """One line of the candidate table."""
    sla = "oui" if row.within_sla else "NON"
    floor = "oui" if row.meets_floor else "non"
    mark = "  ◀ choisi" if row.chosen else ""
    return (
        f"  {row.model_id:<34}{row.tier:<7}{row.q_expected:<8.2f}"
        f"{row.cost:<11.6f}{row.latency_ms:>8.0f} ms  {sla:<5}{floor}{mark}"
    )


def render_decision(decision: DecisionStage, number: int = 3) -> list[str]:
    """Quality floor, budgets, every scored candidate, and the outcome."""
    origin = "forcé en ligne de commande" if decision.q_min_forced else "dérivé de la criticité"
    header = (
        f"  {'modèle':<34}{'tier':<7}{'q att.':<8}{'coût $':<11}"
        f"{'latence':>11}  {'SLA':<5}≥q_min"
    )
    lines = _section(number, "ARBITRAGE TRI-CRITÈRE") + [
        _field("plancher q_min", f"{decision.q_min:.2f}  ({origin})"),
        _field(
            "budgets SLA",
            f"latence ≤ {_budget(decision.l_max)} ms, "
            f"coût ≤ {_budget(decision.c_max)} $",
        ),
        "",
        header,
        f"  {_THIN[:_WIDTH - 2]}",
    ]
    lines.extend(_candidate_row(row) for row in decision.candidates)
    lines.extend(
        [
            "",
            _field("admissibles", f"{decision.admissible_count} candidat(s) dans le SLA"),
            _field("décision", decision.rationale),
        ]
    )
    lines.extend(_render_saving(decision))
    return lines


def _render_saving(decision: DecisionStage) -> list[str]:
    """Cost gap between the chosen model and the most expensive candidate."""
    chosen = next((c for c in decision.candidates if c.chosen), None)
    if chosen is None or not decision.candidates:
        return []
    dearest = max(decision.candidates, key=lambda c: c.cost)
    if dearest.cost <= 0.0 or dearest.model_id == chosen.model_id:
        return []
    saved = 100.0 * (1.0 - chosen.cost / dearest.cost)
    return [
        _field(
            "économie",
            f"{saved:.0f} % vs le candidat le plus cher ({dearest.model_id})",
        )
    ]


def render_execution(trace: Trace, number: int = 4) -> list[str]:
    """The real call: which model served the tier, and what it cost."""
    stage = trace.execution
    if stage is None:
        return []
    chosen = trace.decision.chosen_model_id or "?"
    substitution = (
        "" if stage.serving_model_id == chosen else f"  (sert le pool « {chosen} »)"
    )
    response = stage.response
    return _section(4, "EXÉCUTION") + [
        _field("fournisseur", "local (Ollama)" if stage.provider == "local" else "API (OpenRouter)"),
        _field("modèle appelé", f"{stage.serving_model_id}{substitution}"),
        _field("latence", f"{response.latency_ms:.0f} ms"),
        _field(
            "tokens",
            f"{response.prompt_tokens} prompt / {response.completion_tokens} complétion",
        ),
        _field("coût mesuré", f"{response.cost_estimate:.6f} $"),
        "",
        "  ┌─ réponse " + "─" * (_WIDTH - 13),
        *(f"  │ {line}" for line in response.text.strip().splitlines()),
        "  └" + "─" * (_WIDTH - 3),
    ]


def render_evaluation(trace: Trace, number: int = 5) -> list[str]:
    """The RocketEval checklist, criterion by criterion, and the resulting q."""
    stage = trace.evaluation
    if stage is None:
        return []
    verdicts = stage.score.checklist
    passed = sum(1 for ok in verdicts.values() if ok)
    lines = _section(number, "ÉVALUATION (RocketEval)") + [
        _field("checklist", f"{stage.checklist_model}  ({len(verdicts)} critères)"),
        _field("juge", stage.judge_model),
        "",
    ]
    lines.extend(
        f"  [{'oui' if ok else 'NON'}] {criterion}" for criterion, ok in verdicts.items()
    )
    lines.extend(
        ["", _field("score q", f"{stage.score.q:.2f}  ({passed}/{len(verdicts)})")]
    )
    return lines


def _floor_verdict(trace: Trace) -> Optional[str]:
    """Whether the measured quality actually cleared the floor the router used."""
    if trace.evaluation is None:
        return None
    measured = trace.evaluation.score.q
    floor = trace.decision.q_min
    status = "plancher respecté" if measured >= floor else "PLANCHER MANQUÉ"
    return f"{measured:.2f} vs plancher {floor:.2f} → {status}"


def render_summary(trace: Trace, number: int = 6) -> list[str]:
    """One-glance recap: what was decided, what it delivered, what it cost."""
    chosen = next((c for c in trace.decision.candidates if c.chosen), None)
    path = f"{trace.complexity.label} → " + (
        f"tier {chosen.tier} ({chosen.model_id})" if chosen else "aucun modèle admissible"
    )
    lines = _section(number, "RÉSUMÉ") + [_field("chemin", path)]
    if chosen is not None:
        lines.append(_field("q attendue", f"{chosen.q_expected:.2f}"))
    verdict = _floor_verdict(trace)
    if verdict is not None:
        lines.append(_field("q mesurée", verdict))
    if trace.execution is not None:
        response = trace.execution.response
        lines.append(
            _field(
                "réel",
                f"{response.latency_ms:.0f} ms, {response.cost_estimate:.6f} $",
            )
        )
    return lines


def render(trace: Trace) -> str:
    """Full human-readable report for one run.

    Sections are numbered in the order they actually ran, so a run stopped at
    the decision stage does not show a gap where execution would have been.
    """
    sections = [
        render_intent,
        render_complexity,
        lambda t, n: render_decision(t.decision, n),
        render_execution,
        render_evaluation,
        render_summary,
    ]
    lines = [_RULE, " InferRouter-LLM — traitement d'un intent", _RULE]
    number = 1
    for section in sections:
        body = section(trace, number)
        if body:
            lines.extend(body)
            number += 1
    lines.append("")
    return "\n".join(lines)
