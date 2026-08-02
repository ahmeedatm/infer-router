"""Command-line entry point: run one intent through InferRouter-LLM.

    python -m app.cli "Show the PRB utilisation of cell 12 on site A."
    python -m app.cli "..." --domain ran --criticality high --stage decision
    python -m app.cli "..." --provider api --json

By default the run is local (Ollama) and goes all the way to the judge, so it
costs nothing. ``--provider api`` uses the calibrated OpenRouter pool and is
billed.
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional, Sequence

from app.cli import render
from app.cli.pipeline import PipelineError, RunOptions, run
from app.cli.providers import ProviderError
from app.llm.judge import JudgeError
from app.llm.ollama_client import OllamaClientError
from app.llm.openrouter_client import OpenRouterError

DOMAINS = ("ran", "core", "security", "slice")
CRITICALITIES = ("low", "med", "high")
STAGES = ("decision", "execute", "judge")


def build_parser() -> argparse.ArgumentParser:
    """Declare every flag the CLI accepts."""
    parser = argparse.ArgumentParser(
        prog="python -m app.cli",
        description="Fait passer un intent réseau dans le pipeline InferRouter-LLM "
        "et montre chaque étape : estimation de complexité, arbitrage "
        "tri-critère, appel du modèle retenu, notation par le juge.",
    )
    parser.add_argument("intent", help="L'intent réseau, en langage naturel.")
    parser.add_argument(
        "--domain",
        choices=DOMAINS,
        default="core",
        help="Domaine réseau de l'intent (métadonnée opérateur, non inférée).",
    )
    parser.add_argument(
        "--criticality",
        choices=CRITICALITIES,
        default="med",
        help="Criticité opérateur ; fixe le plancher de qualité q_min.",
    )
    parser.add_argument(
        "--stage",
        choices=STAGES,
        default="judge",
        help="Jusqu'où aller : décision seule, + appel du modèle, + notation.",
    )
    parser.add_argument(
        "--provider",
        choices=("local", "api"),
        default="local",
        help="local = Ollama (gratuit) ; api = pool OpenRouter calibré (facturé).",
    )
    parser.add_argument(
        "--pool",
        choices=("generic", "default"),
        default="generic",
        help="generic = les 2 tiers calibrés ; default = + les 4 spécialistes "
        "de domaine, jamais mesurés.",
    )
    parser.add_argument(
        "--q-min",
        type=float,
        default=None,
        help="Force le plancher de qualité au lieu de le dériver de la criticité.",
    )
    parser.add_argument(
        "--l-max", type=float, default=None, help="Budget de latence (ms)."
    )
    parser.add_argument(
        "--c-max", type=float, default=None, help="Budget de coût (USD par appel)."
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=None,
        help="Plafond de génération du modèle cible.",
    )
    parser.add_argument(
        "--expected-complexity",
        choices=("simple", "medium", "complex"),
        default=None,
        help="Étiquette de vérité-terrain, si elle est connue (sinon l'estimation).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Sortie JSON brute de la trace, au lieu du rapport lisible.",
    )
    return parser


def _options(args: argparse.Namespace) -> RunOptions:
    """Map parsed arguments onto RunOptions, keeping module defaults when unset."""
    overrides = {
        key: value
        for key, value in (
            ("l_max", args.l_max),
            ("c_max", args.c_max),
            ("max_tokens", args.max_tokens),
        )
        if value is not None
    }
    return RunOptions(
        domain=args.domain,
        criticality=args.criticality,
        provider=args.provider,
        pool=args.pool,
        stage=args.stage,
        q_min=args.q_min,
        expected_complexity=args.expected_complexity,
        **overrides,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Parse arguments, run the pipeline, print the trace.

    Returns:
        0 on success, 1 when the run could not complete (every failure is
        reported with its cause on stderr, never swallowed).
    """
    args = build_parser().parse_args(argv)
    try:
        trace = run(args.intent, _options(args))
    except (
        PipelineError,
        ProviderError,
        JudgeError,
        OllamaClientError,
        OpenRouterError,
    ) as exc:
        print(f"Échec : {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(trace.model_dump_json(indent=2))
    else:
        print(render.render(trace))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
