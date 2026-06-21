"""Génération du dataset d'intents télécom par LLM (Plan 3 / ADR-007).

Produit ~250 intents équilibrés sur la matrice domaine x complexité
(4 domaines x 3 complexités), au format de ``data/intents_spike.yaml``. La
génération se fait PAR CELLULE : un appel LLM par couple (domaine, complexité)
produit un lot d'intents pour ce couple.

Les fonctions pures (``build_generation_prompt``, ``parse_generated_intents``,
``dedup_intents``, ``coverage_report``) sont testables sans réseau. Le runner
``main`` fait des appels OpenRouter réels et n'est déclenché que sous
``if __name__ == '__main__'`` — jamais par les tests, ni implicitement.

Discipline de coût (cf. docs/testing-conventions.md) :
  - reprenable : saute toute cellule déjà couverte au quota dans le fichier de sortie,
  - écriture incrémentale : le YAML est réécrit juste après chaque appel payant,
  - validable à bas coût : ``CELLS`` restreint le run à un sous-ensemble de cellules,
  - température 0.7 ici (diversité voulue), à l'inverse des expériences déterministes.

Lancer (réseau réel) :
    .venv/bin/python -m scripts.generate_dataset
Valider une seule cellule à bas coût :
    CELLS=ran:simple N_PER_CELL=5 .venv/bin/python -m scripts.generate_dataset
"""
from __future__ import annotations

import logging
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import ValidationError

from app import config
from app.llm.intents import load_intents
from app.llm.openrouter_client import call_model
from app.llm.schema import Complexity, Domain, Intent

logger = logging.getLogger(__name__)

DOMAINS: tuple[Domain, ...] = ("ran", "core", "security", "slice")
COMPLEXITIES: tuple[Complexity, ...] = ("simple", "medium", "complex")

# Quota par cellule. 12 cellules x 21 ≈ 252 intents (cible ~250 du design).
DEFAULT_N_PER_CELL: int = 21
# Cap de tokens de complétion pour un lot. Les intents "complex" sont longs
# (~300 tokens chacun) : 21 par cellule dépassent 4096. Cap relevé pour ne pas
# tronquer les cellules complexes, tout en bornant le coût (règle 5).
GENERATION_MAX_TOKENS: int = 8192
# Diversité voulue : on échantillonne, on ne cherche pas le déterminisme.
GENERATION_TEMPERATURE: float = 0.7


class GenerationError(RuntimeError):
    """Levée quand un lot ne produit aucun intent exploitable."""


# ════════════════════════════════════════════════════════════════════════════
# Fonctions pures (testables sans réseau)
# ════════════════════════════════════════════════════════════════════════════

# Consignes de gradient de complexité, alignées sur le ch.3 (n entités,
# profondeur d'inférence p, domaines croisés |δ|) et l'en-tête du spike.
_COMPLEXITY_GUIDANCE: dict[str, str] = {
    "simple": (
        "SIMPLE: a state read or a direct query. Inference depth = 1, one single "
        "domain (no cross-domain), 1 to 2 entities. No optimisation, no trade-off. "
        "Example shape: 'What is X on entity Y right now?'"
    ),
    "medium": (
        "MEDIUM: a guided diagnostic or a targeted reconfiguration. Inference "
        "depth = 2, still one domain, a moderate number of entities (sometimes a "
        "correlation between two entities of the same domain). One constraint to "
        "respect, but no multi-domain arbitration."
    ),
    "complex": (
        "COMPLEX: multi-constraint optimisation, arbitration, or multi-domain "
        "reasoning. Inference depth >= 3, a high number of entities, and most "
        "often 2 or more crossed domains. Several SLAs or budgets must hold "
        "simultaneously (latency, energy, revenue, isolation)."
    ),
}

_PROMPT_TEMPLATE = """You generate realistic telecom network intents for a research dataset \
(InferRouter-LLM, a master's thesis). Produce EXACTLY {n} declarative intents as \
a network operator would phrase them.

All {n} intents MUST belong to the SAME domain and the SAME complexity level:
  domain = {domain}
  expected_complexity = {complexity}

Complexity definition for this cell:
{complexity_guidance}

Grounding and realism: anchor every intent in real 3GPP / O-RAN / ETSI ZSM \
scenarios (gNB cells, AMF/SMF/UPF/AUSF network functions, PRB/RSRP/CQI KPIs, \
N3/N6 interfaces, network slices). Use plausible identifiers.

Diversity: the {n} intents must be genuinely different from each other. No \
clones, no near-duplicates that only swap an identifier. Vary the operation, the \
entities and the phrasing.

Carry the complexity gradient through the ATTRIBUTES (number of entities, \
inference depth, crossed domains) described above, NOT merely through sentence \
length. A '{complexity}' intent must read as '{complexity}' on those attributes.

For each intent fill these fields, all coherent with the text:
  id                  short unique slug (lowercase, hyphenated)
  text                the natural-language operator request (English)
  domain              MUST be exactly: {domain}
  expected_complexity MUST be exactly: {complexity}
  criticality         low | med | high (realistic: an URLLC or security incident \
trends high, an mMTC read trends low, an eMBB op trends med)
  slice_type          embb | urllc | mmtc | null (null when the intent is not \
slice-scoped)

Here are reference examples for the style and schema (do NOT copy them, they are \
only a calibration of tone and format):

{seed_block}

Output ONLY valid YAML, rooted on a single top-level key 'intents:' holding a \
list of {n} mappings with the fields above. No prose, no markdown commentary, \
no code fence."""


def _select_seeds(
    seed_examples: tuple[Intent, ...],
    domain: Domain,
    complexity: Complexity,
) -> tuple[Intent, ...]:
    """Pick up to 3 cell-relevant seeds, deterministic.

    Priority: same domain and complexity, then same complexity, then same
    domain, then any. Aligning the few-shot on the target complexity matters
    for the complexity gradient (cf. spike H-C).
    """
    same_both = [s for s in seed_examples if s.domain == domain and s.expected_complexity == complexity]
    same_cx = [s for s in seed_examples if s.expected_complexity == complexity and s not in same_both]
    same_dom = [s for s in seed_examples if s.domain == domain and s not in same_both and s not in same_cx]
    rest = [s for s in seed_examples if s not in same_both and s not in same_cx and s not in same_dom]
    ordered = same_both + same_cx + same_dom + rest
    return tuple(ordered[:3])


def _seed_block(seed_examples: tuple[Intent, ...]) -> str:
    """Render a few-shot YAML block from the given seed intents (deterministic)."""
    chosen = seed_examples[:3]
    lines: list[str] = ["intents:"]
    for seed in chosen:
        slice_value = seed.slice_type if seed.slice_type is not None else "null"
        lines.append(f"  - id: {seed.id}")
        lines.append(f'    text: "{seed.text}"')
        lines.append(f"    domain: {seed.domain}")
        lines.append(f"    expected_complexity: {seed.expected_complexity}")
        lines.append(f"    criticality: {seed.criticality}")
        lines.append(f"    slice_type: {slice_value}")
    return "\n".join(lines)


def build_generation_prompt(
    domain: Domain,
    complexity: Complexity,
    n: int,
    seed_examples: tuple[Intent, ...],
) -> str:
    """Build the LLM prompt for one cell (domain x complexity).

    ``domain`` and ``complexity`` are fixed by the cell; the model only fills
    ``text``/``criticality``/``slice_type`` coherently. The prompt imposes
    realism (3GPP / O-RAN grounding), diversity, and an attribute-borne
    complexity gradient (entities, inference depth, crossed domains).
    """
    return _PROMPT_TEMPLATE.format(
        n=n,
        domain=domain,
        complexity=complexity,
        complexity_guidance=_COMPLEXITY_GUIDANCE[complexity],
        seed_block=_seed_block(_select_seeds(seed_examples, domain, complexity)),
    )


def _strip_code_fence(raw_text: str) -> str:
    """Remove a leading/trailing markdown code fence if the model added one."""
    text = raw_text.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    # Drop the opening fence line (``` or ```yaml) and a closing fence if present.
    lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines)


def _coerce_entry(entry: Any, domain: Domain, complexity: Complexity) -> Optional[Intent]:
    """Validate one raw entry into an Intent, forcing the cell's domain/complexity.

    Returns ``None`` for any malformed entry (logged, never raised) so a single
    bad item never kills the whole batch.
    """
    if not isinstance(entry, dict):
        logger.warning("Skipping non-mapping generated entry: %r", entry)
        return None
    forced = {**entry, "domain": domain, "expected_complexity": complexity}
    try:
        return Intent(**forced)
    except (ValidationError, TypeError) as exc:
        label = entry.get("id", "<no id>") if isinstance(entry, dict) else "<?>"
        logger.warning("Skipping malformed generated intent '%s': %s", label, exc)
        return None


def parse_generated_intents(
    raw_text: str,
    domain: Domain,
    complexity: Complexity,
) -> tuple[Intent, ...]:
    """Parse a generated YAML batch into validated Intents for one cell.

    Forces ``domain`` and ``expected_complexity`` to the cell's values to
    prevent drift. Malformed entries are skipped with a log. Raises
    :class:`GenerationError` only when nothing parses (unparseable YAML, wrong
    shape, or zero valid intent).
    """
    cleaned = _strip_code_fence(raw_text)
    try:
        document = yaml.safe_load(cleaned)
    except yaml.YAMLError as exc:
        raise GenerationError(f"Generated batch is not valid YAML: {exc}") from exc

    if not isinstance(document, dict) or not isinstance(document.get("intents"), list):
        raise GenerationError(
            "Generated batch has no top-level 'intents:' list."
        )

    intents = tuple(
        intent
        for entry in document["intents"]
        if (intent := _coerce_entry(entry, domain, complexity)) is not None
    )
    if not intents:
        raise GenerationError(
            f"No valid intent parsed for cell ({domain}, {complexity})."
        )
    return intents


def _normalize_text(text: str) -> str:
    """Normalize an intent text for dedup: lowercase, collapsed whitespace."""
    return " ".join(text.lower().split())


def dedup_intents(intents: tuple[Intent, ...]) -> tuple[Intent, ...]:
    """Drop duplicates by normalized text, keeping first occurrence. Pure."""
    seen: set[str] = set()
    kept: list[Intent] = []
    for intent in intents:
        key = _normalize_text(intent.text)
        if key in seen:
            continue
        seen.add(key)
        kept.append(intent)
    return tuple(kept)


def coverage_report(intents: tuple[Intent, ...]) -> dict[str, Any]:
    """Build a domain x complexity matrix plus criticality/slice counts. Pure."""
    matrix: dict[str, dict[str, int]] = {
        domain: {complexity: 0 for complexity in COMPLEXITIES}
        for domain in DOMAINS
    }
    criticality = {"low": 0, "med": 0, "high": 0}
    slice_counts = {"embb": 0, "urllc": 0, "mmtc": 0, "none": 0}
    for intent in intents:
        matrix[intent.domain][intent.expected_complexity] += 1
        criticality[intent.criticality] += 1
        slice_key = intent.slice_type if intent.slice_type is not None else "none"
        slice_counts[slice_key] += 1
    return {
        "total": len(intents),
        "matrix": matrix,
        "criticality": criticality,
        "slice_type": slice_counts,
    }


# ════════════════════════════════════════════════════════════════════════════
# Runner réseau (appels OpenRouter réels) — NON exercé par les tests
# ════════════════════════════════════════════════════════════════════════════


def _intent_to_mapping(intent: Intent) -> "OrderedDict[str, Any]":
    """Render an Intent as an ordered mapping for stable YAML output."""
    mapping: "OrderedDict[str, Any]" = OrderedDict()
    mapping["id"] = intent.id
    mapping["text"] = intent.text
    mapping["domain"] = intent.domain
    mapping["expected_complexity"] = intent.expected_complexity
    mapping["criticality"] = intent.criticality
    mapping["slice_type"] = intent.slice_type
    return mapping


def _dump_dataset(intents: tuple[Intent, ...]) -> str:
    """Serialize the full dataset to YAML (single 'intents:' root)."""
    payload = {"intents": [dict(_intent_to_mapping(i)) for i in intents]}
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=1000)


def _load_existing(path: Path) -> tuple[Intent, ...]:
    """Load the partial dataset already written (resume), or empty if absent."""
    if not path.exists():
        return ()
    return load_intents(str(path))


def _write_dataset(path: Path, intents: tuple[Intent, ...]) -> None:
    """Write the dataset YAML immediately (incremental persistence)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_dataset(intents), encoding="utf-8")


def _parse_cells_env(raw: Optional[str]) -> tuple[tuple[Domain, Complexity], ...]:
    """Parse the CELLS env var ('ran:simple,core:complex') into validated cells.

    Empty/unset means the full matrix. Unknown domain/complexity fails fast.
    """
    if not raw or not raw.strip():
        return tuple((d, c) for d in DOMAINS for c in COMPLEXITIES)
    cells: list[tuple[Domain, Complexity]] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            raise GenerationError(f"Invalid CELLS token '{token}' (expected domain:complexity).")
        domain, complexity = (part.strip() for part in token.split(":", 1))
        if domain not in DOMAINS:
            raise GenerationError(f"Unknown domain '{domain}' in CELLS.")
        if complexity not in COMPLEXITIES:
            raise GenerationError(f"Unknown complexity '{complexity}' in CELLS.")
        cells.append((domain, complexity))  # type: ignore[arg-type]
    return tuple(cells)


def _cell_count(intents: tuple[Intent, ...], domain: Domain, complexity: Complexity) -> int:
    """How many intents already cover a given cell."""
    return sum(
        1 for i in intents
        if i.domain == domain and i.expected_complexity == complexity
    )


def _generate_cell(
    domain: Domain,
    complexity: Complexity,
    n: int,
    seed_examples: tuple[Intent, ...],
) -> tuple[Intent, ...]:
    """One paid call: generate, parse and dedup a batch for one cell."""
    prompt = build_generation_prompt(domain, complexity, n, seed_examples)
    response = call_model(
        config.GENERATION_MODEL,
        prompt,
        temperature=GENERATION_TEMPERATURE,
        max_tokens=GENERATION_MAX_TOKENS,
    )
    parsed = parse_generated_intents(response.text, domain, complexity)
    return dedup_intents(parsed)


def main() -> None:
    """Resumable, incremental dataset generation across the requested cells."""
    logging.basicConfig(level=getattr(logging, config.LOG_LEVEL, logging.INFO))
    n_per_cell = int(os.getenv("N_PER_CELL", str(DEFAULT_N_PER_CELL)))
    cells = _parse_cells_env(os.getenv("CELLS"))
    out_path = Path(config.DATASET_PATH)

    seed_examples = load_intents(config.INTENTS_SPIKE_PATH)
    intents = _load_existing(out_path)
    if intents:
        print(f"Reprise : {len(intents)} intent(s) déjà présents dans {out_path}.\n")

    seen_texts = {_normalize_text(i.text) for i in intents}
    for domain, complexity in cells:
        have = _cell_count(intents, domain, complexity)
        if have >= n_per_cell:
            print(f"[skip] {domain}:{complexity} déjà couvert ({have}/{n_per_cell}).")
            continue
        print(f"[gen ] {domain}:{complexity} ({have}/{n_per_cell}) via {config.GENERATION_MODEL} ...", flush=True)
        batch = _generate_cell(domain, complexity, n_per_cell, seed_examples)
        fresh = tuple(i for i in batch if _normalize_text(i.text) not in seen_texts)
        seen_texts.update(_normalize_text(i.text) for i in fresh)
        intents = intents + fresh
        _write_dataset(out_path, intents)  # incrémental : persiste après l'appel payant
        print(f"       +{len(fresh)} intent(s) -> {out_path} (total {len(intents)}).")

    report = coverage_report(intents)
    print("\nCouverture finale :")
    print(yaml.safe_dump(report, sort_keys=False, allow_unicode=True))


if __name__ == "__main__":
    main()
