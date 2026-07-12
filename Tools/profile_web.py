#!/usr/bin/env python3
"""
Tools/profile_web.py — T-075' Profile 账号池管理页面 (Python stdlib only)

端口: 8000
依赖: http.server（内置），无额外依赖
调 backend: profile_backend.py

运行: python Tools/profile_web.py
访问: http://localhost:8000
"""

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import sys
import os
from pathlib import Path

# ── 路径兼容（Tools/ 下跑，也支持项目根下跑）───────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from Tools.profile_backend import (
    list_profiles,
    create_profile,
    delete_profile,
    warmup_profile,
    get_pool_status,
)

# ── HTML 模板 ─────────────────────────────────────────────────────────────────

HTML = """<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="utf-8">
<title>Profile Pool</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 900px; margin: 2rem auto; padding: 0 1rem; background: #f7f8fa; }
  h1 { color: #1a1a2e; }
  .status { background: #e8f5e9; border-radius: 8px; padding: 0.75rem 1rem; margin-bottom: 1.5rem; font-size: 0.9rem; }
  .status span { font-weight: bold; color: #2e7d32; }
  .btn-row { margin-bottom: 1rem; }
  button { padding: 0.4rem 1rem; border: none; border-radius: 6px; cursor: pointer; font-size: 0.85rem; margin-right: 0.5rem; }
  .btn-add { background: #4f46e5; color: #fff; }
  .btn-refresh { background: #374151; color: #fff; }
  .btn-export { background: #0ea5e9; color: #fff; }
  .btn-import { background: #64748b; color: #fff; }
  table { width: 100%%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  th { background: #1a1a2e; color: #fff; padding: 0.6rem 1rem; text-align: left; font-size: 0.85rem; }
  td { padding: 0.55rem 1rem; border-bottom: 1px solid #f0f0f0; font-size: 0.85rem; }
  tr:last-child td { border-bottom: none; }
  .badge { display: inline-block; padding: 0.15rem 0.5rem; border-radius: 99px; font-size: 0.75rem; font-weight: 600; }
  .badge-ready { background: #d1fae5; color: #065f46; }
  .badge-cooldown { background: #fef3c7; color: #92400e; }
  .badge-banned { background: #fee2e2; color: #991b1b; }
  .actions button { padding: 0.2rem 0.6rem; font-size: 0.75rem; border-radius: 4px; }
  .actions .warmup { background: #f0fdf4; color: #166534; border: 1px solid #86efac; }
  .actions .delete { background: #fef2f2; color: #991b1b; border: 1px solid #fca5a5; }
  .msg { padding: 0.5rem 1rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.85rem; }
  .msg-ok { background: #d1fae5; color: #065f46; }
  .msg-err { background: #fee2e2; color: #991b1b; }
</style>
</head>
<body>
<h1>Profile Pool</h1>

<div class="status" id="poolStatus">Loading pool status...</div>

<div class="btn-row">
  <button class="btn-add" onclick="addProfile()">+ Add Profile</button>
  <button class="btn-refresh" onclick="refresh()">↻ Refresh</button>
  <button class="btn-export" onclick="exportAll()">Export All</button>
  <button class="btn-import" onclick="importJson()">Import JSON</button>
</div>

<div id="msgBox"></div>

<table>
  <thead>
    <tr>
      <th>ID</th><th>Name</th><th>Tags</th><th>Status</th><th>Actions</th>
    </tr>
  </thead>
  <tbody id="tableBody"><tr><td colspan="5">Loading...</td></tr></tbody>
</table>

<script>
const API = '';

async function refresh() {
  try {
    const resp = await fetch(API + '/api/profiles');
    const data = await resp.json();
    const status = await fetch(API + '/api/pool_status').then(r => r.json());
    document.getElementById('poolStatus').innerHTML =
      'Pool: <span>' + status.total + '</span> total | ' +
      '<span>' + status.acquired + '</span> acquired | ' +
      '<span>' + status.idle + '</span> idle';
    const tbody = document.getElementById('tableBody');
    if (!data.length) { tbody.innerHTML = '<tr><td colspan="5">No profiles</td></tr>'; return; }
    tbody.innerHTML = data.map(p => {
      const badgeClass = p.status === 'READY' ? 'badge-ready' : p.status === 'COOLDOWN' ? 'badge-cooldown' : 'badge-banned';
      return `<tr>
        <td><code>${p.id}</code></td>
        <td>${p.name || ''}</td>
        <td>${(p.tags||[]).map(t => '<span class="badge" style="background:#e0e7ff;color:#3730a3;margin-right:4px">'+t+'</span>').join('')}</td>
        <td><span class="badge ${badgeClass}">${p.status}</span></td>
        <td class="actions">
          <button class="warmup" onclick="warmup('${p.id}')">Warmup</button>
          <button class="delete" onclick="del('${p.id}')">Delete</button>
        </td>
      </tr>`;
    }).join('');
  } catch(e) { showMsg(e.message, 'err'); }
}

function showMsg(text, type) {
  document.getElementById('msgBox').innerHTML = `<div class="msg msg-${type}">${text}</div>`;
  setTimeout(() => document.getElementById('msgBox').innerHTML = '', 3000);
}

async function addProfile() {
  const name = prompt('Profile name:');
  if (!name) return;
  try {
    const resp = await fetch(API + '/api/profiles', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name})
    });
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Profile added', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function warmup(id) {
  try {
    const resp = await fetch(API + '/api/profiles/' + id + '/warmup', {method: 'POST'});
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Warmup done', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function del(id) {
  if (!confirm('Delete ' + id + '?')) return;
  try {
    const resp = await fetch(API + '/api/profiles/' + id, {method: 'DELETE'});
    if (!resp.ok) throw new Error(await resp.text());
    showMsg('Deleted', 'ok');
    refresh();
  } catch(e) { showMsg(e.message, 'err'); }
}

async function exportAll() {
  const profiles = await fetch(API + '/api/profiles').then(r => r.json());
  const blob = new Blob([JSON.stringify(profiles, null, 2)], {type: 'application/json'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
  a.download = 'profiles.json'; a.click();
}

async function importJson() {
  const input = document.createElement('input'); input.type = 'file';
  input.accept = '.json';
  input.onchange = async () => {
    const text = await input.files[0].text();
    const data = JSON.parse(text);
    const arr = Array.isArray(data) ? data : [data];
    for (const item of arr) {
      await fetch(API + '/api/profiles', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(item)
      });
    }
    showMsg('Imported ' + arr.length + ' profile(s)', 'ok');
    refresh();
  };
  input.click();
}

refresh();
</script>
</body>
</html>
"""

# ── HTTP Handler ──────────────────────────────────────────────────────────────

POOL_STATUS_TEMPLATE = {
    "total": 0, "acquired": 0, "idle": 0,
    "strategy": "least_used", "max_concurrent": 10
}


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        print(f"[{self.address_string()}] {fmt % args}")

    def send_json(self, code: int, data):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        # ── SPA 入口 ────────────────────────────────────────────────────────
        if self.path in ("/", "/index.html", "/profile_web.py"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML.encode())
            return

        # ── REST API ────────────────────────────────────────────────────────
        if self.path == "/api/profiles":
            profiles = list_profiles()
            self.send_json(200, [p.to_dict() for p in profiles])
            return

        if self.path == "/api/pool_status":
            status = get_pool_status()
            # 统一格式：total/acquired/idle
            acquired = status.get("acquired_count", 0)
            total = status.get("total_profiles", 0)
            idle = total - acquired
            self.send_json(200, {**status, "total": total, "acquired": acquired, "idle": idle})
            return

        self.send_error(404, "Not Found")

    def do_POST(self):
        import uuid

        # ── 创建 Profile ────────────────────────────────────────────────────
        if self.path == "/api/profiles":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode()
            data = json.loads(body) if body else {}
            if not data.get("name"):
                self.send_json(400, {"error": "name required"})
                return
            if not data.get("id"):
                data["id"] = str(uuid.uuid4())[:8]
            try:
                profile = create_profile(data)
                self.send_json(201, profile.to_dict())
            except Exception as e:
                self.send_json(400, {"error": str(e)})
            return

        # ── Warmup ──────────────────────────────────────────────────────────
        if self.path.startswith("/api/profiles/") and self.path.endswith("/warmup"):
            pid = self.path.split("/")[3]
            result = warmup_profile(pid)
            if result:
                self.send_json(200, result.to_dict())
            else:
                self.send_json(404, {"error": "not found"})
            return

        self.send_error(404, "Not Found")

    def do_DELETE(self):
        if self.path.startswith("/api/profiles/"):
            pid = self.path.split("/")[3]
            ok = delete_profile(pid)
            self.send_json(200, {"deleted": ok})
            return
        self.send_error(404, "Not Found")


# ── 入口 ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 8000
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Profile Web UI → http://localhost:{port}")
    print(f"Press Ctrl+C to stop")
    server.serve_forever()
