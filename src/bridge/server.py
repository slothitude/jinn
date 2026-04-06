import asyncio
import json
import sys
from typing import Any, Dict

from src.promptos.engine import render_graph


class BridgeServer:
    """Python <-> TypeScript IPC bridge over stdio JSON-RPC.

    Protocol: one JSON object per line.
    Request:  {"id": 1, "method": "render_graph", "params": {...}}
    Response: {"id": 1, "result": {...}} or {"id": 1, "error": "..."}
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
        return {"memories": []}

    async def _handle_ping(self, params: dict) -> dict:
        return {"status": "ok", "version": "0.1.0"}

    async def handle_request(self, raw: str) -> str:
        """Parse a JSON-RPC request, dispatch to handler, return JSON response."""
        request_id = None
        try:
            request = json.loads(raw)
            request_id = request.get("id")
            method = request.get("method", "")
            handler = self._handlers.get(method)
            if not handler:
                result = {"id": request_id, "error": f"Unknown method: {method}"}
            else:
                rpc_result = await handler(request.get("params", {}))
                result = {"id": request_id, "result": rpc_result}
        except json.JSONDecodeError as e:
            result = {"id": request_id, "error": f"Invalid JSON: {e}"}
        except Exception as e:
            result = {"id": request_id, "error": str(e)}
        return json.dumps(result)

    async def run(self) -> None:
        """Main loop: read JSON lines from stdin, write JSON lines to stdout."""
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


def main() -> None:
    asyncio.run(BridgeServer().run())


if __name__ == "__main__":
    main()
