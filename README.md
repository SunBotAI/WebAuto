# WebAuto - Web 页面自动化通用框架

与 ShopAuto 架构风格一致，PascalCase 命名。整合开源项目的核心技术，提供企业级 Web 自动化能力。

## 🎯 核心能力

| 模块 | 技术来源 | 状态 |
|------|---------|------|
| **反检测引擎** | GlmRush (油猴) | ✅ 已完成 |
| **验证码识别** | GlmCodingHelper (PP-OCRv6) | ✅ 已完成 |
| **高精度时间同步** | GlmCodingGrabber (NTP) | ✅ 已完成 |
| **Playwright 封装** | 自研 | ✅ 已完成 |
| **并发请求引擎** | GlmRush | 🚧 待移植 |
| **行为模拟** | 自研 | 🚧 待移植 |

## 📁 项目结构

```
WebAuto/
├── Core/                          # 核心模块
│   ├── WebAuto.py               # 主入口，整合所有能力
│   ├── CaptchaSolver.py         # 验证码识别模块
│   ├── AntiDetect.py            # 反检测注入模块
│   └── TimeSync.py              # 高精度时间同步
│
├── Services/                      # 服务化封装（待实现）
│   ├── CaptchaService.py        # 验证码识别服务
│   └── TimeSyncService.py       # 时间同步服务
│
├── Examples/                      # 使用示例
│   └── example_basic.py         # 基础使用演示
│
├── Tests/                         # 测试用例
│
├── References/                    # 开源项目源码参考
│   ├── GlmRush/                 # GlmRush 抢购助手源码
│   ├── GlmCodingHelper/         # GlmCodingHelper 验证码源码
│   └── GlmCodingGrabber/        # GlmCodingGrabber 后端源码
│
├── Research/                      # 技术调研文档
│   └── captcha_type.md          # 验证码类型调研报告
│
├── Scripts/                       # 辅助脚本
│
├── DESIGN.md                      # 架构设计文档
└── requirements.txt               # 依赖列表
```

## 🚀 快速开始

### 安装依赖

```bash
pip install -r requirements.txt

# 安装 Playwright 浏览器(仅 browser / stealth / human 模式需要)
playwright install chromium
```

### 两个入口

项目提供两个等价入口,**按需选择**:

- **`Core.WebAuto`** —— 简易版 v1,只支持 Playwright 浏览器模式。API 简单,适合"我就想要个浏览器自动化"场景。
- **`Core.WebAuto_v2`** —— 高级版,提供四种模式(http / stealth / browser / human)、智能选择器、四层获取器。同一套 API 可在不同模式间切换。

```python
# v1 简易版
from Core.WebAuto import WebAuto, WebAutoConfig
async with WebAuto(WebAutoConfig()) as auto:
    await auto.goto("https://example.com")

# v2 高级版
from Core.WebAuto_v2 import WebAutoHttp, WebAutoStealth, WebAutoHuman
async with WebAutoHttp() as auto:           # 纯 HTTP,最快
    await auto.goto("https://example.com")
async with WebAutoStealth() as auto:        # 隐形浏览器
    await auto.goto("https://example.com")
async with WebAutoHuman() as auto:          # 人类行为(抢购专用)
    await auto.goto("https://example.com")
```

### 基础使用

```python
import asyncio
from Core.WebAuto import WebAuto, WebAutoConfig

async def main():
    config = WebAutoConfig(
        headless=False,
        anti_detect=True,
        enable_captcha_solver=True,
        enable_time_sync=True
    )
    
    async with WebAuto(config) as auto:
        # 1. 导航到目标页面
        await auto.goto("https://example.com")
        
        # 2. 验证码自动识别和点击
        result = await auto.captcha.solve_from_page(auto.page)
        if result.success:
            await auto.captcha.click_points(auto.page, result)
            
        # 3. 高精度定时抢购
        target_time = "2024-12-31 10:00:00"  # 服务器时间
        await auto.time.sleep_until_server_time(target_timestamp)
        
        # 4. 执行抢购逻辑
        # ...

asyncio.run(main())
```

## 🧪 跑测试 / Demo

```bash
# 跑单测 (需要 httpx + lxml + playwright, 无需 chromium)
python -m unittest discover Tests -v

# 跑 v1 基础 demo (仅 time_sync 演示, 不需要浏览器)
python Examples/example_basic.py

# 跑 v2 基础 demo (HTTP 模式不需要浏览器; 其他模式需要 chromium)
python Examples/example_v2_basic.py

# 跑抢购风格 demo (需要 chromium)
python Examples/example_glm_rush.py
```

## 🧩 核心模块详解

### 1. 反检测引擎 (AntiDetect)

**核心技术来自 GlmRush 项目：**

- ✅ **fetch/XHR hook** - 请求指纹随机化（X-Request-Id / X-Timestamp）
- ✅ **JSON.parse 定向补丁** - 递归修改响应数据（如解除售罄状态）
- ✅ **Shadow DOM 面板隔离** - 自动化 UI 不被页面检测
- ✅ **WebGL/Canvas 指纹随机化** - 添加微小噪声改变哈希
- ✅ **WebDriver 特征隐藏** - 隐藏 navigator.webdriver 等特征

**使用方式：**
```python
from Core.AntiDetect import inject_anti_detect

# Playwright 页面一键注入
await inject_anti_detect(page)
```

### 2. 验证码识别 (CaptchaSolver)

**核心技术来自 GlmCodingHelper 项目：**

- ✅ **PP-OCRv6 / ddddocr 双引擎** - 自动选择可用引擎
- ✅ **中文点选验证码识别** - 腾讯防水墙等主流平台适配
- ✅ **坐标自动映射** - 图片坐标 → 页面坐标（考虑缩放）
- ✅ **人类行为模拟** - 随机移动步数 + 点击间隔

**使用方式：**
```python
from Core.CaptchaSolver import CaptchaSolver

solver = CaptchaSolver()
await solver.init()

# 方式 1: 从图片识别
result = await solver.solve_chinese_click(image_bytes, "你好世界")

# 方式 2: 直接从 Playwright 页面自动识别
result = await solver.solve_from_page(page)
await solver.click_points(page, result)
```

### 3. 高精度时间同步 (TimeSync)

**核心技术来自 GlmCodingGrabber 项目：**

- ✅ **NTP 多次采样取中位数** - 过滤网络抖动，5 次采样
- ✅ **两段式等待** - 粗 sleep + busy spin，精度 ±5ms
- ✅ **自动选最快 NTP 服务器** - 阿里云 / 腾讯云 / 公共 NTP
- ✅ **服务器时间对齐** - 不受本地时钟偏差影响

**使用方式：**
```python
from Core.TimeSync import create_timesync

ts = await create_timesync(samples=5)
print(f"时钟偏移: {ts.stats.offset_ms:+.1f}ms")

# 等待到指定服务器时间
await ts.sleep_until_server_time(target_timestamp)

# 倒计时
await ts.countdown(10.0)  # 10 秒倒计时
```

## 🤖 MCP 集成

WebAuto 通过 MCP（Model Context Protocol）对外暴露 Profile、代理池、浏览器池的管理能力，可接入 Claude Desktop、Cursor 等 AI 工具。

### 支持的 MCP Server

| Server | 端口 | 工具数 | 能力 |
|--------|------|--------|------|
| `webauto-profile` | 8080 | 8 | Profile CRUD + warmup + import/export |
| `webauto-proxy` | 8081 | 8 | 全局代理池 CRUD + 健康检查 + 批量导入 |
| `webauto-pool` | 8082 | 8 | Profile 池借还 + 策略切换 + 状态管理 |

**合计 24 个工具**（profile×8 + proxy×8 + pool×8）。

### 快速配置

#### Claude Desktop

编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`：

```json
{
  "mcpServers": {
    "webauto-profile": {
      "command": "python",
      "args": ["-m", "webauto.mcp.profile_server"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    },
    "webauto-proxy": {
      "command": "python",
      "args": ["-m", "webauto.mcp.proxy_server"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    },
    "webauto-pool": {
      "command": "python",
      "args": ["-m", "webauto.mcp.pool_server"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    }
  }
}
```

#### Cursor

编辑 `.cursor/mcp.json`（项目根目录）：

```json
{
  "mcpServers": {
    "webauto-profile": {
      "command": "uvicorn",
      "args": ["webauto.mcp.profile_server:app", "--host", "127.0.0.1", "--port", "8080"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    },
    "webauto-proxy": {
      "command": "uvicorn",
      "args": ["webauto.mcp.proxy_server:app", "--host", "127.0.0.1", "--port", "8081"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    },
    "webauto-pool": {
      "command": "uvicorn",
      "args": ["webauto.mcp.pool_server:app", "--host", "127.0.0.1", "--port", "8082"],
      "env": { "WEBAUTO_BASE_DIR": "~/.cache/webauto" }
    }
  }
}
```

### 截图配置示意

**Claude Desktop MCP 配置面板**（设置 → Developer → Edit Config）：

```
┌──────────────────────────────────────────────┐
│  MCP Servers                                 │
├──────────────────────────────────────────────┤
│  ☑ webauto-profile                          │
│    Command: python -m webauto.mcp.profile…   │
│                                              │
│  ☑ webauto-proxy                             │
│    Command: python -m webauto.mcp.proxy…     │
│                                              │
│  ☑ webauto-pool                              │
│    Command: python -m webauto.mcp.pool…      │
└──────────────────────────────────────────────┘
```

### 24 Tools 一览表

#### profile_backend（8 tools）

| Tool | 说明 |
|------|------|
| `profile_list` | 列出所有 Profile |
| `profile_get` | 获取单个 Profile 详情 |
| `profile_create` | 创建新 Profile |
| `profile_update` | 更新 Profile 配置 |
| `profile_delete` | 删除 Profile |
| `profile_warmup` | 预热 Profile（生成 user-data） |
| `profile_export` | 导出 Profile 为 .zip |
| `profile_import` | 从 .zip 导入 Profile |

#### proxy_backend（8 tools）

| Tool | 说明 |
|------|------|
| `proxy_list` | 列出所有代理 |
| `proxy_get` | 获取代理详情 + 健康状态 |
| `proxy_create` | 添加新代理 |
| `proxy_update` | 更新代理配置 |
| `proxy_delete` | 删除代理 |
| `proxy_health_check` | 发起健康检查 |
| `proxy_bulk_import` | 批量导入代理 |
| `proxy_reset_health` | 重置健康状态 |

#### pool（8 tools）

| Tool | 说明 |
|------|------|
| `pool_acquire` | 从池中借出 Profile |
| `pool_release` | 归还 Profile |
| `pool_status` | 获取池状态快照 |
| `pool_ban` | 永久封禁 Profile |
| `pool_cooldown` | 临时冷却 Profile |
| `pool_set_strategy` | 切换选择策略 |
| `pool_set_max_concurrent` | 修改最大并发数 |
| `pool_uncooldown_profile` | 提前解除 cooldown |

### 详细 Schema 文档

完整的 JSON Schema 定义见 `docs/MCP/` 目录：

- `docs/MCP/profile_backend.md` — profile 8 tool schema
- `docs/MCP/proxy_backend.md` — proxy 8 tool schema
- `docs/MCP/pool.md` — pool 8 tool schema

### 安装依赖

MCP Server 需要以下依赖（已包含在项目 `requirements.txt` 中）：

```bash
pip install -r requirements.txt
```

关键依赖：
- `mcp` — MCP Python SDK
- `fastapi` + `uvicorn` — HTTP Server（Cursor stdio 模式）
- `playwright` — 浏览器自动化
- `pyyaml` / `json` — 配置文件读写

### stdio 启动命令

适合 Claude Desktop 或直接命令行测试：

```bash
# 方式 1：直接 python 模块（推荐 Claude Desktop）
python -m webauto.mcp.profile_server
python -m webauto.mcp.proxy_server
python -m webauto.mcp.pool_server

# 方式 2：HTTP + uvicorn（适合 Cursor stdio 模式）
uvicorn webauto.mcp.profile_server:app --host 127.0.0.1 --port 8080
uvicorn webauto.mcp.proxy_server:app --host 127.0.0.1 --port 8081
uvicorn webauto.mcp.pool_server:app --host 127.0.0.1 --port 8082

# 方式 3：验证安装是否成功
python -c "import webauto.mcp.profile_server; print('OK')"
python -c "import webauto.mcp.proxy_server; print('OK')"
python -c "import webauto.mcp.pool_server; print('OK')"
```

### 故障排查 FAQ

**Q: MCP Server 启动报错 `ModuleNotFoundError: No module named 'webauto'`**

```bash
# 确保在项目根目录，且 PYTHONPATH 包含 src
cd /path/to/WebAuto
export PYTHONPATH="$(pwd):$PYTHONPATH"
```

或安装为可编辑包：
```bash
pip install -e .
```

**Q: Claude Desktop 检测不到 MCP Server**

1. 确认 `claude_desktop_config.json` 路径正确：
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Linux: `~/.config/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`

2. 重启 Claude Desktop

3. 检查日志：Claude Desktop → Settings → Developer → 查看 MCP 配置状态

**Q: 端口被占用（8080/8081/8082）**

```bash
# 查占用进程
lsof -i :8080
lsof -i :8081
lsof -i :8082

# 换用其他空闲端口，记得同步更新 mcp.json 配置
uvicorn webauto.mcp.profile_server:app --host 127.0.0.1 --port 9000
```

**Q: Profile/Proxy 操作报 `FileNotFoundError: Profile not found`**

Profile/Proxy 数据默认存在 `~/.cache/webauto/profiles/` 和 `~/.cache/webauto/proxies/`。确认：
1. WebAuto 初始化时指定的 `WEBAUTO_BASE_DIR` 与 MCP Server 一致
2. 目录有读写权限

**Q: MCP 工具调用超时**

健康检查（`proxy_health_check`）默认超时 10 秒，代理响应慢时可调大：
```json
{
  "proxy_id": "proxy-001",
  "test_url": "https://www.google.com",
  "timeout": 30
}
```

**Q: Windows 上路径格式问题**

Windows 路径用反斜杠，MCP 配置中建议用正斜杠或 raw string：
```json
{
  "env": {
    "WEBAUTO_BASE_DIR": "C:\\Users\\username\\.cache\\webauto"
  }
}
```

**Q: Cursor MCP 配置不生效**

1. `.cursor/mcp.json` 必须放在项目根目录
2. Cursor 重启后生效（不是 reload）
3. 终端输出查报错：`cursor --verbose` 启动看 MCP 加载日志

---

## 🎯 智谱 AI GLM Coding 套餐抢购

`Core/Zhipu` 子包吸收了 `References/GlmCodingGrabber` 的完整业务实现,可以抢智谱 BigModel 平台的 GLM Coding 套餐 (Lite / Pro / Max)。

**核心能力**:
- ✅ **真实抓包的 5 步下单链路** —— `getCustomerInfo` → `batch-preview` → 售罄检测 → `createBankOrder`
- ✅ **多套餐降级** —— Max 售罄自动试 Pro,避免一个档位没了全军覆没
- ✅ **多账号并发** —— Semaphore + gather,单账号串行避免风控
- ✅ **NTP 时间同步** —— 自动选最快 NTP(腾讯云/阿里云/公共池)
- ✅ **加密凭证存储** —— Fernet (AES-128 + HMAC),口令通过环境变量传入
- ✅ **短信验证码重登** —— 登录态失效时自动发码 → 阻塞等用户输入
- ✅ **指数退避重试** —— 网络错误重试,售罄/风控不盲目重试

### 🚀 智谱快速开始

**Step 1: 安装依赖**
```bash
pip install -r requirements.txt
```

**Step 2: 准备配置文件**
```bash
# 复制示例配置
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入你的 Authorization token（从浏览器 F12 抓 bigmodelJwt）
```

**Step 3: 验证 NTP 同步**
```bash
python -m Core.Zhipu sync
# 输出示例：时钟偏移: -12.3ms  →  OK
```

**Step 4: 执行抢购**
```bash
python -m Core.Zhipu grab -c config.yaml
```

> **多账号抢购**：在 `config.yaml` 的 `accounts` 列表里加多个账号（每个账号独立 token + 独立 BrowserProfile），即可并发抢购。

**端点(已实测)**:
```
GET  /api/biz/customer/getCustomerInfo   # 验证登录态 + userId
POST /api/biz/pay/batch-preview          # 拿全部套餐 + soldOut 状态
POST /api/biz/pay/bank/createBankOrder   # 创建订单 → 支付链接
```

**用法 1: Python 直接调用**
```python
from Core.Zhipu import ApiClient, BigModelApi, SoldOutError, AuthError
from Core.Zhipu.config import AppConfig, Account

cfg = AppConfig(
    accounts=[Account(name="主账号", phone="138xxxxxxxx", token="your-token")],
    target_plan="Max",
    target_plans=["Max", "Pro"],   # Max 抢不到降级 Pro
    billing_cycle="yearly",
    pay_channel="alipay",
)
client = ApiClient(cfg, token="your-token", account_name="主账号")
api = BigModelApi(client, cfg)

try:
    order = await api.run_purchase_chain()
    print(f"下单成功: orderNo={order.order_id} pay_url={order.pay_url}")
except SoldOutError as e:
    print(f"全部售罄: {e}")
except AuthError as e:
    print(f"登录态失效: {e}")
```

**用法 2: CLI 抢购**
```bash
# 1. 准备配置
cp config.example.yaml config.yaml
# 编辑 config.yaml 填入 token / cookie (从浏览器 F12 抓)

# 2. NTP 自检
python -m Core.Zhipu sync

# 3. 录入凭证到加密库
GLM_GRABBER_KEY="your-passphrase" python -m Core.Zhipu store --name "主账号" --phone "138xxxxxxxx"

# 4. 执行抢购
python -m Core.Zhipu grab -c config.yaml
```

**风险提示**: 智谱 GLM Coding 是 Web 抢购场景,需要从浏览器 F12 抓 `Authorization` 头(Bearer token) 或完整 Cookie 才能登录。`createBankOrder` 的字段在补货后可能变化,GlmCodingGrabber 已做多别名兜底但仍需实测。

### 智谱抢购控制台（Gradio）

本地 Gradio 面板统一入口:

```bash
# 1. 装 gradio（已加进 requirements.txt）
pip install -r requirements.txt

# 2. 设置加密口令（必须，用于 Fernet 加密 .secrets.enc）
export GLM_GRABBER_KEY="your-passphrase"

# 3. 启动面板（4 个 Tab：Console / 凭证 / Profile / Proxy）
python Tools/webauto_web.py
# 浏览器打开 http://localhost:7860
```

4 个 Tab 说明:
- **Console** —— 完整版抢购控制台，支持多账号 + 套餐 + 倒计时 + 开始抢
- **凭证** —— 粘贴 Token / Cookie，验证并保存；或手机号 + 短信码登录；已保存账号列表
- **Profile** —— Profile 列表 + 创建 / 编辑 / 删除 + 指纹预览
- **Proxy** —— 代理列表 + 增删改 + 批量导入 + 健康检查

业务后端在 `Tools/credential_backend.py`（凭证）、`Tools/profile_backend.py`（Profile）、`Tools/proxy_backend.py`（Proxy），都跟 `Core/Zhipu` 共享加密库 `.secrets.enc`。

### 设计借鉴(来自 GitHub 优秀项目)

Playwright 扫码登录的设计模式借鉴了以下开源项目:

- **[BetaStreetOmnis/xhs_ai_publisher](https://github.com/BetaStreetOmnis/xhs_ai_publisher)** (2k+ ⭐) — 它的 `_is_creator_logged_in()` 模式:发一个登录态专属的 API 请求 `/creator.xiaohongshu.com/api/galaxy/user/info`,HTTP 200 即认定为登录,比轮询 URL/localStorage 稳 100 倍。我们用智谱等价的 `/api/biz/customer/getCustomerInfo` 作为登录探活手段。
- **[gxagxagx/jimeng-browser-automation](https://github.com/gxagxagx/jimeng-browser-automation)** — 二维码截图保存到 `runtime/artifacts/` 模式,DOM 选择器失效时截全页兜底。我们用 `tempfile.gettempdir() / "webauto_qrcode.png"` 实时落盘,UI 轮询它。
- **GlmRush / GlmCodingHelper / GlmCodingGrabber** — 项目内 `References/` 已有源码,分别为本项目提供了油猴注入模式、PP-OCRv6 验证码、Python 后端抢购骨架。

设计原则:**先调 API 直调(短信登录),再上 Playwright(扫码登录),都不行再手动 F12 抓 cookie**。三种方式覆盖所有用户场景。

## 📚 参考项目

| 项目 | Star | 核心技术 |
|------|------|---------|
| [GlmRush](https://github.com/...) | 373+ | 油猴注入、并发请求、反检测 |
| [GlmCodingHelper](https://github.com/...) | 398+ | PP-OCRv6 验证码识别 |
| [GlmCodingGrabber](https://github.com/...) | - | Python 异步、NTP 时间同步 |

## ⚠️ 免责声明

本项目仅供技术研究和学习使用。使用本工具进行自动化操作可能违反目标网站的服务条款，使用者需自行承担相应风险。

## 📝 开发路线

- [x] 目录结构规范（PascalCase）
- [x] 反检测引擎移植
- [x] 验证码识别模块
- [x] 高精度时间同步
- [x] 并发请求引擎（Zhipu scheduler + adaptive_retry）
- [x] 行为模拟模块（HumanFetcher 贝塞尔鼠标轨迹）
- [x] 任务调度系统（NTP 校时 + Scheduler dry-run）
- [ ] Web API 服务化（Services/ 目录预留，当前未实现）
