# TASKS

> 状态：CURRENT / 最后更新：2026-08-27
> 单一真源：本文件是任务状态的唯一来源。任务 ID 与最终方案 §17 一致。

## 状态机

`backlog → in_progress → done`（阻塞时标 `blocked` 并写进 RISKS.md）

## 当前任务

| ID | 阶段 | 状态 | 负责人 | 证据 |
|---|---|---|---|---|
| B0-00 范围一致性冻结 | B0 | backlog | — | — |
| B0-01 提交基线/固定安装测试命令 | B0 | backlog | — | — |
| B0-02 文档指向 | B0 | backlog | — | — |
| B0-03 基线口径 | B0 | backlog | — | — |
| B1-01 先迁共享 Policy | B1 | backlog | — | — |
| B1-02 收敛到 15 浏览器工具 | B1 | backlog | — | — |
| B1-03 引入 OperationOutcome | B1 | backlog | — | — |
| B1-04 无旁路静态测试 | B1 | backlog | — | — |
| B2-01 建 sqlite3 五类表 | B2 | backlog | — | — |
| B2-02 通用 ActionAttempt/Approval | B2 | backlog | — | — |
| B2-03 通用 governed 工具 | B2 | backlog | — | — |
| B2-04 Web 审批页 | B2 | backlog | — | — |
| B3-01 跨进程 Lease（TTL+fencing） | B3 | backlog | — | — |
| B3-02 Dispatch 前 fencing 校验 | B3 | backlog | — | — |
| B3-03 人机接管与归还 | B3 | backlog | — | — |
| B4-01 零引用后物理删除旧栈 | B4 | backlog | — | — |
| B4-02 同步删/改测试 | B4 | backlog | — | — |
| B4-03 Managed E2E / CDP 冒烟 | B4 | backlog | — | — |
| B4-04 迁移/回滚演练 | B4 | backlog | — | — |
| B4-05 用户文档 + 更新台账 | B4 | backlog | — | — |

## 规则

- 开始任务：状态改 in_progress，填负责人。
- 完成：跑与风险相称的测试，把验证命令与结果写进证据列，再改 done。
- 没有运行证据不得标 done。
