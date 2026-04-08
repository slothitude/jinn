"""Version utilities — single source of truth is pyproject.toml."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_PYPROJECT = _PROJECT_ROOT / "pyproject.toml"
_VERSION_RE = re.compile(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', re.MULTILINE)


def get_version(project_root: Path | None = None) -> str:
    """Read version from pyproject.toml (e.g. '0.3.0')."""
    toml_path = (project_root or _PROJECT_ROOT) / "pyproject.toml"
    text = toml_path.read_text(encoding="utf-8")
    m = _VERSION_RE.search(text)
    if not m:
        return "0.0.0-unknown"
    return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"


def get_git_info() -> dict[str, str]:
    """Return current git branch and short commit hash."""
    result: dict[str, str] = {"branch": "unknown", "commit": "unknown"}
    try:
        branch = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
        )
        if branch.returncode == 0:
            result["branch"] = branch.stdout.strip()

        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(_PROJECT_ROOT),
        )
        if commit.returncode == 0:
            result["commit"] = commit.stdout.strip()
    except FileNotFoundError:
        pass
    return result
