"""DecisionTrace Dashboard — aiohttp web UI for inspecting traces."""

from __future__ import annotations

import json
from aiohttp import web

from src.feedback.trace_logger import TraceLogger


_DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>JINN DecisionTrace Dashboard</title>
<style>
  :root { --bg: #0d1117; --surface: #161b22; --border: #30363d; --text: #c9d1d9; --accent: #58a6ff; --green: #3fb950; --red: #f85149; --yellow: #d29922; }
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: var(--bg); color: var(--text); padding: 20px; }
  h1 { color: var(--accent); margin-bottom: 16px; font-size: 1.4rem; }
  #stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
  .badge { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 14px; font-size: 0.9rem; }
  .badge span { font-weight: 700; }
  .badge.ok span { color: var(--green); }
  .badge.err span { color: var(--red); }
  .badge.warn span { color: var(--yellow); }
  #timeline { display: flex; flex-direction: column; gap: 8px; }
  .trace-row { background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 12px 16px; cursor: pointer; transition: border-color 0.15s; }
  .trace-row:hover { border-color: var(--accent); }
  .trace-row .meta { display: flex; justify-content: space-between; align-items: center; }
  .trace-row .id { color: var(--accent); font-family: monospace; }
  .trace-row .outcome { font-size: 0.8rem; padding: 2px 8px; border-radius: 4px; }
  .outcome-success { background: #1a3a2a; color: var(--green); }
  .outcome-failure { background: #3a1a1a; color: var(--red); }
  .outcome-timeout { background: #3a2a1a; color: var(--yellow); }
  #detail { margin-top: 20px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 16px; display: none; }
  #detail h2 { color: var(--accent); margin-bottom: 12px; font-size: 1.1rem; }
  #detail pre { background: var(--bg); border: 1px solid var(--border); border-radius: 4px; padding: 12px; overflow-x: auto; font-size: 0.85rem; line-height: 1.5; }
  .empty { color: #8b949e; font-style: italic; }
</style>
</head>
<body>
<h1>JINN DecisionTrace Dashboard</h1>
<div id="stats"></div>
<div id="timeline"></div>
<div id="detail"><h2 id="detail-title"></h2><pre id="detail-body"></pre></div>
<script>
async function load() {
  const [statsRes, tracesRes] = await Promise.all([
    fetch('/api/stats'), fetch('/api/traces')
  ]);
  const stats = await statsRes.json();
  const traces = await tracesRes.json();

  // Stats bar
  const statsEl = document.getElementById('stats');
  const total = stats.total || 0;
  statsEl.innerHTML = `<div class="badge">Total traces: <span>${total}</span></div>`;
  for (const [outcome, count] of Object.entries(stats.counts || {})) {
    const cls = outcome === 'success' ? 'ok' : outcome === 'failure' ? 'err' : 'warn';
    statsEl.innerHTML += `<div class="badge ${cls}">${outcome}: <span>${count}</span></div>`;
  }

  // Timeline
  const timeline = document.getElementById('timeline');
  if (!traces.length) { timeline.innerHTML = '<p class="empty">No traces recorded yet.</p>'; return; }
  for (const t of traces) {
    const date = new Date(t.timestamp * 1000).toLocaleString();
    const oc = t.outcome || 'unknown';
    const ocCls = 'outcome-' + (oc === 'success' ? 'success' : oc === 'failure' ? 'failure' : 'timeout');
    timeline.innerHTML += `<div class="trace-row" onclick="showDetail('${t.trace_id}')">
      <div class="meta"><span class="id">${t.trace_id}</span><span class="outcome ${ocCls}">${oc}</span></div>
      <div style="color:#8b949e;font-size:0.85rem;margin-top:4px">${date} — ${t.policy_decision?.agent || 'unknown'}</div>
    </div>`;
  }
}

async function showDetail(traceId) {
  const res = await fetch('/api/traces/' + traceId);
  const t = await res.json();
  document.getElementById('detail-title').textContent = 'Trace: ' + t.trace_id;
  document.getElementById('detail-body').textContent = JSON.stringify(t, null, 2);
  document.getElementById('detail').style.display = 'block';
}

load();
</script>
</body>
</html>"""


class DashboardServer:
    """Lightweight aiohttp dashboard for DecisionTrace visualization."""

    def __init__(self, trace_logger: TraceLogger, host: str = "localhost", port: int = 8080) -> None:
        self.trace_logger = trace_logger
        self.host = host
        self.port = port
        self.app = web.Application()
        self.app.router.add_get("/", self._handle_index)
        self.app.router.add_get("/api/traces", self._handle_traces)
        self.app.router.add_get("/api/traces/{trace_id}", self._handle_trace_by_id)
        self.app.router.add_get("/api/stats", self._handle_stats)

    async def _handle_index(self, request: web.Request) -> web.Response:
        return web.Response(text=_DASHBOARD_HTML, content_type="text/html")

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
