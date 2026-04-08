"""Self-awareness and self-modification tools for JINN.

Provides 5 tools (version_info, version_bump, test_run, git_commit_push,
self_update) that let agents inspect and modify the running system.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from src.execution.toolbox import ToolSchema

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

VERSION_INFO_TOOL = ToolSchema(
    name="version_info",
    description="Get current JINN version, git branch, and commit hash.",
    parameters={
        "type": "object",
        "properties": {},
    },
    cost_factor=0.1,
)

VERSION_BUMP_TOOL = ToolSchema(
    name="version_bump",
    description="Bump the version in pyproject.toml (major/minor/patch).",
    parameters={
        "type": "object",
        "properties": {
            "level": {
                "type": "string",
                "enum": ["major", "minor", "patch"],
                "description": "Which version component to bump",
            },
        },
        "required": ["level"],
    },
    cost_factor=0.5,
    safety_level=1,
)

TEST_RUN_TOOL = ToolSchema(
    name="test_run",
    description="Run pytest and return pass/fail results with output.",
    parameters={
        "type": "object",
        "properties": {
            "args": {
                "type": "string",
                "description": "Extra pytest args (e.g. 'tests/test_memory.py' or '-k test_foo')",
            },
            "timeout": {
                "type": "number",
                "description": "Timeout in seconds (default 120)",
            },
        },
    },
    cost_factor=5.0,
)

GIT_COMMIT_PUSH_TOOL = ToolSchema(
    name="git_commit_push",
    description="Stage files, commit, and push to remote. Runs tests first by default.",
    parameters={
        "type": "object",
        "properties": {
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "File paths to stage (relative to project root)",
            },
            "message": {"type": "string", "description": "Commit message"},
            "test_first": {
                "type": "boolean",
                "description": "Run tests before committing (default true)",
            },
        },
        "required": ["message"],
    },
    cost_factor=10.0,
    safety_level=2,
)

SELF_UPDATE_TOOL = ToolSchema(
    name="self_update",
    description="Pull latest changes from remote master branch.",
    parameters={
        "type": "object",
        "properties": {},
    },
    cost_factor=3.0,
    safety_level=2,
)

SELF_TOOLS: list[ToolSchema] = [
    VERSION_INFO_TOOL,
    VERSION_BUMP_TOOL,
    TEST_RUN_TOOL,
    GIT_COMMIT_PUSH_TOOL,
    SELF_UPDATE_TOOL,
]


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

class SelfToolsAdapter:
    """Adapter for self-modification operations."""

    def __init__(self, project_root: Path | None = None) -> None:
        self._root = project_root or Path(__file__).resolve().parent.parent.parent

    # -- version_info -------------------------------------------------------

    async def version_info(self) -> tuple[str, bool]:
        from src.core.version import get_version, get_git_info
        ver = get_version(project_root=self._root)
        git = get_git_info()
        return json.dumps({
            "version": ver,
            "branch": git["branch"],
            "commit": git["commit"],
        }, indent=2), True

    # -- version_bump -------------------------------------------------------

    async def version_bump(self, level: str) -> tuple[str, bool]:
        toml_path = self._root / "pyproject.toml"
        try:
            text = toml_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return f"pyproject.toml not found at {toml_path}", False

        m = re.search(r'^version\s*=\s*"(\d+)\.(\d+)\.(\d+)"', text, re.MULTILINE)
        if not m:
            return "Could not parse version from pyproject.toml", False

        major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
        old = f"{major}.{minor}.{patch}"

        if level == "major":
            major += 1
            minor = 0
            patch = 0
        elif level == "minor":
            minor += 1
            patch = 0
        elif level == "patch":
            patch += 1
        else:
            return f"Invalid bump level: {level}", False

        new = f"{major}.{minor}.{patch}"
        new_text = re.sub(
            r'^version\s*=\s*"\d+\.\d+\.\d+"',
            f'version = "{new}"',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        toml_path.write_text(new_text, encoding="utf-8")
        return json.dumps({"old": old, "new": new}), True

    # -- test_run -----------------------------------------------------------

    async def test_run(
        self, args: str = "", timeout: float = 120.0,
    ) -> tuple[str, bool]:
        cmd = f"python -m pytest {args}".strip() if args else "python -m pytest"
        try:
            proc = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._root),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            output = stdout.decode(errors="replace")
            passed = proc.returncode == 0
            return json.dumps({
                "passed": passed,
                "returncode": proc.returncode,
                "output": output[-4000:] if len(output) > 4000 else output,
            }), True
        except asyncio.TimeoutError:
            proc.kill()
            return json.dumps({
                "passed": False,
                "returncode": -1,
                "output": f"Tests timed out after {timeout}s",
            }), False
        except Exception as e:
            return json.dumps({"passed": False, "output": str(e)}), False

    # -- git_commit_push ----------------------------------------------------

    async def git_commit_push(
        self,
        message: str,
        files: list[str] | None = None,
        test_first: bool = True,
    ) -> tuple[str, bool]:
        # Step 1: test gate
        if test_first:
            output, ok = await self.test_run(timeout=120.0)
            result = json.loads(output)
            if not result["passed"]:
                return json.dumps({
                    "success": False,
                    "stage": "test_gate",
                    "test_output": result["output"][-2000:],
                }), False

        async def _git(*args: str) -> tuple[str, int]:
            proc = await asyncio.create_subprocess_shell(
                " ".join(["git", *args]),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._root),
            )
            stdout, _ = await proc.communicate()
            return stdout.decode(errors="replace"), proc.returncode or 0

        # Step 2: stage
        if files:
            out, rc = await _git("add", *files)
            if rc != 0:
                return json.dumps({"success": False, "stage": "add", "output": out}), False
        else:
            out, rc = await _git("add", "-A")
            if rc != 0:
                return json.dumps({"success": False, "stage": "add", "output": out}), False

        # Step 3: commit
        out, rc = await _git("commit", "-m", message.replace('"', '\\"'))
        if rc != 0:
            return json.dumps({"success": False, "stage": "commit", "output": out}), False

        # Step 4: get commit hash
        hash_out, _ = await _git("rev-parse", "--short", "HEAD")
        commit_hash = hash_out.strip()

        # Step 5: get current branch
        branch_out, _ = await _git("rev-parse", "--abbrev-ref", "HEAD")
        branch = branch_out.strip()

        # Step 6: push
        push_out, rc = await _git("push", "origin", branch)
        if rc != 0:
            return json.dumps({
                "success": False,
                "stage": "push",
                "commit": commit_hash,
                "output": push_out,
            }), False

        return json.dumps({
            "success": True,
            "commit": commit_hash,
            "branch": branch,
        }), True

    # -- self_update --------------------------------------------------------

    async def self_update(self) -> tuple[str, bool]:
        try:
            proc = await asyncio.create_subprocess_shell(
                "git pull origin master",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(self._root),
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode(errors="replace")
            return json.dumps({
                "success": proc.returncode == 0,
                "output": output,
            }), proc.returncode == 0
        except Exception as e:
            return json.dumps({"success": False, "output": str(e)}), False
