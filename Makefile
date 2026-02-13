.PHONY: install run build up down clean

install:
	python3 -m venv .venv
	./.venv/bin/pip install -r requirements.txt

run:
	REDIS_HOST=localhost QUEUE_THRESHOLD=$(or $(THRESHOLD), 5) ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

build:
	docker-compose build

up:
	docker-compose up -d

redis:
	docker-compose up -d redis

test:
	@echo "🧪 Starting test with THRESHOLD=$(or $(THRESHOLD), 5) and N=$(or $(N), 10)..."
	-lsof -t -i:8000 | xargs kill -9
	docker exec infer-router-redis redis-cli FLUSHALL
	REDIS_HOST=localhost QUEUE_THRESHOLD=$(or $(THRESHOLD), 5) ./.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 & \
	PID=$$!; \
	sleep 2; \
	python3 scripts/send_requests.py --count $(or $(N), 10); \
	sleep 10; \

down:
	docker-compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +

send-requests:
	python3 scripts/send_requests.py --count $(or $(N), 10)
