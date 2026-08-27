# WebAuto - Python Web 自动化框架

> Last updated: 2026-07-20

## 项目概述

通用 Web 自动化框架，支持反检测、验证码识别、高精度定时抢购。支持四种模式：http / stealth / browser / human。

**技术栈**：Python, Playwright, httpx, PaddleOCR, Gradio
**代码根目录**：`/mnt/f/project/WebAuto/`
**当前分支**：`feat/webauto`

## Agent 团队

| 角色 | Agent | 职责 |
|------|-------|------|
| 协调者 | 大白 | 任务分发、进度跟踪、最终验收 |
| 后端开发 | 小千 | Core/Services/Python 框架开发 |
| 前端开发 | 小月 | Web UI / Gradio 面板 |
| BA/PM | 小豆 | PRD、需求分析 |
| E2E 测试 | 小测 | 端到端测试、验收 |

## 必须加载的 Skills

**所有 Agent 必须加载：**
```
/project-protocol              # 任务接收→执行→交接全流程（必读）
/task-driver-handoff           # 提交结果信封
/verification-before-completion # 完成前验证（证据优先）
```

**开发 Agent 额外加载：**
```
/test-driven-development       # TDD 开发
```

**测试 Agent 额外加载：**
```
/code-review                   # Standards + Spec 双轴审查
/e2e-testing                   # Playwright E2E 测试模式
```

## 共享协作目录

`docs/` 是所有 agent 协作的单一真源，入口为 [docs/README.md](docs/README.md)：

| 文件 | 作用 |
|------|------|
| docs/02-项目执行/TASKS.md | 任务状态跟踪 |
| docs/02-项目执行/WORKLOG.md | 工作日志 |
| docs/02-项目执行/PROJECT_STATUS.md | 项目状态总览 |
| docs/03-技术文档/ADR/ | 架构决策记录 ADR |

## 任务管理

- **任务 ID**：`{AGENT}-{PROJECT}-{NNN}`（如 `XIAOQIAN-WEBAUTO-001`）
- **状态机**：backlog → ready → leased → running → submitted → review → verify → done
- **交接协议**：见 `docs/02-项目执行/TASKS.md` 和 `/task-driver-handoff` skill

## 质量门禁

**每次 submitted 前必须运行：**
```bash
# 单元测试
pytest Tests/ -x -q

# 代码检查
pylint Core/ Services/ Tools/ --errors-only
```

**铁律**：没有证据的 claim = 作弊。必须运行验证命令后才能声明通过。

## 目录结构

```
WebAuto/
├── src/webauto/           # 正式源码（domain/application/runtime/adapters/storage/site_skills）
├── Tests/                 # 单元、契约、集成与 Chrome E2E
├── docs/                  # ⭐ 协作目录（必读，入口 docs/README.md）
└── CLAUDE.md              # 本文件
```



## 快速开始

1. 阅读 [docs/README.md](docs/README.md) 了解文档结构与读序
2. 阅读 [docs/02-项目执行/TASKS.md](docs/02-项目执行/TASKS.md) 了解当前任务
3. 领取任务前阅读 `/project-protocol` skill
4. 使用 `/task-driver-handoff` 提交结果信封

## 关键规范

1. **单一真源**：`docs/02-项目执行/TASKS.md` 是任务状态的唯一来源
2. **证据优先**：每个 claim 必须有对应的验证命令输出
3. **交接有据**：每次交接必须提交结构化结果信封
4. **不交叉比对**：不与 ShopAuto/Auto 的文档交叉比较
