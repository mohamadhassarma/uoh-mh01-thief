"""The running build's own git commit hash (rule #53) — read via
`git rev-parse HEAD` at process start, never hand-typed, so a code change
between sub-games is reflected automatically."""

from __future__ import annotations

import subprocess


def current_commit_hash(cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"
