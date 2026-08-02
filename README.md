# InferRouter-LLM

Routes natural-language network intents to a pool of LLMs under a quality
guarantee. For each intent, the system picks the cheapest model whose expected
quality clears a floor set by the intent's operational criticality.

Master's thesis work (CNAM Paris, Networks & Connected Objects). The full report
is in `docs/InferRouter-LLM.pdf` (French).

## What it does

An intent such as *"correlate the RAN congestion alarms on site B with the UPF
losses and propose a slice resize"* arrives with two operator-supplied fields:
its network domain and its criticality. The system estimates its semantic
complexity, then arbitrates:

```
minimise cost   subject to   q(m) >= q_min(criticality)
                             latency(m) <= L_max
                             cost(m)    <= C_max
```

Criticality sets the floor (`low` 0.35 / `med` 0.50 / `high` 0.70). A
low-criticality intent goes to the cheap tier and costs roughly 170x less; a
critical one requires the strong tier. That floor is the operator's
cost-versus-quality dial.

The router does not maximise quality. With a strong heavy tier, maximising
quality sends everything to it and routing disappears.

## Quick start

Locally:

```bash
python -m venv .venv && .venv/bin/pip install -r requirements-runtime.txt
```

`requirements-runtime.txt` is enough to run the router and the test suite.
`requirements.txt` adds torch and sentence-transformers, needed only to retrain
the combined variant of the complexity estimator.

The routing decision needs neither an API key nor Ollama:

```bash
.venv/bin/python -m app.cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low --stage decision
```

It prints the attributes the estimator read, the predicted class, the candidate
table with expected quality, cost and SLA admissibility, and the selected model
with the reason it won.

Going all the way to a real model call and its judge grading requires Ollama and
four local models (about 21 GB):

```bash
ollama pull gemma2:2b && ollama pull qwen2.5:14b-instruct && ollama pull qwen2.5:7b-instruct && ollama pull gemma2:9b
```

```bash
.venv/bin/python -m app.cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low
```

Roughly 20 seconds, no cost. The full pipeline is printed stage by stage:
estimation, arbitration, real call, RocketEval checklist item by item, then
promised quality against measured quality.

Through Docker, with nothing installed (see the Docker section):

```bash
docker compose run --rm cli "Show the PRB utilisation of cell 12 on site A." --domain ran --criticality low --stage decision
```

## The CLI

`python -m app.cli "<intent>" [options]`

| Option | Default | Effect |
|---|---|---|
| `--domain` | `core` | Network domain: `ran`, `core`, `security`, `slice` |
| `--criticality` | `med` | `low`, `med`, `high`; sets the `q_min` floor |
| `--stage` | `judge` | `decision`, `execute` or `judge` |
| `--provider` | `local` | `local` (Ollama, free) or `api` (OpenRouter, billed) |
| `--pool` | `generic` | `generic` (two tiers) or `default` (+ 4 domain specialists) |
| `--q-min` | derived | Forces the floor instead of deriving it from criticality |
| `--l-max`, `--c-max` | unlimited | SLA budgets (ms, USD per call) |
| `--max-tokens` | 4096 | Generation cap for the target model |
| `--expected-complexity` | the estimate | Ground-truth label, when known |
| `--json` | off | Raw JSON trace instead of the readable report |

Domain and criticality are not guessed. They are operator metadata, not
properties of the text: inferring them would mean deciding the SLA on the
operator's behalf. Only complexity is estimated from the wording.

A few typical uses:

```bash
.venv/bin/python -m app.cli "Reroute core NF traffic after the DC-2 outage." --domain core --criticality high --stage decision
```

```bash
.venv/bin/python -m app.cli "List the active gNBs on site A." --l-max 12000 --stage decision
```

A tight latency budget removes the heavy tier from the admissible set, which the
`SLA` column of the table shows directly.

```bash
.venv/bin/python -m app.cli "Create a URLLC slice under 5 ms for factory X." --domain slice --criticality high --json
```

In `local` mode, both tiers are served by the Ollama pair used on the network
bench (gemma2:2b for the light tier, qwen2.5:14b-instruct for the heavy one).
The decision itself still uses the calibrated cost and latency profiles of the
API pool: only the model serving the tier changes, not the arbitration.

In `api` mode the production pool is used (qwen-2.5-72b and claude-opus-4.8) and
`OPENROUTER_API_KEY` must be set.

## Components

The **complexity estimator** predicts `simple`, `medium` or `complex` from
length-independent attributes: number of network entities, number of
constraints, number of crossed domains, number of numeric values. Measured at
3.4 ms per intent in steady state.

The **router** first discards candidates outside the SLA budgets, keeps those
reaching the quality floor, and returns the cheapest. Cost ties are broken by
quality, then latency — a domain specialist shares its base model's price, so
without that rule its measured advantage would never be claimed. When no
candidate reaches the floor, the router falls back to the best available rather
than refusing the intent.

The **LLM judge** grades a response with the RocketEval method: a stronger model
generates a checklist of verifiable, intent-specific criteria, a small local
model (gemma2:9b) ticks each one, and `q` is the share of criteria met. The
judge is used for offline calibration, not for the decision: at runtime the
router reads the already-measured quality matrix
(`config.QUALITY_LIGHT_BY_COMPLEXITY`).

## Measured results

Benchmark over 74 intents, gemma2:9b judge, neutral checklists generated by
claude-sonnet-4.6:

| Strategy | Quality | Mean cost | P50 latency |
|---|---|---|---|
| Always-Heavy | 0.88 | $0.0285 | 19.1 s |
| InferRouter | 0.78 | $0.0201 | 19.5 s |
| Random | 0.65 | $0.0124 | 11.9 s |
| Always-Light | 0.46 | $0.0002 | 7.9 s |

The gain is economic: 30 % less cost than always-heavy for 0.10 less quality.
Neither latency nor quality improves, both tiers of this pool being slow.

That 30 % is not a property of the system. Replayed on a different sample it
drops to 11 % at unchanged quality, because only intents that are both simple
and low-criticality reach the cheap tier. The saving measures the composition of
the intent flow as much as the policy itself, which is the expected behaviour of
an arbitration indexed on criticality.

**The most interesting result concerns the choice of the light model.** Of six
candidates tested, the best one in absolute terms (deepseek-v3.2, more robust
and cheaper) *breaks* routing: InferRouter falls below random selection. Being
uniformly capable, it leaves no signal indicating where the heavy tier is worth
paying for. Conversely qwen-2.5-72b, weaker overall but whose quality decreases
with complexity (0.64 / 0.39 / 0.32), makes routing work. The right light model
is not the strongest one, it is the one whose weakness is predictable.

**Domain specialisation is measured, not assumed.** An expertise framing gains
0.038 on its own domain (0.962 against 0.924) and loses 0.137 outside it (0.777
against 0.914). The penalty is 3.6x the gain, so specialisation only pays when
domain routing is reliable — a system that picks the wrong specialist loses more
than one that uses none. That gain sits below the judge's resolution, though, so
it does not show up in the aggregate score.

## Repository layout

```
app/
  cli/                  interactive CLI (pipeline, rendering, trace, providers)
  config.py             every parameter, overridable by environment variable
  llm/
    schema.py           Intent, ModelResponse, JudgeScore (pydantic, frozen)
    intents.py          intent set loading and validation
    features.py         complexity attributes
    prompting.py        prompt framing and model-id conventions
    intent_plan.py      the target model's output contract (typed plan)
    openrouter_client.py  target LLM calls (API)
    ollama_client.py    local model calls
    judge.py            LLM judge (RocketEval, absolute and pairwise)
    checklist.py        per-intent checklist generation
    pool.py             model pool (generic_pool and default_pool)
    policy.py           expected quality per candidate
    router.py           constrained selection (pure decision)
    inferrouter.py      decision orchestrator

bench/                  emulated-network validation bench (Mininet + OVS)
  verbs/                one pure module per verb family
data/                   intent datasets, persisted estimator
experiments/            measurement campaigns; results/ holds the measurements
tests/unit/             no network, no service
tests/integration/      require Ollama or the bench VM
docs/                   thesis report

Dockerfile              runtime and full targets
docker-compose.yml      cli, tests, bench, train, ollama services
requirements-runtime.txt  runtime dependencies (no torch)
requirements.txt          + embeddings stack
```

`data/complexity_estimator.joblib` and `experiments/results/` are versioned:
without them a fresh clone can neither route an intent nor recompute a
measurement. The estimator is deterministic (`random_state=42`) and weighs
1.1 MB.

The CLI defaults to `generic_pool`, which holds only the two generic tiers.
`default_pool` adds four domain specialists; use it to see the specialisation
effect described above.

## Configuration

Everything goes through `app/config.py`, overridable by environment variables.
The ones that matter in practice:

| Variable | Default | Role |
|---|---|---|
| `OPENROUTER_API_KEY` | empty | Required for `--provider api` |
| `MODEL_LIGHT` | `qwen/qwen-2.5-72b-instruct` | Light tier of the pool |
| `MODEL_HEAVY` | `anthropic/claude-opus-4.8` | Heavy tier of the pool |
| `JUDGE_MODEL` | `gemma2:9b` | Local judge |
| `CHECKLIST_MODEL` | `anthropic/claude-sonnet-4.6` | Generates the checklists |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama server |
| `QMIN_LOW/MED/HIGH` | 0.35 / 0.50 / 0.70 | Quality floors |

Do not downgrade `JUDGE_MODEL` to gemma2:2b: that model showed only 40 to 50 %
agreement and invalidates any quality measurement.

## Docker

Two targets in the `Dockerfile`. `runtime` (561 MB) carries the routing
decision, the LLM calls, the judge, the tests and the offline benchmark. `full`
(1.5 GB) adds torch and sentence-transformers to retrain the combined estimator.

No LLM runs inside the image. The API pool goes through OpenRouter, local models
through an Ollama server — the host's by default, via `host.docker.internal`,
since it already holds the 21 GB of weights.

```bash
docker compose run --rm cli "Create a URLLC slice under 5 ms for factory X." --domain slice --criticality high --stage decision
```

```bash
docker compose run --rm tests
```

```bash
docker compose run --rm bench
```

The `bench` service replays the offline benchmark and reproduces the four rows
of the table above without a single billed call. It is the most direct check
that the report's figures are reconstructible.

On a machine without Ollama installed, a containerised server is available as a
profile:

```bash
docker compose --profile ollama up -d ollama
```

```bash
docker compose --profile ollama exec ollama ollama pull gemma2:2b
```

`OLLAMA_HOST` must then point at `http://ollama:11434` in `.env`.

## Tests

```bash
.venv/bin/pytest -q
```

478 unit tests, no network and no service: HTTP clients are injectable and the
tests go through `httpx.MockTransport`. Integration tests
(`tests/integration/`) need a live Ollama, or the Mininet bench for those marked
`bench`, and are not collected by default.

```bash
.venv/bin/ruff check .
```

Lint settings live in `ruff.toml` and the CI pins the linter version, so the
same command yields the same verdict locally and in CI.

## Reproducing the campaigns

`experiments/` holds the measurement scripts: judge reliability, complexity
separability, per-model quality calibration, Pareto frontier, strategy
comparison, domain specialisation. Results already produced are under
`experiments/results/`.

These scripts call billed APIs. They validate on a small sample before scaling
up, reuse existing artefacts and are resumable. The offline benchmark replays
the measurements with no new call:

```bash
.venv/bin/python -m experiments.exp_benchmark_offline
```

To retrain the complexity estimator:

```bash
.venv/bin/python -m experiments.train_complexity_estimator
```

## Emulated-network bench

`bench/` applies the plans produced by the models directly as OpenFlow rules on
Open vSwitch, inside a Linux VM running Mininet, and verifies in the data plane
that the intent was actually realised. The target model emits a plan of several
operations over seven verbs (allow and block, including on a specific
application port, cap a bitrate, mirror a flow to a probe, pin a path, mark a
priority class), applied on a four-switch diamond topology with two paths. Lima
VM provisioning is under `bench/provision/`.

Every check is validated by two controls before any measurement. The negative
control replays the set with a plan that has no network effect and must fail
everything; the positive control replays it with the plan derived from the
ground truth and must pass everything. Both are free, neither calls a model:

```bash
python experiments/run_realworld_validation.py --strategy noop
limactl shell inferbench bash -c 'cd /opt/infer-router && sudo python3 -m bench.run_bench --strategy noop'
```

This two-sided proof ruled out several checks that produced a readable result
without depending on the model under test, among them a path check satisfied by
the default forwarding.

Result over 24 stratified intents on the production pool: the heavy model
realises 79 % of the intents, InferRouter 75 %, the light one 67 %. The light
model also emits one unusable plan out of 24, rejected before any network
application. Routing to a weak light tier therefore has a cost measurable in the
data plane, not merely a lower judge score.

## Known limits

The estimator persisted in `data/complexity_estimator.joblib` is the
four-attribute variant, measured at 65-73 % under cross-validation. This is a
deliberate prototype choice — attributes readable in domain terms, insensitive
to verbosity by construction — rather than the combined attributes + embeddings
variant, which reaches 85-94 %. In practice the CLI therefore classifies
coarsely: two intents of very different difficulty may land in the same class,
and the routing decision that follows will be the same.

The local judge reliably tells a good answer from a clearly bad one (100 % on
coarse discrimination), which is what routing needs. It does not detect a subtle
error injected into an otherwise correct answer: over twenty correct/degraded
pairs it returns twenty ties. A strong API judge settles half of them, so model
capability moves the limit without lifting it.

The economic gain depends on the composition of the intent flow, 30 % on one
sample and 11 % on another, because only intents that are both simple and
low-criticality reach the cheap tier.

Measured latencies come from a MacBook Air M5 and the OpenRouter API. They are
indicative, not representative of an edge deployment.

## License

MIT, see [LICENSE](LICENSE).
