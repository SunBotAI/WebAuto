# ARCHITECTURE

> 状态：CURRENT / 最后更新：2026-08-27

当前架构快照以代码为准；目标架构见 [最终方案 §4](../01-项目方案/WebAuto-最终方案.md)。

## 当前事实（v3.3 起点）

- 入口：stdio MCP（`adapters/mcp_server.py`），每个 server 实例化一个 `McpBrowserRuntime`。
- 执行门面（待统一）：`application/mcp_browser.py`（765 行）已具备会话、快照/ref、页面动作、Challenge、一次性写边界。
- 第二执行栈（待删）：`application/browser_agent.py` + `local_execution.py` + `agent_backends/*` + `butler/vertical/scenarios`。
- 领域模型：`domain/contracts.py`。
- 存储：当前为文件配置 + PostgreSQL/JSON 迁移输入；v3.3 收敛为安全关键状态持久化（Lease/ActionAttempt/Approval/Budget+Audit）。

## 依赖方向（目标）

```text
domain <- application <- runtime/adapters
```

- `domain` 不依赖 Playwright、FastAPI、MCP、数据库。
- 页面/Context 只在唯一执行门面内部可见。

## 唯一执行边界

B2 之后，除 `McpBrowserRuntime`（及其迁移后的 `action_policy`/`policy`）外，
任何模块 import Playwright 或注解 `Page`/`BrowserContext` 都应由 `test_no_bypass.py` 判定失败。
