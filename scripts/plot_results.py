"""Benchmark result plotter for InferRouter.

Reads data/bench/<strategy>/<load>.json and generates comparison charts
saved to data/plots/.

Charts produced:
  1. Grouped bar: avg/P95/P99 latency per strategy × load scenario
  2. Bar: average accuracy per strategy
  3. Scatter: throughput vs average latency (one point per strategy × load)
  4. Line (infer-router only): k_active and λ over time
  5. Grouped bar: Redis vs RabbitMQ queue push latency + throughput (Phase 7)

Usage:
    python3 scripts/plot_results.py
    python3 scripts/plot_results.py --bench-dir data/bench --output-dir data/plots
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

STRATEGY_COLORS = {
    "always-fast": "#f7a24f",
    "always-accurate": "#4f8ef7",
    "infer-router": "#a0e0a0",
}
LOAD_ORDER = ["normal", "burst", "mixed"]
STRATEGY_ORDER = ["always-fast", "always-accurate", "infer-router"]


# ─── Data loading ────────────────────────────────────────────────────────────

def _load_bench_data(bench_dir: Path) -> dict[str, dict[str, list[dict]]]:
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
            "count": 0, "avg_latency": 0.0, "p95": 0.0, "p99": 0.0,
            "avg_e2e": 0.0, "p95_e2e": 0.0, "p99_e2e": 0.0,
            "avg_accuracy": None, "throughput": 0.0,
        }
    latencies = [r["latency"] for r in results if r.get("latency") is not None]
    e2e = [r["e2e_latency"] for r in results if r.get("e2e_latency") is not None]
    accuracies = [r["accuracy"] for r in results if r.get("accuracy") is not None]
    timestamps = [r["processed_at"] for r in results if r.get("processed_at") is not None]

    n = len(latencies)
    arr = np.array(latencies)
    e2e_arr = np.array(e2e)
    duration = max(timestamps) - min(timestamps) if len(timestamps) >= 2 else 0.0
    return {
        "count": n,
        "avg_latency": float(np.mean(arr)) if n else 0.0,
        "p95": float(np.percentile(arr, 95)) if n else 0.0,
        "p99": float(np.percentile(arr, 99)) if n else 0.0,
        "avg_e2e": float(np.mean(e2e_arr)) if len(e2e) else 0.0,
        "p95_e2e": float(np.percentile(e2e_arr, 95)) if len(e2e) else 0.0,
        "p99_e2e": float(np.percentile(e2e_arr, 99)) if len(e2e) else 0.0,
        "avg_accuracy": float(np.mean(accuracies)) if accuracies else None,
        "throughput": round(n / duration, 3) if duration > 0 else 0.0,
    }


# ─── Chart 1: Latency comparison (grouped bar) ───────────────────────────────

def _plot_latency_comparison(
    all_stats: dict[str, dict[str, dict]],
    loads: list[str],
    strategies: list[str],
    output_dir: Path,
) -> None:
    metrics = ["avg_latency", "p95", "p99"]
    metric_labels = ["Avg latency", "P95 latency", "P99 latency"]
    fig, axes = plt.subplots(1, len(loads), figsize=(5 * len(loads), 6), sharey=False)
    if len(loads) == 1:
        axes = [axes]

    for ax, load in zip(axes, loads):
        x = np.arange(len(strategies))
        width = 0.25
        for i, (metric, label) in enumerate(zip(metrics, metric_labels)):
            values = [
                all_stats.get(s, {}).get(load, {}).get(metric, 0.0)
                for s in strategies
            ]
            bars = ax.bar(x + i * width, values, width, label=label, alpha=0.85)
            for bar, val in zip(bars, values):
                if val > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7,
                    )
        ax.set_title(f"Load: {load}", fontweight="bold")
        ax.set_xticks(x + width)
        ax.set_xticklabels(strategies, rotation=15, ha="right", fontsize=9)
        ax.set_ylabel("Latency (s)")
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle("Latency Comparison: Avg / P95 / P99 by Strategy and Load", fontweight="bold")
    fig.tight_layout()
    path = output_dir / "latency_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Chart 2: Accuracy comparison (bar) ─────────────────────────────────────

def _plot_accuracy_comparison(
    all_stats: dict[str, dict[str, dict]],
    loads: list[str],
    strategies: list[str],
    output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 5))
    x = np.arange(len(strategies))
    width = 0.8 / max(len(loads), 1)

    for i, load in enumerate(loads):
        values = []
        for s in strategies:
            acc = all_stats.get(s, {}).get(load, {}).get("avg_accuracy")
            values.append(acc if acc is not None else 0.0)
        offset = (i - len(loads) / 2 + 0.5) * width
        ax.bar(x + offset, values, width, label=load, alpha=0.85)

    ax.set_xticks(x)
    ax.set_xticklabels(strategies, rotation=15, ha="right")
    ax.set_ylabel("Average accuracy (0–1)")
    ax.set_ylim(0, 1.1)
    ax.set_title("Average Accuracy by Strategy and Load", fontweight="bold")
    ax.legend(title="Load scenario")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    path = output_dir / "accuracy_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Chart 3: Throughput vs latency scatter ───────────────────────────────────

def _plot_throughput_vs_latency(
    all_stats: dict[str, dict[str, dict]],
    loads: list[str],
    strategies: list[str],
    output_dir: Path,
) -> None:
    fig, ax = plt.subplots(figsize=(8, 6))
    markers = {"normal": "o", "burst": "^", "mixed": "s"}

    for strategy in strategies:
        color = STRATEGY_COLORS.get(strategy, "#888888")
        for load in loads:
            stats = all_stats.get(strategy, {}).get(load, {})
            if stats.get("count", 0) == 0:
                continue
            ax.scatter(
                stats["throughput"],
                stats["avg_latency"],
                color=color,
                marker=markers.get(load, "o"),
                s=120,
                label=f"{strategy} / {load}",
                zorder=5,
            )
            ax.annotate(
                f"{strategy}\n{load}",
                (stats["throughput"], stats["avg_latency"]),
                textcoords="offset points",
                xytext=(6, 4),
                fontsize=7,
                color=color,
            )

    ax.set_xlabel("Throughput (req/s)")
    ax.set_ylabel("Average latency (s)")
    ax.set_title("Throughput vs Latency (lower-right = better)", fontweight="bold")
    ax.grid(alpha=0.3)
    fig.tight_layout()
    path = output_dir / "throughput_vs_latency.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Chart 4: InferRouter time series (k_active and λ) ───────────────────────

def _plot_infer_router_timeseries(
    results_by_load: dict[str, list[dict]],
    output_dir: Path,
) -> None:
    for load, results in results_by_load.items():
        if not results:
            continue

        results_sorted = sorted(results, key=lambda r: r.get("processed_at", 0))
        timestamps = [r.get("processed_at", 0) for r in results_sorted]
        if not timestamps:
            continue

        t0 = timestamps[0]
        times = [t - t0 for t in timestamps]
        k_actives = [r.get("k_active", 2) for r in results_sorted]
        lambdas = [r.get("lambda_at_decision", 0.0) for r in results_sorted]

        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 6), sharex=True)

        ax1.step(times, k_actives, where="post", color="#a0e0a0", linewidth=2)
        ax1.set_ylabel("k actifs")
        ax1.set_ylim(0.5, 2.5)
        ax1.set_yticks([1, 2])
        ax1.set_title(f"InferRouter — {load}: k_active and λ over time", fontweight="bold")
        ax1.grid(alpha=0.3)

        ax2.plot(times, lambdas, color="#f7a24f", linewidth=1.5)
        ax2.set_xlabel("Time since start (s)")
        ax2.set_ylabel("λ (req/s)")
        ax2.set_ylim(bottom=0)
        ax2.grid(alpha=0.3)

        fig.tight_layout()
        path = output_dir / f"infer_router_timeseries_{load}.png"
        fig.savefig(path, dpi=150)
        plt.close(fig)
        logger.info("Saved %s", path)


# ─── Chart 5: Redis vs RabbitMQ backend comparison (Phase 7) ─────────────────

def _compute_backend_stats(results: list[dict]) -> dict:
    """Compute queue-specific stats from result dicts."""
    if not results:
        return {"count": 0, "push_p50": 0.0, "push_p95": 0.0, "push_p99": 0.0, "throughput": 0.0}
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
        p50 = float(np.percentile(arr, 50))
        p95 = float(np.percentile(arr, 95))
        p99 = float(np.percentile(arr, 99))
    else:
        p50 = p95 = p99 = 0.0
    return {
        "count": n,
        "push_p50": p50,
        "push_p95": p95,
        "push_p99": p99,
        "throughput": round(n / duration, 3) if duration > 0 else 0.0,
    }


def _plot_backend_comparison(
    redis_results: list[dict],
    rabbitmq_results: list[dict],
    output_dir: Path,
) -> None:
    redis_stats = _compute_backend_stats(redis_results)
    rmq_stats = _compute_backend_stats(rabbitmq_results)

    backends = ["Redis", "RabbitMQ"]
    colors = ["#4f8ef7", "#f7a24f"]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    # Left: push latency P50/P95/P99
    metrics = ["push_p50", "push_p95", "push_p99"]
    labels = ["P50", "P95", "P99"]
    x = np.arange(len(labels))
    width = 0.35
    redis_vals = [redis_stats[m] for m in metrics]
    rmq_vals = [rmq_stats[m] for m in metrics]

    bars_r = ax1.bar(x - width / 2, redis_vals, width, label="Redis", color=colors[0], alpha=0.85)
    bars_m = ax1.bar(x + width / 2, rmq_vals, width, label="RabbitMQ", color=colors[1], alpha=0.85)
    for bars in (bars_r, bars_m):
        for bar in bars:
            val = bar.get_height()
            if val > 0:
                ax1.text(
                    bar.get_x() + bar.get_width() / 2, val + 0.01,
                    f"{val:.2f}", ha="center", va="bottom", fontsize=8,
                )
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels)
    ax1.set_ylabel("Push latency (ms)")
    ax1.set_title("Queue push latency: Redis vs RabbitMQ", fontweight="bold")
    ax1.legend()
    ax1.grid(axis="y", alpha=0.3)
    ax1.set_ylim(bottom=0)

    # Right: throughput
    throughputs = [redis_stats["throughput"], rmq_stats["throughput"]]
    bars = ax2.bar(backends, throughputs, color=colors, alpha=0.85)
    for bar, val in zip(bars, throughputs):
        if val > 0:
            ax2.text(
                bar.get_x() + bar.get_width() / 2, val + 0.01,
                f"{val:.2f} req/s", ha="center", va="bottom", fontsize=9,
            )
    ax2.set_ylabel("Throughput (req/s)")
    ax2.set_title("Throughput: Redis vs RabbitMQ", fontweight="bold")
    ax2.grid(axis="y", alpha=0.3)
    ax2.set_ylim(bottom=0)

    fig.suptitle("Queue Backend Comparison (Phase 7)", fontweight="bold")
    fig.tight_layout()
    path = output_dir / "backend_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Chart 6: E2E latency comparison (queue wait + inference) ────────────────

def _plot_e2e_latency(
    all_stats: dict[str, dict[str, dict]],
    loads: list[str],
    strategies: list[str],
    output_dir: Path,
) -> None:
    """Compare avg/P95/P99 of end-to-end latency (queue wait + inference)."""
    # Skip if no e2e data at all
    has_e2e = any(
        all_stats.get(s, {}).get(ld, {}).get("avg_e2e", 0) > 0
        for s in strategies for ld in loads
    )
    if not has_e2e:
        logger.info("Skipping e2e latency chart — no e2e_latency data (re-run bench after update)")
        return

    metrics = ["avg_e2e", "p95_e2e", "p99_e2e"]
    metric_labels = ["Avg e2e", "P95 e2e", "P99 e2e"]
    fig, axes = plt.subplots(1, len(loads), figsize=(5 * len(loads), 6), sharey=False)
    if len(loads) == 1:
        axes = [axes]

    for ax, load in zip(axes, loads):
        x = np.arange(len(strategies))
        width = 0.25
        for i, (metric, label) in enumerate(zip(metrics, metric_labels)):
            values = [
                all_stats.get(s, {}).get(load, {}).get(metric, 0.0)
                for s in strategies
            ]
            bars = ax.bar(x + i * width, values, width, label=label, alpha=0.85)
            for bar, val in zip(bars, values):
                if val > 0:
                    ax.text(
                        bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01,
                        f"{val:.2f}", ha="center", va="bottom", fontsize=7,
                    )
        ax.set_title(f"Load: {load}", fontweight="bold")
        ax.set_xticks(x + width)
        ax.set_xticklabels(strategies, rotation=15, ha="right", fontsize=9)
        ax.set_ylabel("E2E latency (s)")
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle(
        "Latence E2E (attente file + inférence) : Avg / P95 / P99 par stratégie\n"
        "← C'est ici que InferRouter montre son avantage sous charge",
        fontweight="bold",
    )
    fig.tight_layout()
    path = output_dir / "e2e_latency_comparison.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Chart 7: Routing reason distribution (stacked bar per strategy × load) ──

REASON_COLORS = {
    "static_fast":       "#f7a24f",
    "static_accurate":   "#4f8ef7",
    "infer_k1_gold":     "#a0e0a0",
    "infer_k2_accurate": "#5bc8af",
    "infer_k2_fast":     "#e07040",
}
REASON_ORDER = ["static_fast", "static_accurate", "infer_k1_gold", "infer_k2_accurate", "infer_k2_fast"]
REASON_LABELS = {
    "static_fast":       "static_fast (always-fast)",
    "static_accurate":   "static_accurate (always-accurate)",
    "infer_k1_gold":     "infer_k1_gold (k=1, modèle précis)",
    "infer_k2_accurate": "infer_k2_accurate (k=2, GPP→précis)",
    "infer_k2_fast":     "infer_k2_fast (k=2, GPP→rapide)",
}


def _plot_routing_reasons(
    bench_data: dict[str, dict[str, list[dict]]],
    strategies: list[str],
    loads: list[str],
    output_dir: Path,
) -> None:
    """Stacked bar showing % of each routing_reason per strategy × load."""
    fig, axes = plt.subplots(1, len(loads), figsize=(5 * len(loads), 6), sharey=True)
    if len(loads) == 1:
        axes = [axes]

    legend_handles: list = []
    legend_labels: list = []

    for ax, load in zip(axes, loads):
        x = np.arange(len(strategies))
        width = 0.55
        bottoms = [0.0] * len(strategies)

        for reason in REASON_ORDER:
            pcts = []
            for s in strategies:
                results = bench_data.get(s, {}).get(load, [])
                if not results:
                    pcts.append(0.0)
                    continue
                n = len(results)
                count = sum(1 for r in results if r.get("routing_reason") == reason)
                pcts.append(count / n * 100)

            if sum(pcts) == 0:
                continue

            color = REASON_COLORS.get(reason, "#aaaaaa")
            bars = ax.bar(x, pcts, width, bottom=bottoms, color=color, alpha=0.9, label=REASON_LABELS[reason])

            # Keep legend entries unique
            if REASON_LABELS[reason] not in legend_labels:
                legend_handles.append(bars)
                legend_labels.append(REASON_LABELS[reason])

            # Annotate if segment large enough
            for i, (pct, bot) in enumerate(zip(pcts, bottoms)):
                if pct > 8:
                    ax.text(
                        x[i], bot + pct / 2,
                        f"{pct:.0f}%",
                        ha="center", va="center", fontsize=8,
                        color="white", fontweight="bold",
                    )
            bottoms = [b + p for b, p in zip(bottoms, pcts)]

        ax.set_title(f"Load: {load}", fontweight="bold")
        ax.set_xticks(x)
        ax.set_xticklabels(strategies, rotation=15, ha="right", fontsize=9)
        ax.set_ylabel("Requêtes (%)")
        ax.set_ylim(0, 115)
        ax.grid(axis="y", alpha=0.3)

    fig.suptitle(
        "Distribution des décisions de routage par stratégie et charge\n"
        "Seul InferRouter produit des décisions k1/k2 — les baselines sont statiques",
        fontweight="bold",
    )
    fig.legend(legend_handles, legend_labels, loc="lower center", ncol=3, fontsize=8,
               bbox_to_anchor=(0.5, -0.05))
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    path = output_dir / "routing_reasons.png"
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    logger.info("Saved %s", path)


# ─── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Plot InferRouter benchmark results")
    parser.add_argument("--bench-dir", default="data/bench", help="Directory with benchmark JSON files")
    parser.add_argument("--output-dir", default="data/plots", help="Directory for output PNG files")
    args = parser.parse_args()

    bench_dir = Path(args.bench_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    bench_data = _load_bench_data(bench_dir)
    if not bench_data:
        logger.error("No benchmark data found in %s. Run 'make bench' first.", bench_dir)
        return

    # Compute stats for all (strategy, load) combinations
    all_stats: dict[str, dict[str, dict]] = {}
    for strategy, loads_data in bench_data.items():
        all_stats[strategy] = {}
        for load, results in loads_data.items():
            all_stats[strategy][load] = _compute_stats(results)

    available_strategies = [s for s in STRATEGY_ORDER if s in all_stats]
    available_loads = [load for load in LOAD_ORDER if any(load in all_stats.get(s, {}) for s in available_strategies)]

    if not available_strategies or not available_loads:
        logger.error("No usable data found.")
        return

    _plot_latency_comparison(all_stats, available_loads, available_strategies, output_dir)
    _plot_e2e_latency(all_stats, available_loads, available_strategies, output_dir)
    _plot_routing_reasons(bench_data, available_strategies, available_loads, output_dir)
    _plot_accuracy_comparison(all_stats, available_loads, available_strategies, output_dir)
    _plot_throughput_vs_latency(all_stats, available_loads, available_strategies, output_dir)

    # InferRouter time series (only if infer-router data exists)
    if "infer-router" in bench_data:
        _plot_infer_router_timeseries(bench_data["infer-router"], output_dir)

    # Queue backend comparison (Phase 7) — only if both backend files exist
    redis_file = bench_dir / "redis" / "normal.json"
    rabbitmq_file = bench_dir / "rabbitmq" / "normal.json"
    if redis_file.exists() and rabbitmq_file.exists():
        try:
            with open(redis_file) as f:
                redis_results = json.load(f).get("results", [])
            with open(rabbitmq_file) as f:
                rabbitmq_results = json.load(f).get("results", [])
            _plot_backend_comparison(redis_results, rabbitmq_results, output_dir)
        except Exception as exc:
            logger.warning("Could not generate backend comparison chart: %s", exc)
    else:
        logger.info("Skipping backend comparison (run 'make bench-redis bench-rabbitmq' first)")

    logger.info("All plots saved to %s/", output_dir)


if __name__ == "__main__":
    main()
