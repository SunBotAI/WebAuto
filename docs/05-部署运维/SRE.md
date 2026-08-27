# SRE

> 状态：CURRENT / 最后更新：2026-08-27

## 关键状态与告警

- 健康检查异步并行；本地 Environment 单次超时 2 秒，远程 5 秒；失败标记 `UNKNOWN/DEGRADED`，不阻止启动。
- Challenge / 登录 / OTP / 扫码 / 设备确认立即冻结；用户接管期间 Agent 动作必须为 0。
- 连续 403 两次熔断 30 分钟；429 遵守 Retry-After，否则冷却 15 分钟。
- Managed Download 距到期 7 天内，`browser_status` / `/status` / 启动扫描各写一条结构化 Warning。

## 指标

v3.3 用结构化 `MetricEvent` + SQLite 聚合 JSON 报告，不引入 Prometheus/OTel。Label 只允许低基数维度
（action kind、status、error category、risk、environment type）。

## 应急

- 浏览器锁死（stdio 被 SIGKILL 后租约未释放）：租约 TTL 过期后自动可抢占，不手删数据库。
- 旧 Browser Use 配置：迁移读取器禁用并返回一次 `BACKEND_RETIRED` 告警，不继续创建后端。
