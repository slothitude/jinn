# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"    # Install with dev dependencies
python main.py             # Run the CLI REPL
jinn                       # Run via PATH wrapper (after install.bat)
pytest                     # Run all tests
pytest tests/test_memory.py  # Run a single test file
pytest -k "test_policy"    # Run tests by name pattern
```

### REPL Commands

| Command | Purpose |
|---------|---------|
| `/restart` | Clear screen and continue session |
| `/update` | `git pull origin master` and print result |
| `/compile [dir] [--limit N] [--category name]` | Compile raw docs into encyclopedia pages |
| `/dashboard` | Print dashboard URL |
| `quit` / `exit` | Shutdown |

## Architecture

JINN is a programmable cognition system — a multi-agent framework with an event-driven, layered architecture. All I/O is async.

### Layers

| Layer | Component | Key File |
|-------|-----------|----------|
| L2 | EventBus (reactive backbone) | `src/core/bus.py` |
| L2.5 | LLM Provider (OpenAI-compatible client) | `src/core/provider.py` |
| L2.6 | ResourceManager (quota tracking + fallback chains) | `src/core/resource_manager.py` |
| L3 | PolicyEngine (request routing) | `src/core/policy_engine.py` |
| L4 | Memory (SQLite store + retrieval + AutoDream consolidation) | `src/memory/` |
| L5 | PromptOS (Jinja2 prompt assembly) | `src/promptos/engine.py` |
| L6-L7 | Agents (execute + stream) | `src/agents/` |
| L7.5 | AgentToolExecutor (batch delegation) | `src/execution/agent_tools.py` |
| L7.6 | Self Tools (version, test, git) | `src/execution/self_tools.py` |
| L8 | Feedback (safety monitors, trace logging) | `src.feedback/` |

### Request flow

`main.py` wires everything. A user input flows through `QueryEngine.process()`:
1. **PolicyEngine** — keyword-based intent matching + structural multi-part detection + complexity-based escalation (threshold 0.8) routes to an agent.
2. **Memory retrieval** — tag-filtered SQLite lookup with composite ranking (relevance 0.4 + importance 0.3 + recency 0.2 + policy 0.1).
3. **PromptOS** — Jinja2 template assembly from `prompts/` (base → agent-specific → macros like `strategy.jinja`).
4. **Agent execution** — `BaseAgent.execute(prompt, state)` streams LLM content.
5. **Plan Detection** — If `ULTRAPLAN` is used and outputs a `PlanGraph` JSON, `QueryEngine` parses it into `AgentState.execution_graph` and auto-transitions to `BUDDY`.
6. **Multi-step Execution** — `BUDDY` iterates through the `PlanGraph` nodes, updating status and streaming each step.
7. **EventBus** — broadcasts typed `Event` enum values (`TURN_START`, `AGENT_CHUNK`, `KAIROS_INTERRUPT`, `DELEGATION_START`, `DELEGATION_END`, etc.)

### Agents

- **BUDDY** (`src/agents/buddy.py`) — Default collaborative assistant (Tier 2 worker). Supports `PlanGraph` execution, listening for `KAIROS_INTERRUPT` to pause or redirect mid-plan.
- **ULTRAPLAN** (`src/agents/ultraplan.py`) — Heavy architecture agent. Uses `strategy.jinja` macros for atomic decomposition, risk assessment (analyzing past failures from memory), and compute budgeting. Outputs a JSON `PlanGraph`.
- **KAIROS** (`src/agents/kairos.py`) — Real-time monitor. Subscribes to `AGENT_CHUNK` events and checks `AgentState` for plan-level risks. Emits `KAIROS_INTERRUPT` to stop agents when anomalies are detected. Also enforces delegation depth limits via `DELEGATION_START` listener.
- **ORCHESTRATOR** (`src/agents/orchestrator.py`) — Tier 0 PM agent. Decomposes complex requests into parallel subtask batches via `delegate_batch` tool. Synthesizes results from multiple supervisors.
- **SUPERVISOR** (`src/agents/supervisor.py`) — Tier 1 planning agent. Receives scoped tasks, spawns parallel workers via `spawn_workers` tool, validates outputs.

All agents extend `BaseAgent` (abstract `execute()` + `stream_llm()` helper + optional `steer()` interrupt hook).

### Hierarchical Multi-Agent Orchestration

3-tier delegation architecture with parallel batch execution and multi-provider support:

```
ORCHESTRATOR (Tier 0) — provider: zhipu
  Tool: delegate_batch(tasks: list)
  │  Spawns N supervisors via asyncio.gather, each with fresh AgentState(history=[])
  ├─→ SUPERVISOR-A ─→ WORKER-1 (nvidia) ──┐
  ├─→ SUPERVISOR-B ─→ WORKER-2 (nvidia) ──┤  ← parallel
  └─→ SUPERVISOR-C ─→ WORKER-3 (nvidia) ──┘
       (Tier 1, zhipu)   (Tier 2, nvidia)
```

- **AgentToolExecutor** (`src/execution/agent_tools.py`) — Intercepts `delegate_batch` and `spawn_workers` tool calls, creates fresh `AgentState` per task, runs all agents concurrently via `asyncio.gather()`. Falls through to `ToolExecutor` for standard tools (bash/read/write). Enforces max delegation depth (3).
- **Multi-provider routing** — `BaseAgent.__init__(provider="nvidia")` creates a separate `AsyncOpenAI` client. Provider registry in `provider.py` caches clients per provider name. Env vars: `ZHIPU_API_KEY`, `NVIDIA_API_KEY`.
- **Context scoping** — Each delegation creates `AgentState(session_id="del-...", history=[])` — no parent context leaks between tiers.
- **Policy routing** — Keywords "multi-agent", "hierarchy", "delegate", "parallel" route to ORCHESTRATOR.

| Tier | Agent | Provider | Role |
|------|-------|----------|------|
| 0 | ORCHESTRATOR | zhipu | Decompose + synthesize |
| 1 | SUPERVISOR | zhipu | Plan + delegate workers |
| 2 | BUDDY/Worker | nvidia | Execute with tools |

### LLM Provider

`src/core/provider.py` wraps an OpenAI-compatible API client. Configuration via `.env` (gitignored):
- `LLM_BASE_URL` — API endpoint (e.g. `https://api.z.ai/api/coding/paas/v4`)
- `LLM_API_KEY` — API key
- `LLM_MODEL` — model name (e.g. `glm-5.1`)

Module-level `default_client` and `default_model` singletons for backward compatibility. Multi-provider support via `get_provider_client(provider_name)` which creates/caches separate `AsyncOpenAI` clients per provider (zhipu, nvidia). Agents use `self._client`/`self._model` (set in `BaseAgent.__init__` from provider param or defaults) — `stream_llm()` no longer uses module singletons directly. If the LLM is unavailable, agents fall back to mock simulation so tests run offline.

### ResourceManager

`src/core/resource_manager.py` — central provider registry with quota tracking and fallback chains. Registered in `main.py` at startup and wired into all agents via `set_resource_manager(rm, tier)`.

- **ProviderProfile** — per-provider config: name, base_url, api_key_env, models, rate_limit, rate_window_secs, priority
- **Quota tracking** — sliding window (timestamps pruned after `rate_window_secs`). `check_quota()` returns False when used >= rate_limit. rate_limit=0 means unlimited.
- **Fallback chains** — per-tier ordered list of `(provider, model)` pairs. Planning tiers (ORCHESTRATOR, SUPERVISOR) prefer zhipu; worker tiers (BUDDY) prefer nvidia. On LLM failure, `stream_llm()` tries the next entry in the chain.
- **Fallback chain example:** ORCHESTRATOR: `[(zhipu, glm-5.1), (zhipu, glm-5), (nvidia, llama-70b), ...]` — when zhipu quota is exhausted, automatically routes to nvidia.
- **Dashboard integration** — provider/model dropdown in chat UI sends overrides via `PolicyDecision.provider_override`/`model_override`.
- **Per-task routing** — `delegate_batch`/`spawn_workers` accept optional `provider`/`model` per task spec; `AgentToolExecutor` creates fresh agents for per-task providers.

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

SQLite databases in `data/` (`memory.db`, `traces.db`, `wiki.db`) — gitignored.

### Dashboard (Web UI)

`src/dashboard/server.py` provides an aiohttp web dashboard at `http://localhost:8080`. Started automatically alongside CLI in `main.py`. Tabbed SPA (embedded HTML/CSS/JS, no build tools):

| Tab | Purpose |
|-----|---------|
| **Chat** | Talk to JINN via `POST /api/chat` → QueryEngine |
| **Encyclopedia** | Browse JINN's internal knowledge base (wiki pages by category, search) |
| **Memory** | View JINN's episodic memories with tags and importance |
| **Traces** | Decision trace timeline (policy, memory, tool calls, outcomes) |
| **Events** | Live SSE stream of cognition events from EventBus |

**API endpoints:**

| Endpoint | Purpose |
|----------|---------|
| `POST /api/chat` | Send message to JINN via QueryEngine |
| `GET /api/status` | Version, uptime, active agents |
| `GET /api/encyclopedia` | Encyclopedia index grouped by category |
| `GET /api/encyclopedia/{id}` | Full encyclopedia page |
| `GET /api/encyclopedia/search?q=` | Search JINN's knowledge |
| `GET /api/memory` | Episodic memories |
| `GET /api/traces` | Decision traces |
| `GET /api/traces/{id}` | Trace detail |
| `GET /api/stats` | Outcome stats |
| `GET /api/events` | SSE stream — live cognition events |

**DashboardServer** constructor: `(trace_logger, wiki_store=None, memory_store=None, bus=None, query_engine=None)`. Backward-compatible — existing tests pass `trace_logger` only.

### Encyclopedia (Wiki)

The wiki is JINN's internal encyclopedia — structured knowledge it builds and references during cognition. NOT a user docs browser. Pages are compiled from raw docs via the encyclopedia compiler (`WikiCompiler`) and stored in `WikiStore` (SQLite).

- **WikiStore** (`src/memory/wiki.py`) — CRUD for encyclopedia pages (title, category, summary, content, tags)
- **WikiCompiler** (`src/memory/wiki_compiler.py`) — reads raw docs, distills via LLM into concise encyclopedia pages
- **Wiki Export** (`src/memory/wiki_export.py`) — exports encyclopedia pages to standalone HTML

### Web Tools (web_eyes integration)

`src/execution/web_tools.py` provides 6 web tools wrapping [web_eyes](https://github.com/slothitude/web_eyes) controller functions. Available to all agents (BUDDY, SUPERVISOR, ORCHESTRATOR):

| Tool | web_eyes Function | Purpose |
|------|-------------------|---------|
| `web_search` | `controller.search_and_crawl()` | Search SearXNG → crawl → summarize |
| `web_crawl` | `controller.crawl_only()` | Crawl URLs, return raw text |
| `web_summarize` | `controller.summarize_urls()` | Crawl + summarize URLs |
| `web_ask` | `controller.ask_question()` | Full pipeline: search → crawl → answer with citations |
| `web_see` | `controller.see_urls()` | Screenshot + vision extraction + summarize |
| `web_look` | `summarizer.vision_extract()` | Analyze base64 image with vision AI |

- **WebToolsAdapter** — lazy adapter in `src/execution/web_tools.py`. Imports web_eyes modules only on first use. If web_eyes or SearXNG aren't available, tools return clear error messages instead of crashing.
- **ToolExecutor dispatch** — All 6 web tools are dispatched from `ToolExecutor.execute()`. SUPERVISOR/ORCHESTRATOR call web tools via `AgentToolExecutor` fallthrough to `ToolExecutor`.
- **Setup**: `git submodule add https://github.com/slothitude/web_eyes vendor/web_eyes`, `pip install -e ".[web]"`, `playwright install chromium`, SearXNG running, `NIM_API_KEY` in `.env`.

### Self-Awareness & Self-Modification

`src/core/version.py` provides `get_version()` and `get_git_info()` — single source of truth from `pyproject.toml`. Injected into all prompts via `PromptOS._build_context()` as `jinn_version`, `jinn_git_branch`, `jinn_git_commit`. Displayed in `base/system.jinja` `{% block self_awareness %}`.

`src/execution/self_tools.py` provides 5 tools via `SelfToolsAdapter`:

| Tool | Safety | Purpose |
|------|--------|---------|
| `version_info` | 0 | Read current version + git branch/commit |
| `version_bump` | 1 | Bump major/minor/patch in pyproject.toml |
| `test_run` | 0 | Run pytest subprocess, return pass/fail + output |
| `git_commit_push` | 2 | Stage → commit → push. Runs tests first by default. |
| `self_update` | 2 | `git pull origin master` |

- **ToolExecutor dispatch** — All 5 self tools are dispatched from `ToolExecutor.execute()`, lazy-loaded via `SelfToolsAdapter`.
- **`git_commit_push` flow** — if `test_first=true`, runs pytest first; aborts if tests fail, then stages/commits/pushes.
- **`version_bump` flow** — regex parses `pyproject.toml`, increments the specified component, writes back.
- **PromptOS** — `self_tools` added to tool list: `DEFAULT_TOOLS + WEB_TOOLS + SELF_TOOLS`.
- **BUDDY** — `self_tools` added to tool loop. `buddy.jinja` includes self-modification protocol (test → bump → commit+push).

### Windows Install

- **`jinn.bat`** — thin wrapper: `python main.py %*` for PATH execution.
- **`install.bat`** — checks Python 3.11+, runs `pip install -e .[dev]`, adds project dir to user PATH. Double-click to install.

## Conventions
- Python 3.11+, Pydantic v2 for models, Jinja2 for templates, aiofiles for async I/O
- `openai>=1.0` for LLM provider, `httpx` for reliable async HTTP on Windows; fallback chain: `glm-5.1 → glm-5 → glm-5-turbo → glm-4.7 → glm-4.6 → glm-4.5-air`
- `pytest-asyncio>=0.23` with `asyncio_mode = "auto"` — test functions can be `async def` directly
- Agents yield chunks via async generators; never return a single string
- Use `Event` enum constants (not raw strings) for all event types
- Policy routing is keyword-based in `POLICY_RULES` list + structural multi-part detection via `_detect_multi_part()` — add new intents there
- Memory tags determine what each agent sees; role-to-tag mapping lives in the retrieval pipeline
- `emit()` returns `EventResult` — check `.cancelled` and `.errors` for production error handling

- When no LLM is available, agents fall back to mock simulation (echo fallback at buddy.py:104-114, or ultraplan.py:24-35) — tests run offline via mock
- To run specific tests: `python tests/test_ultimate.py` (standalone runner, no pytest required)
- `test_dashboard.py` is excluded from pytest — its `aiohttp` server import hangs during collection
- `BaseAgent` accepts optional `provider` param — pass `provider="nvidia"` to route to a different LLM; omit for default provider
- `AgentToolExecutor` intercepts delegation tools (`delegate_batch`, `spawn_workers`) and runs agents in parallel via `asyncio.gather()`; falls through to `ToolExecutor` for bash/read/write/web tools
- `ResourceManager` (`src/core/resource_manager.py`) tracks per-provider quotas via sliding window and builds fallback chains per agent tier; agents call `get_next_available(tier)` before LLM calls
- `BaseAgent` has `_resource_manager` and `_tier` attributes (set via `set_resource_manager()`); `stream_llm()` checks quota before calling LLM and falls back through chain on failure
- `PolicyDecision` has optional `provider_override`/`model_override` fields — set by dashboard chat or request metadata to force a specific provider/model
- Web tools (`web_search`, `web_crawl`, `web_summarize`, `web_ask`, `web_see`, `web_look`) are defined in `src/execution/web_tools.py` as `WEB_TOOLS` list; added to all agent tool loops via `DEFAULT_TOOLS + WEB_TOOLS`
- Self tools (`version_info`, `version_bump`, `test_run`, `git_commit_push`, `self_update`) are defined in `src/execution/self_tools.py` as `SELF_TOOLS` list; added via `DEFAULT_TOOLS + WEB_TOOLS + SELF_TOOLS`
- `WebToolsAdapter.is_available()` checks if web_eyes can be imported; `ToolExecutor.close_web()` shuts down the crawler at exit
- Install web extras: `pip install -e ".[web]"` — core JINN works without them
- Windows install: run `install.bat` to install + add to PATH, then `jinn` to launch
