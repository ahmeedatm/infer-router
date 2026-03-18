.PHONY: install run build up down clean kill test test-docker

install:
	python3 -m venv .venv
	./.venv/bin/pip install -r requirements.txt

run:
	REDIS_HOST=localhost QUEUE_THRESHOLD=$(or $(THRESHOLD), 5) ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

build:
	docker compose build

up:
	docker compose up -d

redis:
	docker compose up -d redis

test:
	@echo "🧪 Starting test with THRESHOLD=$(or $(THRESHOLD), 5) and N=$(or $(N), 10)..."
	-pkill -f "uvicorn app.main" 2>/dev/null; sleep 1
	docker exec infer-router-redis redis-cli FLUSHALL
	REDIS_HOST=localhost QUEUE_THRESHOLD=$(or $(THRESHOLD), 5) ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 & \
	PID=$$!; \
	sleep 2; \
	python3 scripts/send_requests.py --count $(or $(N), 10); \
	sleep 10; \

# Test against already-running Docker containers (make up must be running)
test-docker:
	@echo "Testing against Docker containers (N=$(or $(N), 10))..."
	docker exec infer-router-redis redis-cli FLUSHALL
	sleep 1
	python3 scripts/send_requests.py --count $(or $(N), 10) --scenario $(or $(SCENARIO), docker-test)
	@echo "Waiting for results..."
	sleep 10
	curl -s "http://localhost:8000/results?scenario=$(or $(SCENARIO), docker-test)" | python3 -m json.tool

down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +

kill:
	-lsof -t -i:8000 | xargs kill -9

send-requests:
	python3 scripts/send_requests.py --count $(or $(N), 10)
