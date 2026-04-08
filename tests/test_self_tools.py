"""Tests for self_tools: version_info, version_bump, test_run."""

import asyncio
import json
from pathlib import Path

import pytest

from src.execution.self_tools import SelfToolsAdapter


# Helper: create a temp pyproject.toml in isolated directory

def _make_temp_project(tmp_path: Path, version: str = "1.2.3") -> Path:
    toml = tmp_path / "pyproject.toml"
    toml.write_text(
        f'[project]\nname = "test-jinn"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    return tmp_path


# --- version_info ---

async def test_version_info_reads_pyproject(tmp_path):
    root = _make_temp_project(tmp_path, "2.5.1")
    adapter = SelfToolsAdapter(project_root=root)
    output, ok = await adapter.version_info()
    assert ok
    data = json.loads(output)
    assert data["version"] == "2.5.1"


# --- version_bump ---

async def test_version_bump_patch_increments(tmp_path):
    root = _make_temp_project(tmp_path, "1.2.3")
    adapter = SelfToolsAdapter(project_root=root)
    output, ok = await adapter.version_bump("patch")
    assert ok
    data = json.loads(output)
    assert data["old"] == "1.2.3"
    assert data["new"] == "1.2.4"
    # Verify the file was actually updated
    text = (root / "pyproject.toml").read_text()
    assert 'version = "1.2.4"' in text


async def test_version_bump_minor_resets_patch(tmp_path):
    root = _make_temp_project(tmp_path, "1.2.9")
    adapter = SelfToolsAdapter(project_root=root)
    output, ok = await adapter.version_bump("minor")
    assert ok
    data = json.loads(output)
    assert data["old"] == "1.2.9"
    assert data["new"] == "1.3.0"


async def test_version_bump_major_resets_all(tmp_path):
    root = _make_temp_project(tmp_path, "3.9.9")
    adapter = SelfToolsAdapter(project_root=root)
    output, ok = await adapter.version_bump("major")
    assert ok
    data = json.loads(output)
    assert data["new"] == "4.0.0"


# --- test_run ---

async def test_test_run_returns_results(tmp_path):
    root = _make_temp_project(tmp_path, "0.1.0")
    # Create a minimal test that passes
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_dummy.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8",
    )
    adapter = SelfToolsAdapter(project_root=root)
    output, ok = await adapter.test_run(args=str(tests_dir / "test_dummy.py"))
    assert ok  # the tool itself succeeded (ran pytest)
    data = json.loads(output)
    assert isinstance(data["passed"], bool)
    assert isinstance(data["output"], str)
