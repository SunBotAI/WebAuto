# TECH_DEBT（遗留代码迁移清理台账）

> 状态：CURRENT / 最后更新：2026-08-27
> 用途：记录尚未解决的迁移/清理事项，以及 B0—B4 本轮处置状态。原始更新时间 2026-08-21。

## 规则

采用 Strangler：替代实现 → 契约测试 → 切换入口 → 零引用扫描 → 物理删除/归档 → 全量回归。旧代码不因“看起来没用”而盲删；用户运行数据、环境、图片和归档资料不在源码清理中删除。

## CLEAN 执行状态

| ID | 状态 | 当前事实与证据 |
| --- | --- | --- |
| CL-01 依赖与入口图 | 完成 | `rg` 覆盖生产 import、测试引用、动态入口、配置和文档；v3 包无 Core/Tools/Services 反向依赖 |
| CL-02 清理台账 | 完成 | 本表记录 keep/adapt/archive/delete、替代路径与门禁 |
| CL-03 收集与死导入 | 完成 | 全量收集与执行 0 errors；最后一个 `Examples` 死导入已随实验测试归档 |
| CL-04 双入口 | 完成 | `Core/WebAuto.py`、`Core/WebAuto_v2.py` 删除；正式入口为 pyproject 的 `webauto`/`webauto-web`/`webauto-mcp` |
| CL-05 Profile 合并 | 完成 | 旧 Profile 实现随 `Core` 归档到 `experiments/legacy/Core`；正式 Session/Lease 位于 `runtime/browser` |
| CL-06 Fetcher 拆分 | 完成 | 浏览器执行进入 `runtime/browser`；旧 Fetcher 随 `Core` 归档，不进入正式测试或 wheel |
| CL-07 Retry | 完成 | 重复 `Core/Retry` 删除；Error Taxonomy、Recovery、幂等保护进入 domain/agent/runtime/storage |
| CL-08 进程内 Task | 完成 | `Core/Spider` 删除；Run/Worker/Redis/Outbox/Checkpoint/Reconciler 替代；Worker 支持持久幂等 |
| CL-09 Service/入口 | 完成 | CLI、Web、API、13 个 MCP 工具统一进入 ApplicationService；正式入口源码不导入 Core 或旧 backend |
| CL-10 POC | 完成 | stealth/cloak/undetected POC 位于 `experiments/providers`，不进入生产依赖 |
| CL-11 脚本/示例/测试 | 完成 | `Core/Tools/Services/E2E` 与 48 个旧测试已归档；旧示例/配置/POC 分类进入 experiments；正式测试仅保留 v3 基线与 `Tests/v3` |
| CL-12 最终删除门禁 | 完成 | 用户授权后完成物理归档；零旧模块导入、正式回归、Chrome E2E、wheel、Secret 与格式门禁通过 |

## 已删除或归档

- 删除：双 WebAuto、Core/Spider、Core/Retry、陈旧 SMS/UI panel 测试、跟踪的诊断截图与明文位置 Secret 文件；
- 历史源码归档：`Core/Tools/Services/E2E` → `experiments/legacy`，48 个旧测试 → `experiments/legacy/tests`；
- 归档：Provider POC、v1/v2 示例、旧 Gradio/MCP/只读 API 与测试、旧 Profile CLI、智谱 YAML/requirements/示例、Captcha/CDP/Mock 实验；
- 正式替代：`src/webauto/application`、`src/webauto/adapters`、`runtime/browser`、`storage` 与 `site_skills`。

## 保留且不盲删

- `var/archive`、根目录特殊归档区域、用户图片/环境/运行资料：未证明可删除；
- `data/profiles`、`data/secrets`：属于旧运行数据，含加密凭证和 Profile；在用户确认备份与迁移前不移动或删除；
- `experiments/legacy`：只作历史追溯，不进入正式导入路径、测试门禁或 wheel。

## 删除门禁证据

- 归档后正式 WSL Tests：126 passed、1 skipped，0 failed、0 errors；归档前兼容基线曾为 657 passed、5 skipped、35 subtests passed；
- Windows Google Chrome 正式 E2E：2 passed；
- 生产入口反向依赖扫描：0 个 Core/旧 backend import；
- wheel 隔离安装与资源清单：通过；
- Secret 扫描：0 命中；
- 测试固定 `tmp` 写入已迁到 pytest 临时目录，工作区 `tmp` 已删除且不再重建。

回滚：所有已跟踪删除/移动均可由 Git 恢复；实验归档保留原文件。用户数据未删除。

## 本轮 B0—B4 处置（v3.3，2026-08-27）

> 依据：[最终方案 §17](../01-项目方案/WebAuto-最终方案.md)。本段只记处置结果与门禁，不重复文件级清单（见 §17.3）。

| ID | 状态 | 当前事实与证据 |
| --- | --- | --- |
| B0 范围与基线 | 待执行 | 范围一致性冻结、提交/tag、固定 `.[api,mcp,dev]` 安装测试命令 |
| B1 只读主链 | 待执行 | 先迁共享 Policy；收敛到 15 浏览器工具；OperationOutcome；无旁路测试 |
| B2 通用写入替代 | 待执行 | sqlite3 五表（Lease/ActionAttempt/Approval/Budget/Audit）；通用 governed 写入 + Web 审批 |
| B3 会话所有权 | 待执行 | 跨进程 Lease（TTL+心跳+fencing）、Dispatch 前校验、人机接管归还 |
| B4 删除与发布 | 待执行 | 零引用后删 Browser Use/Butler/Run/Vertical/Agent；同步删测试；E2E/CDP 冒烟/文档 |

关键顺序：先迁 Policy 再删 Browser Use；先实现通用写入再删 Run/Vertical；B1—B4 每阶段末非 Chrome 测试全绿（B0 只冻结既有基线）。

物理删除/归档需用户确认后执行；归档目录沿用 `experiments/legacy`。未确认前，处置范围只停在代码切离 + 门禁断言。
