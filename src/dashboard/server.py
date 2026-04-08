"""JINN Dashboard — interaction surface for chatting with JINN, browsing its
encyclopedia, viewing episodic memory, inspecting decision traces, and watching
live cognition events via SSE."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Optional

from aiohttp import web

from src.core.bus import EventBus
from src.core.models import AgentRequest, AgentState
from src.core.query_engine import QueryEngine
from src.core.version import get_version, get_git_info
from src.feedback.trace_logger import TraceLogger


# ---------------------------------------------------------------------------
# Tabbed SPA — embedded HTML/CSS/JS (no build tools)
# ---------------------------------------------------------------------------

_DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JINN Dashboard</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --surface2: #1c2128; --border: #30363d;
    --text: #c9d1d9; --heading: #f0f6fc; --accent: #58a6ff; --green: #3fb950;
    --red: #f85149; --yellow: #d29922; --muted: #8b949e; --sidebar-w: 240px;
  }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); height: 100vh; display: flex; flex-direction: column; }

  /* Header */
  #header { background: var(--surface); border-bottom: 1px solid var(--border);
            padding: 10px 20px; display: flex; align-items: center; gap: 12px; flex-shrink: 0; }
  #header h1 { color: var(--accent); font-size: 1.1rem; font-weight: 600; }
  #header .meta { color: var(--muted); font-size: 0.8rem; margin-left: auto; }

  /* Tab bar */
  #tabs { background: var(--surface); border-bottom: 1px solid var(--border);
          display: flex; padding: 0 16px; flex-shrink: 0; }
  .tab { padding: 10px 18px; cursor: pointer; color: var(--muted); font-size: 0.9rem;
         border-bottom: 2px solid transparent; transition: all 0.15s; user-select: none; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--accent); border-bottom-color: var(--accent); }

  /* Main content area */
  #content { flex: 1; overflow: hidden; position: relative; }
  .panel { display: none; height: 100%; overflow-y: auto; padding: 20px; }
  .panel.active { display: flex; flex-direction: column; }

  /* ---- Chat Panel ---- */
  #chat-panel { padding: 0; }
  #chat-messages { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
  .msg { max-width: 80%; padding: 10px 14px; border-radius: 10px; line-height: 1.5; font-size: 0.9rem; word-wrap: break-word; }
  .msg.user { align-self: flex-end; background: #1f3a5f; color: var(--heading); }
  .msg.jinn { align-self: flex-start; background: var(--surface2); border: 1px solid var(--border); }
  .msg .agent-tag { font-size: 0.75rem; color: var(--accent); margin-bottom: 4px; }
  #chat-input-area { padding: 12px 20px; background: var(--surface); border-top: 1px solid var(--border);
                     display: flex; gap: 10px; align-items: center; flex-shrink: 0; }
  #chat-provider { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
                   padding: 8px 10px; color: var(--text); font-size: 0.85rem; outline: none;
                   min-width: 80px; }
  #chat-provider:focus { border-color: var(--accent); }
  #chat-model { background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
                padding: 8px 10px; color: var(--text); font-size: 0.82rem; outline: none;
                min-width: 120px; }
  #chat-model:focus { border-color: var(--accent); }
  #chat-input { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 6px;
                padding: 10px 14px; color: var(--text); font-size: 0.9rem; outline: none; }
  #chat-input:focus { border-color: var(--accent); }
  #chat-send { background: var(--accent); color: #fff; border: none; border-radius: 6px;
               padding: 0 18px; cursor: pointer; font-weight: 600; font-size: 0.9rem; }
  #chat-send:hover { opacity: 0.9; }

  /* ---- Encyclopedia Panel ---- */
  #encyclopedia-panel { flex-direction: row; }
  #enc-sidebar { width: var(--sidebar-w); border-right: 1px solid var(--border);
                 overflow-y: auto; padding: 16px; flex-shrink: 0; }
  #enc-sidebar h3 { color: var(--muted); font-size: 0.75rem; text-transform: uppercase;
                    letter-spacing: 0.05em; margin-bottom: 8px; }
  .enc-cat { margin-bottom: 12px; }
  .enc-cat-title { color: var(--accent); font-size: 0.85rem; font-weight: 600; cursor: pointer;
                   margin-bottom: 4px; }
  .enc-cat-title:hover { text-decoration: underline; }
  .enc-item { padding: 3px 0 3px 12px; font-size: 0.82rem; color: var(--text);
              cursor: pointer; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .enc-item:hover { color: var(--accent); }
  #enc-main { flex: 1; overflow-y: auto; padding: 20px; }
  #enc-search { width: 100%; background: var(--bg); border: 1px solid var(--border);
                border-radius: 6px; padding: 8px 12px; color: var(--text); font-size: 0.85rem;
                margin-bottom: 16px; outline: none; }
  #enc-search:focus { border-color: var(--accent); }
  #enc-content h1 { color: var(--heading); font-size: 1.4rem; margin-bottom: 8px; }
  #enc-content .category-tag { color: var(--accent); font-size: 0.8rem; margin-bottom: 12px; }
  #enc-content .page-body { line-height: 1.7; font-size: 0.9rem; }
  #enc-content .page-body pre { background: var(--bg); border: 1px solid var(--border);
                                 border-radius: 4px; padding: 12px; overflow-x: auto; margin: 8px 0; }
  #enc-content .page-body code { background: var(--surface); padding: 2px 5px; border-radius: 3px; font-size: 0.85rem; }
  #enc-content .page-body pre code { background: none; padding: 0; }
  .search-result { padding: 10px 0; border-bottom: 1px solid var(--border); cursor: pointer; }
  .search-result:hover { background: var(--surface); }
  .search-result .sr-title { color: var(--accent); font-weight: 600; }
  .search-result .sr-summary { color: var(--muted); font-size: 0.85rem; margin-top: 2px; }

  /* ---- Memory Panel ---- */
  #memory-panel .mem-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
  .mem-card { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
              padding: 12px 16px; }
  .mem-card .mem-summary { font-size: 0.9rem; margin-bottom: 8px; }
  .mem-card .mem-tags { display: flex; gap: 6px; flex-wrap: wrap; }
  .mem-tag { background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
             padding: 2px 8px; font-size: 0.75rem; color: var(--accent); }
  .mem-card .mem-meta { color: var(--muted); font-size: 0.75rem; margin-top: 8px; }

  /* ---- Traces Panel ---- */
  #traces-panel .badge-bar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .badge { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
           padding: 6px 12px; font-size: 0.85rem; }
  .badge span { font-weight: 700; }
  .badge.ok span { color: var(--green); }
  .badge.err span { color: var(--red); }
  .badge.warn span { color: var(--yellow); }
  .trace-row { background: var(--surface); border: 1px solid var(--border); border-radius: 6px;
               padding: 10px 14px; cursor: pointer; transition: border-color 0.15s; margin-bottom: 8px; }
  .trace-row:hover { border-color: var(--accent); }
  .trace-row .meta { display: flex; justify-content: space-between; align-items: center; }
  .trace-row .tid { color: var(--accent); font-family: monospace; font-size: 0.85rem; }
  .trace-row .outcome { font-size: 0.75rem; padding: 2px 8px; border-radius: 4px; }
  .outcome-success { background: #1a3a2a; color: var(--green); }
  .outcome-failure { background: #3a1a1a; color: var(--red); }
  .outcome-timeout { background: #3a2a1a; color: var(--yellow); }
  #trace-detail { margin-top: 16px; background: var(--surface); border: 1px solid var(--border);
                  border-radius: 6px; padding: 16px; display: none; }
  #trace-detail h2 { color: var(--accent); font-size: 1rem; margin-bottom: 10px; }
  #trace-detail pre { background: var(--bg); border: 1px solid var(--border); border-radius: 4px;
                      padding: 12px; overflow-x: auto; font-size: 0.82rem; line-height: 1.5; }

  /* ---- Events Panel ---- */
  #events-panel .events-log { background: var(--surface); border: 1px solid var(--border);
                               border-radius: 6px; padding: 12px; font-family: monospace;
                               font-size: 0.82rem; overflow-y: auto; flex: 1; }
  .evt-line { padding: 3px 0; border-bottom: 1px solid var(--border); display: flex; gap: 10px; }
  .evt-time { color: var(--muted); min-width: 80px; }
  .evt-type { color: var(--accent); min-width: 140px; font-weight: 600; }
  .evt-data { color: var(--text); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; }
  #events-status { margin-bottom: 12px; font-size: 0.85rem; color: var(--muted); }

  .empty { color: var(--muted); font-style: italic; padding: 20px; }
</style>
</head>
<body>

<div id="header">
  <h1>JINN</h1>
  <span class="meta" id="status-meta">loading...</span>
</div>

<div id="tabs">
  <div class="tab active" data-tab="chat">Chat</div>
  <div class="tab" data-tab="encyclopedia">Encyclopedia</div>
  <div class="tab" data-tab="memory">Memory</div>
  <div class="tab" data-tab="traces">Traces</div>
  <div class="tab" data-tab="events">Events</div>
</div>

<div id="content">
  <!-- Chat -->
  <div class="panel active" id="chat-panel">
    <div id="chat-messages"></div>
    <div id="chat-input-area">
      <select id="chat-provider"><option value="">Auto</option><option value="zhipu">zhipu</option><option value="nvidia">nvidia</option></select>
      <input id="chat-model" type="text" placeholder="model (auto)" autocomplete="off">
      <input id="chat-input" type="text" placeholder="Talk to JINN..." autocomplete="off">
      <button id="chat-send">Send</button>
    </div>
  </div>

  <!-- Encyclopedia -->
  <div class="panel" id="encyclopedia-panel">
    <div id="enc-sidebar">
      <input id="enc-search" type="text" placeholder="Search knowledge...">
      <div id="enc-tree"></div>
    </div>
    <div id="enc-main">
      <div id="enc-content"><p class="empty">Select a topic from the sidebar or search.</p></div>
    </div>
  </div>

  <!-- Memory -->
  <div class="panel" id="memory-panel">
    <div id="mem-list" class="mem-grid"><p class="empty">Loading memories...</p></div>
  </div>

  <!-- Traces -->
  <div class="panel" id="traces-panel">
    <div class="badge-bar" id="trace-badges"></div>
    <div id="trace-timeline"></div>
    <div id="trace-detail"><h2 id="trace-detail-title"></h2><pre id="trace-detail-body"></pre></div>
  </div>

  <!-- Events -->
  <div class="panel" id="events-panel">
    <div id="events-status">Connecting...</div>
    <div class="events-log" id="events-log"></div>
  </div>
</div>

<script>
/* ---- Tab switching ---- */
const tabs = document.querySelectorAll('.tab');
const panels = document.querySelectorAll('.panel');
function switchTab(name) {
  tabs.forEach(t => t.classList.toggle('active', t.dataset.tab === name));
  panels.forEach(p => p.classList.toggle('active', p.id === name + '-panel'));
  if (name === 'chat') document.getElementById('chat-input').focus();
  if (name === 'encyclopedia') loadEncyclopedia();
  if (name === 'memory') loadMemory();
  if (name === 'traces') loadTraces();
  if (name === 'events') connectEvents();
}
tabs.forEach(t => {
  t.dataset.tab = t.textContent.trim().toLowerCase();
  t.addEventListener('click', () => switchTab(t.dataset.tab));
});

/* ---- Status ---- */
let _status = {};
async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    _status = await r.json();
    document.querySelector('#header .meta').textContent =
      'v' + _status.version + ' | ' + _status.git_branch + ' | ' + _status.uptime;
  } catch {}
}
loadStatus();
setInterval(loadStatus, 30000);

/* ======== CHAT ======== */
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');

function addMsg(text, cls, agent) {
  const div = document.createElement('div');
  div.className = 'msg ' + cls;
  if (agent) div.innerHTML = '<div class="agent-tag">' + agent + '</div>';
  div.innerHTML += (cls === 'user' ? escapeHtml(text) : text);
  chatMessages.appendChild(div);
  chatMessages.scrollTop = chatMessages.scrollHeight;
}

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

async function sendChat() {
  const msg = chatInput.value.trim();
  if (!msg) return;
  chatInput.value = '';
  addMsg(msg, 'user');
  chatSend.disabled = true;
  chatSend.textContent = '...';
  const providerSel = document.getElementById('chat-provider');
  const modelIn = document.getElementById('chat-model');
  const body = {message: msg};
  if (providerSel.value) body.provider = providerSel.value;
  if (modelIn.value.trim()) body.model = modelIn.value.trim();
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body)
    });
    const data = await r.json();
    const agent = data.agent || 'JINN';
    addMsg(escapeHtml(data.response || ''), 'jinn', agent);
  } catch (e) {
    addMsg('Error: ' + e.message, 'jinn', 'ERROR');
  }
  chatSend.disabled = false;
  chatSend.textContent = 'Send';
}

chatSend.addEventListener('click', sendChat);
chatInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendChat(); });

/* ======== ENCYCLOPEDIA ======== */
let _encIndex = {};
async function loadEncyclopedia() {
  try {
    const r = await fetch('/api/encyclopedia');
    _encIndex = await r.json();
    renderEncSidebar();
    document.getElementById('enc-content').innerHTML = '<p class="empty">Select a page from the sidebar or search.</p>';
  } catch {}
}

function renderEncSidebar() {
  const sb = document.getElementById('enc-sidebar');
  let html = '<h3>Encyclopedia</h3>';
  for (const [cat, pages] of Object.entries(_encIndex)) {
    html += '<div class="enc-cat"><div class="enc-cat-title">' + escapeHtml(cat) + '</div>';
    for (const p of pages) {
      html += '<div class="enc-item" onclick="loadPage(\'' + escapeHtml(p.id) + '\')">' + escapeHtml(p.title) + '</div>';
    }
    html += '</div>';
  }
  sb.innerHTML = html;
}

async function loadPage(id) {
  try {
    const r = await fetch('/api/encyclopedia/' + encodeURIComponent(id));
    const page = await r.json();
    document.getElementById('enc-content').innerHTML =
      '<h1>' + escapeHtml(page.title) + '</h1>' +
      '<div class="category-tag">' + escapeHtml(page.category) + '</div>' +
      '<div class="page-body">' + escapeHtml(page.content) + '</div>';
  } catch {}
}

document.getElementById('enc-search').addEventListener('input', async function() {
  const q = this.value.trim();
  if (!q) { renderEncSidebar(); document.getElementById('enc-content').innerHTML = ''; return; }
  try {
    const r = await fetch('/api/encyclopedia/search?q=' + encodeURIComponent(q));
    const results = await r.json();
    let html = '';
    for (const p of results) {
      html += '<div class="search-result" onclick="loadPage(\'' + escapeHtml(p.id) + '\')">' +
              '<div class="sr-title">' + escapeHtml(p.title) + '</div>' +
              '<div class="sr-summary">' + escapeHtml(p.summary || '') + '</div></div>';
    }
    document.getElementById('enc-content').innerHTML = html || '<p class="empty">No results.</p>';
  } catch {}
});

/* ======== MEMORY ======== */
async function loadMemory() {
  try {
    const r = await fetch('/api/memory');
    const memories = await r.json();
    const grid = document.querySelector('#memory-panel .mem-grid');
    if (!memories.length) { grid.innerHTML = '<p class="empty">No episodic memories stored.</p>'; return; }
    grid.innerHTML = memories.map(m => {
      const tags = (m.tags || []).map(t => '<span class="mem-tag">' + escapeHtml(t) + '</span>').join('');
      const date = new Date(m.created_at * 1000).toLocaleDateString();
      return '<div class="mem-card"><div class="mem-summary">' + escapeHtml(m.summary) +
             '</div><div class="mem-tags">' + tags +
             '</div><div class="mem-meta">Importance: ' + (m.importance || 0).toFixed(2) +
             ' | Accessed: ' + (m.access_count || 0) + ' | ' + date + '</div></div>';
    }).join('');
  } catch {}
}

/* ======== TRACES ======== */
async function loadTraces() {
  try {
    const [statsRes, tracesRes] = await Promise.all([
      fetch('/api/stats'), fetch('/api/traces')
    ]);
    const stats = await statsRes.json();
    const traces = await tracesRes.json();

    const statsEl = document.querySelector('#traces-panel .badge-bar');
    const total = stats.total || 0;
    let shtml = '<div class="badge">Total traces: <span>' + total + '</span></div>';
    for (const [outcome, count] of Object.entries(stats.counts || {})) {
      const cls = outcome === 'success' ? 'ok' : outcome === 'failure' ? 'err' : 'warn';
      shtml += '<div class="badge ' + cls + '">' + outcome + ': <span>' + count + '</span></div>';
    }
    statsEl.innerHTML = shtml;

    const timeline = document.getElementById('traces-timeline');
    if (!traces.length) { timeline.innerHTML = '<p class="empty">No traces recorded yet.</p>'; return; }
    timeline.innerHTML = traces.map(t => {
      const date = new Date(t.timestamp * 1000).toLocaleString();
      const oc = t.outcome || 'unknown';
      const ocCls = 'outcome-' + (oc === 'success' ? 'success' : oc === 'failure' ? 'failure' : 'timeout');
      return '<div class="trace-row" onclick="showTrace(\'' + t.trace_id + '\')">' +
             '<div class="meta"><span class="tid">' + t.trace_id + '</span><span class="outcome ' + ocCls + '">' + oc + '</span></div>' +
             '<div style="color:var(--muted);font-size:0.8rem;margin-top:4px">' + date + ' — ' + (t.policy_decision?.agent || 'unknown') + '</div></div>';
    }).join('');
  } catch {}
}

async function showTrace(traceId) {
  const r = await fetch('/api/traces/' + traceId);
  const t = await r.json();
  document.getElementById('trace-detail-title').textContent = 'Trace: ' + t.trace_id;
  document.getElementById('trace-detail-body').textContent = JSON.stringify(t, null, 2);
  document.getElementById('trace-detail').style.display = 'block';
}

/* ======== EVENTS (SSE) ======== */
let _evtSource = null;
let _evtConnected = false;
function connectEvents() {
  if (_evtSource) return; // already connected
  _evtSource = new EventSource('/api/events');
  _evtSource.onopen = () => {
    _evtConnected = true;
    document.getElementById('events-status').textContent = 'Connected — live cognition events';
    document.getElementById('events-status').style.color = 'var(--green)';
  };
  _evtSource.onerror = () => {
    _evtConnected = false;
    document.getElementById('events-status').textContent = 'Disconnected — retrying...';
    document.getElementById('events-status').style.color = 'var(--red)';
  };
  _evtSource.onmessage = (e) => {
    try {
      const evt = JSON.parse(e.data);
      const log = document.getElementById('events-log');
      const now = new Date().toLocaleTimeString();
      const dataStr = typeof evt.data === 'object' ? JSON.stringify(evt.data) : String(evt.data || '');
      log.innerHTML += '<div class="evt-line"><span class="evt-time">' + now + '</span>' +
                       '<span class="evt-type">' + evt.type + '</span>' +
                       '<span class="evt-data">' + escapeHtml(dataStr.substring(0, 200)) + '</span></div>';
      log.scrollTop = log.scrollHeight;
    } catch {}
  };
}

/* ---- Init: show Chat tab ---- */
switchTab('chat');
</script>
</body>
</html>"""


class DashboardServer:
    """Web dashboard for JINN — chat, encyclopedia, memory, traces, live events."""

    def __init__(
        self,
        trace_logger: TraceLogger,
        wiki_store=None,
        memory_store=None,
        bus: Optional[EventBus] = None,
        query_engine: Optional[QueryEngine] = None,
        host: str = "localhost",
        port: int = 8080,
    ) -> None:
        self.trace_logger = trace_logger
        self.wiki_store = wiki_store
        self.memory_store = memory_store
        self.bus = bus
        self.query_engine = query_engine
        self.host = host
        self.port = port
        self._start_time = time.time()

        self.app = web.Application()
        self.app.router.add_get("/", self._handle_index)
        # API
        self.app.router.add_post("/api/chat", self._handle_chat)
        self.app.router.add_get("/api/status", self._handle_status)
        self.app.router.add_get("/api/encyclopedia", self._handle_encyclopedia_index)
        self.app.router.add_get("/api/encyclopedia/search", self._handle_encyclopedia_search)
        self.app.router.add_get("/api/encyclopedia/{page_id}", self._handle_encyclopedia_page)
        self.app.router.add_get("/api/memory", self._handle_memory)
        self.app.router.add_get("/api/traces", self._handle_traces)
        self.app.router.add_get("/api/traces/{trace_id}", self._handle_trace_by_id)
        self.app.router.add_get("/api/stats", self._handle_stats)
        self.app.router.add_get("/api/events", self._handle_events)

    # ---- UI ----

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

    # ---- Chat ----

    async def _handle_chat(self, request: web.Request) -> web.Response:
        body = await request.json()
        msg = body.get("message", "").strip()
        if not msg:
            return web.json_response({"response": "", "agent": "JINN"})

        if self.query_engine is None:
            return web.json_response(
                {"response": "QueryEngine not connected to dashboard.", "agent": "SYSTEM"},
                status=503,
            )

        provider_override = body.get("provider") or None
        model_override = body.get("model") or None

        agent_request = AgentRequest(
            session_id="dashboard",
            input_text=msg,
            metadata={"provider_override": provider_override, "model_override": model_override} if provider_override or model_override else {},
        )
        state = AgentState(session_id="dashboard")
        try:
            response = await self.query_engine.process(agent_request, state)
        except Exception as exc:
            return web.json_response(
                {"response": f"Error: {exc}", "agent": "ERROR"}, status=500
            )
        return web.json_response({"response": response, "agent": "JINN"})

    # ---- Status ----

    async def _handle_status(self, request: web.Request) -> web.Response:
        uptime = int(time.time() - self._start_time)
        m, s = divmod(uptime, 60)
        h, m = divmod(m, 60)
        git = get_git_info()
        return web.json_response({
            "version": get_version(),
            "git_branch": git.get("branch", "unknown"),
            "git_commit": git.get("commit", "unknown"),
            "uptime": f"{h}h {m}m {s}s",
            "active_agents": list(self.query_engine.agents.keys()) if self.query_engine else [],
        })

    # ---- Encyclopedia (JINN's wiki knowledge) ----

    async def _handle_encyclopedia_index(self, request: web.Request) -> web.Response:
        if self.wiki_store is None:
            return web.json_response({})
        index = self.wiki_store.get_index()
        # Enrich with page IDs
        result = {}
        for cat, pages in index.items():
            enriched = []
            for p in pages:
                # Look up the full page to get its ID
                found = self.wiki_store.search(p["title"], limit=1)
                page_id = found[0].id if found else p["title"].lower().replace(" ", "-")
                enriched.append({**p, "id": page_id})
            result[cat] = enriched
        return web.json_response(result)

    async def _handle_encyclopedia_page(self, request: web.Request) -> web.Response:
        if self.wiki_store is None:
            return web.json_response({"error": "encyclopedia not available"}, status=503)
        page_id = request.match_info["page_id"]
        # Try to find by ID — search is the only flexible lookup without a get_by_id
        results = self.wiki_store.search(page_id, limit=1)
        if not results:
            return web.json_response({"error": "not found"}, status=404)
        page = results[0]
        return web.json_response(page.to_dict() | {"id": page.id})

    async def _handle_encyclopedia_search(self, request: web.Request) -> web.Response:
        if self.wiki_store is None:
            return web.json_response([])
        q = request.query.get("q", "")
        if not q:
            return web.json_response([])
        pages = self.wiki_store.search(q)
        return web.json_response([p.to_dict() | {"id": p.id} for p in pages])

    # ---- Memory (episodic) ----

    async def _handle_memory(self, request: web.Request) -> web.Response:
        if self.memory_store is None:
            return web.json_response([])
        limit = int(request.query.get("limit", "100"))
        memories = self.memory_store.get_all(limit=limit)
        return web.json_response([m.to_dict() for m in memories])

    # ---- Traces ----

    async def _handle_traces(self, request: web.Request) -> web.Response:
        limit = int(request.query.get("limit", "50"))
        traces = self.trace_logger.get_all(limit=limit)
        return web.json_response([self._trace_to_dict(t) for t in traces])

    async def _handle_trace_by_id(self, request: web.Request) -> web.Response:
        trace_id = request.match_info["trace_id"]
        trace = self.trace_logger.get_by_id(trace_id)
        if trace is None:
            return web.json_response({"error": "not found"}, status=404)
        return web.json_response(self._trace_to_dict(trace))

    async def _handle_stats(self, request: web.Request) -> web.Response:
        counts = self.trace_logger.get_outcome_counts()
        return web.json_response({"total": self.trace_logger.count(), "counts": counts})

    # ---- Events (SSE) ----

    async def _handle_events(self, request: web.Request) -> web.StreamResponse:
        resp = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )
        await resp.prepare(request)

        if self.bus is None:
            await resp.write(b"data: {\"error\": \"EventBus not connected\"}\n\n")
            await resp.write_eof()
            return resp

        # Build queue for this client
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)

        async def _on_event(payload):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                pass

        # Subscribe to all known event types
        event_types = [
            "turn_start", "turn_end", "agent_start", "agent_chunk",
            "agent_end", "kairos_interrupt", "memory_update",
            "tool_call_request", "tool_call_result",
            "delegation_start", "delegation_end",
        ]
        for et in event_types:
            self.bus.subscribe(et, _on_event, priority=100, name=f"sse-{id(queue)}-{et}")

        try:
            while not resp.task or not resp.task.done():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=30)
                except asyncio.TimeoutError:
                    # Keepalive
                    await resp.write(b": keepalive\n\n")
                    continue
                data = json.dumps({"type": "event", "data": payload})
                await resp.write(f"data: {data}\n\n".encode())
        except (ConnectionResetError, ConnectionError):
            pass
        finally:
            for et in event_types:
                self.bus.unsubscribe(et, _on_event)

        return resp

    # ---- Helpers ----

    @staticmethod
    def _trace_to_dict(trace) -> dict:
        return {
            "trace_id": trace.trace_id,
            "session_id": trace.session_id,
            "timestamp": trace.timestamp,
            "policy_decision": trace.policy_decision,
            "memory_retrieved": trace.memory_retrieved,
            "prompt_template": trace.prompt_template,
            "tool_calls": trace.tool_calls,
            "cost_estimate": trace.cost_estimate,
            "actual_cost": trace.actual_cost,
            "outcome": trace.outcome,
            "user_feedback": trace.user_feedback,
        }

    def run(self) -> None:
        web.run_app(self.app, host=self.host, port=self.port, print=None)


if __name__ == "__main__":
    from src.feedback.trace_logger import TraceLogger

    logger = TraceLogger()
    DashboardServer(logger).run()
