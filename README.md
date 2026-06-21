# InferRouter

Adaptive inference router implementing the three algorithms from Section IV of
*Mitigating Tail Latency for On-Device Inference With Load-Balanced Heterogeneous Models* (IEEE):

- **AAP** — Anti-Idling Accuracy Profiling: keeps per-model accuracy estimates up-to-date during idle periods.
- **GPP** — Gold-Pair Prioritizing: selects the best model by minimising `p(i) = α_i + ω·c/μ_i`.
- **Threshold Control** — decides how many models to keep active (`k ∈ {1, 2}`) based on `w(k)` and a SLA budget `τ`.

Three routing strategies can be compared: `always-fast`, `always-accurate`, `infer-router`.

> ⚠️ **Statut (2026-06) — système pré-pivot parqué.** La section ci-dessus (app FastAPI, AAP/GPP/Threshold, routage d'images) décrit le système d'origine, désormais en pause. Le projet a pivoté (cf. ADR-001) vers **InferRouter-LLM** : routage d'intents réseau en texte vers des LLM cibles, avec un LLM-Juge local. Le cœur post-pivot est en cours de construction dans `app/llm/` (spike risk-first, ADR-005). Voir le plan dans le vault : `Memoire/docs/superpowers/plans/2026-06-21-spike-risk-first-validation.md`.

---

## Architecture

```
Client
  │  POST /new_pod_run_model
  ▼
FastAPI (app/main.py)
  │  push → QueueBackend (Redis LIST or RabbitMQ queue)
  ▼
Worker (app/worker.py)  ←──── λ tracker (app/arrival.py)
  │  decide_k()               μ tracker  (app/mu.py)
  │  rank_models()            AAP probes (app/aap.py)
  ▼
Model container (HTTP)
  │  pntumba/model_variant_tiny   (Fast-Model)
  │  pntumba/model_variant_large  (Accurate-Model)
  ▼
Redis  ←── results / accuracy / metrics
```

**Request flow:**
1. `POST /new_pod_run_model` receives a base64 image, assigns a `sensor_id`, measures push latency, and enqueues to the queue backend.
2. The background worker pops from the queue, reads cached `λ` and `μ` values, then runs the routing decision (threshold → GPP).
3. The selected model container is called via HTTP. Its latency is recorded and `μ` is updated.
4. If the Accurate-Model was used, an AAP probe is fired as a background task to update the Fast-Model's accuracy estimate.
5. The result dict (model, latency, accuracy, k_active, λ, routing_reason, …) is stored in Redis and returned via `GET /results`.

---

## Prerequisites

| Tool | Version |
|------|---------|
| Docker + Docker Compose | ≥ 24 |
| Python | ≥ 3.9 |
| make | any |

Images for inference must be present in `data/images/` (JPEG files). A sample set is already included.

---

## Step-by-step tutorial

### Step 1 — Clone and inspect the project

```bash
git clone <repo-url>
cd infer-router
ls
# app/         scripts/     data/        docker-compose.yml  Makefile  requirements.txt
```

### Step 2 — Start all containers

```bash
make up
```

This starts four containers on the `infer-net` Docker network:

| Container | Role |
|-----------|------|
| `infer-router-api` | FastAPI router on port 8000 |
| `infer-router-redis` | Redis 8 — queue, metrics, results |
| `infer-model-fast` | YOLO tiny (fast, lower accuracy) |
| `infer-model-accurate` | YOLO large (slower, higher accuracy) |

Check they are up:

```bash
docker compose ps
curl http://localhost:8000/health
# {"status":"ok"}
```

### Step 3 — Inspect the current configuration

```bash
curl http://localhost:8000/config | python3 -m json.tool
```

Key fields:
- `routing_strategy` — active algorithm (`infer-router` by default)
- `tau` — SLA waiting-time budget in seconds (default: 5.0)
- `k_active` — number of models currently active (1 or 2)
- `lambda_current` — measured arrival rate (req/s)
- `mu` — service rates per model (updated from measured latencies)
- `queue_backend` — `redis` or `rabbitmq`

### Step 4 — Send a single inference request

The router expects a base64-encoded image:

```bash
IMAGE=$(base64 -i data/images/000000000009.jpg)
curl -s -X POST http://localhost:8000/new_pod_run_model \
  -H "Content-Type: application/json" \
  -d "{\"image\": \"$IMAGE\", \"scenario\": \"test\"}" | python3 -m json.tool
# {"status": "queued", "scenario": "test"}
```

Wait a few seconds for the worker to process it, then retrieve results:

```bash
curl "http://localhost:8000/results?scenario=test" | python3 -m json.tool
```

Each result contains:
- `model` — which model was used
- `latency` — end-to-end inference time (seconds)
- `accuracy` — measured accuracy from AAP (null until probed)
- `routing_reason` — why this model was chosen (`infer_k1_gold`, `infer_k2_fast`, `static_fast`, …)
- `k_active` — active models at decision time
- `lambda_at_decision` — arrival rate at decision time

### Step 5 — Send a traffic burst with the traffic client

The `traffic_client.py` script reads images from `data/images/`, sends them to the router at a configurable rate, and starts a local Flask server on port 5002 to receive model callbacks.

```bash
# 20 requests, 0.5s between each, tagged as scenario "demo"
python3 scripts/traffic_client.py --count 20 --rate 0.5 --scenario demo
```

Or use the Makefile shortcut:

```bash
# Default: 20 req at 0.1s interval, scenario "default"
make traffic

# Custom
make traffic N=50 RATE=0.2 SCENARIO=my_test
```

> **Note:** keep `traffic_client.py` running while sending requests — it hosts the callback server that the model containers call back on port 5002.

### Step 6 — Watch the live dashboard

Open in a browser (auto-refreshes every 10 seconds):

```
http://localhost:8000/dashboard
```

The dashboard shows:
- Recent results table (latency, model, routing reason, accuracy)
- System metrics (k_active, λ, τ, w(k))
- Per-model accuracy and priority score

### Step 7 — Try the three routing strategies

You can restart the API with a different strategy without stopping the model containers:

```bash
# Always use the fast model (lowest latency, accuracy not guaranteed)
ROUTING_STRATEGY=always-fast docker compose up -d --no-deps api

# Always use the accurate model (highest accuracy, higher latency under load)
ROUTING_STRATEGY=always-accurate docker compose up -d --no-deps api

# InferRouter adaptive algorithm (default)
ROUTING_STRATEGY=infer-router docker compose up -d --no-deps api
```

Verify the active strategy:

```bash
curl http://localhost:8000/config | python3 -m json.tool | grep routing_strategy
```

### Step 8 — Run the full benchmark campaign

The benchmark runs all 3 strategies × 3 load scenarios automatically and saves results to `data/bench/`.

> Requires Docker to be running (`make up` first).

```bash
make bench
```

Load scenarios:

| Scenario | Requests | Rate | Description |
|----------|----------|------|-------------|
| `normal` | 100 | 2.0s interval | Moderate, steady load |
| `burst` | 50 | 0.1s interval | High-frequency spike |
| `mixed` | 200 + 50 + 200 | mixed | Ramp up, burst, cooldown |

Results are saved as:
```
data/bench/
  always-fast/     normal.json  burst.json  mixed.json
  always-accurate/ normal.json  burst.json  mixed.json
  infer-router/    normal.json  burst.json  mixed.json
```

### Step 9 — Plot the results

```bash
make plot
# → data/plots/latency_comparison.png
# → data/plots/accuracy_comparison.png
# → data/plots/throughput_vs_latency.png
# → data/plots/infer_router_timeseries_normal.png  (+ burst, mixed)
```

Open the generated PNG files to compare the three strategies across all load scenarios.

### Step 10 — Benchmark queue backends (Redis vs RabbitMQ)

Compare the Redis LIST queue versus RabbitMQ under identical load:

```bash
# Benchmark with Redis backend
make bench-redis

# Benchmark with RabbitMQ backend (starts rabbitmq container automatically)
make bench-rabbitmq
```

The RabbitMQ management UI is available at `http://localhost:15672` (user: `guest`, password: `guest`).

After both benchmarks complete, re-run the plot to generate the backend comparison chart:

```bash
make plot
# → data/plots/backend_comparison.png
```

### Step 11 — Generate the analysis report

```bash
make report
# → REPORT.md
```

The report is auto-generated from all available benchmark JSON files. It includes:
- Latency (avg / P95 / P99) and throughput per strategy and load scenario
- Average accuracy per strategy
- Analysis prose comparing InferRouter vs baselines
- τ parameter impact explanation
- Redis vs RabbitMQ comparison (if both backend benchmarks were run)
- General conclusion

---

## Local development (without Docker)

Install dependencies in a virtual environment:

```bash
make install
# Creates .venv and installs requirements.txt
```

Start a local Redis container:

```bash
make redis
```

Run the API with hot-reload:

```bash
make run
# Runs with REDIS_HOST=localhost, ROUTING_STRATEGY=infer-router, TAU=5.0

# Override parameters
make run ROUTING_STRATEGY=always-fast TAU=3.0
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Service health check |
| `POST` | `/new_pod_run_model` | Submit an inference request |
| `GET` | `/results?scenario=` | Last 10 results for a scenario |
| `GET` | `/export?scenario=` | All results for a scenario (no cap, for benchmarking) |
| `GET` | `/scenarios` | List all scenario names present in Redis |
| `GET` | `/config` | Active configuration and live metrics (λ, μ, k, τ) |
| `GET` | `/accuracy` | Per-model accuracy, alpha, mu, and GPP priority score |
| `GET` | `/dashboard` | Live HTML dashboard (auto-refresh 10s) |

### POST /new_pod_run_model

```json
{
  "image": "<base64-encoded JPEG string>",
  "scenario": "my_scenario"
}
```

Response:

```json
{
  "status": "queued",
  "scenario": "my_scenario"
}
```

---

## Configuration

All parameters are set via environment variables (with defaults):

| Variable | Default | Description |
|----------|---------|-------------|
| `ROUTING_STRATEGY` | `infer-router` | `infer-router` \| `always-fast` \| `always-accurate` |
| `QUEUE_BACKEND` | `redis` | `redis` \| `rabbitmq` |
| `TAU` | `5.0` | SLA waiting-time budget (seconds) |
| `C_COEFFICIENT` | `1.0` | GPP cost coefficient |
| `OMEGA` | `1.0` | GPP calibration weight |
| `AAP_WINDOW` | `10` | AAP sliding window size (number of samples) |
| `REDIS_HOST` | `redis` | Redis hostname |
| `REDIS_PORT` | `6379` | Redis port |
| `FAST_MODEL_URL` | `http://model-fast:5002/new_pod_run_model` | Fast model endpoint |
| `ACCURATE_MODEL_URL` | `http://model-accurate:5002/new_pod_run_model` | Accurate model endpoint |
| `RABBITMQ_URL` | `amqp://guest:guest@rabbitmq:5672/` | RabbitMQ connection URL |
| `LOG_LEVEL` | `INFO` | Logging level |

---

## Project structure

```
infer-router/
├── app/
│   ├── main.py          # FastAPI app, lifespan, all HTTP endpoints
│   ├── worker.py        # Background inference worker, routing pipeline
│   ├── config.py        # All configuration constants from env vars
│   ├── models.py        # Pydantic request/response models
│   ├── inference.py     # HTTP call to model containers
│   ├── arrival.py       # λ tracker: sliding-window arrival rate (Redis ZSET)
│   ├── mu.py            # μ tracker: rolling per-model service rate (Redis LIST)
│   ├── aap.py           # AAP: Anti-Idling Accuracy Profiling
│   ├── gpp.py           # GPP: Gold-Pair Prioritizing (pure Python)
│   ├── threshold.py     # Threshold Control FSM (w(k) formula, k_active state)
│   ├── dashboard.py     # HTML dashboard builder
│   └── queue/
│       ├── base.py          # QueueBackend Protocol
│       ├── redis_backend.py # Redis LIST implementation (lpush/brpop/llen)
│       └── rabbitmq_backend.py  # RabbitMQ implementation (aio-pika)
├── scripts/
│   ├── traffic_client.py    # Traffic generator + callback Flask server
│   ├── plot_results.py      # Benchmark result plotter (5 charts)
│   └── generate_report.py   # Auto-generate REPORT.md from bench JSON
├── data/
│   ├── images/          # JPEG images used as inference input
│   ├── bench/           # Benchmark JSON outputs (gitignored)
│   ├── plots/           # Generated PNG charts (gitignored)
│   └── responses/       # Callback CSVs from traffic_client (gitignored)
├── docker-compose.yml   # API + Redis + models + RabbitMQ
├── Dockerfile
├── Makefile
└── requirements.txt
```

---

## Makefile reference

```
make install          Create .venv and install dependencies
make run              Start API locally with hot-reload (requires Redis)
make redis            Start only the Redis container
make up               Start all Docker containers (API + Redis + models)
make build            Rebuild Docker images
make down             Stop all containers
make traffic          Send 20 requests at 0.1s interval (scenario=default)
make bench            Full benchmark: 3 strategies × 3 load scenarios
make bench-redis      Redis backend benchmark (100 req, normal load)
make bench-rabbitmq   RabbitMQ backend benchmark (100 req, normal load)
make plot             Generate comparison charts from bench data
make report           Generate REPORT.md from bench data
make clean            Remove __pycache__ directories
```
