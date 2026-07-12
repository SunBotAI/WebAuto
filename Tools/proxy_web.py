#!/usr/bin/env python3
"""
Tools/proxy_web.py — T-076' Proxy 代理池管理页面 (Python stdlib only)

端口: 8001
依赖: http.server（内置），无额外依赖
调 backend: proxy_backend.py

运行: python Tools/proxy_web.py
访问: http://localhost:8001
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Tools.proxy_backend import (
    list_all_health,
    add_proxy,
    remove_proxy,
    mark_proxy_dead,
    reset_proxy_failures,
    get_pool_visual_status,
)

# ── HTML 模板 ─────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Proxy Pool</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 1100px; margin: 2rem auto; padding: 0 1rem; background: #f7f8fa; }
  h1 { color: #1a1a2e; }
  .stats { display: flex; gap: 1rem; margin-bottom: 1.5rem; flex-wrap: wrap; }
  .stat-card { background: #fff; border-radius: 8px; padding: 0.75rem 1.25rem; box-shadow: 0 1px 4px rgba(0,0,0,.08); min-width: 120px; }
  .stat-card .label { font-size: 0.75rem; color: #6b7280; margin-bottom: 0.25rem; }
  .stat-card .value { font-size: 1.5rem; font-weight: 700; }
  .value-active { color: #059669; }
  .value-cooldown { color: #d97706; }
  .value-banned { color: #dc2626; }
  .btn-row { margin-bottom: 1rem; }
  button { padding: 0.4rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; margin-right: 0.5rem; }
  .btn-reset { background: #7c3aed; color: #fff; }
  .btn-refresh { background: #374151; color: #fff; }
  table { width: 100%%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  th { background: #1a1a2e; color: #fff; padding: 0.6rem 1rem; text-align: left; font-size: 0.85rem; }
  td { padding: 0.55rem 1rem; border-bottom: 1px solid #f0f0f0; font-size: 0.85rem; vertical-align: middle; }
  tr:last-child td { border-bottom: none; }
  .health-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%%; margin-right: 6px; }
  .dot-active { background: #10b981; box-shadow: 0 0 4px #10b981; }
  .dot-cooldown { background: #f59e0b; }
  .dot-banned { background: #ef4444; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
  .badge-active { background: #d1fae5; color: #065f46; }
  .badge-cooldown { background: #fef3c7; color: #92400e; }
  .badge-banned { background: #fee2e2; color: #991b1b; }
  .actions button { padding: 0.2rem 0.6rem; font-size: 0.75rem; border-radius: 4px; }
  .actions .reset { background: #f5f3ff; color: #5b21b6; border: 1px solid #c4b5fd; }
  .actions .dead { background: #fef2f2; color: #991b1b; border: 1px solid #fca5a5; }
  .actions .remove { background: #f9fafb; color: #374151; border: 1px solid #d1d5db; }
  .msg { padding: 0.5rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }
  .msg-ok { background: #d1fae5; color: #065f46; }
  .msg-err { background: #fee2e2; color: #991b1b; }
  .profile-section { margin-bottom: 2rem; }
  .profile-header { font-size: 0.85rem; font-weight: 600; color: #374151; margin-bottom: 0.5rem; }
</style>
</head>
<body>
<h1>Proxy Pool</h1>

<div class="stats" id="statsRow">Loading...</div>

<div class="btn-row">
  <button class="btn-reset" onclick="resetAll()">Reset All Cooldowns</button>
  <button class="btn-refresh" onclick="refresh()">↻ Refresh</button>
</div>

<div id="msgBox"></div>

<div id="profileList">Loading...</div>

<script>
const API = '';

async function refresh() {
  try {
    const status = await fetch(API + '/api/pool_status').then(r => r.json());
    const health = await fetch(API + '/api/health').then(r => r.json());

    // 顶部统计
    const byState = status.by_state || {};
    document.getElementById('statsRow').innerHTML = `
      <div class="stat-card">
        <div class="label">Total Proxies</div>
        <div class="value">${status.total || 0}</div>
      </div>
      <div class="stat-card">
        <div class="label">Active</div>
        <div class="value value-active">${byState.active || 0}</div>
      </div>
      <div class="stat-card">
        <div class="label">Cooldown</div>
        <div class="value value-cooldown">${byState.cooldown || 0}</div>
      </div>
      <div class="stat-card">
        <div class="label">Banned</div>
        <div class="value value-banned">${byState.banned || 0}</div>
      </div>
      <div class="stat-card">
        <div class="label">Profiles</div>
        <div class="value">${(status.profiles || []).length}</div>
      </div>
    `;

    // Profile 列表
    if (!health.length) {
      document.getElementById('profileList').innerHTML = '<p>No proxies registered.</p>';
      return;
    }
    document.getElementById('profileList').innerHTML = health.map(h => `
      <div class="profile-section">
        <div class="profile-header">Profile: <code>${h.profile_id}</code> — ${h.total} proxies</div>
        <table>
          <thead>
            <tr><th>URL</th><th>State</th><th>Failures</th><th>Actions</th></tr>
          </thead>
          <tbody>
            ${h.proxies.map(p => {
              const dotClass = p.state === 'active' ? 'dot-active' : p.state === 'cooldown' ? 'dot-cooldown' : 'dot-banned';
              const badgeClass = p.state === 'active' ? 'badge-active' : p.state === 'cooldown' ? 'badge-cooldown' : 'badge-banned';
              return `<tr>
                <td><code style="font-size:0.75rem">${p.url}</code></td>
                <td><span class="health-dot ${dotClass}"></span><span class="badge ${badgeClass}">${p.state}</span></td>
                <td>${p.consecutive_failures || 0}</td>
                <td class="actions">
                  <button class="reset" onclick="resetFail('${h.profile_id}','${p.url}')">Reset</button>
                  <button class="dead" onclick="markDead('${h.profile_id}','${p.url}')">Mark Dead</button>
                  <button class="remove" onclick="removeProxy('${h.profile_id}','${p.url}')">Remove</button>
                </td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>
    `).join('');

  } catch(e) { showMsg(e.message, 'err'); }
}

function showMsg(text, type) {
  document.getElementById('msgBox').innerHTML = `<div class="msg msg-${type}">${text}</div>`;
  setTimeout(() => document.getElementById('msgBox').innerHTML = '', 3000);
}

async function resetFail(pid, url) {
  try {
    const resp = await fetch(API + '/api/proxies/' + pid + '/reset_failures', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url})
    });
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Failures reset', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function markDead(pid, url) {
  if (!confirm('Mark ' + url + ' as dead?')) return;
  try {
    const resp = await fetch(API + '/api/proxies/' + pid + '/mark_dead', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url})
    });
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Proxy marked dead', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function removeProxy(pid, url) {
  if (!confirm('Remove ' + url + '?')) return;
  try {
    const resp = await fetch(API + '/api/proxies/' + pid + '/' + encodeURIComponent(url), {method: 'DELETE'});
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Proxy removed', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function resetAll() {
  try {
    const resp = await fetch(API + '/api/health/reset_all', {method: 'POST'});
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('All cooldowns reset', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

refresh();
</script>
</body>
</html>
"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def send_json(self, code: int, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path in ("/", "/index.html", "/proxy_web.py"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
            return

        if self.path == "/api/health":
            health = list_all_health()
            self.send_json(200, health)
            return

        if self.path == "/api/pool_status":
            status = get_pool_visual_status()
            self.send_json(200, status)
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        # 重置单个 proxy failures
        import urllib.parse
        if self.path.startswith("/api/proxies/") and "/reset_failures" in self.path:
            parts = self.path.split("/")
            pid = parts[3]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            data = json.loads(body) if body else {}
            url = data.get("url", "")
            ok = reset_proxy_failures(pid, url)
            self.send_json(200, {"ok": ok})
            return

        # 标记 dead
        if self.path.startswith("/api/proxies/") and "/mark_dead" in self.path:
            parts = self.path.split("/")
            pid = parts[3]
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            data = json.loads(body) if body else {}
            url = data.get("url", "")
            ok = mark_proxy_dead(pid, url)
            self.send_json(200, {"ok": ok})
            return

        # 批量重置所有 cooldown → 遍历 health，重置所有 cooldown proxy
        if self.path == "/api/health/reset_all":
            health = list_all_health()
            count = 0
            for h in health:
                for p in h.get("proxies", []):
                    if p.get("state") == "cooldown":
                        ok = reset_proxy_failures(h["profile_id"], p["url"])
                        if ok:
                            count += 1
            self.send_json(200, {"reset": count})
            return

        self.send_error(404, "Not Found")

    def do_DELETE(self):
        import urllib.parse
        if self.path.startswith("/api/proxies/"):
            # /api/proxies/{pid}/{url_encoded}
            parts = self.path[1:].split("/")  # 去掉前导 /
            if len(parts) >= 3 and parts[2]:
                pid = parts[2]
                url = urllib.parse.unquote(parts[3]) if len(parts) > 3 else ""
                if url:
                    ok = remove_proxy(pid, url)
                    self.send_json(200, {"removed": ok})
                    return
        self.send_error(404, "Not Found")


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 8001
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Proxy Web UI → http://localhost:{port}")
    print(f"Press Ctrl+C to stop")
    server.serve_forever()
