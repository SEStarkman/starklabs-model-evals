# starklabs model evals

This repository contains the original public fixtures plus a macOS-first local
evaluation MVP. The app is intentionally local: it binds to `127.0.0.1`, uses a
random per-launch bearer token, stores run data in SQLite, and never calls real
model providers in tests.

`EVALS.md` and `SCORECARD.md` remain public fixture/source material.

## Run the original public tests

1. Give a model that can open links the repository URL, `https://github.com/SEStarkman/starklabs-model-evals`, then paste this exact instruction:

```text
Open ONLY EVALS.md in https://github.com/SEStarkman/starklabs-model-evals. Run every test in order. Do not read or use SCORECARD.md. Label each answer with the exact heading requested in EVALS.md.
```

2. If the model cannot open links, copy all of [EVALS.md](EVALS.md) and paste it into the chat.

## Score the answers

Give a separate judge model the candidate's answers and [SCORECARD.md](SCORECARD.md), or score the answers yourself with the same rubric.

## Add a test

1. Add one numbered section to `EVALS.md`.
2. Add a section with the same number to `SCORECARD.md`.

```markdown
<!-- EVALS.md -->
## Test N

[Question and answer instructions]

<!-- SCORECARD.md -->
## Test N

[Scoring rules]
```

## Limitation

Running every test in one chat is convenient, but it is not a laboratory benchmark because later answers share context from earlier tests. It is still useful for quick personal comparisons.

## Local MVP

Backend:

```bash
STARKLABS_SESSION_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" \
UV_CACHE_DIR=.uv-cache uv run python -m starklabs_evals.server --host 127.0.0.1 --port 8765
```

Direct backend startup requires `STARKLABS_SESSION_TOKEN` in the environment.
The server never prints the bearer token; the macOS launcher passes its generated
token to the backend through env and to the browser through the URL fragment.

Web:

```bash
npm ci --prefix web
npm run dev --prefix web
```

Open the web UI through the macOS launcher when possible so the session token is
passed in the URL fragment and then removed from browser history. The app does
not use browser storage for credentials or the bearer token.

Validation:

```bash
UV_CACHE_DIR=.uv-cache uv run ruff check backend sandbox packaging
UV_CACHE_DIR=.uv-cache uv run mypy
UV_CACHE_DIR=.uv-cache uv run pytest backend/tests sandbox/tests packaging/macos/tests -q
npm run lint --prefix web
npm run typecheck --prefix web
npm test --prefix web
npm run build --prefix web
npm run smoke --prefix web
```

## Public Example Pack

The importable example pack is at `evals/public/1.0.0/pack.json` and adapts the
public markdown tests. It does not contain private prompts, private rubrics, or
credentials.

## macOS Packaging

Build an unsigned local `.app`:

```bash
python3 packaging/macos/build_app.py --repo-root . --output packaging/macos/build
```

The package is unsigned and not notarized. Code signing, notarization, hardened
runtime entitlements, and distribution outside local development are deferred.
HTML model output is shown only in an opt-in, script-disabled sandboxed preview;
interactive JavaScript previews are deferred until a separately hardened isolated
renderer exists. The launcher starts the loopback backend, serves the built UI,
browser, passes a random token via URL fragment, and shuts down the backend when
the launcher exits.

## Concourse

The Rainmaker-style pipeline lives in `ci/pipeline.yml` and watches `main`.
It has backend, web, sandbox-security, gitleaks, and manual macOS package gates.
Linux tasks do not claim to package macOS artifacts.

To statically validate the pipeline without setting, unpausing, or triggering it:

```bash
TARGET=starklabs \
PIPELINE=starklabs-model-evals \
SECRETS_FILE=starklabs-ci/concourse/secrets.yml \
ci/set-pipeline.sh
```

## Adding Private Tests Locally

After launch, Sam should create or import six private tests through the Suites
workflow. Keep those private prompts/rubrics outside git. Exports omit
credentials by design, but private packs should still be handled as sensitive
local files.
