# DEPLOYMENT

> 状态：CURRENT / 最后更新：2026-08-28

本文是 v3.3 的部署、首次启动、审批、接管、失败恢复与回滚说明。

## 启动

Windows 双击 `start-webauto.cmd`，或 PowerShell：

```powershell
cd F:\Project\WebAuto
.\scripts\start-webauto.ps1
```

- 配置中心：`http://127.0.0.1:7860/setup`；
- 根路径 `/` 跳转到 `/setup`；
- 三页控制面：`/setup`、`/status`、`/approvals/{id}`；
- Setup Token：`var/config/setup.token`；
- MCP Token：`var/config/mcp.token`，由 stdio server 自行读取，不粘贴给智能体。

## MCP 接入（stdio，当前推荐）

页面「生成 MCP 配置」产出不含 Token 的命令+参数，典型形态：

```json
{
  "mcpServers": {
    "webauto": {
      "command": "wsl.exe",
      "args": ["--cd", "/mnt/f/Project/WebAuto", "-e",
        ".venv/bin/python", "-m", "webauto.adapters.mcp_server",
        "--transport", "stdio"]
    }
  }
}
```

- AI 客户端拉起本地 MCP 子进程；Token 在传输边界读取，不进工具 Schema/载荷/提示词。
- 22 个 Agent 工具：15 浏览器工具 + `file_upload`/`file_list` + 3 `governed_action_*` + `human_takeover`/`human_return_control`。
- Agent 不能自审批，所有写动作必须由 Web `/approvals/{id}` 确认。
- HTTP MCP 不自动注入 Token，个人本机模式不建议开启。

## 审批 / 接管 / 归还

写动作统一走 Governed Actions 三步：

```text
MCP:  governed_action_prepare → {approval_id, action_hash, object_digest}
用户: 打开 /approvals/{approval_id}，点 Approve（或 Reject）
MCP:  governed_action_execute(approval_id, expected_object_digest) → succeeded/blocked
```

- `governed_action_prepare` 把 SHA-256(payload + page revision + identity) 绑进 Approval。
- `governed_action_execute` 原子消费 Approval：若页面版本漂移 / Object digest 不匹配 → `rejected`。
- Dispatch 前做 fencing_token 校验（B3-02）：Profile Lease 被抢占后旧 holder 的 execute 立即 `rejected`，approval 保持 unconsumed。

人工接管用 `human_takeover` / `human_return_control`：

```text
Agent:  human_takeover → control_owner=human
用户:  在真实 Chrome 中操作
Agent:  human_return_control → control_owner=None
```

- 接管期间所有 `governed_action_execute` 返回 `status=blocked, reason=CONTROL_OWNED_BY_HUMAN`，approval 不被消耗。
- 归还后必须先 `browser_snapshot` 重新观察页面，再用 `governed_action_execute`。

## 失败与恢复

| 失败类型 | 表现 | 恢复路径 |
|---|---|---|
| 页面 ref stale | `STALE_REF` | 重新 `browser_snapshot` 后再操作 |
| 页面变化 | `PAGE_CHANGED` | 只读可重新 snapshot；写动作不可重发 |
| 触发审批 | `APPROVAL_REQUIRED` | `/approvals/{id}` 审批；`governed_action_get` 查状态 |
| 验证码 | `CHALLENGE_DETECTED` | `human_takeover` → 用户接管 → 解除后 `human_return_control` |
| 用户接管中 | `CONTROL_OWNED_BY_HUMAN` | 等待用户归还 |
| Profile 被抢 | `PROFILE_LEASED` | 等 TTL 到期，或 `human_takeover` 走人工流程 |
| Provider 不可用 | `PROVIDER_UNAVAILABLE` | `browser_status` 查 session；必要时 restart MCP |
| Fencing 漂移 | `fencing_token stale` | 重新申请 lease；旧 approval 仍 unconsumed 可重 prepare |

## Managed Download 到期告警

`browser_status` 返回的 `cleanup_warnings[]` 字段列出距到期 7 天内的下载：

```json
{
  "state": "open",
  "cleanup_warnings": [
    {"artifact_id": "art-1", "type": "download",
     "expires_at": "2026-08-30T...", "days_remaining": -2}
  ]
}
```

- 7 天内到期 → 在 `/status` 显示，用户及时导出。
- 30 天到期 → 自动清理，user_downloads 目录独立于 application-state 备份。

## 发布 / 备份 / 回滚

v3.3 存储为标准库 `sqlite3`（`var/webauto.db`，五表：Lease/ActionAttempt/Approval/Budget/Audit）+ 文件 Artifact，无 Redis/Outbox/Worker、无独立 Daemon。执行原则：

1. 安全终止活跃动作，不再新建动作；
2. 备份旧 JSON/PostgreSQL 状态与现有数据库文件；
3. Importer 只读导入旧来源，输出「来源记录数 → 目标表记录数」矩阵：
   ```python
   from webauto.storage.importer import matrix
   print(matrix(legacy_json, sqlite_path))
   # {"runs": {"legacy": 12, "sqlite": 12, "status": "matched"}, ...}
   ```
4. 启动 MCP 进程/Web 服务，跑健康检查 + Managed E2E + CDP 冒烟；
5. 回滚不重发 DISPATCHING/UNCERTAIN 写动作，不删除用户下载。

详见 [最终方案 §22](../01-项目方案/WebAuto-最终方案.md)。
