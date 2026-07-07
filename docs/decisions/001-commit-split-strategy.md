# ADR-001: Commit Split Strategy

**Status:** Accepted
**Date:** 2026-07-07
**Author:** 小千
**Context:** WebAuto repo 110 tracked files, need modular commit strategy aligned with independent module boundaries.

---

## Context

WebAuto 项目包含 110 个 tracked 文件，涵盖多个独立功能域：
AntiDetect / BrowserProfile / CaptchaSolver / Errors / Fetchers / Selector /
TimeSync / WebAuto(主编排) / Zhipu(智铺) / Tests / Tools / Examples / Scripts / 设计文档 / 配置

老大要求"必须拆分，独立"原则，每个功能模块应独立 commit，不应捆绑无关改动。

---

## Decision

### 一、独立模块识别（11 个子模块）

| # | 模块 | 路径 | 文件数 | 依赖边界 |
|---|------|------|--------|---------|
| 1 | **Core/Errors** | Core/Errors/ | 2 | 零依赖（所有模块可引用） |
| 2 | **Core/TimeSync** | Core/TimeSync.py | 1 | 依赖 Core/Errors |
| 3 | **Core/AntiDetect** | Core/AntiDetect.py | 1 | 依赖 Core/Errors |
| 4 | **Core/BrowserProfile** | Core/BrowserProfile/ | 3 | 依赖 Core/Errors |
| 5 | **Core/CaptchaSolver** | Core/CaptchaSolver.py | 1 | 依赖 Core/Errors |
| 6 | **Core/Fetchers** | Core/Fetchers/ | 6 | 依赖 Core/Errors, Core/TimeSync |
| 7 | **Core/Selector** | Core/Selector/ | 2 | 依赖 Core/Errors, Core/Fetchers |
| 8 | **Core/Zhipu** | Core/Zhipu/ | 19 | 依赖 Core/Errors, Core/TimeSync |
| 9 | **Core/WebAuto_v2** | Core/WebAuto_v2.py (+ WebAuto.py) | 2 | 依赖上述所有 Core 子模块 |
| 10 | **Tests** | Tests/ | 17 | 独立测试代码，不引入业务依赖 |
| 11 | **Tools** | Tools/ | 16 | 工具脚本，跨模块组合 |

**半隔离模块：**
- **Examples/** — 示例代码，可独立 commit
- **Scripts/** — 诊断脚本，可独立 commit
- **docs/** — 文档（设计文档 / agent 文档 / decisions），独立 commit

---

### 二、未来 Commit 拆分规则

#### 规则 1：模块内改动 → 单模块 commit
```
feat(antidetect): 添加 xxx 反检测逻辑
feat(fetchers): 支持 human-like 模式
fix(selector): 修复 xxx 选择器 bug
```

#### 规则 2：跨模块联动改动 → 拆成 N 个独立 commit
❌ 错误：`git commit -m "feat: 同时改 AntiDetect 和 Fetchers"`
✅ 正确：
```bash
git commit -m "feat(antidetect): 新增 xxx"
git commit -m "feat(fetchers): 适配 xxx 接口变更"
```

#### 规则 3：WebAuto_v2 编排层改动 → 单独 commit（不捆绑子模块）
WebAuto_v2.py 属于**编排层**，任何对它的改动应单独 commit：
```
feat(webauto-v2): 接入新版 Selector API
```

#### 规则 4：Tests 永远独立 commit
```
test(antidetect): 新增反检测行为测试
test: 覆盖 Zhipu session 异常场景
```
- 测试文件与业务模块一一对应：`test_antidetect_behavior.py` → `Core/AntiDetect.py`
- 伴随业务 commit 的测试用例，**拆出单独 test commit**

#### 规则 5：Config / .gitignore / secrets → 单独 commit
```
chore(config): 更新 example 配置
chore: 升级 .gitignore 忽略规则
```

#### 规则 6：文档改动 → 按文档类型独立 commit
```
docs(architecture): 更新 ARCHITECTURE_V2.md
docs(agent): 更新 TASKS.md
docs(decisions): 添加 ADR-002
```

#### 规则 7：Tools 工具脚本 → 按工具链独立 commit
```
feat(tools): 新增 cdp_launch 交互菜单
feat(tools): credential_panel 支持批量导出
```

---

### 三、已知可拆分边界（绝对红线）

以下边界**禁止跨 commit 混入**：

| 边界 | 说明 |
|------|------|
| `Core/Errors/` | 任何模块的异常类，**禁止**和其他模块混在同一个 commit |
| `Core/Fetchers/` | http / browser / human / stealth 四种子 fetcher 是一个模块，但子 fetcher 各自独立 commit |
| `Core/Zhipu/` | 19 个文件整体是一个模块，内部按子域可拆分（见下） |
| `Core/WebAuto.py` vs `Core/WebAuto_v2.py` | v1 和 v2 是两个独立编排层，禁止混在一个 commit |
| `Tests/` | 测试文件永远不和业务代码同 commit |
| `Tools/` | CDP 工具链 / credential 工具 / console 工具 三组分开 |

---

### 四、Core/Zhipu 内部子域拆分建议（19 文件）

| 子域 | 核心文件 | 建议 |
|------|---------|------|
| Zhipu 核心接口 | `api.py`, `http_client.py` | 独立 commit |
| Zhipu 会话管理 | `session.py`, `scheduler.py`, `orchestrator.py` | 独立 commit |
| Zhipu 时间同步 | `timesync.py` | 独立 commit（已和 Core/TimeSync 解耦设计） |
| Zhipu 浏览器集成 | `browser.py` | 独立 commit |
| Zhipu 配置/常量/加密 | `config.py`, `constants.py`, `crypto.py` | 独立 commit |
| Zhipu 通知/日志 | `notifier.py`, `logger.py` | 独立 commit |
| Zhipu 异常 | `exceptions.py` | 独立 commit |
| Zhipu 调度器 | `group_scheduler.py` | 独立 commit |

---

### 五、Commit Message 规范

遵循 [Conventional Commits](https://www.conventionalcommits.org/) + 铁律 10.1 footer：

```
<type>(<scope>): <subject>

<body（可选）>

操作人: 小千
工具: <codex CLI / claude CLI / sessions_send 派活 / 自主 commit>
Git-Author: Sun-day <759460011@qq.com>
```

**type 范围：** feat / fix / docs / test / chore / refactor / perf / ci

**scope：** 模块名小写（antidetect / fetchers / webauto-v2 / zhipu / tools 等）

---

### 六、禁止行为

| 禁止 | 正确做法 |
|------|---------|
| 把 Core/AntiDetect + Core/Fetchers 写在同一个 commit | 拆成 2 个独立 commit |
| 把业务代码和测试写在同一个 commit | 拆成 2 个独立 commit |
| 把 config.yaml 和业务代码写在同一个 commit | 拆成 2 个独立 commit |
| 把 5 个模块改动压进 1 个 commit message | 拆成 5 个 commit |
| 在 `feat:` 里写"同时更新了 X/Y/Z" | 说明这是多个 commit 的动作 |

---

## Consequences

### 正面
- 每个 commit 语义清晰，可单独 revert
- Code review 更容易聚焦
- 便于追踪特定模块的改动历史
- 避免一个 bug 触发多个不相关模块的回滚

### 负面
- 跨模块重构需要协调多个 commit
- 需要开发者 discipline（不偷懒合并 commit）

### 中性
- git log --oneline 更长
- 需要更好的 commit 规划习惯

---

## 附录：文件归属速查表

```
Core/Errors/                    → module: errors
Core/TimeSync.py                → module: timesync
Core/AntiDetect.py              → module: antidetect
Core/BrowserProfile/            → module: browserprofile
Core/CaptchaSolver.py           → module: captchasolver
Core/Fetchers/                  → module: fetchers
Core/Selector/                  → module: selector
Core/WebAuto.py                 → module: webauto-v1
Core/WebAuto_v2.py              → module: webauto-v2
Core/Zhipu/                     → module: zhipu
Core/__init__.py                → 无独立 commit，随主模块
Services/                       → module: services（独立模块）
Tests/                          → module: tests（独立模块）
Tools/                          → module: tools（分三组：cdp/credential/console）
Examples/                       → module: examples
Scripts/                        → module: scripts
docs/agent/                      → module: docs-agent
docs/decisions/                  → module: docs-decisions
ARCHITECTURE_V2.md              → module: docs-architecture
DESIGN*.md / STATUS.md / ISOLATION_CHECK.md → module: docs-design
config.yaml / .gitignore / .secrets.enc → module: config
requirements.txt                → module: deps
```

---

*生成：XIAOQIAN-WEBAUTO-INIT-REVIEW-002*
