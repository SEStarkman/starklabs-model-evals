# StarkLabs Model Evals

Vendor-neutral, one-shot model evaluation gauntlet.

## Cases

1. **Poker Hand Analysis** — GTO analysis of a supplied hand history
2. **Python Murmuration** — Bird flocking simulation following the mouse
3. **Website Redesign** — Standalone redesign of samstarkman.com
4. **Long-Form X Post** — Educational post about the evaluated model in Sam's voice
5. **Interesting Fact** — Sourced, interest-aligned fact with relevance explanation

## Scoring

Each case rated 0–5. Total out of 25. See [scoreboard.md](scoreboard.md).

## Run Layout

```
runs/<model>/<date>/
├── run.md
├── poker-hand-analysis/
├── python-murmuration/
├── personal-website-redesign/
├── new-model-x-post/
├── interesting-fact/
└── scores.md
```

## Running

Use the `starklabs-model-eval` skill (in `starklabs-skills`) to orchestrate runs. Each run is one prompt, one attempt per case.
