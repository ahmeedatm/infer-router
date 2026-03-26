.PHONY: install run build up down clean traffic bench plot send-requests test

# ─── Local dev ───────────────────────────────────────────────────────────────

install:
	python3 -m venv .venv
	./.venv/bin/pip install -r requirements.txt

run:
	REDIS_HOST=localhost \
	ROUTING_STRATEGY=$(or $(ROUTING_STRATEGY),infer-router) \
	TAU=$(or $(TAU),5.0) \
	./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# ─── Docker ──────────────────────────────────────────────────────────────────

build:
	docker compose build

up:
	docker compose up -d

redis:
	docker compose up -d redis

down:
	docker compose down

# ─── Traffic ─────────────────────────────────────────────────────────────────

# Send N requests at RATE seconds between each (default: 20 req at 0.1s interval)
traffic:
	python3 scripts/traffic_client.py \
		--count $(or $(N),20) \
		--rate $(or $(RATE),0.1) \
		--scenario $(or $(SCENARIO),default)

send-requests:
	python3 scripts/traffic_client.py \
		--count $(or $(N),50) \
		--rate 0.1 \
		--scenario default

# Legacy test target (Phase 1): kill port, flush Redis, start API, send N requests
test:
	-kill -9 $$(lsof -ti:8000) 2>/dev/null; true
	redis-cli -h localhost flushall 2>/dev/null; true
	REDIS_HOST=localhost ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
	sleep 2
	python3 scripts/traffic_client.py \
		--count $(or $(N),20) \
		--rate $(or $(RATE),0.1) \
		--scenario $(or $(SCENARIO),default)
	sleep 10

# ─── Benchmark campaign (Phase 5) ────────────────────────────────────────────
# Runs 3 strategies × 3 load scenarios.
# Requires Docker to be running (make up first).
# Results saved to data/bench/<strategy>/<load>.json

BENCH_NORMAL_N    := 100
BENCH_NORMAL_RATE := 2.0
BENCH_BURST_N     := 50
BENCH_BURST_RATE  := 0.1
BENCH_MIXED_N1    := 200
BENCH_MIXED_N2    := 100

bench:
	@mkdir -p data/bench/always-fast data/bench/always-accurate data/bench/infer-router
	@for strategy in always-fast always-accurate infer-router; do \
	    for load in normal burst mixed; do \
	        echo ""; \
	        echo "═══ strategy=$$strategy  load=$$load ═══"; \
	        ROUTING_STRATEGY=$$strategy docker compose up -d --no-deps api; \
	        sleep 3; \
	        docker exec infer-router-redis redis-cli FLUSHALL; \
	        sleep 1; \
	        scenario=$${strategy}_$${load}; \
	        if [ "$$load" = "normal" ]; then \
	            python3 scripts/traffic_client.py \
	                --count $(BENCH_NORMAL_N) \
	                --rate $(BENCH_NORMAL_RATE) \
	                --scenario $$scenario; \
	        elif [ "$$load" = "burst" ]; then \
	            python3 scripts/traffic_client.py \
	                --count $(BENCH_BURST_N) \
	                --rate $(BENCH_BURST_RATE) \
	                --scenario $$scenario; \
	        else \
	            python3 scripts/traffic_client.py \
	                --count $(BENCH_MIXED_N1) \
	                --rate $(BENCH_NORMAL_RATE) \
	                --scenario $$scenario; \
	            python3 scripts/traffic_client.py \
	                --count $(BENCH_MIXED_N2) \
	                --rate $(BENCH_BURST_RATE) \
	                --scenario $$scenario; \
	            python3 scripts/traffic_client.py \
	                --count $(BENCH_MIXED_N1) \
	                --rate $(BENCH_NORMAL_RATE) \
	                --scenario $$scenario; \
	        fi; \
	        echo "Waiting for queue to drain..."; \
	        sleep 10; \
	        curl -s "http://localhost:8000/export?scenario=$$scenario" \
	            > data/bench/$$strategy/$${load}.json; \
	        echo "Saved data/bench/$$strategy/$${load}.json"; \
	    done; \
	done
	@echo ""
	@echo "Benchmark complete. Run 'make plot' to generate graphs."

# ─── Plotting (Phase 5) ──────────────────────────────────────────────────────

plot:
	python3 scripts/plot_results.py

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
