.PHONY: install run build up down clean set-threshold traffic

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

down:
	docker compose down

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +

set-threshold:
	@test -n "$(THRESHOLD)" || (echo "Usage: make set-threshold THRESHOLD=<value>" && exit 1)
	curl -s -X PUT http://localhost:8000/threshold \
		-H "Content-Type: application/json" \
		-d '{"value": $(THRESHOLD)}' | python3 -m json.tool

traffic:
	python3 scripts/traffic_client.py --count $(or $(N), 20) --rate $(or $(RATE), 0.1) --scenario $(or $(SCENARIO), default)
