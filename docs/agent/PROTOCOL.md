# WebAuto 项目文档索引 v1.0

> **本文件只放 WebAuto 项目特有内容（命名空间 / 目录结构 / 项目边界）。**
> **协作规范（流程 / 铁律 / 护栏 / 红线 / 通讯规范）= 全局最高法则 = `~/.openclaw/workspace/PROTOCOL.md`**
> **WebAuto 不另写协作规范，所有 agent 必须遵守全局 PROTOCOL.md。**

---

## 1. 协作规范最高法则（全局公用）

**`/home/claw/.openclaw/workspace/PROTOCOL.md`**（全局版本，所有项目共用）

包含：4 步任务发布流程 / 派活护栏 / 7 铁律 / git ref 操作规范 / Agent 通讯规范 / 红线清单。

**所有 WebAuto 工作必须遵守此全局协作规范。**

> 源文件保留：`/mnt/f/Project/ShopAuto/docs/agent/Agent_协作规范.md`（向后兼容，向全局版本同步）

---

## 2. WebAuto 项目边界

| 项 | WebAuto | ShopAuto |
|----|---------|----------|
| 项目定位 | **通用 Web 自动化框架** | **电商专用 AI 项目** |
| 代码目录 | `/mnt/f/Project/WebAuto/` | `/mnt/f/Project/ShopAuto/` |
| 文档目录 | `/mnt/f/Project/WebAuto/docs/` | `/mnt/f/Project/ShopAuto/docs/` |
| 任务管理 | `WebAuto/docs/agent/TASKS.md` | `ShopAuto/docs/agent/TASKS.md` |
| 工作日志 | `WebAuto/docs/agent/WORKLOG.md` | `ShopAuto/docs/agent/WORKLOG.md` |
| 命名空间 | `*-WEBAUTO-*` | `XIAOQIAN-` / `XIAOYUE-` 等 |

**项目独立红线**（这些是 WebAuto 特有的，不在公用协作规范里）：
- ❌ WebAuto 任务**不挂** ShopAuto TASKS.md
- ❌ ShopAuto 任务**不挂** WebAuto TASKS.md
- ❌ **不交叉比对**（不在记忆/文档里写"WebAuto 比 ShopAuto 快"等）
- ❌ **不交叉派活**

---

## 3. WebAuto 任务 ID 命名空间

- `XIAOQIAN-WEBAUTO-NNN-XXX` — 小千
- `XIAOYUE-WEBAUTO-NNN-XXX` — 小月
- `XIAODOU-WEBAUTO-NNN-XXX` — 小豆
- `XIAOCE-WEBAUTO-NNN-XXX` — 小测
- `XIAOBAI-WEBAUTO-NNN-XXX` — 大白

---

## 4. WebAuto 工作路径

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

*最后更新：2026-07-07 09:42（大白改：协作规范 = 公用，引用 ShopAuto Agent_协作规范.md）*