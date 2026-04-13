from __future__ import annotations

import datetime
import json
import logging
from collections import Counter

from redis.asyncio import Redis

from app.arrival import get_lambda
from app.config import (
    ACCURATE_MODEL_NAME,
    C_COEFFICIENT,
    FAST_MODEL_NAME,
    OMEGA,
    TAU,
)
from app.mu import get_mu
from app.redis_keys import ACCURACY_KEY_PREFIX, RESULTS_KEY_PREFIX
from app.threshold import compute_waiting_time, get_k_active

logger = logging.getLogger(__name__)


async def _load_accuracy(redis_client: Redis) -> dict[str, float | None]:
    fast_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{FAST_MODEL_NAME}")
    accurate_raw = await redis_client.get(f"{ACCURACY_KEY_PREFIX}:{ACCURATE_MODEL_NAME}")
    return {
        FAST_MODEL_NAME: float(fast_raw) if fast_raw is not None else None,
        ACCURATE_MODEL_NAME: float(accurate_raw) if accurate_raw is not None else None,
    }


async def build_dashboard_html(redis_client: Redis) -> str:
    keys = await redis_client.keys(f"{RESULTS_KEY_PREFIX}:*")
    prefix = f"{RESULTS_KEY_PREFIX}:"
    scenarios = sorted(
        k.decode() if isinstance(k, bytes) else k
        for k in keys
    )
    scenario_names = [s[len(prefix):] for s in scenarios]

    scenarios_data: dict[str, list[dict]] = {}
    for name in scenario_names:
        scenarios_data[name] = await _load_scenario_data(redis_client, name)

    accuracy = await _load_accuracy(redis_client)

    # Fetch live system metrics
    k_active = await get_k_active(redis_client)
    lambda_current = await get_lambda(redis_client)
    mu_fast = await get_mu(redis_client, FAST_MODEL_NAME)
    mu_accurate = await get_mu(redis_client, ACCURATE_MODEL_NAME)
    mu_k = (mu_fast + mu_accurate) / 2 if k_active == 2 and mu_fast > 0 else mu_accurate
    # Use a sample queue length of 0 for the dashboard display (steady-state estimate)
    w_k = compute_waiting_time(0, mu_k, lambda_current, TAU)

    system_metrics = {
        "k_active": k_active,
        "lambda_current": lambda_current,
        "tau": TAU,
        "w_k": round(w_k, 3) if w_k != float("inf") else "∞",
        "mu_fast": mu_fast,
        "mu_accurate": mu_accurate,
    }

    return _render_html(scenarios_data, accuracy, system_metrics)


async def _load_scenario_data(redis_client: Redis, scenario: str) -> list[dict]:
    key = f"{RESULTS_KEY_PREFIX}:{scenario}"
    raw_entries = await redis_client.lrange(key, 0, 999)
    results = []
    for raw in raw_entries:
        try:
            results.append(json.loads(raw))
        except json.JSONDecodeError as exc:
            logger.warning("Skipping malformed dashboard entry: %s", exc)
    return results


def _compute_throughput(timestamps: list[float], total: int) -> float:
    if len(timestamps) < 2:
        return 0.0
    duration = max(timestamps) - min(timestamps)
    return round(total / duration, 2) if duration > 0 else 0.0


def _compute_stats(results: list[dict]) -> dict:
    if not results:
        return {
            "total": 0,
            "avg_latency": 0.0,
            "min_latency": 0.0,
            "max_latency": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "fast_count": 0,
            "accurate_count": 0,
            "throughput": 0.0,
            "routing_reasons": Counter(),
            "avg_image_size": None,
        }

    latencies = sorted(r["latency"] for r in results)
    n = len(latencies)
    fast_count = sum(1 for r in results if r.get("model") == FAST_MODEL_NAME)
    timestamps = [r["processed_at"] for r in results if r.get("processed_at") is not None]
    routing_reasons = Counter(r.get("routing_reason") for r in results if r.get("routing_reason"))
    image_sizes = [r["image_size"] for r in results if r.get("image_size") is not None]
    avg_image_size = round(sum(image_sizes) / len(image_sizes)) if image_sizes else None
    return {
        "total": n,
        "avg_latency": round(sum(latencies) / n, 4),
        "min_latency": round(latencies[0], 4),
        "max_latency": round(latencies[-1], 4),
        "p50": round(latencies[int(n * 0.50)], 4),
        "p95": round(latencies[min(int(n * 0.95), n - 1)], 4),
        "p99": round(latencies[min(int(n * 0.99), n - 1)], 4),
        "fast_count": fast_count,
        "accurate_count": n - fast_count,
        "throughput": _compute_throughput(timestamps, n),
        "routing_reasons": routing_reasons,
        "avg_image_size": avg_image_size,
    }


def _format_time_labels(ordered: list[dict]) -> list[str]:
    return [
        datetime.datetime.fromtimestamp(r["processed_at"]).strftime("%H:%M:%S")
        if r.get("processed_at") is not None else ""
        for r in ordered
    ]


def _build_chart_data(results: list[dict]) -> dict:
    ordered = list(reversed(results))
    latencies = [r["latency"] for r in ordered]
    queue_depths = [r.get("queue_at_start", 0) for r in ordered]
    models = [r.get("model", "") for r in ordered]
    has_timestamps = bool(ordered) and ordered[0].get("processed_at") is not None
    labels = _format_time_labels(ordered) if has_timestamps else list(range(1, len(latencies) + 1))
    point_colors = ["#f7a24f" if m == FAST_MODEL_NAME else "#4f8ef7" for m in models]
    return {
        "labels": labels,
        "latencies": latencies,
        "queue_depths": queue_depths,
        "point_colors": point_colors,
    }


def _render_routing_reason_stats(routing_reasons: Counter) -> str:
    reason_colors = {
        "infer_k1_gold": "#4f8ef7",
        "infer_k2_accurate": "#6fbcf7",
        "infer_k2_fast": "#f7a24f",
        "static_fast": "#f7a24f",
        "static_accurate": "#4f8ef7",
        # legacy reasons (kept for backward compat)
        "low_queue": "#4f8ef7",
        "queue_pressure": "#f7a24f",
        "accuracy_override": "#a0e0a0",
        "fallback": "#888888",
    }
    items = ""
    for reason, count in routing_reasons.most_common():
        color = reason_colors.get(reason, "#aaaaaa")
        label = reason.replace("_", " ")
        items += f'<div class="stat"><span class="label" style="color:{color}">{label}</span><span class="value" style="color:{color}">{count}</span></div>\n'
    return items


def _render_stats_grid(stats: dict) -> str:
    throughput_display = f"{stats['throughput']} req/s" if stats["throughput"] > 0 else "n/a"
    routing_items = _render_routing_reason_stats(stats.get("routing_reasons", Counter()))
    avg_size = stats.get("avg_image_size")
    avg_size_display = f"{avg_size / 1024:.1f} KB" if avg_size is not None else "n/a"
    return f"""
      <div class="stats-grid">
        <div class="stat"><span class="label">Total</span><span class="value">{stats["total"]}</span></div>
        <div class="stat"><span class="label">Avg latency</span><span class="value">{stats["avg_latency"]}s</span></div>
        <div class="stat"><span class="label">P50</span><span class="value">{stats["p50"]}s</span></div>
        <div class="stat"><span class="label">P95</span><span class="value">{stats["p95"]}s</span></div>
        <div class="stat"><span class="label">P99</span><span class="value">{stats["p99"]}s</span></div>
        <div class="stat"><span class="label">Min</span><span class="value">{stats["min_latency"]}s</span></div>
        <div class="stat"><span class="label">Max</span><span class="value">{stats["max_latency"]}s</span></div>
        <div class="stat"><span class="label">Fast-Model</span><span class="value">{stats["fast_count"]}</span></div>
        <div class="stat"><span class="label">Accurate-Model</span><span class="value">{stats["accurate_count"]}</span></div>
        <div class="stat"><span class="label">Throughput</span><span class="value">{throughput_display}</span></div>
        <div class="stat"><span class="label">Avg img size</span><span class="value">{avg_size_display}</span></div>
        {routing_items}
      </div>"""


def _render_line_chart_script(line_id: str, chart_data: dict) -> str:
    return f"""
    new Chart(document.getElementById("{line_id}"), {{
      type: "line",
      data: {{
        labels: {json.dumps(chart_data["labels"])},
        datasets: [
          {{
            label: "Latency (s)",
            data: {json.dumps(chart_data["latencies"])},
            borderColor: "#4f8ef7",
            backgroundColor: "rgba(79,142,247,0.1)",
            fill: true,
            tension: 0.3,
            pointRadius: 3,
            pointBackgroundColor: {json.dumps(chart_data["point_colors"])},
            yAxisID: "y",
          }},
          {{
            label: "Queue depth",
            data: {json.dumps(chart_data["queue_depths"])},
            borderColor: "#f7a24f",
            backgroundColor: "rgba(247,162,79,0.08)",
            fill: true,
            tension: 0.3,
            pointRadius: 2,
            borderDash: [5, 5],
            yAxisID: "y1",
          }}
        ]
      }},
      options: {{
        plugins: {{
          legend: {{ display: true }},
          title: {{ display: true, text: "Latency & queue depth over time" }},
        }},
        scales: {{
          y: {{
            beginAtZero: true,
            position: "left",
            title: {{ display: true, text: "latency (s)" }}
          }},
          y1: {{
            beginAtZero: true,
            position: "right",
            title: {{ display: true, text: "queue depth" }},
            grid: {{ drawOnChartArea: false }}
          }}
        }}
      }}
    }});"""


def _render_comparison_section(all_stats: dict[str, dict]) -> tuple[str, str]:
    names = list(all_stats.keys())
    avg_latencies = [all_stats[n]["avg_latency"] for n in names]
    p95_latencies = [all_stats[n]["p95"] for n in names]
    fast_counts = [all_stats[n]["fast_count"] for n in names]
    accurate_counts = [all_stats[n]["accurate_count"] for n in names]

    html = """
    <section class="scenario comparison">
      <h2>Scenario Comparison</h2>
      <div class="charts">
        <div class="chart-wrap"><canvas id="cmp_latency" aria-label="Latency comparison across scenarios"></canvas></div>
        <div class="chart-wrap"><canvas id="cmp_model" aria-label="Model usage per scenario"></canvas></div>
      </div>
    </section>
    """

    script = f"""
    new Chart(document.getElementById("cmp_latency"), {{
      type: "bar",
      data: {{
        labels: {json.dumps(names)},
        datasets: [
          {{
            label: "Avg latency (s)",
            data: {json.dumps(avg_latencies)},
            backgroundColor: "rgba(79,142,247,0.75)",
          }},
          {{
            label: "P95 latency (s)",
            data: {json.dumps(p95_latencies)},
            backgroundColor: "rgba(247,162,79,0.75)",
          }}
        ]
      }},
      options: {{
        plugins: {{ title: {{ display: true, text: "Latency comparison: Avg vs P95" }} }},
        scales: {{ y: {{ beginAtZero: true, title: {{ display: true, text: "seconds" }} }} }}
      }}
    }});
    new Chart(document.getElementById("cmp_model"), {{
      type: "bar",
      data: {{
        labels: {json.dumps(names)},
        datasets: [
          {{
            label: "Fast-Model",
            data: {json.dumps(fast_counts)},
            backgroundColor: "rgba(247,162,79,0.75)",
          }},
          {{
            label: "Accurate-Model",
            data: {json.dumps(accurate_counts)},
            backgroundColor: "rgba(79,142,247,0.75)",
          }}
        ]
      }},
      options: {{
        plugins: {{ title: {{ display: true, text: "Model usage per scenario" }} }},
        scales: {{
          x: {{ stacked: true }},
          y: {{ stacked: true, beginAtZero: true }}
        }}
      }}
    }});
    """
    return html, script


def _render_scenario_section(scenario: str, results: list[dict], chart_id: int) -> tuple[str, str]:
    stats = _compute_stats(results)
    line_id = f"line_{chart_id}"
    donut_id = f"donut_{chart_id}"
    chart_data = _build_chart_data(results)

    html = f"""
    <section class="scenario">
      <h2>{scenario}</h2>
      {_render_stats_grid(stats)}
      <div class="charts">
        <div class="chart-wrap"><canvas id="{line_id}" aria-label="Latency and queue depth over time for {scenario}"></canvas></div>
        <div class="chart-wrap"><canvas id="{donut_id}" aria-label="Model distribution for {scenario}"></canvas></div>
      </div>
    </section>
    """

    script = _render_line_chart_script(line_id, chart_data)
    script += f"""
    new Chart(document.getElementById("{donut_id}"), {{
      type: "doughnut",
      data: {{
        labels: ["{FAST_MODEL_NAME}", "{ACCURATE_MODEL_NAME}"],
        datasets: [{{
          data: [{stats["fast_count"]}, {stats["accurate_count"]}],
          backgroundColor: ["#f7a24f", "#4f8ef7"]
        }}]
      }},
      options: {{
        plugins: {{ title: {{ display: true, text: "Model distribution" }} }}
      }}
    }});
    """
    return html, script


def _render_accuracy_section(accuracy: dict[str, float | None]) -> str:
    def _fmt(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "n/a"

    fast_val = accuracy.get(FAST_MODEL_NAME)
    acc_val = accuracy.get(ACCURATE_MODEL_NAME)
    fast_display = _fmt(fast_val)
    acc_display = _fmt(acc_val)

    fast_color = "#f7a24f"
    acc_color = "#4f8ef7"

    return f"""
    <section class="scenario accuracy-section">
      <h2 style="color:#a0e0a0">Current Model Accuracy</h2>
      <div class="stats-grid">
        <div class="stat">
          <span class="label" style="color:{fast_color}">{FAST_MODEL_NAME}</span>
          <span class="value" style="color:{fast_color}">{fast_display}</span>
        </div>
        <div class="stat">
          <span class="label" style="color:{acc_color}">{ACCURATE_MODEL_NAME}</span>
          <span class="value" style="color:{acc_color}">{acc_display}</span>
        </div>
      </div>
      <p style="font-size:0.75rem;color:#555;margin:0">
        Fast-Model accuracy auto-updated via AAP probes. Use <code>GET /accuracy</code> for raw values.
      </p>
    </section>
    """


def _render_system_metrics_section(system_metrics: dict) -> str:
    w_display = (
        f"{system_metrics['w_k']}s"
        if isinstance(system_metrics["w_k"], (int, float))
        else system_metrics["w_k"]
    )
    return f"""
    <section class="scenario accuracy-section">
      <h2 style="color:#a0e0ff">System Metrics (Live)</h2>
      <div class="stats-grid">
        <div class="stat">
          <span class="label" style="color:#a0e0ff">k actifs</span>
          <span class="value" style="color:#a0e0ff">{system_metrics['k_active']}</span>
        </div>
        <div class="stat">
          <span class="label" style="color:#a0e0ff">λ (req/s)</span>
          <span class="value" style="color:#a0e0ff">{system_metrics['lambda_current']}</span>
        </div>
        <div class="stat">
          <span class="label" style="color:#ff5050">τ (budget)</span>
          <span class="value" style="color:#ff5050">{system_metrics['tau']}s</span>
        </div>
        <div class="stat">
          <span class="label" style="color:#f7a24f">w(k) estimé</span>
          <span class="value" style="color:#f7a24f">{w_display}</span>
        </div>
        <div class="stat">
          <span class="label" style="color:#f7a24f">μ Fast-Model</span>
          <span class="value" style="color:#f7a24f">{system_metrics['mu_fast']}</span>
        </div>
        <div class="stat">
          <span class="label" style="color:#4f8ef7">μ Accurate-Model</span>
          <span class="value" style="color:#4f8ef7">{system_metrics['mu_accurate']}</span>
        </div>
      </div>
    </section>
    """


def _render_html(scenarios_data: dict[str, list[dict]], accuracy: dict[str, float | None], system_metrics: dict) -> str:
    if not scenarios_data:
        return _empty_html(accuracy, system_metrics)

    all_stats = {name: _compute_stats(results) for name, results in scenarios_data.items()}

    sections = [
        _render_system_metrics_section(system_metrics),
        _render_accuracy_section(accuracy),
    ]
    chart_scripts = []

    if len(scenarios_data) > 1:
        cmp_html, cmp_script = _render_comparison_section(all_stats)
        sections.append(cmp_html)
        chart_scripts.append(cmp_script)

    for chart_id, (scenario, results) in enumerate(scenarios_data.items()):
        s_html, s_script = _render_scenario_section(scenario, results, chart_id)
        sections.append(s_html)
        chart_scripts.append(s_script)

    sections_html = "\n".join(sections)
    scripts_html = "\n".join(chart_scripts)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>InferRouter Dashboard</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
  <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-annotation@3"></script>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f1117; color: #e0e0e0; margin: 0; padding: 24px; }}
    h1 {{ text-align: center; color: #4f8ef7; margin-bottom: 8px; }}
    .reload-bar-wrap {{ height: 3px; background: #1a1d27; margin-bottom: 6px; border-radius: 2px; overflow: hidden; }}
    .reload-bar {{ height: 3px; background: #4f8ef7; width: 100%; transition: width 1s linear; border-radius: 2px; }}
    .reload-info {{ text-align: center; font-size: 0.75rem; color: #555; margin-bottom: 28px; }}
    .scenario {{ background: #1a1d27; border-radius: 12px; padding: 24px; margin-bottom: 32px; }}
    .comparison h2 {{ color: #4f8ef7; }}
    h2 {{ color: #f7a24f; margin-top: 0; text-transform: capitalize; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .stat {{ background: #0f1117; border-radius: 8px; padding: 12px; text-align: center; }}
    .label {{ display: block; font-size: 0.75rem; color: #888; margin-bottom: 4px; }}
    .value {{ font-size: 1.2rem; font-weight: bold; color: #e0e0e0; }}
    .charts {{ display: grid; grid-template-columns: 2fr 1fr; gap: 24px; }}
    .chart-wrap {{ background: #0f1117; border-radius: 8px; padding: 16px; }}
    @media (max-width: 600px) {{ .charts {{ grid-template-columns: 1fr; }} }}
  </style>
</head>
<body>
  <h1>InferRouter Dashboard</h1>
  <div class="reload-bar-wrap"><div class="reload-bar" id="reloadBar"></div></div>
  <div class="reload-info">
    Last updated: <span id="lastUpdated"></span>
    &nbsp;&middot;&nbsp;
    Refreshing in <span id="countdown">10</span>s
  </div>
  {sections_html}
  <script>
    {scripts_html}
    document.getElementById("lastUpdated").textContent = new Date().toLocaleTimeString();
    let remaining = 10;
    const bar = document.getElementById("reloadBar");
    const cd = document.getElementById("countdown");
    const iv = setInterval(() => {{
      remaining--;
      cd.textContent = remaining;
      bar.style.width = (remaining * 10) + "%";
      if (remaining <= 0) {{ clearInterval(iv); location.reload(); }}
    }}, 1000);
  </script>
</body>
</html>"""


def _empty_html(accuracy: dict[str, float | None] | None = None, system_metrics: dict | None = None) -> str:
    accuracy_html = _render_accuracy_section(accuracy) if accuracy else ""
    system_metrics_html = _render_system_metrics_section(system_metrics) if system_metrics else ""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>InferRouter Dashboard</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #0f1117; color: #e0e0e0;
           display: flex; flex-direction: column; align-items: center;
           justify-content: center; height: 100vh; margin: 0; gap: 8px; }}
    p {{ font-size: 1.5rem; color: #888; margin: 0; }}
    small {{ color: #444; }}
    .scenario {{ background: #1a1d27; border-radius: 12px; padding: 24px; margin-bottom: 32px; width: 90%; max-width: 600px; }}
    .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(120px, 1fr)); gap: 12px; margin-bottom: 24px; }}
    .stat {{ background: #0f1117; border-radius: 8px; padding: 12px; text-align: center; }}
    .label {{ display: block; font-size: 0.75rem; color: #888; margin-bottom: 4px; }}
    .value {{ font-size: 1.2rem; font-weight: bold; color: #e0e0e0; }}
  </style>
</head>
<body>
  {system_metrics_html}
  {accuracy_html}
  <p>No scenario data found. Send some requests first.</p>
  <small id="ts"></small>
  <script>
    document.getElementById("ts").textContent = "Checked at " + new Date().toLocaleTimeString();
    setTimeout(() => location.reload(), 5000);
  </script>
</body>
</html>"""
