"""Small project-environment loader for local development.

The command-line tools are intentionally dependency-light and do not require
python-dotenv. They load the repository root ``.env`` when present, while
keeping explicitly exported process variables authoritative.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_project_env(path: str | Path | None = None) -> Path | None:
    """Load simple ``KEY=VALUE`` entries without overwriting process values."""

    env_path = Path(path) if path is not None else Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return None
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        # Some copied dashboard values escape underscores even though dotenv
        # values do not require it. Normalize that harmless presentation
        # escape so RPC hostnames remain usable.
        value = value.replace("\\_", "_")
        os.environ[key] = value
    return env_path
