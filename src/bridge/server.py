import asyncio
import json
import sys
from typing import Any, Dict

from src.promptos.engine import render_graph


class BridgeServer:
    """Python <-> TypeScript IPC bridge over stdio JSON-RPC.

    Request format:
        {"method": "render_graph", "template_names": [...], "context": {...}, "agent_role": "buddy"}
        {"method": "retrieve", "query": "...", "agent_role": "buddy", "k": 10}

    Response format:
        {"system_prompt": "...", "memory_blocks_used": 8}
        {"memories": [...]}
    """

    def __init__(self) -> None:
        self._handlers: Dict[str, Any] = {
            "render_graph": self._handle_render_graph,
            "retrieve": self._handle_retrieve,
            "ping": self._handle_ping,
        }

    async def _handle_render_graph(self, params: dict) -> dict:
        template_names = params.get("template_names", [])
        context = params.get("context", {})
        agent_role = params.get("agent_role")

        system_prompt = await render_graph(template_names, context, agent_role=agent_role)
        memory_count = len(context.get("memories", []))
        return {"system_prompt": system_prompt, "memory_blocks_used": memory_count}

    async def _handle_retrieve(self, params: dict) -> dict:
        # Stub — will be wired to MemoryStore in production
        return {"memories": []}

    async def _handle_ping(self, params: dict) -> dict:
        return {"status": "ok", "version": "0.1.0"}

    async def handle_request(self, raw: str) -> str:
        try:
            request = json.loads(raw)
            method = request.get("method", "")
            handler = self._handlers.get(method)
            if not handler:
                result = {"error": f"Unknown method: {method}"}
            else:
                result = await handler(request.get("params", {}))
        except json.JSONDecodeError as e:
            result = {"error": f"Invalid JSON: {e}"}
        except Exception as e:
            result = {"error": str(e)}
        return json.dumps(result)

    async def run(self) -> None:
        """Main loop — read JSON from stdin, write JSON to stdout."""
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            line = await reader.readline()
            if not line:
                break
            raw = line.decode("utf-8").strip()
            if not raw:
                continue
            response = await self.handle_request(raw)
            sys.stdout.write(response + "\n")
            sys.stdout.flush()
