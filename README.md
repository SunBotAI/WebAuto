# WebAuto v3

WebAuto 是一个供 AI 智能体通过 MCP 使用的本地、受治理 Web 浏览器运行时。你的 AI 客户端负责理解需求、规划和动态调整；WebAuto 负责 Google Chrome/CDP、长期 Profile、页面快照引用、域名与文件边界、审批、一次性写操作、证据和审计。

**Web 页面只负责配置，不创建任务，也不运行第二个智能体。**

## 当前产品边界

- 默认入口：外部 AI 客户端 + 本地 stdio MCP；
- Web：`/setup` 配置后台，覆盖 PostgreSQL、Redis、Chrome/CDP、Profile/Artifact、站点和审批策略；
- 浏览器：Playwright 驱动的 Managed Google Chrome 或用户授权的现有 Chrome CDP；
- 内置 Butler/Browser Use：仅为兼容模式，可选；MCP-first 不需要配置内部模型；
- 远程专属浏览器、多租户、自动支付和验证码绕过不在当前范围；
- 不承诺绕过所有反自动化机制。登录、验证码、安全校验和支付由人处理。

## 已实现能力

- 50 个外部 Agent MCP 工具；`settings_*` 不暴露给 Agent；
- `browser_open/status/close` 长期浏览器会话；
- `browser_navigate/snapshot/click/type/select/scroll/wait` 原子交互；
- `browser_tabs/tab_open/tab_switch/tab_close` 多标签操作；
- `browser_screenshot` 内容寻址截图证据；
- 快照 `ref`、URL、元素语义与 `page_revision` 绑定，页面变化后旧引用失效；
- 网页文字标记为 `untrusted_web_content`，不能改变系统权限；
- 私网、非 HTTP(S)、未授权域名和跨域导航阻断；
- 密码、银行卡、OTP、验证码、支付字段强制人工；
- 加购、下单、发布、改价、下架、消息等写操作先返回 `approval_required`，不会直接点击；
- `governed_action_execute` 在最终浏览器边界校验页面、消费一次性审批并最多点击一次；
- 非幂等写结果不确定时禁止自动重试；
- 文件 Inbox、Run Grant、哈希绑定、购物和咸鱼工作区；
- PostgreSQL 状态、Redis Streams、Artifact、Site Skill、Fixture/Replay 与兼容 Goal/Run/Approval API。

## 安装

Python 3.11+ 推荐：

```bash
python -m pip install -e ".[api,postgres,redis,mcp,dev]"
```

只有使用可选内置 Browser Use 兼容链时才安装：

```bash
python -m pip install -e ".[api,postgres,redis,mcp,browser-agent,dev]"
```

程序不会自动读取 `.env`。公开设置写入 `var/config/settings.json`，数据库、Redis 和模型 Secret 加密写入 `var/config/secrets.enc`。`setup.token` 与 `mcp.token` 都不得提交 Git。

## 第一次配置

Windows 可双击 `start-webauto.cmd`，或运行：

```powershell
.\scripts\start-webauto.ps1
```

打开 [http://127.0.0.1:7860/setup](http://127.0.0.1:7860/setup)，从 `var/config/setup.token` 读取 Setup Token，然后：

1. 配置并检测 PostgreSQL、Redis；
2. 选择“托管 Google Chrome”或“CDP 接管”；
3. 配置 Profile、Artifact、站点和审批策略；
4. 保存后按页面提示重启 WebAuto；
5. 点击“生成 MCP 配置”，复制通用 JSON 或 Codex TOML。

模型配置位于“内置兼容 Agent”区域。只使用外部 MCP 智能体时可以留空。

## 智能体 MCP 配置

推荐直接复制 `/setup` 生成的配置，因为它会使用当前实际项目路径。WSL 形式类似：

```json
{
  "mcpServers": {
    "webauto": {
      "command": "wsl.exe",
      "args": [
        "--cd",
        "/mnt/f/Project/WebAuto",
        "-e",
        ".venv/bin/python",
        "-m",
        "webauto.adapters.mcp_server",
        "--transport",
        "stdio"
      ]
    }
  }
}
```

stdio server 会在本机进程边界自行读取独立 MCP Token。**不要把 `mcp_token` 写入客户端配置、提示词或工具参数。** HTTP transport 不自动注入凭据，当前不推荐用于本机个人模式。

Web 服务不是 stdio MCP 的运行依赖；完成配置后，AI 客户端会按上面的命令自行启动 MCP server。

## 怎么使用

在已经加载 WebAuto MCP 的 AI 客户端里直接说，例如：

- “打开京东和淘宝，比较三款 500 元以内的机械键盘，列出来源，先不要加购物车。”
- “用 personal Profile 打开咸鱼，查看我当前在售商品并整理需要处理的内容。”
- “根据这些图片和事实生成咸鱼草稿，填到发布页，最终发布前停下来让我确认。”
- “继续当前浏览器，把选中的商品加入购物车；不要下单和支付。”

智能体应按以下主链调用：

```text
browser_open(profile_id, allowed_domains)
 -> browser_navigate
 -> browser_snapshot
 -> browser_click/type/select
 -> 每次动作后重新 browser_snapshot
 -> 遇到外部写：governed_action_prepare
 -> 用户批准
 -> governed_action_execute（一次）
 -> browser_snapshot 做只读结果核验
```

支付、验证码、密码、设备安全确认始终由用户在真实 Chrome 中完成。

## 正式入口

```bash
webauto-web --host 127.0.0.1 --port 7860
webauto-mcp --transport stdio
```

兼容 CLI 和 Control API 仍保留，但不是默认用户任务入口。

## 验证

```bash
python -m pytest Tests/v3 -q
```

真实购物、消息、下单和商品发布只能使用用户授权账号，并保留审批与人工接管。Fixture 与单元测试不能替代淘宝、京东、咸鱼授权账号实站验收。

## 项目结构

- `src/webauto/application/mcp_browser.py`：MCP 浏览器会话、快照引用和最终安全边界；
- `src/webauto/application/mcp.py`：Agent 工具、任务/审批和垂直工作流分发；
- `src/webauto/adapters/mcp_server.py`：stdio/HTTP MCP transport；
- `src/webauto/application/dashboard.py`：纯 Web 配置页面；
- `src/webauto/runtime/browser`：Chrome/CDP Provider、观察、执行和可靠性；
- `src/webauto/storage`：PostgreSQL、Repository、UoW 与 migration；
- `src/webauto/site_skills`：站点 Skill SDK 与 Fixture；
- `Tests/v3`：单元、契约、集成和真实 Chrome E2E；
- `docs`：项目方案、实施方案、SRE 与测试报告。

## 文档

- [文档导航](docs/README.md)：结构与读序
- [项目状态](docs/02-项目执行/PROJECT_STATUS.md)：当前做到哪里、缺什么
- [最终方案](docs/01-项目方案/WebAuto-最终方案.md)：唯一方案 + 执行计划（§17 B0—B4）
- [任务列表](docs/02-项目执行/TASKS.md)
- [测试质量](docs/04-测试验收/QUALITY_STATUS.md)
- [部署与首次启动](docs/05-部署运维/DEPLOYMENT.md)