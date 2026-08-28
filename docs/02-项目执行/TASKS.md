# TASKS

> 状态：CURRENT / 最后更新：2026-08-28
> 单一真源：本文件是任务状态的唯一来源。任务 ID 与最终方案 §17 一致。

## 状态机

`backlog → in_progress → done`（阻塞时标 `blocked` 并写进 RISKS.md）

## 当前任务

| ID | 阶段 | 状态 | 负责人 | 证据 |
|---|---|---|---|---|
| B0-00 范围一致性冻结 | B0 | done | — | `40adaa4` |
| B0-01 提交基线/固定安装测试命令 | B0 | done | — | `e86d124` |
| B0-02 文档指向 | B0 | done | — | `40adaa4` |
| B0-03 基线口径 | B0 | done | — | `cb433e9` |
| B1-01 先迁共享 Policy | B1 | done | — | `738274a` |
| B1-02 收敛到 15 浏览器工具 | B1 | done | — | `b631229` |
| B1-03 引入 OperationOutcome | B1 | done | — | `e6f3d73` |
| B1-04 无旁路静态测试 | B1 | done | — | `090f276` |
| B2-01 建 sqlite3 五类表 | B2 | done | — | `a624b8a` |
| B2-02 通用 ActionAttempt/Approval | B2 | done | — | `faee0d4` + 2026-08-28 审批门禁回归 |
| B2-03 通用 governed 工具 | B2 | done | — | `84b31c5` |
| B2-04 Web 审批页 | B2 | done | — | `0d40c7b` + 跨 session 查找回归 |
| B3-01 跨进程 Lease（TTL+fencing） | B3 | done | — | `e067621` |
| B3-02 Dispatch 前 fencing 校验 | B3 | done | — | `b2c3362` |
| B3-03 人机接管与归还 | B3 | done | — | `e8d598e` + 2026-08-28 MCP 路由/跨进程回归 |
| B4-01 零引用后物理删除旧栈 | B4 | in_progress | — | 依赖已删；正式源码符号扫描仍有命中 |
| B4-02 同步删/改测试 | B4 | done | — | 2026-08-28 `160 passed, 1 skipped` |
| B4-03 Managed E2E / CDP 冒烟 | B4 | blocked | — | 本机无 `WEBAUTO_CHROME_EXECUTABLE`；CDP 实跑证据缺失 |
| B4-04 迁移/回滚演练 | B4 | done | — | `c6e3642` |
| B4-05 用户文档 + 更新台账 | B4 | done | — | `910846a` |

## 规则

- 开始任务：状态改 in_progress，填负责人。
- 完成：跑与风险相称的测试，把验证命令与结果写进证据列，再改 done。
- 没有运行证据不得标 done。
