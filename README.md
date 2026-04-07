# JINN — Programmable Cognition System

A multi-agent framework with an event-driven, layered architecture. All I/O is async.

## Architecture

| Layer | Component | Key File |
|-------|-----------|----------|
| L2 | EventBus (reactive backbone) | `src/core/bus.py` |
| L2.5 | LLM Provider (httpx + OpenAI fallback chain) | `src/core/provider.py` |
| L3 | PolicyEngine (intent routing + complexity escalation) | `src/core/policy_engine.py` |
| L4 | Memory (SQLite store + retrieval + AutoDream consolidation) | `src/memory/` |
| L5 | PromptOS (Jinja2 prompt assembly) | `src/promptos/engine.py` |
| L6-L7 | Agents (execute + stream) | `src/agents/` |
| L8 | Feedback (safety monitors, trace logging) | `src/feedback/` |

## Agents

- **BUDDY** — Default collaborative assistant. Executes `PlanGraph` nodes, listens for `KAIROS_INTERRUPT`.
- **ULTRAPLAN** — Architecture planner. Uses strategy macros for atomic decomposition and risk assessment. Outputs JSON `PlanGraph`.
- **KAIROS** — Real-time safety monitor. Emits `KAIROS_INTERRUPT` to stop agents on anomaly detection.

## Quick Start

```bash
pip install -e ".[dev]"    # Install with dev dependencies
python main.py             # Run the CLI REPL
pytest                     # Run all tests
```

### Configuration

Create a `.env` file (gitignored):

```
LLM_BASE_URL=https://api.z.ai/api/coding/paas/v4
LLM_API_KEY=your-key-here
LLM_MODEL=glm-5.1
```

The provider uses httpx directly with a model fallback chain: `glm-5.1 → glm-5 → glm-5-turbo → glm-4.7 → glm-4.6 → glm-4.5 → glm-4.5-air`.

## REPL Commands

```
/compile raw/godot --limit 10           # Compile first 10 wiki pages
/compile raw/godot --category classes   # Compile only class reference docs
/compile raw/godot --limit 5 --category tutorials
```

## Wiki Compiler (Phase 3)

The Librarian pipeline distills raw documentation into high-density wiki pages:

1. **Ingest** — RST sources extracted from official Godot offline docs into `raw/godot/`
2. **Distill** — LLM-powered compilation via `WikiCompiler` with incremental MD5 dedup
3. **Store** — Wiki pages stored in SQLite (`data/wiki.db`) and filesystem (`wiki/`)
4. **Retrieve** — Wiki-aware retrieval with category boosting surfaces relevant pages in agent context

Each distilled page includes: Overview, Key Patterns, API Reference, Gotchas, Cross-References (`[[PageName]]`), and Jinn Heuristics.

## Request Flow

```
User Input → PolicyEngine (route to agent)
           → Memory Retrieval (wiki-aware, tag-filtered)
           → PromptOS (Jinja2 template assembly)
           → Agent Execution (stream LLM content)
           → EventBus (broadcast typed events)
```

## EventBus

Error-isolated, priority-based pub/sub. Lower priority number = runs first.

- Safety hooks at priority 0, core logic at 50, observers at 100
- `EventCancelled` stops propagation to lower-priority subscribers
- `once()` auto-unsubscribes after first call
- `wait_for(event, timeout)` — awaitable future
- `list_subscribers()` for introspection

## Conventions

- Python 3.11+, Pydantic v2, Jinja2 templates, aiofiles
- `openai>=1.0` for LLM provider, `httpx` for reliable async HTTP on Windows
- `pytest-asyncio` with `asyncio_mode = "auto"`
- Agents yield chunks via async generators
- `Event` string enum constants for all event types
- Memory tags drive per-agent retrieval; policy routing is keyword-based

## License

MIT
