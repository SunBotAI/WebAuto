# WebAuto Agent 总览 v1.0

> 本文件只放 WebAuto 的 Agent 配置。
> **跟 ShopAuto 的 AGENTS.md 完全独立，不交叉、不比对。**

---

## 🤖 WebAuto Agent 名单

| ID | 角色 | 主要工作 | Primary 模型 | 工作目录 |
|----|------|---------|-------------|----------|
| ⚙️ **小千** | 后端开发 | WebAuto Core / Services / Python 框架 | volcengine/doubao-seed-2.0-code | `/mnt/f/Project/WebAuto/` |
| 🎨 **小月** | 前端开发 | WebAuto 控制台 / Web UI（待立项） | qianfan/glm-5.1 | `/mnt/f/Project/WebAuto/web/`（待建） |
| 📋 **小豆** | BA/PM | WebAuto PRD / 需求分析 | minimax/MiniMax-M3 | `/mnt/f/Project/WebAuto/docs/01-PRD/`（待建） |
| 🧪 **小测** | E2E 验收 | WebAuto E2E / 接口测试 | minimax/MiniMax-M3 | `/mnt/f/Project/WebAuto/tests/` |
| 🤖 **大白** | 总指挥 | 派活 / 协调 / 把控规则 | minimax/MiniMax-M3 | `~/.openclaw/workspace/` |

---

## 📂 WebAuto 工作路径

| 项 | 路径 |
|----|------|
| 代码根 | `/mnt/f/Project/WebAuto/` |
| 核心模块 | `/mnt/f/Project/WebAuto/Core/` |
| 服务化 | `/mnt/f/Project/WebAuto/Services/` |
| 示例 | `/mnt/f/Project/WebAuto/Examples/` |
| 测试 | `/mnt/f/Project/WebAuto/Tests/` |
| 工具 | `/mnt/f/Project/WebAuto/Tools/` |
| 配置 | `/mnt/f/Project/WebAuto/config.yaml` |
| 文档 | `/mnt/f/Project/WebAuto/docs/` |
| Agent 文档 | `/mnt/f/Project/WebAuto/docs/agent/` |
| 决策日志 | `/mnt/f/Project/WebAuto/docs/decisions/` |

---

## 🚧 WebAuto 当前状态

- ✅ Core/ 反检测引擎（GlmRush）
- ✅ Core/ 验证码识别（GlmCodingHelper PP-OCRv6）
- ✅ Core/ 高精度时间同步（GlmCodingGrabber NTP）
- ✅ Core/ Playwright 封装（自研）
- ✅ v2 四种模式（http / stealth / browser / human）
- 🚧 Services/ 服务化封装（待实现）
- 🚧 行为模拟（自研，待移植）
- 🚧 并发请求引擎（GlmRush，待移植）
- 🚧 AI Agent 集成（abencat/browser-use，待立项）
- ❌ Git 仓库（**未初始化**，待老大拍板）

---

*最后更新：2026-07-07 09:41（大白建，独立 v1.0）*