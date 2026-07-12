## 6. 实现 Roadmap

### 6.1 P0 — 指纹浏览器底座(2 周)

| # | 任务 | 估时 | 依赖 | 验收 |
|---|------|------|------|------|
| 1 | `Core/Profile/profile.py` 数据类 | 3h | 无 | 单元测试通过,支持 YAML roundtrip |
| 2 | `Core/Profile/store.py` 持久化 | 4h | #1 | CRUD + import/export 通过 |
| 3 | `Core/Profile/fingerprint_gen.py` 指纹生成 | 6h | 无 | 生成的指纹通过统计一致性检查 |
| 4 | `Core/Profile/orchestrator.py` 浏览器编排 | 8h | #1, #2 | 能为 3 个 Profile 创建隔离 BrowserContext |
| 5 | `Core/Profile/pool.py` Profile 池 | 4h | #1 | 并发 acquire/release 100 次无死锁 |
| 6 | 整合 AntiDetect + BrowserProfile 到 Profile | 4h | #3, #4 | profile.fingerprint.canvas_seed 真的影响 AntiDetect 噪声 |
| 7 | `Tests/test_isolation.py` Cookie 隔离 | 4h | #4 | 2 个 Profile 的 Cookie 完全独立 |
| 8 | `Tests/test_profile_pool.py` 池子测试 | 3h | #5 | 各种借/还策略 + 并发安全 |
| 9 | `Tests/test_fingerprint_gen.py` 指纹测试 | 4h | #3 | 100 个生成指纹的统计一致性 |
| 10 | `Tools/profile_manager.py` CLI | 4h | #1, #2 | `webauto profile list/create/delete/export` 可用 |
| 11 | 文档 + 1 个 Example (多账号抢购) | 4h | 全部 | 跑通 2 账号并发抢购 |

**P0 完成标准:** 100 个 Profile 持久化 + 5 个并发 BrowserContext 启动 < 10 秒 + Profile 间 Cookie 100% 隔离。

### 6.2 P1 — HTTP/TLS + 人类行为(2 周)

| # | 任务 | 估时 | 依赖 |
|---|------|------|------|
| 12 | `Core/Fetchers/http.py` 升级 curl_cffi | 6h | curl_cffi |
| 13 | TLS 指纹池 (chrome120 / chrome124 / firefox120) | 4h | #12 |
| 14 | 代理轮换 (Profile-level proxy) | 4h | #4 |
| 15 | `Core/Profile/geoip.py` IP 地理推断 | 3h | ipapi / ipinfo |
| 16 | Humanizer 升级 Profile-aware | 4h | #4 |
| 17 | Spider 引擎并发 Profile | 8h | #5 |
| 18 | Spider 暂停恢复 (checkpoint) | 4h | #17 |
| 19 | MCP 服务暴露 Profile 管理 | 4h | #1, #10 |
| 20 | 集成测试 (爬 100 个商品 + 多账号) | 6h | #17 |
| 21 | 文档更新 (README + STATUS) | 2h | 全部 |

**P1 完成标准:** 100 个商品 × 3 个 Profile 并发爬取,Cookie 隔离 + TLS 指纹通过 sannysoft 检测。

### 6.3 P2 — 高级能力(1 个月)

| # | 任务 | 估时 |
|---|------|------|
| 22 | Profile 模板市场 (内置 10 种 OS+Browser 组合) | 6h |
| 23 | 行为学习 (从真实浏览器录制 → 重放) | 12h |
| 24 | 验证码自适应 (Profile 维度统计识别率) | 8h |
| 25 | Profile 健康监控 (自动 cooldown) | 6h |
| 26 | 云同步 hook (S3 / Dropbox) | 6h |
| 27 | Web UI (Gradio 面板) | 8h |
| 28 | 与 Selenium/CDP 兼容 (adapter 模式) | 8h |
| 29 | 性能优化 (Chromium 启动 < 2s) | 8h |
| 30 | 文档站 (MkDocs) | 6h |

### 6.4 优先级判定原则

- **P0 不可砍**: Profile + 编排 + 池子是底座,缺一个上层都跑不起来。
- **P1 可分批**: HTTP/TLS 和 Spider 可以分别交付,不强求同时。
- **P2 看用户反馈**: 行为学习和云同步是"有最好"的优化,不阻塞主线。

---

