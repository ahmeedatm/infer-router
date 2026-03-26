#!/usr/bin/env bash
# =============================================================================
# InferRouter — Demo commands
# Run each scene block manually, one at a time.
# Before starting: make up && docker exec infer-router-redis redis-cli FLUSHALL
# =============================================================================

# ─── SETUP ────────────────────────────────────────────────────────────────────
# Pane 1 (left)  — live logs
#   docker compose logs -f api 2>&1 | grep -E "(INFO|WARNING|ERROR)"
#
# Pane 3 (right) — auto-refresh results
#   watch -n 3 'curl -s "http://localhost:8000/results?scenario=demo_burst" | python3 -m json.tool 2>/dev/null | head -40'
#
# Browser — open these tabs before recording:
#   http://localhost:8000/dashboard
#   http://localhost:8000/config
# =============================================================================


# ─── SCENE 1: Start & health check (30s) ──────────────────────────────────────

docker compose ps

curl http://localhost:8000/health


# ─── SCENE 2: Live configuration (30s) ────────────────────────────────────────

curl http://localhost:8000/config | python3 -m json.tool


# ─── SCENE 3: Single inference request (45s) ──────────────────────────────────

IMAGE=$(base64 -i data/images/000000000009.jpg)

curl -s -X POST http://localhost:8000/new_pod_run_model \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$IMAGE\", \"scenario\": \"demo\"}"

# Wait ~3s for worker to process, then:
curl -s "http://localhost:8000/results?scenario=demo" | python3 -m json.tool


# ─── SCENE 4: Dashboard (20s) ─────────────────────────────────────────────────
# Switch to browser — show http://localhost:8000/dashboard
# Let it auto-refresh once (10s cycle)


# ─── SCENE 5: Traffic burst — KEY SCENE (90s) ─────────────────────────────────
# Make all 3 panes visible before running this.
# Watch Pane 1 logs: routing_reason switches infer_k1_gold → infer_k2_fast
# Watch Pane 3: results appear in real time
# Watch browser dashboard refresh

python3 scripts/traffic_client.py --count 30 --rate 0.1 --scenario demo_burst


# ─── SCENE 6: Switch strategies (60s) ─────────────────────────────────────────

ROUTING_STRATEGY=always-fast docker compose up -d --no-deps api
sleep 4

python3 scripts/traffic_client.py --count 10 --rate 0.5 --scenario demo_fast

curl -s "http://localhost:8000/results?scenario=demo_fast" | python3 -m json.tool

# Switch back to infer-router
ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api


# ─── SCENE 7: Benchmark results & plots (45s) ─────────────────────────────────

ls data/bench/

curl -s "http://localhost:8000/export?scenario=infer-router_burst" | python3 -m json.tool | head -30

open data/plots/latency_comparison.png

open data/plots/infer_router_timeseries_mixed.png


# ─── SCENE 8: Auto-generated report (20s) ─────────────────────────────────────

make report

head -60 REPORT.md


# ─── RESET between takes ───────────────────────────────────────────────────────

docker exec infer-router-redis redis-cli FLUSHALL
