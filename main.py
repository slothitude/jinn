import asyncio
import os
import sys
from pathlib import Path

# Ensure stdout can handle unicode (emojis etc.) when piped
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from aiohttp import web

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState, Event
from src.core.query_engine import QueryEngine
from src.core.resource_manager import ResourceManager
from src.agents.buddy import BuddyAgent
from src.agents.kairos import KairosAgent
from src.agents.ultraplan import UltraplanAgent
from src.agents.orchestrator import OrchestratorAgent
from src.agents.supervisor import SupervisorAgent
from src.execution.toolbox import ToolExecutor
from src.execution.agent_tools import AgentToolExecutor
from src.execution.web_tools import WebToolsAdapter
from src.memory.store import MemoryStore
from src.memory.wiki import WikiStore
from src.memory.retrieval import retrieve as memory_retrieve
from src.memory.retrieval import retrieve_with_wiki
from src.memory.wiki_compiler import WikiCompiler
from src.memory.autodream import AutoDream
from src.feedback.trace_logger import TraceLogger
from src.feedback.observability import register_feedback_hooks
from src.core.registry import wire
from src.dashboard.server import DashboardServer


def _read_lines_sync():
    """Yield lines from stdin (pipe mode)."""
    for line in sys.stdin:
        yield line.rstrip("\n")


async def main() -> None:
    # L2: EventBus
    bus = EventBus()

    # L2.5: ResourceManager — provider registry + quota tracking
    # Profiles loaded from defaults in resource_manager.py
    # Override via env: ZHIPU_RATE_LIMIT, ZHIPU_RATE_WINDOW, ZHIPU_PRIORITY, etc.
    rm = ResourceManager.from_defaults()

    # L4: Memory
    store = MemoryStore()
    wiki_store = WikiStore()
    autodream = AutoDream(bus, store)

    # L6: Agents
    buddy = BuddyAgent(bus)
    kairos = KairosAgent(bus)
    ultraplan = UltraplanAgent(bus)
    orchestrator = OrchestratorAgent(bus, provider="zhipu")
    supervisor = SupervisorAgent(bus, provider="zhipu")

    # Wire ResourceManager into all agents
    buddy.set_resource_manager(rm, "BUDDY")
    kairos.set_resource_manager(rm, "KAIROS")
    ultraplan.set_resource_manager(rm, "ULTRAPLAN")
    orchestrator.set_resource_manager(rm, "ORCHESTRATOR")
    supervisor.set_resource_manager(rm, "SUPERVISOR")

    # Wire declarative subscriptions via @listens decorators
    wire(bus, autodream, kairos, buddy, orchestrator, supervisor)

    # L7: Tool Execution
    tool_executor = ToolExecutor(bus)
    buddy.set_tool_executor(tool_executor)

    # L7.5: Agent-to-agent delegation bridge (multi-provider)
    agent_tool_executor = AgentToolExecutor(bus, {}, tool_executor)
    orchestrator.set_agent_tool_executor(agent_tool_executor)
    supervisor.set_agent_tool_executor(agent_tool_executor)

    # L8: Feedback
    trace_logger = TraceLogger()
    register_feedback_hooks(bus, trace_logger)

    # L9: Rich CLI Renderer (graceful fallback if rich unavailable or non-TTY)
    renderer = None
    pipe_mode = not sys.stdin.isatty()
    if not pipe_mode:
        try:
            from src.cli.renderer import RichOrchestrationRenderer
            renderer = RichOrchestrationRenderer(bus)
            renderer.start()
        except ImportError:
            pass

    # L3-L7: QueryEngine orchestrator
    engine = QueryEngine(bus)
    engine.set_resource_manager(rm)
    engine.register_agent(buddy)
    engine.register_agent(kairos)
    engine.register_agent(ultraplan)
    engine.register_agent(orchestrator)
    engine.register_agent(supervisor)

    # Wire agent tool executor with full agent registry (after registration)
    agent_tool_executor.agents = engine.agents
    engine.memory_retriever = lambda q, strategy: memory_retrieve(q, strategy, store)
    engine.wiki_retriever = lambda q, strategy: retrieve_with_wiki(q, strategy, store, wiki_store)

    # Wiki Compiler (needs PromptOS from QueryEngine)
    compiler = WikiCompiler(bus, engine.prompt_os, wiki_store)

    # Dashboard (web UI)
    dashboard = DashboardServer(
        trace_logger=trace_logger,
        wiki_store=wiki_store,
        memory_store=store,
        bus=bus,
        query_engine=engine,
    )
    dashboard_runner = web.AppRunner(dashboard.app)
    await dashboard_runner.setup()
    dashboard_site = web.TCPSite(dashboard_runner, "localhost", 8080)
    await dashboard_site.start()

    # Session state
    state = AgentState(session_id="cli-session-001")

    if renderer is None:
        print("=== JINN — Programmable Cognition System ===")
        print("Dashboard: http://localhost:8080")
        quota_status = rm.get_quota_status()
        for pname, info in quota_status.items():
            remaining = "unlimited" if info["remaining"] < 0 else f"{info['remaining']}/{info['limit']}"
            print(f"  [provider] {pname}: {remaining} requests remaining")
        if WebToolsAdapter.is_available():
            print("[web] web_eyes integration available")
        if pipe_mode:
            print("[pipe mode] reading from stdin\n")
        else:
            print("Type your input (or 'quit' to exit):\n")

    # Build input source: pipe reads stdin lines, interactive uses input()
    if pipe_mode:
        input_source = _read_lines_sync()
    else:
        input_source = None  # use input() per iteration

    while True:
        try:
            if pipe_mode:
                try:
                    user_input = next(input_source).strip()
                except StopIteration:
                    break
            else:
                if renderer:
                    renderer.pause()
                loop = asyncio.get_event_loop()
                user_input = await loop.run_in_executor(None, lambda: input("> ").strip())
                if renderer:
                    renderer.resume()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break

        if user_input.lower() in ("quit", "exit", "q"):
            print("Goodbye.")
            break

        if not user_input:
            continue

        if renderer:
            renderer.resume()

        if user_input.startswith("/restart"):
            print("Restarting JINN...")
            os.system("cls" if os.name == "nt" else "clear")
            print("=== JINN — Programmable Cognition System ===\n")
            continue

        if user_input.startswith("/update"):
            print("Pulling latest changes...")
            _project_root = str(Path(__file__).resolve().parent)
            proc = await asyncio.create_subprocess_shell(
                "git pull origin master",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=_project_root,
            )
            stdout, _ = await proc.communicate()
            print(stdout.decode(errors="replace"))
            if proc.returncode == 0:
                print("Update successful.")
            else:
                print("Update failed.")
            continue

        if user_input.startswith("/dashboard"):
            print("Dashboard: http://localhost:8080")
            continue

        if user_input.startswith("/compile"):
            parts = user_input.split()
            raw_dir = "raw/godot"
            limit = 0
            category_filter = ""

            # Parse args: /compile [dir] [--limit N] [--category name]
            for i, part in enumerate(parts[1:], 1):
                if part == "--limit" and i < len(parts) - 1:
                    limit = int(parts[i + 1])
                elif part == "--category" and i < len(parts) - 1:
                    category_filter = parts[i + 1]
                elif not part.startswith("--") and raw_dir == "raw/godot" and part == parts[1]:
                    raw_dir = part

            result = await compiler.compile_directory(
                Path(raw_dir), limit=limit, category_filter=category_filter
            )
            print(f"\nCompiled: {result.compiled} | Skipped: {result.skipped} | Errors: {result.errors}")
            if result.pages_written:
                print("Pages written:")
                for p in result.pages_written:
                    print(f"  - {p}")
            print()
            continue

        if user_input.startswith("/export"):
            from src.memory.wiki_export import export_to_html
            pages = export_to_html(Path("wiki/godot"), Path("wiki/html"))
            print(f"Exported {len(pages)} pages to wiki/html/")
            continue

        request = AgentRequest(session_id=state.session_id, input_text=user_input)

        if renderer:
            renderer.set_user_input(user_input)

        response = await engine.process(request, state)

        # Always print the final response so it's visible as scrollback
        if renderer:
            renderer.pause()
        print(f"\n{response}\n", flush=True)

    # Cleanup
    if renderer:
        renderer.stop()
    await dashboard_runner.cleanup()
    await tool_executor.close_web()
    store.close()
    wiki_store.close()
    trace_logger.close()


if __name__ == "__main__":
    asyncio.run(main())
