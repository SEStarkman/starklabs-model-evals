# starklabs-model-evals

A personal set of model evaluation tests spanning coding, writing, game theory, design, critical thinking, logic, and more.

`starkeval` is a compact Python 3.11+ runner for declarative, repeatable model checks. One command runs every case for every selected model, isolates failures, and writes both machine-readable JSON and a skimmable Markdown report.

## Quick start (no credentials)

```bash
uv sync
uv run starkeval run \
  --suite suites/core.yaml \
  --model mock/baseline \
  --mode parallel \
  --concurrency 4
```

The built-in `mock/baseline` provider makes no network calls and uses no credentials. It exercises suite loading, request isolation, scheduling, grading, aggregation, and report persistence.

Sequential execution is deterministic and still runs the whole matrix:

```bash
uv run starkeval run \
  --suite suites/core.yaml \
  --model mock/baseline \
  --mode sequential \
  --repeat 2
```

## Hosted and local models

Real providers are routed through the optional [LiteLLM](https://docs.litellm.ai/) adapter so suite definitions are not tied to one vendor:

```bash
uv sync --extra providers
cp .env.example .env            # optional convenience; never commit .env
export OPENAI_API_KEY=...        # use the provider's normal environment variable

uv run starkeval run \
  --suite suites/core.yaml \
  --model openai/gpt-4o-mini \
  --model anthropic/claude-3-5-haiku-latest \
  --mode sequential
```

A LiteLLM-supported local endpoint uses the same path, for example `--model ollama/llama3.1`. Provider API keys come only from the environment. Credential-like keys are rejected recursively throughout suite `settings`, including nested mappings and lists, and environment values are never copied into reports.

## Suite format

YAML is the source of truth for prompts and checks:

```yaml
name: example
settings:
  temperature: 0
  max_tokens: 200
cases:
  - id: concise-answer
    title: Concise answer
    system_prompt: Answer directly.   # optional
    prompt: Reply with exactly OK.
    graders:
      - type: exact
        value: OK
      - type: regex
        value: '^OK$'
        weight: 2
```

Each case gets a newly constructed model request containing only that case's optional system prompt and user prompt. The runner supports `exact`, `contains`, and `regex` graders. Checks can be case-insensitive and weighted; a case passes only when every check passes, while the weighted score preserves partial credit.

`suites/core.yaml` contains:

- `strawberry-count`: explicitly a smoke check, not a reasoning benchmark.
- `poker-river-analysis`: a fixed hand with deterministic invariants for action, pot odds, value range, bluffs, and blocker analysis.

The poker checks verify required analytical content, not whether a subjective strategy is solver-optimal. An automated LLM judge is intentionally not presented as implemented. The next extension is an isolated judge request with an explicit schema like:

```yaml
graders:
  - type: llm_judge             # planned; currently rejected by validation
    model: openai/gpt-4o-mini
    rubric:
      - Correctly computes the call threshold.
      - Builds coherent value and bluff ranges.
    score_range: [0, 4]
```

That extension should persist the judge model, rubric, raw judgment, and score, and should treat judge errors independently from candidate-model errors.

## Scheduling and failure behavior

- `--mode parallel --concurrency N` bounds in-flight requests across the full model/case/repeat matrix.
- `--mode sequential` runs model, case, and repeat loops in stable order.
- Repeat `--model` to compare multiple model IDs in one invocation.
- `--repeat N` samples each model/case pair N times.
- A provider or case failure becomes an `error` result; remaining jobs continue.
- The command writes reports before exiting. It exits nonzero when any case fails or errors.

## Results

By default, reports land under ignored `results/` with timestamped matching names:

```text
results/core_20260825T120000.000000Z.json
results/core_20260825T120000.000000Z.md
```

JSON includes raw output, duration, error text, model and generation settings, provider metadata, grader details, per-case status/score, and overall/per-model summaries. Markdown leads with the aggregate and then shows case outputs and checks.

Use `--output-dir PATH` to change the destination. Credential-like settings are rejected before a suite can run, so API keys are never part of suite data or result metadata.

## Development

```bash
uv sync
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv build
uv run starkeval --help
uv run starkeval run --help
```
