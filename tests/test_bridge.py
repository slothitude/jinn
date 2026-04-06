import json

import pytest

from src.bridge.server import BridgeServer


@pytest.mark.asyncio
async def test_bridge_ping():
    server = BridgeServer()
    request = json.dumps({"id": 1, "method": "ping", "params": {}})
    response_raw = await server.handle_request(request)
    response = json.loads(response_raw)
    assert response["id"] == 1
    assert response["result"]["status"] == "ok"


@pytest.mark.asyncio
async def test_bridge_render_graph():
    server = BridgeServer()
    request = json.dumps({
        "id": 2,
        "method": "render_graph",
        "params": {
            "template_names": ["base/system", "agents/buddy"],
            "context": {"memories": [], "tools_list": []},
            "agent_role": "buddy",
        },
    })
    response_raw = await server.handle_request(request)
    response = json.loads(response_raw)
    assert response["id"] == 2
    assert "BUDDY" in response["result"]["system_prompt"]
    assert response["result"]["memory_blocks_used"] == 0


@pytest.mark.asyncio
async def test_bridge_unknown_method():
    server = BridgeServer()
    request = json.dumps({"id": 3, "method": "nonexistent", "params": {}})
    response_raw = await server.handle_request(request)
    response = json.loads(response_raw)
    assert response["id"] == 3
    assert "error" in response


@pytest.mark.asyncio
async def test_bridge_invalid_json():
    server = BridgeServer()
    response_raw = await server.handle_request("not json at all")
    response = json.loads(response_raw)
    assert "error" in response
    assert "Invalid JSON" in response["error"]


@pytest.mark.asyncio
async def test_bridge_retrieve():
    server = BridgeServer()
    request = json.dumps({
        "id": 4,
        "method": "retrieve",
        "params": {"query": "test", "agent_role": "buddy"},
    })
    response_raw = await server.handle_request(request)
    response = json.loads(response_raw)
    assert response["id"] == 4
    assert "memories" in response["result"]
