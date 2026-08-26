# Agent Notes

This repository is a macOS-first local model evaluation MVP. Keep `EVALS.md` and
`SCORECARD.md` public and unchanged unless Sam explicitly edits the public fixture.

## Constraints

- Do not commit or push unless Sam explicitly authorizes that action for the current task.
- Do not deploy, activate CI, call real model providers, or use credentials.
- Default backend bind is `127.0.0.1`; non-loopback requires explicit dev override.
- Credentials belong in the keychain abstraction only. They must not enter SQLite, API
  responses, exports, browser storage, logs, screenshots, exceptions, or fixtures.
- Treat imported packs, filenames, HTML, model output, logs, and artifacts as hostile.
- Sandbox execution is container-spec first and must never execute directly on the host.
- Docker/Podman absence is expected on some macOS hosts; report unavailable truthfully.

## Local Commands

```bash
UV_CACHE_DIR=.uv-cache uv run pytest backend/tests sandbox/tests packaging/macos/tests -q
UV_CACHE_DIR=.uv-cache uv run ruff check backend sandbox packaging
UV_CACHE_DIR=.uv-cache uv run mypy
npm ci --prefix web
npm run lint --prefix web
npm run typecheck --prefix web
npm test --prefix web
npm run build --prefix web
npm run smoke --prefix web
python3 packaging/macos/build_app.py --repo-root . --output packaging/macos/build
```

With restricted network, use the checked-in source and report dependency fetch failures
instead of replacing real dependencies with local stubs.

## Private Tests

Sam can launch the app, import the public pack, then create/import six private tests
locally through the Suites workflow. Private prompts and rubrics should stay outside the
repository.
