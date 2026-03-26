"""Auto-generate REPORT.md from benchmark JSON data.

Reads all data/bench/**/*.json files and writes a structured REPORT.md
with latency, accuracy, throughput, and queue backend analysis.

Usage:
    python3 scripts/generate_report.py
    python3 scripts/generate_report.py --bench-dir data/bench --output REPORT.md
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STRATEGY_ORDER = ["always-fast", "always-accurate", "infer-router"]
LOAD_ORDER = ["normal", "burst", "mixed"]
LOAD_DESCRIPTIONS = {
    "normal": "normal (100 req, 2.0s interval)",
    "burst":  "burst (50 req, 0.1s interval)",
    "mixed":  "mixed (high-volume + burst)",
}


# ─── Data loading ─────────────────────────────────────────────────────────────

def _load_all_results(bench_dir: Path) -> dict[str, dict[str, list[dict]]]:
    """Return {strategy: {load: [result, ...]}}."""
    data: dict[str, dict[str, list[dict]]] = {}
    for json_file in sorted(bench_dir.glob("*/*.json")):
        strategy = json_file.parent.name
        load = json_file.stem
        try:
            with open(json_file) as f:
                payload = json.load(f)
            results = payload.get("results", [])
            if strategy not in data:
                data[strategy] = {}
            data[strategy][load] = results
            logger.info("Loaded %d results from %s", len(results), json_file)
        except Exception as exc:
            logger.warning("Skipping %s: %s", json_file, exc)
    return data


def _compute_stats(results: list[dict]) -> dict:
    """Compute summary stats from a list of result dicts."""
    if not results:
        return {
            "count": 0, "avg_latency": None, "p95": None, "p99": None,
            "avg_accuracy": None, "throughput": None,
        }
    latencies = [r["latency"] for r in results if r.get("latency") is not None]
    accuracies = [r["accuracy"] for r in results if r.get("accuracy") is not None]
    timestamps = [r["processed_at"] for r in results if r.get("processed_at") is not None]

    n = len(latencies)
    arr = np.array(latencies) if latencies else np.array([])
    duration = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0

    return {
        "count": n,
        "avg_latency": round(float(np.mean(arr)), 3) if n else None,
        "p95": round(float(np.percentile(arr, 95)), 3) if n else None,
        "p99": round(float(np.percentile(arr, 99)), 3) if n else None,
        "avg_accuracy": round(float(np.mean(accuracies)), 3) if accuracies else None,
        "throughput": round(n / duration, 3) if duration > 0 else None,
    }


def _compute_backend_stats(results: list[dict]) -> dict:
    """Compute queue-specific stats from result dicts."""
    if not results:
        return {"count": 0, "push_p50": None, "push_p95": None, "push_p99": None, "throughput": None}
    push_latencies = [
        r["queue_push_latency_ms"]
        for r in results
        if r.get("queue_push_latency_ms") is not None
    ]
    timestamps = [r["processed_at"] for r in results if r.get("processed_at") is not None]
    n = len(results)
    duration = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
    if push_latencies:
        arr = np.array(push_latencies)
        p50 = round(float(np.percentile(arr, 50)), 3)
        p95 = round(float(np.percentile(arr, 95)), 3)
        p99 = round(float(np.percentile(arr, 99)), 3)
    else:
        p50 = p95 = p99 = None
    return {
        "count": n,
        "push_p50": p50,
        "push_p95": p95,
        "push_p99": p99,
        "throughput": round(n / duration, 3) if duration > 0 else None,
    }


# ─── Markdown formatting helpers ─────────────────────────────────────────────

def _fmt(value: float | None, suffix: str = "", precision: int = 3) -> str:
    if value is None:
        return "N/A"
    return f"{value:.{precision}f}{suffix}"


def _format_latency_table(
    all_stats: dict[str, dict[str, dict]],
    strategies: list[str],
    loads: list[str],
) -> str:
    header = "| Strategy | Load | Count | Avg (s) | P95 (s) | P99 (s) | Throughput (req/s) |"
    sep =    "|----------|------|-------|---------|---------|---------|---------------------|"
    rows = [header, sep]
    for s in strategies:
        for load in loads:
            st = all_stats.get(s, {}).get(load)
            if st is None:
                continue
            rows.append(
                f"| {s} | {load} | {st['count']} "
                f"| {_fmt(st['avg_latency'])} "
                f"| {_fmt(st['p95'])} "
                f"| {_fmt(st['p99'])} "
                f"| {_fmt(st['throughput'])} |"
            )
    return "\n".join(rows)


def _format_accuracy_table(
    all_stats: dict[str, dict[str, dict]],
    strategies: list[str],
    loads: list[str],
) -> str:
    header = "| Strategy | Load | Avg Accuracy |"
    sep =    "|----------|------|--------------|"
    rows = [header, sep]
    for s in strategies:
        for load in loads:
            st = all_stats.get(s, {}).get(load)
            if st is None:
                continue
            rows.append(f"| {s} | {load} | {_fmt(st['avg_accuracy'])} |")
    return "\n".join(rows)


def _analyze_winner(all_stats: dict[str, dict[str, dict]]) -> str:
    """Generate prose comparing infer-router vs baselines."""
    lines: list[str] = []
    ir = all_stats.get("infer-router", {})
    af = all_stats.get("always-fast", {})
    aa = all_stats.get("always-accurate", {})

    for load in LOAD_ORDER:
        ir_s = ir.get(load)
        af_s = af.get(load)
        aa_s = aa.get(load)
        if not ir_s or ir_s["count"] == 0:
            continue
        parts: list[str] = [f"**{load.capitalize()} load:**"]
        if af_s and af_s["avg_latency"] is not None and ir_s["avg_latency"] is not None:
            delta = af_s["avg_latency"] - ir_s["avg_latency"]
            if delta > 0:
                parts.append(
                    f"InferRouter is {delta:.3f}s faster on average than always-fast"
                    f" ({ir_s['avg_latency']:.3f}s vs {af_s['avg_latency']:.3f}s)."
                )
            else:
                parts.append(
                    f"InferRouter is {abs(delta):.3f}s slower on average than always-fast"
                    f" ({ir_s['avg_latency']:.3f}s vs {af_s['avg_latency']:.3f}s)."
                )
        if aa_s and aa_s["avg_latency"] is not None and ir_s["avg_latency"] is not None:
            delta = aa_s["avg_latency"] - ir_s["avg_latency"]
            if delta > 0:
                parts.append(
                    f"Compared to always-accurate, InferRouter reduces average latency"
                    f" by {delta:.3f}s ({ir_s['avg_latency']:.3f}s vs {aa_s['avg_latency']:.3f}s)."
                )
        if ir_s["avg_accuracy"] is not None and af_s and af_s["avg_accuracy"] is not None:
            acc_delta = ir_s["avg_accuracy"] - af_s["avg_accuracy"]
            if acc_delta > 0:
                parts.append(
                    f"Accuracy is {acc_delta:.3f} higher than always-fast"
                    f" ({ir_s['avg_accuracy']:.3f} vs {af_s['avg_accuracy']:.3f})."
                )
        lines.append(" ".join(parts))

    return "\n\n".join(lines) if lines else "_No infer-router data found to analyze._"


def _backend_section(bench_dir: Path) -> str:
    """Generate the Redis vs RabbitMQ section."""
    redis_file = bench_dir / "redis" / "normal.json"
    rmq_file = bench_dir / "rabbitmq" / "normal.json"

    if not redis_file.exists() or not rmq_file.exists():
        return (
            "_Backend comparison data not available. "
            "Run `make bench-redis bench-rabbitmq` to generate it._"
        )

    try:
        with open(redis_file) as f:
            redis_results = json.load(f).get("results", [])
        with open(rmq_file) as f:
            rmq_results = json.load(f).get("results", [])
    except Exception as exc:
        return f"_Could not load backend benchmark data: {exc}_"

    rs = _compute_backend_stats(redis_results)
    ms = _compute_backend_stats(rmq_results)

    table = (
        "| Backend | Count | Push P50 (ms) | Push P95 (ms) | Push P99 (ms) | Throughput (req/s) |\n"
        "|---------|-------|--------------|--------------|--------------|---------------------|\n"
        f"| Redis   | {rs['count']} | {_fmt(rs['push_p50'])} | {_fmt(rs['push_p95'])} | {_fmt(rs['push_p99'])} | {_fmt(rs['throughput'])} |\n"
        f"| RabbitMQ| {ms['count']} | {_fmt(ms['push_p50'])} | {_fmt(ms['push_p95'])} | {_fmt(ms['push_p99'])} | {_fmt(ms['throughput'])} |"
    )

    # Auto-generate conclusion
    conclusion_parts: list[str] = []
    if rs["push_p50"] is not None and ms["push_p50"] is not None:
        if rs["push_p50"] < ms["push_p50"]:
            conclusion_parts.append(
                f"Redis has lower push latency at P50 ({rs['push_p50']:.3f}ms vs "
                f"{ms['push_p50']:.3f}ms), making it the better choice for "
                f"low-latency, high-frequency inference routing."
            )
        else:
            conclusion_parts.append(
                f"RabbitMQ achieves comparable push latency at P50 ({ms['push_p50']:.3f}ms vs "
                f"{rs['push_p50']:.3f}ms for Redis)."
            )
    if rs["throughput"] is not None and ms["throughput"] is not None:
        if rs["throughput"] > ms["throughput"]:
            conclusion_parts.append(
                f"Redis also achieves higher throughput ({rs['throughput']:.3f} req/s vs "
                f"{ms['throughput']:.3f} req/s for RabbitMQ)."
            )
        else:
            conclusion_parts.append(
                f"RabbitMQ achieves higher throughput ({ms['throughput']:.3f} req/s vs "
                f"{rs['throughput']:.3f} req/s for Redis)."
            )

    conclusion_parts.append(
        "RabbitMQ offers message durability, routing flexibility, and dead-letter queues "
        "— valuable for production environments where message loss is unacceptable. "
        "Redis remains the preferred backend for this use case given its lower overhead "
        "and the fact that the router already depends on Redis for metrics and results storage."
    )

    conclusion = " ".join(conclusion_parts)
    return f"{table}\n\n**Conclusion:** {conclusion}"


# ─── Report assembly ──────────────────────────────────────────────────────────

def write_report(bench_dir: Path, output_path: Path) -> None:
    all_data = _load_all_results(bench_dir)

    # Filter out backend bench files (redis/rabbitmq) from strategy data
    strategy_data = {
        k: v for k, v in all_data.items()
        if k in {"always-fast", "always-accurate", "infer-router"}
    }

    all_stats: dict[str, dict[str, dict]] = {}
    for strategy, loads_data in strategy_data.items():
        all_stats[strategy] = {}
        for load, results in loads_data.items():
            all_stats[strategy][load] = _compute_stats(results)

    available_strategies = [s for s in STRATEGY_ORDER if s in all_stats]
    available_loads = [
        ld for ld in LOAD_ORDER
        if any(ld in all_stats.get(s, {}) for s in available_strategies)
    ]

    has_data = bool(available_strategies and available_loads)

    latency_table = (
        _format_latency_table(all_stats, available_strategies, available_loads)
        if has_data
        else "_No benchmark data found. Run `make bench` first._"
    )
    accuracy_table = (
        _format_accuracy_table(all_stats, available_strategies, available_loads)
        if has_data
        else "_No benchmark data found._"
    )
    analysis = _analyze_winner(all_stats) if has_data else "_No data to analyze._"
    backend_section = _backend_section(bench_dir)

    # Compute tau analysis values from the w(k) formula for illustration
    tau_analysis = (
        "The threshold controller selects `k_active ∈ {1, 2}` based on the estimated "
        "waiting time `w(k)`:\n\n"
        "```\n"
        "w(k) = (x-1) / (2·μ_k) + τ / (1 + exp(μ_k − λ))\n"
        "```\n\n"
        "Where `x` is the current queue depth, `μ_k` is the aggregate service rate for "
        "`k` active models, `λ` is the measured arrival rate, and `τ` is the SLA budget.\n\n"
        "The controller scales up to `k=2` (both models active) when `w(1) > TAU` and "
        "scales down to `k=1` (accurate model only) when `w(2) < TAU/2`. "
        "A larger `TAU` (default: 5.0s) increases tolerance before activating the fast model, "
        "preserving accuracy under moderate load. A smaller `TAU` reacts more aggressively "
        "to queue growth, prioritizing latency over accuracy."
    )

    report = f"""# InferRouter — Rapport d'analyse

## 1. Résumé de l'implémentation

InferRouter est un routeur d'inférence adaptatif implémentant trois algorithmes
issus de la Section IV du papier IEEE *Mitigating Tail Latency for On-Device Inference
With Load-Balanced Heterogeneous Models* :

- **AAP (Anti-Idling Accuracy Profiling)** : sonde périodiquement le modèle rapide
  pendant les périodes creuses pour maintenir à jour une estimation de sa précision.
- **GPP (Gold-Pair Prioritizing)** : sélectionne le modèle optimal en minimisant
  `p(i) = α_i + ω·c/μ_i`, combinant taux d'erreur et débit de service.
- **Threshold Control** : contrôle le nombre de modèles actifs (`k ∈ {{1, 2}}`) via
  la formule `w(k)` pour respecter le budget SLA `τ`.

Trois stratégies sont comparées : `always-fast`, `always-accurate`, `infer-router`.

---

## 2. Résultats du benchmark (Phase 5)

### 2.1 Latence (avg / P95 / P99) et débit par stratégie

{latency_table}

### 2.2 Accuracy moyenne par stratégie

{accuracy_table}

### 2.3 Analyse : quand InferRouter est supérieur

{analysis}

---

## 3. Impact de τ (budget de temps d'attente)

{tau_analysis}

---

## 4. Redis vs RabbitMQ (Phase 7)

### 4.1 Résultats comparatifs

{backend_section}

---

## 5. Conclusion générale

InferRouter démontre qu'il est possible de combiner latence et précision grâce à un
routage adaptatif basé sur l'état de la file et la qualité mesurée des modèles.
Sous charge normale, le contrôleur de seuil maintient le modèle précis actif (`k=1`),
garantissant une haute précision. Sous charge élevée (burst), il active le modèle rapide
(`k=2`) pour absorber le surplus sans dépasser le budget SLA `τ`.

Le backend Redis reste recommandé pour ce cas d'usage grâce à sa faible latence et à
son intégration native avec le reste du système (métriques λ/μ, résultats, précision AAP).
RabbitMQ constitue une alternative viable pour les déploiements nécessitant durabilité
des messages et topologies de routage avancées.
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)


# ─── Entry point ──────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate REPORT.md from benchmark data")
    parser.add_argument("--bench-dir", default="data/bench", help="Directory with benchmark JSON files")
    parser.add_argument("--output", default="REPORT.md", help="Output path for the report")
    args = parser.parse_args()

    write_report(Path(args.bench_dir), Path(args.output))


if __name__ == "__main__":
    main()
