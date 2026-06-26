"""Corrections d'annotation du dataset, issues de la revue d'expert réseau.

Applique les corrections ciblées de façon tracée et reproductible plutôt qu'à
la main. Conventions retenues :

- Criticité = impact de l'action. Une lecture de KPI ne dépasse pas `med`, sauf
  lectures de sécurité / compteurs d'échec (criticité intrinsèque, conservées).
- Domaine au niveau complex = point d'entrée de l'intent. Seuls les intents
  clairement mal domainés sont reclassés ; les transverses gardent leur domaine.
- Complexité selon n(e)/p(e)/|delta(e)|.

Lancer :  .venv/bin/python -m scripts.fix_dataset_annotations
"""
from __future__ import annotations

from pathlib import Path

from app import config
from scripts.generate_dataset import _load_existing, _write_dataset

# Lectures URLLC (KPI purs) sur-cotées high -> med (impact d'une lecture borné).
CRITICALITY_TO_MED = (
    "core-read-upf-n3-packet-loss",
    "core-read-upf-throughput-urllc",
    "slice-read-ssr-urllc",
    "slice-read-latency-urllc",
    "slice-read-jitter-urllc",
    "slice-read-pdu-session-count",
    "slice-read-isolation-level",
    "slice-read-ul-throughput-urllc",
    "slice-read-upf-assigned",
    "ran-read-cell-availability",
)

# Intents clairement core, mal étiquetés ran (AMF/UPF dominants).
DOMAIN_TO_CORE = (
    "ran-amf-load-rebalance-slice-aware-registration",
    "ran-qos-flow-remap-upf-relocation-latency",
)

# Complex déguisé en medium (énumération NF + rotation coordonnée sans coupure).
COMPLEXITY_TO_COMPLEX = ("core-ausf-certificate-expiry",)


def apply_corrections(intents):
    """Retourne un nouveau tuple d'Intents corrigés (immuable) + un journal."""
    by_id = {i.id: i for i in intents}
    log: list[str] = []

    def _update(intent_id, field, value):
        if intent_id not in by_id:
            log.append(f"  INTROUVABLE: {intent_id} ({field}) — ignoré")
            return
        current = by_id[intent_id]
        old = getattr(current, field)
        if old == value:
            log.append(f"  déjà OK: {intent_id} {field}={value}")
            return
        by_id[intent_id] = current.model_copy(update={field: value})
        log.append(f"  {intent_id}: {field} {old} -> {value}")

    for iid in CRITICALITY_TO_MED:
        _update(iid, "criticality", "med")
    for iid in DOMAIN_TO_CORE:
        _update(iid, "domain", "core")
    for iid in COMPLEXITY_TO_COMPLEX:
        _update(iid, "expected_complexity", "complex")

    # Préserve l'ordre d'origine.
    corrected = tuple(by_id[i.id] for i in intents)
    return corrected, log


def _coverage(intents) -> str:
    from collections import Counter
    c = Counter((i.domain, i.expected_complexity) for i in intents)
    lines = [f"Total : {len(intents)}"]
    for dom in ("ran", "core", "security", "slice"):
        cells = "  ".join(f"{cx}={c.get((dom, cx), 0)}" for cx in ("simple", "medium", "complex"))
        lines.append(f"  {dom:9s} {cells}")
    return "\n".join(lines)


def main() -> None:
    path = Path(config.DATASET_PATH)
    intents = _load_existing(path)
    corrected, log = apply_corrections(intents)

    print("Corrections appliquées :")
    print("\n".join(log))
    _write_dataset(path, corrected)
    print(f"\nÉcrit : {path}")
    print("\nCouverture finale :")
    print(_coverage(corrected))


if __name__ == "__main__":
    main()
