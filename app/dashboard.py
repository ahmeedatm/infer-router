import datetime
import json
import logging

from redis.asyncio import Redis

from app.config import (
    ACCURATE_MODEL_NAME,
    FAST_MODEL_NAME,
    QUEUE_THRESHOLD,
    RESULTS_KEY_PREFIX,
)

logger = logging.getLogger(__name__)


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

    return _render_html(scenarios_data)


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
        }

    latencies = sorted(r["latency"] for r in results)
    n = len(latencies)
    fast_count = sum(1 for r in results if r.get("model") == FAST_MODEL_NAME)
    timestamps = [r["processed_at"] for r in results if r.get("processed_at") is not None]
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


def _render_stats_grid(stats: dict) -> str:
    throughput_display = f"{stats['throughput']} req/s" if stats["throughput"] > 0 else "n/a"
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
        <div class="stat"><span class="label" style="color:#ff5050">Threshold</span><span class="value" style="color:#ff5050">{QUEUE_THRESHOLD}</span></div>
      </div>"""


def _render_line_chart_script(line_id: str, chart_data: dict, threshold: int) -> str:
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
          annotation: {{
            annotations: {{
              thresholdLine: {{
                type: "line",
                yMin: {threshold},
                yMax: {threshold},
                yScaleID: "y1",
                borderColor: "rgba(255,80,80,0.85)",
                borderWidth: 2,
                borderDash: [6, 4],
                label: {{
                  display: true,
                  content: "Routing threshold ({threshold})",
                  position: "start",
                  backgroundColor: "rgba(255,80,80,0.15)",
                  color: "#ff5050",
                }}
              }}
            }}
          }}
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

    script = _render_line_chart_script(line_id, chart_data, QUEUE_THRESHOLD)
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


def _render_html(scenarios_data: dict[str, list[dict]]) -> str:
    if not scenarios_data:
        return _empty_html()

    all_stats = {name: _compute_stats(results) for name, results in scenarios_data.items()}

    sections = []
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


def _empty_html() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>InferRouter Dashboard</title>
  <style>
    body { font-family: system-ui, sans-serif; background: #0f1117; color: #e0e0e0;
           display: flex; flex-direction: column; align-items: center;
           justify-content: center; height: 100vh; margin: 0; gap: 8px; }
    p { font-size: 1.5rem; color: #888; margin: 0; }
    small { color: #444; }
  </style>
</head>
<body>
  <p>No scenario data found. Send some requests first.</p>
  <small id="ts"></small>
  <script>
    document.getElementById("ts").textContent = "Checked at " + new Date().toLocaleTimeString();
    setTimeout(() => location.reload(), 5000);
  </script>
</body>
</html>"""
