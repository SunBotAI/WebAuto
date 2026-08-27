# RISKS

> 状态：CURRENT / 最后更新：2026-08-27

| 风险 | 影响 | 缓解 / 待决策 |
|---|---|---|
| 仓库已跑着比 v3.3 大得多的实现 | 收敛是删代码，不是加代码 | 先建通用写入再删旧栈（B2→B4），B1—B4 每阶段末非 Chrome 测试全绿 |
| `agent_backends/__init__.py` eager import `.browser_use` | 先删 Browser Use 会打断 MCP 主路径 | B1-01 先迁 `action_policy.py`/`policy.py` 再清父包，B4-01 才物理删 |
| 无 Daemon，stdio 进程被 SIGKILL | 租约无法释放，浏览器永久锁死 | B3-01 租约带 TTL + 心跳续期，过期可抢占 |
| 审批跨进程（Web 写、MCP 读） | 接管/归还断链 | B2-04 Web 审批 + B3 跨进程 sqlite3 协调 |
| 旧栈测试先删会红 | 阶段门禁「全绿」被破坏 | 代码+入口+测试同任务更新，删旧栈放到 B4 |
| 历史文档与最终方案冲突 | 执行者被误导 | 已删除旧历史报告，最终方案是唯一依据 |
| 未知按钮点击被 `external_write_operation` 放行 | 未知写入风险被低估 | B1 引入 OperationOutcome 时 None 路径改为需审批/人工 |
