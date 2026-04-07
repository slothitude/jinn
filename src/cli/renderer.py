"""Rich CLI renderer — live orchestration tree visualization.

Subscribes to EventBus events and renders a live agent tree using Rich.
Observer-only: never modifies agent state or flow.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass, field

from rich.console import Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree

from src.cli.themes import (
    AGENT_COLORS,
    AGENT_ICONS,
    REFRESH_INTERVAL,
    STATUS_COLORS,
    STATUS_ICONS,
    TOOL_ICONS,
)
from src.core.bus import EventBus
from src.core.models import Event


@dataclass
class AgentNode:
    """In-memory node representing an agent in the orchestration tree."""

    name: str
    agent_type: str
    status: str = "queued"
    provider: str = ""
    model: str = ""
    parent_key: str | None = None
    task_desc: str = ""
    tool_calls: list[str] = field(default_factory=list)
    started_at: float = 0.0

    @property
    def elapsed(self) -> str:
        if self.started_at == 0:
            return ""
        secs = time.monotonic() - self.started_at
        if secs < 60:
            return f"{secs:.1f}s"
        return f"{secs / 60:.1f}m"


# Step marker pattern from BUDDY plan execution
_STEP_RE = re.compile(r"---\s*Step\s+(\d+):\s*(.+?)\s*---")


class RichOrchestrationRenderer:
    """EventBus subscriber that renders a live orchestration tree with Rich."""

    def __init__(self, bus: EventBus) -> None:
        self._bus = bus
        self._agents: dict[str, AgentNode] = {}
        self._active_stack: list[str] = []
        self._session_map: dict[str, str] = {}  # session_id -> node_key
        self._output_buffer: list[str] = []
        self._turn_count: int = 0
        self._plan_nodes: dict[int, tuple[str, str]] = {}  # step -> (desc, status)
        self._last_refresh: float = 0.0
        self._live: Live | None = None
        self._running: bool = False

    # -- Lifecycle --

    def start(self) -> None:
        """Subscribe to events and start the Rich Live display."""
        if not sys.stdout.isatty():
            return

        self._running = True
        self._subscribe()
        self._live = Live(
            self._build_banner(),
            console=None,
            refresh_per_second=15,
            vertical_overflow="visible",
        )
        self._live.start()

    def stop(self) -> None:
        """Unsubscribe and stop the Rich Live display."""
        self._running = False
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._unsubscribe_all()

    def pause(self) -> None:
        """Pause the live display (e.g. for user input)."""
        if self._live is not None:
            self._live.stop()

    def resume(self) -> None:
        """Resume the live display after pause."""
        if self._live is not None and self._running:
            self._live.start()

    # -- Event subscriptions --

    def _subscribe(self) -> None:
        bus = self._bus
        bus.subscribe(Event.TURN_START, self.on_turn_start, priority=100, name="cli.renderer")
        bus.subscribe(Event.AGENT_START, self.on_agent_start, priority=100, name="cli.renderer")
        bus.subscribe(Event.AGENT_CHUNK, self.on_agent_chunk, priority=100, name="cli.renderer")
        bus.subscribe(Event.AGENT_END, self.on_agent_end, priority=100, name="cli.renderer")
        bus.subscribe(
            Event.DELEGATION_START, self.on_delegation_start, priority=100, name="cli.renderer"
        )
        bus.subscribe(
            Event.DELEGATION_END, self.on_delegation_end, priority=100, name="cli.renderer"
        )
        bus.subscribe(
            Event.TOOL_CALL_REQUEST, self.on_tool_call_request, priority=100, name="cli.renderer"
        )
        bus.subscribe(
            Event.TOOL_CALL_RESULT, self.on_tool_call_result, priority=100, name="cli.renderer"
        )
        bus.subscribe(
            Event.KAIROS_INTERRUPT, self.on_kairos_interrupt, priority=100, name="cli.renderer"
        )

    def _unsubscribe_all(self) -> None:
        events = [
            Event.TURN_START,
            Event.AGENT_START,
            Event.AGENT_CHUNK,
            Event.AGENT_END,
            Event.DELEGATION_START,
            Event.DELEGATION_END,
            Event.TOOL_CALL_REQUEST,
            Event.TOOL_CALL_RESULT,
            Event.KAIROS_INTERRUPT,
        ]
        for evt in events:
            self._bus.unsubscribe(evt, self.on_turn_start)  # won't match most, safe no-op
        # Direct unsubscribe by method reference
        self._bus.unsubscribe(Event.TURN_START, self.on_turn_start)
        self._bus.unsubscribe(Event.AGENT_START, self.on_agent_start)
        self._bus.unsubscribe(Event.AGENT_CHUNK, self.on_agent_chunk)
        self._bus.unsubscribe(Event.AGENT_END, self.on_agent_end)
        self._bus.unsubscribe(Event.DELEGATION_START, self.on_delegation_start)
        self._bus.unsubscribe(Event.DELEGATION_END, self.on_delegation_end)
        self._bus.unsubscribe(Event.TOOL_CALL_REQUEST, self.on_tool_call_request)
        self._bus.unsubscribe(Event.TOOL_CALL_RESULT, self.on_tool_call_result)
        self._bus.unsubscribe(Event.KAIROS_INTERRUPT, self.on_kairos_interrupt)

    # -- Refresh throttle --

    def _refresh(self) -> None:
        """Update the live display (throttled to ~15fps)."""
        if self._live is None:
            return
        now = time.monotonic()
        if now - self._last_refresh < REFRESH_INTERVAL:
            return
        self._last_refresh = now
        self._live.update(self._build_composite())

    # -- Event handlers --

    async def on_turn_start(self, payload: dict) -> None:
        self._turn_count += 1
        self._agents.clear()
        self._active_stack.clear()
        self._session_map.clear()
        self._output_buffer.clear()
        self._plan_nodes.clear()
        self._refresh()

    async def on_agent_start(self, payload: dict) -> None:
        agent_name: str = payload.get("agent", "UNKNOWN")
        # Determine agent type for icon/color lookup
        agent_type = self._resolve_agent_type(agent_name)
        provider = payload.get("provider", "")
        model = payload.get("model", "")

        # If this is a top-level agent (not delegated), add as root
        parent_key = self._active_stack[-1] if self._active_stack else None
        key = self._make_key(agent_name, parent_key)

        node = AgentNode(
            name=agent_name,
            agent_type=agent_type,
            status="thinking",
            provider=provider,
            model=model,
            parent_key=parent_key,
            started_at=time.monotonic(),
        )
        self._agents[key] = node
        self._active_stack.append(key)
        self._refresh()

    async def on_agent_chunk(self, payload: dict) -> None:
        agent_name: str = payload.get("agent", "UNKNOWN")
        chunk: str = payload.get("chunk", "")

        # Find the active node for this agent
        key = self._find_active_key(agent_name)
        if key and key in self._agents:
            self._agents[key].status = "streaming"

        # Accumulate output (last 500 chars)
        self._output_buffer.append(chunk)
        if len(self._output_buffer) > 50:
            self._output_buffer = self._output_buffer[-50:]
        total = "".join(self._output_buffer)
        if len(total) > 500:
            self._output_buffer = [total[-500:]]

        # Detect plan step markers
        step_match = _STEP_RE.search(chunk)
        if step_match:
            step_id = int(step_match.group(1))
            step_desc = step_match.group(2).strip()
            self._plan_nodes[step_id] = (step_desc, "running")
            # Mark previous steps as done
            for sid in self._plan_nodes:
                if sid < step_id:
                    _, st = self._plan_nodes[sid]
                    if st == "running":
                        self._plan_nodes[sid] = (self._plan_nodes[sid][0], "done")

        self._refresh()

    async def on_agent_end(self, payload: dict) -> None:
        agent_name: str = payload.get("agent", "UNKNOWN")
        # Pop from active stack
        if self._active_stack:
            top = self._active_stack[-1]
            if top in self._agents and self._agents[top].name == agent_name:
                self._active_stack.pop()
                self._agents[top].status = "done"
            else:
                # Find by name in stack
                for i in range(len(self._active_stack) - 1, -1, -1):
                    k = self._active_stack[i]
                    if k in self._agents and self._agents[k].name == agent_name:
                        self._agents[k].status = "done"
                        self._active_stack.pop(i)
                        break

        # Mark current plan step as done
        if self._plan_nodes:
            max_step = max(self._plan_nodes.keys())
            desc, st = self._plan_nodes[max_step]
            if st == "running":
                self._plan_nodes[max_step] = (desc, "done")

        self._refresh()

    async def on_delegation_start(self, payload: dict) -> None:
        task: str = payload.get("task", "")
        tier: str = payload.get("tier", "BUDDY")
        index: int = payload.get("index", 0)
        session_id: str = payload.get("session_id", "")

        # Parent is the current active agent
        parent_key = self._active_stack[-1] if self._active_stack else None
        agent_type = self._resolve_agent_type(tier)
        display_name = f"{tier}-{index}"
        key = f"{parent_key}:{tier}:{index}" if parent_key else f"{tier}:{index}"

        node = AgentNode(
            name=display_name,
            agent_type=agent_type,
            status="queued",
            parent_key=parent_key,
            task_desc=task[:60],
            started_at=time.monotonic(),
        )
        self._agents[key] = node

        if session_id:
            self._session_map[session_id] = key

        # Show delegation tool call on parent
        if parent_key and parent_key in self._agents:
            tool_name = "delegate_batch" if tier == "SUPERVISOR" else "spawn_workers"
            icon = TOOL_ICONS.get(tool_name, "\u2022")
            self._agents[parent_key].tool_calls.append(
                f"{icon} {tool_name}({task[:40]})"
            )
        self._refresh()

    async def on_delegation_end(self, payload: dict) -> None:
        tier: str = payload.get("tier", "BUDDY")
        index: int = payload.get("index", 0)
        success: bool = payload.get("success", True)
        session_id: str = payload.get("session_id", "")

        # Find the node by session_id or by tier+index
        key = self._session_map.pop(session_id, None) if session_id else None
        if not key:
            # Fallback: search by name
            key = self._find_node_by_tier_index(tier, index)

        if key and key in self._agents:
            self._agents[key].status = "done" if success else "error"
        self._refresh()

    async def on_tool_call_request(self, payload: dict) -> None:
        name: str = payload.get("name", "")
        arguments: str = payload.get("arguments", "{}")
        icon = TOOL_ICONS.get(name, "\u2022")

        # Extract a short summary from arguments
        summary = self._summarize_tool_args(name, arguments)

        # Attach to the active agent
        if self._active_stack:
            top = self._active_stack[-1]
            if top in self._agents:
                self._agents[top].tool_calls.append(f"{icon} {name}: {summary}")
        self._refresh()

    async def on_tool_call_result(self, payload: dict) -> None:
        # Tool completed — just refresh (the request already added the tool call line)
        self._refresh()

    async def on_kairos_interrupt(self, payload: dict) -> None:
        target: str = payload.get("target", "")
        message: str = payload.get("message", "")

        # Mark the target agent as interrupted
        for key, node in self._agents.items():
            if node.name == target:
                node.status = "interrupted"

        # Flash the alert in output
        self._output_buffer.append(f"\n\u26a0 KAIROS: {message}\n")
        self._refresh()

    # -- Key / lookup helpers --

    @staticmethod
    def _resolve_agent_type(name: str) -> str:
        upper = name.upper().rstrip("0123456789-_")
        for known in ("ORCHESTRATOR", "SUPERVISOR", "BUDDY", "ULTRAPLAN", "KAIROS", "SYSTEM"):
            if known in upper:
                return known
        return "BUDDY"

    @staticmethod
    def _make_key(name: str, parent_key: str | None) -> str:
        return f"{parent_key}/{name}" if parent_key else name

    def _find_active_key(self, agent_name: str) -> str | None:
        """Find the key for the most recently started agent with this name."""
        for i in range(len(self._active_stack) - 1, -1, -1):
            k = self._active_stack[i]
            if k in self._agents and self._agents[k].name == agent_name:
                return k
        # Fallback: search all agents
        for k, node in self._agents.items():
            if node.name == agent_name and node.status in ("thinking", "streaming"):
                return k
        return None

    def _find_node_by_tier_index(self, tier: str, index: int) -> str | None:
        display = f"{tier}-{index}"
        for k, node in self._agents.items():
            if node.name == display:
                return k
        return None

    @staticmethod
    def _summarize_tool_args(name: str, arguments: str) -> str:
        """Extract a short summary from tool arguments JSON."""
        try:
            import json
            args = json.loads(arguments)
        except (ValueError, TypeError):
            return arguments[:50]

        if name == "bash":
            cmd = args.get("command", "")
            return cmd[:60]
        if name in ("read", "write"):
            return args.get("path", args.get("file_path", ""))[:60]
        if name.startswith("web_"):
            url = args.get("url", args.get("query", ""))
            return url[:60]
        return str(args)[:60]

    # -- Rendering --

    def _build_composite(self) -> Group:
        """Build the full composite renderable."""
        parts: list = [self._build_banner()]
        if self._agents:
            parts.append(self._build_tree_panel())
        if self._output_buffer:
            parts.append(self._build_output_panel())
        if self._plan_nodes:
            parts.append(self._build_plan_progress())
        return Group(*parts)

    def _build_banner(self) -> Panel:
        turn_text = f"turn {self._turn_count}" if self._turn_count else ""
        title = Text()
        title.append(" \u26a1 JINN ", style="bold white")
        title.append("\u00b7", style="dim")
        title.append("  Programmable Cognition System", style="dim")
        if turn_text:
            title.append(f"  {turn_text}", style="bold cyan")
        return Panel(title, style="bold blue", padding=(0, 2))

    def _build_tree_panel(self) -> Panel:
        tree = Tree("")
        # Find root nodes (no parent)
        roots = [k for k, n in self._agents.items() if n.parent_key is None]
        for root_key in roots:
            self._render_subtree(tree, root_key)
        return Panel(tree, title="Orchestration", border_style="blue", padding=(0, 1))

    def _render_subtree(self, parent: Tree, key: str) -> None:
        node = self._agents.get(key)
        if node is None:
            return
        branch = parent.add(self._render_agent_node(node))
        # Find children
        children = sorted(
            [k for k, n in self._agents.items() if n.parent_key == key],
            key=lambda k: self._agents[k].name,
        )
        for child_key in children:
            self._render_subtree(branch, child_key)

    def _render_agent_node(self, node: AgentNode) -> Text:
        icon = AGENT_ICONS.get(node.agent_type, "\u2022")
        color = AGENT_COLORS.get(node.agent_type, "")
        status_icon = STATUS_ICONS.get(node.status, "\u25cc")
        status_color = STATUS_COLORS.get(node.status, "dim")

        text = Text()
        text.append(f"  {icon} ", style=color)
        text.append(node.name, style=color)
        text.append(f"  {status_icon} {node.status}", style=status_color)

        # Provider line
        if node.provider:
            model_str = f"{node.provider}/{node.model}" if node.model else node.provider
            text.append(f"  {model_str}", style="dim")

        # Elapsed time
        if node.elapsed and node.status in ("running", "streaming", "thinking"):
            text.append(f"  {node.elapsed}", style="dim")

        # Task description
        if node.task_desc:
            text.append(f"\n      {node.task_desc}", style="dim italic")

        # Tool calls (show last 3)
        for tc in node.tool_calls[-3:]:
            text.append(f"\n      {tc}", style="dim")

        return text

    def _build_output_panel(self) -> Panel:
        text = Text("".join(self._output_buffer[-20:])[-800:])
        return Panel(text, title="Output", border_style="green", padding=(0, 1))

    def _build_plan_progress(self) -> Panel:
        if not self._plan_nodes:
            return Panel("", title="Plan Progress", border_style="yellow")

        table = Table(show_header=False, box=None, padding=(0, 1))
        table.add_column("Step", width=40)
        table.add_column("Status", width=12)

        done_count = 0
        total = len(self._plan_nodes)
        for step_id in sorted(self._plan_nodes.keys()):
            desc, status = self._plan_nodes[step_id]
            status_icon = STATUS_ICONS.get(status, "\u25cc")
            status_color = STATUS_COLORS.get(status, "dim")
            table.add_row(
                Text(f"Step {step_id}/{total}: {desc}"),
                Text(f"{status_icon} {status}", style=status_color),
            )
            if status == "done":
                done_count += 1

        pct = int(100 * done_count / total) if total else 0
        bar = Progress(
            TextColumn("{task.description}"),
            BarColumn(bar_width=40),
            TextColumn("{task.percentage:>3.0f}%"),
        )
        bar.add_task("Progress", total=total, completed=done_count)

        return Panel(
            Group(table, bar),
            title="Plan Progress",
            border_style="yellow",
            padding=(0, 1),
        )
