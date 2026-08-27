# PROJECT_STATUS

> 状态：CURRENT / 最后更新：2026-08-27

## 一句话

WebAuto v3.3 目标是「外部 AI 经 MCP 调用的受治理本地浏览器执行服务」，当前处于**方案已定、实施未开始**阶段。

## 当前做到哪里

- 最终方案定稿：[WebAuto-最终方案.md](../01-项目方案/WebAuto-最终方案.md)，其中 §17 是唯一完整执行计划（B0—B4）。
- 代码基线（未提交迁移中）：`src/webauto` 86 个 py、`Tests/v3` 66 个测试文件。
- 测试基线：`Tests` 全量 235 passed / 2 failed / 4 skipped；两个失败为 Dashboard 断言（conversation / vertical 控件）。

## 缺什么（下一步）

按 B0 → B1 → B2 → B3 → B4 执行，总工期约 15—22 个工作日：

1. B0 范围与基线：统一方案/DoD、提交基线、固定安装测试命令。
2. B1 只读主链：先迁共享 Policy，收敛到 15 浏览器工具，引入 OperationOutcome，无旁路测试。
3. B2 通用写入替代：sqlite3 五表、通用 ActionAttempt/Approval、文件绑定、Web 审批、3 个 governed 工具。
4. B3 会话所有权：跨进程 Lease、心跳续期、Dispatch 前 fencing、人机接管与归还。
5. B4 删除与发布：零引用后删 Butler/Run/Vertical/Agent，同步删测试，Managed E2E、CDP 冒烟、文档。

## 关键风险

见 [RISKS.md](./RISKS.md)。最突出的一条：仓库里已跑着一套比 v3.3 大得多的实现（50 个 Agent 工具、内置 Butler/垂直/托管/PG/Redis），收敛是删代码而不是加代码，工时主要在删和测试重写。
