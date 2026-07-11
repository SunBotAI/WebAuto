# WebAuto 架构文档

> 基于 v2.0 架构设计，已实现部分标注 ✅，规划中标注 📋。

---

## 系统架构图

```
┌──────────────────────────────────────────────────────┐
│                    WebAuto 统一入口                   │
│              WebAuto / WebAuto_v2                    │
├──────────────────────────────────────────────────────┤
│                   核心能力层                          │
│  ┌───────────┐  ┌────────────┐  ┌──────────────┐  │
│  │ 反检测引擎 │  │ 验证码识别 │  │  时间同步    │  │
│  │ AntiDetect│  │CaptchaSolver│  │  TimeSync   │  │
│  └───────────┘  └────────────┘  └──────────────┘  │
│  ┌──────────────────────┐  ┌────────────────────┐  │
│  │ Profile 浏览器配置管理 │  │ ProxyPool 代理池   │  │
│  │ ProfileOrchestrator   │  │ ProxyRotator       │  │
│  └──────────────────────┘  └────────────────────┘  │
├──────────────────────────────────────────────────────┤
│                   底层执行层                          │
│         Playwright  /  httpx  /  PP-OCRv6           │
└──────────────────────────────────────────────────────┘
```

---

## 两种入口

| 入口 | 模式 | 适用场景 |
|------|------|---------|
| `Core.WebAuto` | Playwright 基础封装 | 简单浏览器自动化 |
| `Core.WebAuto_v2` | 四种模式（HTTP/Stealth/Browser/Human） | 复杂场景，按需切换 |

---

## 已完成模块

### Core/AntiDetect — 反检测引擎

注入 JS 代码绕过浏览器检测。

| 能力 | 说明 |
|------|------|
| fetch/XHR hook | 请求指纹随机化（X-Request-Id / X-Timestamp） |
| JSON.parse 补丁 | 递归修改响应数据（如解除售罄状态） |
| WebGL/Canvas 指纹 | 添加微小噪声改变哈希 |
| WebDriver 隐藏 | 隐藏 `navigator.webdriver` 等特征 |

### Core/CaptchaSolver — 验证码识别

| 能力 | 说明 |
|------|------|
| PP-OCRv6 / ddddocr | 自动选择可用引擎 |
| 中文点选验证码 | 腾讯防水墙等主流平台适配 |
| 坐标自动映射 | 图片坐标 → 页面坐标（考虑缩放） |
| 人类行为模拟 | 随机移动步数 + 点击间隔 |

### Core/TimeSync — 高精度时间同步

| 能力 | 说明 |
|------|------|
| NTP 多次采样 | 5 次采样取中位数，过滤网络抖动 |
| 两段式等待 | 粗 sleep + busy spin，精度 ±5ms |
| 服务器时间对齐 | 不受本地时钟偏差影响 |

### Core/Profile — 浏览器配置管理

| 文件 | 职责 |
|------|------|
| `profile.py` | Profile 数据模型（指纹 + 网络配置 + 状态） |
| `store.py` | Profile 持久化（CRUD + import/export） |
| `orchestrator.py` | 浏览器生命周期管理（共享 Chromium 进程） |
| `pool.py` | Profile 池（并发借还 + 策略 + 脏页追踪） |

### Core/ProxyPool — 全局代理池

| 文件 | 职责 |
|------|------|
| `proxy.py` | 代理数据模型 + URL 解析 |
| `health.py` | 代理健康追踪（active/cooldown/banned） |
| `proxy_rotator.py` | 代理轮换策略 |

### Core/Zhipu — 智谱 GLM Coding 抢购

| 能力 | 说明 |
|------|------|
| 真实抓包链路 | 5 步下单（getCustomerInfo → batch-preview → createBankOrder） |
| 多套餐降级 | Max 售罄自动试 Pro |
| 凭证加密存储 | Fernet (AES-128 + HMAC) |
| 短信验证码重登 | 登录态失效时自动发码 |

---

## MCP 集成层

WebAuto 通过 MCP（Model Context Protocol）对外暴露管理能力。

| Server | 工具数 | 文档 |
|--------|--------|------|
| `webauto-profile` | 8 | `MCP/profile_backend.md` |
| `webauto-proxy` | 8 | `MCP/proxy_backend.md` |
| `webauto-pool` | 8 | `MCP/pool.md` |

详见 `MCP/` 目录和 `../README.md` 的 MCP 集成章节。

---

## 项目目录结构

```
WebAuto/
├── Core/                         # 核心模块
│   ├── WebAuto.py              # 主入口（v1）
│   ├── WebAuto_v2.py           # 主入口（v2，四种模式）
│   ├── AntiDetect.py           # 反检测引擎
│   ├── CaptchaSolver.py        # 验证码识别
│   ├── TimeSync.py             # 时间同步
│   ├── Profile/                # 浏览器配置
│   │   ├── profile.py
│   │   ├── store.py
│   │   ├── orchestrator.py
│   │   └── pool.py
│   ├── ProxyPool/              # 代理池
│   │   ├── proxy.py
│   │   ├── health.py
│   │   └── proxy_rotator.py
│   └── Zhipu/                  # 智谱抢购
│
├── Examples/                     # 使用示例
├── Tests/                        # 测试用例
├── References/                    # 开源项目源码参考
│   ├── GlmRush/               # 油猴注入参考
│   ├── GlmCodingHelper/       # 验证码参考
│   └── GlmCodingGrabber/      # 后端抢购参考
├── docs/                         # 本文档目录
│   ├── README.md              # 文档索引
│   ├── ARCHITECTURE.md        # 本文档
│   ├── MODULES.md             # 模块参考
│   ├── QUICKSTART.md          # 快速开始
│   └── MCP/                   # MCP 文档
└── requirements.txt
```

---

## 依赖关系

```
requirements.txt
├── playwright               # 浏览器自动化
├── ppocr                    # 汉字 OCR
├── ddddocr                  # 通用 OCR
├── pyyaml                   # 配置文件
├── fastapi + uvicorn        # MCP HTTP Server
└── mcp                      # MCP Python SDK
```

---

*最后更新：2026-07-14*
