# PROJECT_STATUS

> 状态：CURRENT / 最后更新：2026-08-28

## 一句话

WebAuto v3.3 主体已实现，当前是**不可发布的候选版**：非 Chrome 测试全绿，但旧栈零引用清理和真实 Chrome/CDP 门禁证据未完成。

## 当前做到哪里

- 最终方案定稿：[WebAuto-最终方案.md](../01-项目方案/WebAuto-最终方案.md)，其中 §17 是唯一完整执行计划（B0—B4）。
- 代码基线（未提交迁移中）：`src/webauto` 86 个 py、`Tests/v3` 66 个测试文件。
- 2026-08-28 当前工作树：`Tests` 全量 160 passed / 1 skipped；跳过项为真实 Chrome E2E。
- 审批强制校验、拒绝终态、跨进程接管状态和 22 个 MCP 工具路由已有回归测试。

## 缺什么（下一步）

1. 完成 B4-01 零引用扫描并物理删除 Butler/Run/Vertical/Agent 残留。
2. 在交付目标机运行 Managed Chrome E2E 和 Existing Chrome CDP 冒烟。
3. 门禁全部通过后再将 v3.3 标记为完成/可发布。

## 关键风险

见 [RISKS.md](./RISKS.md)。最突出的一条：仓库里已跑着一套比 v3.3 大得多的实现（50 个 Agent 工具、内置 Butler/垂直/托管/PG/Redis），收敛是删代码而不是加代码，工时主要在删和测试重写。
