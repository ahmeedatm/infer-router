#!/usr/bin/env python3
"""Route (and optionally answer) a single network intent from the command line.

This is a thin operator-facing wrapper around the library API:

    route()      -> decides which model should serve the intent (no network).
    call_model() -> actually queries the chosen model (needs OPENROUTER_API_KEY).

Examples
--------
Decision only (offline, no credits spent)::

    .venv/bin/python run_intent.py \
        "Create a low-latency URLLC slice for connected vehicles." \
        --domain slice --complexity complex --criticality high

Decision + real answer from the chosen model::

    .venv/bin/python run_intent.py "Block host A from host B on the edge switch." \
        --domain security --complexity simple --criticality med --call

By default the complexity you pass is used directly. Pass ``--estimate`` to
predict it from the text instead (requires the trained estimator bundle
``data/complexity_estimator.joblib`` -- run
``python -m experiments.train_complexity_estimator`` to build it).
"""

from __future__ import annotations

import argparse
import sys

from app import config
from app.llm.inferrouter import route
from app.llm.openrouter_client import OpenRouterError, call_model
from app.llm.pool import PoolModel
from app.llm.schema import Intent

DOMAINS = ("ran", "core", "security", "slice")
COMPLEXITIES = ("simple", "medium", "complex")
CRITICALITIES = ("low", "med", "high")
SLICE_TYPES = ("embb", "urllc", "mmtc")

# Final campaign pool (chapter 5 benchmark): light qwen vs heavy opus, two
# generic models only -- no domain specialists, which were just the heavy model
# relabeled and masked any light/heavy arbitrage.
DEFAULT_LIGHT = "qwen/qwen-2.5-72b-instruct"
DEFAULT_HEAVY = "anthropic/claude-opus-4.8"


def _build_pool(light_id: str, heavy_id: str) -> tuple[PoolModel, ...]:
    """Two-generic pool (light, heavy) with cost/latency profiles from config."""
    light = PoolModel(
        model_id=light_id, tier="light", domain=None,
        cost=config.POOL_LIGHT_COST, latency_ms=config.POOL_LIGHT_LATENCY_MS,
    )
    heavy = PoolModel(
        model_id=heavy_id, tier="heavy", domain=None,
        cost=config.POOL_HEAVY_COST, latency_ms=config.POOL_HEAVY_LATENCY_MS,
    )
    return (light, heavy)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route a network intent to the best-suited LLM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("text", help="The intent, in natural language.")
    parser.add_argument("--domain", choices=DOMAINS, default="slice",
                        help="Network domain of the intent (default: slice).")
    parser.add_argument("--complexity", choices=COMPLEXITIES, default="medium",
                        help="Complexity used for routing (default: medium). "
                             "Ignored when --estimate is set.")
    parser.add_argument("--criticality", choices=CRITICALITIES, default="med",
                        help="Operational criticality (default: med).")
    parser.add_argument("--slice-type", choices=SLICE_TYPES, default=None,
                        help="Slice family, if applicable (default: none).")
    parser.add_argument("--light", default=DEFAULT_LIGHT,
                        help=f"Light generic model id (default: {DEFAULT_LIGHT}).")
    parser.add_argument("--heavy", default=DEFAULT_HEAVY,
                        help=f"Heavy generic model id (default: {DEFAULT_HEAVY}).")
    parser.add_argument("--l-max", type=float, default=config.BENCH_L_MAX_MS,
                        help="Max tolerated latency in ms (default: unbounded, "
                             "like the benchmark). Tighten below a tier latency "
                             "profile to exclude it via admissibility.")
    parser.add_argument("--c-max", type=float, default=config.BENCH_C_MAX,
                        help="Max tolerated cost per inference (default: "
                             "unbounded). Tighten below a tier cost profile to "
                             "exclude it via admissibility.")
    parser.add_argument("--estimate", action="store_true",
                        help="Predict complexity from text instead of using "
                             "--complexity (needs the trained estimator).")
    parser.add_argument("--call", action="store_true",
                        help="Also query the chosen model for a real answer "
                             "(needs OPENROUTER_API_KEY and credits).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    intent = Intent(
        id="cli",
        text=args.text,
        domain=args.domain,
        expected_complexity=args.complexity,
        criticality=args.criticality,
        slice_type=args.slice_type,
    )

    pool = _build_pool(args.light, args.heavy)

    # When --estimate is not set, feed the provided complexity so route() does
    # not need the persisted sklearn bundle.
    complexity = None if args.estimate else intent.expected_complexity
    try:
        decision = route(intent, pool=pool, l_max=args.l_max, c_max=args.c_max,
                         complexity=complexity)
    except (FileNotFoundError, ImportError) as exc:
        print(f"[erreur] estimation de complexité impossible : {exc}\n"
              "  -> entraîne l'estimateur "
              "(python -m experiments.train_complexity_estimator)\n"
              "     ou relance sans --estimate.", file=sys.stderr)
        return 2

    print("== Décision de routage ==")
    print(f"  intent      : {intent.text}")
    print(f"  pool        : léger {args.light} | lourd {args.heavy}")
    print(f"  domaine     : {intent.domain} | complexité : {decision.complexity} "
          f"| criticité : {intent.criticality}")
    print(f"  modèle      : {decision.model_id or '(aucun modèle admissible)'}")
    print(f"  raison      : {decision.rationale}")
    print(f"  admissibles : {decision.admissible_count} "
          f"(budgets L<={args.l_max:g} ms, C<={args.c_max:g})")

    if not args.call:
        print("\n(décision seule. Ajoute --call pour obtenir la réponse du modèle.)")
        return 0

    if decision.model_id is None:
        print("\n[stop] aucun modèle admissible : rien à appeler.", file=sys.stderr)
        return 1

    if not config.OPENROUTER_API_KEY:
        print("\n[stop] OPENROUTER_API_KEY absente : impossible d'appeler le modèle.\n"
              "  -> renseigne-la dans .env, puis relance avec --call.",
              file=sys.stderr)
        return 1

    print(f"\n== Appel du modèle {decision.model_id} ==")
    try:
        resp = call_model(decision.model_id, intent.text,
                          max_tokens=config.RESPONSE_MAX_TOKENS)
    except OpenRouterError as exc:
        print(f"[erreur] appel OpenRouter échoué : {exc}\n"
              "  (crédits épuisés ? modèle indisponible ? clé invalide ?)",
              file=sys.stderr)
        return 1

    print(resp.text)
    print(f"\n  latence : {resp.latency_ms:.0f} ms | "
          f"tokens : {resp.prompt_tokens}+{resp.completion_tokens} | "
          f"coût estimé : {resp.cost_estimate:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
