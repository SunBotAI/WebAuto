# DEPLOYMENT

> 状态：CURRENT / 最后更新：2026-08-27

本文是 v3.3 的部署与首次启动说明。

## 启动

Windows 双击 `start-webauto.cmd`，或 PowerShell：

```powershell
cd F:\Project\WebAuto
.\scripts\start-webauto.ps1
```

- 配置中心：`http://127.0.0.1:7860/setup`；
- 根路径 `/` 跳转到 `/setup`；
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
- `settings_*` 不注册为 Agent 工具，配置只能从 Web 完成。
- HTTP MCP 不自动注入 Token，个人本机模式不建议开启。

## 发布 / 备份 / 回滚

v3.3 存储为标准库 `sqlite3`（`var/webauto.db`，五表：Lease/ActionAttempt/Approval/Budget/Audit）+ 文件 Artifact，无 Redis/Outbox/Worker、无独立 Daemon。执行原则：

1. 安全终止活跃动作，不再新建动作；
2. 备份旧 JSON/PostgreSQL 状态与现有数据库文件；
3. Importer 只读导入旧来源，输出「来源记录数 → 目标表记录数」矩阵；
4. 启动 MCP 进程/Web 服务，跑健康检查 + Managed E2E + CDP 冒烟；
5. 回滚不重发 DISPATCHING/UNCERTAIN 写动作，不删除用户下载。

详见 [最终方案 §22](../01-项目方案/WebAuto-最终方案.md)。
