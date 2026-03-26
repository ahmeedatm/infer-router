.PHONY: install run build up down clean traffic bench bench-quick plot send-requests test bench-redis bench-rabbitmq report

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
	.venv/bin/python3 scripts/traffic_client.py \
		--count $(or $(N),20) \
		--rate $(or $(RATE),0.1) \
		--scenario $(or $(SCENARIO),default)

send-requests:
	.venv/bin/python3 scripts/traffic_client.py \
		--count $(or $(N),50) \
		--rate 0.1 \
		--scenario default

# Legacy test target (Phase 1): kill port, flush Redis, start API, send N requests
test:
	-kill -9 $$(lsof -ti:8000) 2>/dev/null; true
	redis-cli -h localhost flushall 2>/dev/null; true
	REDIS_HOST=localhost ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 &
	sleep 2
	.venv/bin/python3 scripts/traffic_client.py \
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
	        docker exec infer-router-redis redis-cli SET accuracy:Fast-Model 0.90; \
	        docker exec infer-router-redis redis-cli SET accuracy:Accurate-Model 1.0; \
	        docker exec infer-router-redis redis-cli SET "metrics:mu:Fast-Model" 5.0; \
	        docker exec infer-router-redis redis-cli SET "metrics:mu:Accurate-Model" 1.0; \
	        scenario=$${strategy}_$${load}; \
	        if [ "$$load" = "normal" ]; then \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_NORMAL_N) \
	                --rate $(BENCH_NORMAL_RATE) \
	                --scenario $$scenario; \
	        elif [ "$$load" = "burst" ]; then \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_BURST_N) \
	                --rate $(BENCH_BURST_RATE) \
	                --scenario $$scenario; \
	        else \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_MIXED_N1) \
	                --rate $(BENCH_NORMAL_RATE) \
	                --scenario $$scenario; \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_MIXED_N2) \
	                --rate $(BENCH_BURST_RATE) \
	                --scenario $$scenario; \
	            .venv/bin/python3 scripts/traffic_client.py \
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

# ─── Quick benchmark (for demo / dev — ~8 min instead of ~45 min) ────────────
# Reduced parameters: normal=30req/1s, burst=30req/0.1s, mixed=50+30+50
# Overwrites data/bench/ — use make bench for the full campaign.

BENCH_QUICK_NORMAL_N    := 30
BENCH_QUICK_NORMAL_RATE := 1.0
BENCH_QUICK_BURST_N     := 30
BENCH_QUICK_BURST_RATE  := 0.1
BENCH_QUICK_MIXED_N1    := 50
BENCH_QUICK_MIXED_N2    := 30

bench-quick:
	@mkdir -p data/bench/always-fast data/bench/always-accurate data/bench/infer-router
	@for strategy in always-fast always-accurate infer-router; do \
	    for load in normal burst mixed; do \
	        echo ""; \
	        echo "═══ strategy=$$strategy  load=$$load ═══"; \
	        ROUTING_STRATEGY=$$strategy docker compose up -d --no-deps api; \
	        sleep 3; \
	        docker exec infer-router-redis redis-cli FLUSHALL; \
	        sleep 1; \
	        docker exec infer-router-redis redis-cli SET accuracy:Fast-Model 0.90; \
	        docker exec infer-router-redis redis-cli SET accuracy:Accurate-Model 1.0; \
	        docker exec infer-router-redis redis-cli SET "metrics:mu:Fast-Model" 5.0; \
	        docker exec infer-router-redis redis-cli SET "metrics:mu:Accurate-Model" 1.0; \
	        scenario=$${strategy}_$${load}; \
	        if [ "$$load" = "normal" ]; then \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_QUICK_NORMAL_N) \
	                --rate $(BENCH_QUICK_NORMAL_RATE) \
	                --scenario $$scenario; \
	        elif [ "$$load" = "burst" ]; then \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_QUICK_BURST_N) \
	                --rate $(BENCH_QUICK_BURST_RATE) \
	                --scenario $$scenario; \
	        else \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_QUICK_MIXED_N1) \
	                --rate $(BENCH_QUICK_NORMAL_RATE) \
	                --scenario $$scenario; \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_QUICK_MIXED_N2) \
	                --rate $(BENCH_QUICK_BURST_RATE) \
	                --scenario $$scenario; \
	            .venv/bin/python3 scripts/traffic_client.py \
	                --count $(BENCH_QUICK_MIXED_N1) \
	                --rate $(BENCH_QUICK_NORMAL_RATE) \
	                --scenario $$scenario; \
	        fi; \
	        sleep 10; \
	        curl -s "http://localhost:8000/export?scenario=$$scenario" \
	            > data/bench/$$strategy/$${load}.json; \
	        echo "Saved data/bench/$$strategy/$${load}.json"; \
	    done; \
	done
	@echo ""
	@echo "Quick benchmark complete. Run 'make plot' to generate graphs."

# ─── Plotting (Phase 5) ──────────────────────────────────────────────────────

plot:
	.venv/bin/python3 scripts/plot_results.py

# ─── Queue backend benchmark (Phase 7) ───────────────────────────────────────
# Compares Redis vs RabbitMQ queue backends under identical load.
# Saves results to data/bench/redis/normal.json and data/bench/rabbitmq/normal.json.

bench-redis:
	@mkdir -p data/bench/redis
	QUEUE_BACKEND=redis ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api
	sleep 3
	docker exec infer-router-redis redis-cli FLUSHALL
	sleep 1
	.venv/bin/python3 scripts/traffic_client.py \
		--count $(BENCH_NORMAL_N) \
		--rate $(BENCH_NORMAL_RATE) \
		--scenario bench_redis
	sleep 10
	curl -s "http://localhost:8000/export?scenario=bench_redis" > data/bench/redis/normal.json
	@echo "Saved data/bench/redis/normal.json"

bench-rabbitmq:
	@mkdir -p data/bench/rabbitmq
	QUEUE_BACKEND=rabbitmq ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api rabbitmq
	sleep 8
	docker exec infer-router-redis redis-cli FLUSHALL
	sleep 1
	.venv/bin/python3 scripts/traffic_client.py \
		--count $(BENCH_NORMAL_N) \
		--rate $(BENCH_NORMAL_RATE) \
		--scenario bench_rabbitmq
	sleep 10
	curl -s "http://localhost:8000/export?scenario=bench_rabbitmq" > data/bench/rabbitmq/normal.json
	@echo "Saved data/bench/rabbitmq/normal.json"

# ─── Auto-generated report (Phase 8) ─────────────────────────────────────────

report:
	.venv/bin/python3 scripts/generate_report.py

# ─── Cleanup ─────────────────────────────────────────────────────────────────

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
