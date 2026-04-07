"""Rich CLI renderer — live orchestration tree visualization.

Subscribes to EventBus events and renders a live agent tree using Rich.
Observer-only: never modifies agent state or flow.
"""

from __future__ import annotations

import random
import re
import sys
import threading
import time
from dataclasses import dataclass, field

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.table import Table
from rich.text import Text

from src.cli.themes import (
    AGENT_COLORS,
    AGENT_ICONS,
    JINN_LOGO,
    MATRIX_CHARS,
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
        self._last_input: str = ""
        self._thinking_since: float = 0.0
        self._rain_drops: list[tuple[int, int]] = []
        self._rain_timer_active: bool = False

    # -- Lifecycle --

    def start(self) -> None:
        """Subscribe to events and start the Rich Live display."""
        if not sys.stdout.isatty():
            return

        self._running = True
        self._subscribe()

        # Play startup animation before entering normal live loop
        self._play_startup_animation()

        self._live = Live(
            self._build_status_bar(),
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

    def set_user_input(self, text: str) -> None:
        """Set the current user input to display in the status bar."""
        self._last_input = text

    # -- Startup animation --

    def _play_startup_animation(self) -> None:
        """Matrix rain dissolve into JINN logo (~2s animation)."""
        import shutil

        term_w, term_h = shutil.get_terminal_size((80, 24))
        logo_width = max(len(line) for line in JINN_LOGO)
        logo_height = len(JINN_LOGO)
        cols = min(term_w, 80)
        rows = min(term_h, 24)
        logo_col = (cols - logo_width) // 2
        logo_row = (rows - logo_height) // 2

        # Each column tracks a rain drop: (head_row, length)
        drops: list[tuple[int, int]] = [(random.randint(0, rows), random.randint(3, rows)) for _ in range(cols)]

        def _make_rain_frame() -> Text:
            grid = Text()
            for r in range(rows):
                for c in range(cols):
                    head, length = drops[c]
                    tail_start = head - length
                    if tail_start <= r <= head:
                        dist_from_head = head - r
                        ch = random.choice(MATRIX_CHARS)
                        if dist_from_head == 0:
                            grid.append(ch, style="bold bright_green")
                        elif dist_from_head <= 2:
                            grid.append(ch, style="green")
                        else:
                            grid.append(ch, style="dim green")
                    else:
                        grid.append(" ")
                if r < rows - 1:
                    grid.append("\n")
            return grid

        def _make_dissolve_frame(phase_ratio: float) -> Text:
            grid = Text()
            for r in range(rows):
                for c in range(cols):
                    # Check if this position is in the logo
                    lr = r - logo_row
                    lc = c - logo_col
                    is_logo = (
                        0 <= lr < logo_height
                        and 0 <= lc < len(JINN_LOGO[lr])
                        and JINN_LOGO[lr][lc] != " "
                    )

                    if is_logo and random.random() < phase_ratio:
                        # Show logo char
                        ch = JINN_LOGO[lr][lc]
                        if phase_ratio > 0.7:
                            grid.append(ch, style="bold bright_cyan")
                        else:
                            grid.append(ch, style="cyan")
                    elif random.random() < (1.0 - phase_ratio) * 0.3:
                        # Fading matrix char
                        ch = random.choice(MATRIX_CHARS)
                        grid.append(ch, style="dim green")
                    else:
                        grid.append(" ")
                if r < rows - 1:
                    grid.append("\n")

            # Add subtitle during final frames
            if phase_ratio > 0.5:
                grid.append("\n")
                subtitle = "Slothitude Games: Jinn"
                visible = int(len(subtitle) * min(1.0, (phase_ratio - 0.5) * 2))
                grid.append(" " * ((cols - visible) // 2))
                grid.append(subtitle[:visible], style="dim white")
            return grid

        console = Console()
        with Live(console=console, refresh_per_second=15, vertical_overflow="visible") as live:
            # Phase 1: Matrix rain (~1s, 15 frames)
            for _ in range(15):
                for c in range(cols):
                    head, length = drops[c]
                    head += random.randint(1, 2)
                    if head - length > rows:
                        head = random.randint(0, 3)
                        length = random.randint(3, rows)
                    drops[c] = (head, length)
                live.update(Panel(_make_rain_frame(), style="on black", padding=0))
                time.sleep(0.066)

            # Phase 2: Dissolve into logo (~1s, 15 frames)
            for frame in range(15):
                ratio = (frame + 1) / 15.0
                live.update(Panel(_make_dissolve_frame(ratio), style="on black", padding=0))
                time.sleep(0.066)

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
        self._thinking_since = 0.0
        self._rain_drops.clear()
        self._rain_timer_active = False
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
        if self._thinking_since == 0.0:
            self._thinking_since = time.monotonic()
        self._refresh()

    async def on_agent_chunk(self, payload: dict) -> None:
        agent_name: str = payload.get("agent", "UNKNOWN")
        chunk: str = payload.get("chunk", "")

        # Find the active node for this agent
        key = self._find_active_key(agent_name)
        if key and key in self._agents:
            self._agents[key].status = "streaming"

        # Accumulate output (keep last ~5000 chars for scrollable view)
        self._output_buffer.append(chunk)
        if len(self._output_buffer) > 100:
            self._output_buffer = self._output_buffer[-100:]
        total = "".join(self._output_buffer)
        if len(total) > 5000:
            self._output_buffer = [total[-5000:]]

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

        # Clear output buffer — main.py prints the final response as plain text
        self._output_buffer.clear()
        # Only reset rain timer if no agents are still active
        if not any(n.status in ("thinking", "streaming") for n in self._agents.values()):
            self._thinking_since = 0.0
            self._rain_drops.clear()
            self._rain_timer_active = False
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

    def _is_long_thinking(self) -> bool:
        """Check if any agent has been thinking/streaming for >30 seconds."""
        if self._thinking_since == 0.0:
            return False
        # Must have at least one active agent
        has_active = any(
            n.status in ("thinking", "streaming") for n in self._agents.values()
        )
        return has_active and (time.monotonic() - self._thinking_since) > 30.0

    def _schedule_rain_frame(self) -> None:
        """Self-scheduling timer to keep rain animating between events."""
        if not self._is_long_thinking() or self._live is None:
            self._rain_timer_active = False
            return
        self._rain_timer_active = True
        self._advance_rain_drops()
        self._live.update(self._build_rain_idle())
        t = threading.Timer(REFRESH_INTERVAL, self._schedule_rain_frame)
        t.daemon = True
        t.start()

    def _build_composite(self) -> Group:
        """Build the full composite renderable.

        Layout (top to bottom):
          1. Compact status bar (banner + active agents, 1-2 lines)
          2. Output panel (takes remaining terminal height)
          3. Plan progress (if any)
        """
        if self._is_long_thinking():
            if not self._rain_timer_active:
                self._schedule_rain_frame()
            return self._build_rain_idle()

        parts: list = []

        # Compact status bar: banner + agent status in one line
        parts.append(self._build_status_bar())

        # Active agents inline (compact, no tree)
        if self._agents:
            parts.append(self._build_agents_inline())

        # Output panel — largest element
        if self._output_buffer:
            parts.append(self._build_output_panel())

        # Plan progress (compact)
        if self._plan_nodes:
            parts.append(self._build_plan_progress())

        return Group(*parts)

    def _advance_rain_drops(self) -> None:
        """Move rain drops down by 1-2 rows."""
        if not self._rain_drops:
            return
        import shutil
        _, term_h = shutil.get_terminal_size((80, 24))
        rows = min(term_h, 24) - 2  # match _build_rain_idle grid size
        for c in range(len(self._rain_drops)):
            head, length = self._rain_drops[c]
            head += random.randint(1, 2)
            if head - length > rows:
                head = random.randint(0, 3)
                length = random.randint(3, rows)
            self._rain_drops[c] = (head, length)

    def _build_rain_line(self, row: int, cols: int) -> Text:
        """Build one row of rain with batched same-style segments."""
        segments: list[tuple[str, str]] = []
        for c in range(cols):
            head, length = self._rain_drops[c]
            tail_start = head - length
            if tail_start <= row <= head:
                dist = head - row
                ch = random.choice(MATRIX_CHARS)
                if dist == 0:
                    style = "bold bright_green"
                elif dist <= 2:
                    style = "green"
                else:
                    style = "dim green"
                segments.append((ch, style))
            else:
                segments.append((" ", ""))

        # Batch consecutive same-style chars into single append calls
        result = Text()
        buf = ""
        buf_style = ""
        for ch, st in segments:
            if st == buf_style:
                buf += ch
            else:
                if buf:
                    result.append(buf, style=buf_style)
                buf = ch
                buf_style = st
        if buf:
            result.append(buf, style=buf_style)
        return result

    def _build_rain_idle(self) -> Group:
        """Full-screen matrix rain with centered content block for long waits (>30s)."""
        import shutil

        term_w, term_h = shutil.get_terminal_size((80, 24))
        cols = min(term_w, 80)
        # -2 for Panel top/bottom border so it fits without scrolling
        rows = min(term_h, 24) - 2

        # Lazily init persistent rain drops
        if not self._rain_drops or len(self._rain_drops) != cols:
            self._rain_drops = [
                (random.randint(0, rows), random.randint(3, rows)) for _ in range(cols)
            ]

        # Collect content to embed
        active_agents = [
            n for n in self._agents.values() if n.status in ("thinking", "streaming")
        ]
        elapsed_str = ""
        if self._thinking_since:
            elapsed_str = f"{time.monotonic() - self._thinking_since:.1f}s"

        # Build content lines: (text, style)
        content_lines: list[tuple[str, str]] = []

        if self._last_input:
            content_lines.append((f"> {self._last_input[:cols - 6]}", "bold bright_cyan"))
            content_lines.append(("", ""))

        for agent in active_agents[:4]:
            icon = AGENT_ICONS.get(agent.agent_type, "\u2022")
            color = AGENT_COLORS.get(agent.agent_type, "")
            status_icon = STATUS_ICONS.get(agent.status, "\u25cc")
            line = f"  {icon} {agent.name} {status_icon} {agent.status}"
            if elapsed_str:
                line += f" ({elapsed_str})"
            if agent.provider:
                line += f"  {agent.provider}"
            content_lines.append((line, color))

            if agent.tool_calls:
                content_lines.append(
                    (f"    \u2192 {agent.tool_calls[-1]}", "dim yellow")
                )

        if self._output_buffer:
            raw = "".join(self._output_buffer[-50:])[-2000:]
            filtered = "".join(c for c in raw if c.isprintable() or c in "\n\t")
            out_lines = filtered.split("\n")
            show = out_lines[-8:]
            content_lines.append(("", ""))
            for ol in show:
                content_lines.append((f"  {ol[:cols - 6]}", "bright_green"))

        # Build grid: rain rows above / content block / rain rows below
        content_start = max(0, (rows - len(content_lines)) // 2)
        content_end = content_start + len(content_lines)

        grid = Text()
        for r in range(rows):
            if content_start <= r < content_end:
                # Content row — clean dark background, no rain mixing
                text, style = content_lines[r - content_start]
                # Left pad to center
                pad = max(0, (cols - len(text)) // 2)
                grid.append(" " * pad)
                grid.append(text, style=style or "bright_green")
                # Right pad to fill row
                remaining = cols - pad - len(text)
                if remaining > 0:
                    grid.append(" " * remaining)
            else:
                # Rain row
                grid.append_text(self._build_rain_line(r, cols))

            if r < rows - 1:
                grid.append("\n")

        return Group(Panel(grid, style="on black", padding=0))

    def _build_status_bar(self) -> Text:
        """Compact single-line status bar."""
        bar = Text()
        bar.append(" \u26a1 JINN ", style="bold white")
        bar.append(" \u2502 ", style="dim")
        if self._turn_count:
            bar.append(f"turn {self._turn_count}", style="bold cyan")
            bar.append(" \u2502 ", style="dim")

        # Show user input if set
        if self._last_input:
            bar.append(f"> {self._last_input[:50]}", style="bold yellow")
            bar.append(" \u2502 ", style="dim")

        # Count active agents
        active = [n for n in self._agents.values() if n.status in ("thinking", "streaming")]
        done = [n for n in self._agents.values() if n.status == "done"]
        if active:
            names = ", ".join(n.name for n in active[:4])
            bar.append(f"{len(active)} active: {names}", style="green")
        elif done:
            bar.append(f"{len(done)} done", style="dim green")
        else:
            bar.append("ready", style="dim")
        return bar

    def _build_agents_inline(self) -> Text:
        """Compact multi-line agent status (replaces the full tree panel)."""
        lines = Text()

        # Show all agents as compact lines
        roots = [k for k, n in self._agents.items() if n.parent_key is None]
        for root_key in roots:
            self._render_agent_inline(lines, root_key, 0)
        for child_key in sorted(
            (k for k, n in self._agents.items() if n.parent_key is not None),
            key=lambda k: self._agents[k].name,
        ):
            self._render_agent_inline(lines, child_key, 1)

        return lines

    def _render_agent_inline(self, out: Text, key: str, indent: int) -> None:
        """Append a compact single-line agent status."""
        node = self._agents.get(key)
        if node is None:
            return

        icon = AGENT_ICONS.get(node.agent_type, "\u2022")
        color = AGENT_COLORS.get(node.agent_type, "")
        status_icon = STATUS_ICONS.get(node.status, "\u25cc")
        status_color = STATUS_COLORS.get(node.status, "dim")

        pad = "  " + ("  " * indent)
        out.append(f"{pad}{icon} ", style=color)
        out.append(node.name, style=color)
        out.append(f" {status_icon}", style=status_color)

        if node.provider:
            model_str = f"{node.provider}/{node.model}" if node.model else node.provider
            out.append(f" {model_str}", style="dim")

        if node.elapsed and node.status in ("thinking", "streaming"):
            out.append(f" {node.elapsed}", style="dim")

        # Last tool call only
        if node.tool_calls:
            out.append(f" \u2192 {node.tool_calls[-1]}", style="dim")

        out.append("\n")

    def _build_output_panel(self) -> Panel:
        """Output panel sized to content (shown during streaming only)."""
        raw = "".join(self._output_buffer[-100:])[-5000:]
        # Strip non-printable characters (keep newlines, tabs, and printable unicode)
        filtered = "".join(c for c in raw if c.isprintable() or c in "\n\t")

        import shutil
        _, term_h = shutil.get_terminal_size((80, 24))
        max_lines = max(term_h - 6, 5)

        # Split into lines and take the last N that fit
        all_lines = filtered.split("\n")
        show_lines = all_lines[-max_lines:]

        text = Text("\n".join(show_lines))
        return Panel(
            text,
            title="Output",
            border_style="green",
            padding=(0, 1),
        )

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
