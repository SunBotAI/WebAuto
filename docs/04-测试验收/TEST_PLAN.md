# TEST_PLAN

> 状态：CURRENT / 最后更新：2026-08-27

## 分层

| 层 | 内容 |
|---|---|
| Unit | 工具面、风险分类、Lease、审批绑定、状态机 |
| Static | `test_no_bypass.py`：唯一执行边界、无旁路 |
| Contract | Schema、Environment、Connector、MCP 工具面 |
| Integration | MCP、Playwright、文件、持久化 |
| E2E | Managed Chrome 自动 E2E、Existing Chrome CDP 冒烟 |
| Fault Injection | 崩溃、断连、重复消息、租约过期 |

## 必测场景

- 两个 MCP 进程同时申请同一 Profile，只有一者成功；
- stdio 进程被 SIGKILL 后租约 TTL 过期可抢占；
- 接管期间 Agent 动作 0；归还后旧 Attempt 终结并重新观察；
- 非幂等写不重发；崩溃恢复不盲目重放；
- 未知写入（无文本按钮）`browser_click` 被要求审批；
- 除执行门面外无 Playwright/Page 导入。

## 发布门禁

以最终方案 §19.3 为准；当前尚无可声明的发布证据。
