from __future__ import annotations

import argparse
import os
from pathlib import Path

import uvicorn

from .app import create_app


def session_token_from_env() -> str:
    token = os.environ.get("STARKLABS_SESSION_TOKEN")
    if not token:
        msg = "STARKLABS_SESSION_TOKEN must be set for direct server startup"
        raise SystemExit(msg)
    return token


def main() -> None:
    parser = argparse.ArgumentParser()
    default_db = Path.home() / ".starklabs-model-evals" / "evals.sqlite"
    parser.add_argument("--db", default=str(default_db))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--allow-non-loopback", action="store_true")
    parser.add_argument("--web-dist", default="")
    args = parser.parse_args()
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    app = create_app(
        db_path=db_path,
        bind_host=args.host,
        allow_non_loopback=args.allow_non_loopback,
        session_token=session_token_from_env(),
        web_dist=args.web_dist or None,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
