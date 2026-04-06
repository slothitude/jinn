# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"    # Install with dev dependencies
python main.py             # Run the CLI REPL
pytest                     # Run all tests
pytest tests/test_memory.py  # Run a single test file
pytest -k "test_policy"    # Run tests by name pattern
```

## Architecture

JINN is a programmable cognition system — a multi-agent framework with an event-driven, layered architecture. All I/O is async.

### Layers

| Layer | Component | Key File |
|-------|-----------|----------|
| L2 | EventBus (reactive backbone) | `src/core/bus.py` |
| L2.5 | LLM Provider (OpenAI-compatible client) | `src/core/provider.py` |
| L3 | PolicyEngine (request routing) | `src/core/policy_engine.py` |
| L4 | Memory (SQLite store + retrieval + AutoDream consolidation) | `src/memory/` |
| L5 | PromptOS (Jinja2 prompt assembly) | `src/promptos/engine.py` |
| L6-L7 | Agents (execute + stream) | `src/agents/` |
| L8 | Feedback (safety monitors, trace logging) | `src.feedback/` |

### Request flow

`main.py` wires everything. A user input flows through `QueryEngine.process()`:
1. **PolicyEngine** — keyword-based intent matching routes to an agent, selects model tier and memory strategy
2. **Memory retrieval** — tag-filtered SQLite lookup with composite ranking (relevance 0.4 + importance 0.3 + recency 0.2 + policy 0.1)
3. **PromptOS** — Jinja2 template assembly from `prompts/` (base → agent-specific → macros → tools → flows)
4. **Agent execution** — `BaseAgent.execute()` calls `self.stream_llm(prompt)` for real LLM streaming via the provider, falling back to mock simulation on error. Returns an `AsyncGenerator[str, None]`.
5. **EventBus** — broadcasts typed `Event` enum values (`TURN_START`, `AGENT_CHUNK`, `AGENT_END`, `TURN_END`, etc.)

### Agents

- **BUDDY** (`src/agents/buddy.py`) — default collaborative engineering assistant
- **ULTRAPLAN** (`src/agents/ultraplan.py`) — heavy planning / task decomposition
- **KAIROS** (`src/agents/kairos.py`) — monitoring agent; subscribes to `agent_chunk` events for anomaly detection, can interrupt via `steer()`

All agents extend `BaseAgent` (abstract `execute()` + `stream_llm()` helper + optional `steer()` interrupt hook).

### LLM Provider

`src/core/provider.py` wraps an OpenAI-compatible API client. Configuration via `.env` (gitignored):
- `LLM_BASE_URL` — API endpoint (e.g. `https://api.z.ai/api/coding/paas/v4`)
- `LLM_API_KEY` — API key
- `LLM_MODEL` — model name (e.g. `glm-5.1`)

Module-level `default_client` and `default_model` singletons are loaded at import. Agents use `BaseAgent.stream_llm(prompt)` which calls the provider. If the LLM is unavailable, agents fall back to mock simulation so tests run offline.

### EventBus

Error-isolated, priority-based pub/sub. Lower number = runs first. Safety hooks at 0, core logic at 50, observers at 100. Features:
- **Error isolation** — one failing subscriber doesn't crash others
- **Cancellation** — raise `EventCancelled` to stop propagation to lower-priority subscribers
- **`once()`** — auto-unsubscribe after first call
- **`wait_for(event, timeout)`** — awaitable future for the next event
- **Event history** — optional `max_history` constructor param, `get_history()` for introspection
- **`list_subscribers()`** — returns priority, name, callback for each subscriber
- **Typed events** — use `Event` string enum (defined in `src/core/models.py`) instead of raw strings

### Prompt templates

`prompts/` uses Jinja2 inheritance. Agent templates extend `base/system.jinja`. Macros in `prompts/macros/` inject memory context, tool schemas, and constraints. Add new agents by creating a template in `prompts/agents/` and wiring it in `PromptOS`.

### Bridge

`src/bridge/server.py` provides JSON-RPC over stdio for Python <-> TypeScript IPC (methods: `ping`, `render_graph`, `retrieve`).

### Data

SQLite databases in `data/` (`memory.db`, `traces.db`) — gitignored.

## Conventions

- Python 3.11+, Pydantic v2 for models, Jinja2 for templates, aiofiles for async I/O
- `openai>=1.0` for LLM provider, `python-dotenv` for `.env` loading
- `pytest-asyncio` with `asyncio_mode = "auto"` — test functions can be `async def` directly
- Agents yield chunks via async generators; never return a single string
- Use `Event` enum constants (not raw strings) for all event types
- Policy routing is keyword-based in `POLICY_RULES` list — add new intents there
- Memory tags determine what each agent sees; role-to-tag mapping lives in the retrieval pipeline
- `emit()` returns `EventResult` — check `.cancelled` and `.errors` for production error handling
