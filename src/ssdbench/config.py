"""Configuration and default paths."""
from __future__ import annotations

import os
from pathlib import Path


def default_runs_root() -> Path:
    """Return the default location for run directories.

    Can be overridden via the SSDBENCH_RUNS_DIR environment variable.
    """
    env = os.environ.get("SSDBENCH_RUNS_DIR")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".ssdbench" / "runs"
