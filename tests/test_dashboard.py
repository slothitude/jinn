"""Tests for DecisionTrace Dashboard API and HTML."""

import json

import pytest

from src.feedback.trace_logger import DecisionTrace, TraceLogger
from src.dashboard.server import DashboardServer

from aiohttp.test_utils import TestClient, TestServer


@pytest.fixture
def trace_logger(tmp_path):
    tl = TraceLogger(db_path=tmp_path / "test_dashboard.db")
    yield tl
    tl.close()


@pytest.fixture
async def client(trace_logger):
    ds = DashboardServer(trace_logger)
    server = TestServer(ds.app)
    c = TestClient(server)
    await c.start_server()
    yield c
    await c.close()


# --- Test 1: /api/traces empty ---


@pytest.mark.asyncio
async def test_api_traces_empty(client):
    resp = await client.get("/api/traces")
    assert resp.status == 200
    data = await resp.json()
    assert data == []


# --- Test 2: /api/traces returns recorded ---


@pytest.mark.asyncio
async def test_api_traces_returns_recorded(client, trace_logger):
    trace_logger.record(DecisionTrace(
        trace_id="abc123",
        session_id="s1",
        outcome="success",
        policy_decision={"agent": "BUDDY"},
        tool_calls=[{"name": "bash", "args": '{"command": "ls"}'}],
    ))
    resp = await client.get("/api/traces")
    data = await resp.json()
    assert len(data) == 1
    assert data[0]["trace_id"] == "abc123"
    assert data[0]["outcome"] == "success"
    assert data[0]["tool_calls"][0]["name"] == "bash"


# --- Test 3: /api/traces/{id} found ---


@pytest.mark.asyncio
async def test_api_trace_by_id(client, trace_logger):
    trace_logger.record(DecisionTrace(
        trace_id="def456",
        session_id="s2",
        outcome="failure",
        policy_decision={"agent": "KAIROS"},
    ))
    resp = await client.get("/api/traces/def456")
    data = await resp.json()
    assert data["trace_id"] == "def456"
    assert data["outcome"] == "failure"


# --- Test 4: /api/traces/{id} not found ---


@pytest.mark.asyncio
async def test_api_trace_not_found(client):
    resp = await client.get("/api/traces/nonexistent")
    assert resp.status == 404
    data = await resp.json()
    assert "error" in data


# --- Test 5: /api/stats ---


@pytest.mark.asyncio
async def test_api_stats(client, trace_logger):
    trace_logger.record(DecisionTrace(trace_id="s1", outcome="success"))
    trace_logger.record(DecisionTrace(trace_id="s2", outcome="success"))
    trace_logger.record(DecisionTrace(trace_id="s3", outcome="failure"))

    resp = await client.get("/api/stats")
    data = await resp.json()
    assert data["total"] == 3
    assert data["counts"]["success"] == 2
    assert data["counts"]["failure"] == 1


# --- Test 6: / serves HTML ---


@pytest.mark.asyncio
async def test_dashboard_html_served(client):
    resp = await client.get("/")
    assert resp.status == 200
    text = await resp.text()
    assert "JINN DecisionTrace Dashboard" in text
    assert "<html" in text
