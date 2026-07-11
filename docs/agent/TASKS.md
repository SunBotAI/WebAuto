# WebAuto TASKS v1.4（独立任务管理）

> **本文件是 WebAuto 项目唯一的任务状态记录。**
> **跟 ShopAuto 的 `ShopAuto/docs/agent/TASKS.md` 完全独立。**
> **不在本文件记录 ShopAuto 任务。**

---

## 📋 任务状态总览

| ID | 任务 | 责任人 | 状态 | 截止 | 验收标准 |
|----|------|--------|------|------|----------|
| XIAOQIAN-WEBAUTO-AUDIT-001 | 审计 ShopAuto TASKS 是否真有 webauto 任务 | 小千 | ✅ DONE | 2026-07-07 22:00 | audit 结论：ShopAuto 当前 TASKS.md 0 个 WEBAUTO 匹配，无需迁移 |
| XIAOQIAN-WEBAUTO-TASKLIST-T014 | T-014 Edg UA 移除（fingerprint_gen.py） | 小千 | ✅ DONE | 2026-07-09 18:00 | `grep -c "Edg" = 0` |
| XIAOQIAN-WEBAUTO-TASKLIST-T010 | T-010 Proxy 认证三元组 | 小千 | ✅ DONE | 2026-07-09 18:00 | 8 个测试全过 |
| XIAOQIAN-WEBAUTO-TASKLIST-T063 | T-063 warmup calibrate() 修复 | 小千 | ✅ DONE | 2026-07-09 18:00 | mock 断言 `calibrate_called=True` |
| XIAOQIAN-WEBAUTO-FINGERPRINT-001 | Core/Profile/ 目录 + profile.py 数据类 | 小千 | ✅ DONE | 2026-07-09 17:55 | 56/56 测试全过（含 profile roundtrip + fingerprint statistical）|
| XIAOQIAN-WEBAUTO-FINGERPRINT-002 | fingerprint_gen.py 指纹生成器 | 小千 | ✅ DONE | 2026-07-09 17:55 | 14/14 statistical tests + 7/7 roundtrip tests |
| XIAOQIAN-WEBAUTO-FINGERPRINT-003 | store.py 本地持久化 CRUD+import/export | 小千 | ✅ DONE | 2026-07-09 18:55 | 20/20 测试全过 + YAML roundtrip |
| XIAOQIAN-WEBAUTO-FINGERPRINT-004 | orchestrator.py 浏览器编排器 | 小千 | ✅ DONE | 2026-07-09 19:10 | 38/38 测试全过 + max_concurrent + 内存监控 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-005 | pool.py Profile 池（借/还/轮换） | 小千 | ✅ DONE | 2026-07-09 19:35 | 14/14 测试全过 + cooldown + 5 策略 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-006 | 整合 AntiDetect + BrowserProfile 到 Profile | 小千 | ✅ DONE | 2026-07-09 19:50 | 50/50 测试全过 + 7项字段seed同步 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-007 | 集成测试 + Cookie 隔离验证 | 小千 | ✅ DONE | 2026-07-09 20:05 | 77/77 测试全过 + Cookie 隔离 + Profile roundtrip |
| XIAOQIAN-WEBAUTO-FINGERPRINT-008 | profile_manager.py CLI（增删改查 + warmup） | 小千 | ✅ DONE | 2026-07-09 20:35 | 18/18 测试全过 + 6 命令（list/create/delete/warmup/export/import） |
| XIAOQIAN-WEBAUTO-FINGERPRINT-009 | curl_cffi TLS 指纹升级 Core/Fetchers/http.py | 小千 | ✅ DONE | 2026-07-10 15:50 | curl_cffi 替换 httpx，impersonate 池全通 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-010 | AntiDetect seed 强制同步测试 | 小千 | ✅ DONE | 2026-07-09 18:34 | a4dd874 - seed 强制同步 + 7项字段同步测试全过 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-011 | Spider checkpoint 暂停恢复 | 小千 | ✅ DONE | 2026-07-11 00:05 | commit `deb0ae3` 7/7 PASSED |
| XIAOCE-WEBAUTO-T045 | test_orchestrator.py 智谱5账号并发 | 小测 | ✅ DONE | 2026-07-11 18:00 | 7/7 PASSED（commit b71b497）|
| XIAOCE-WEBAUTO-T046 | test_pool.py 智谱5账号并发 | 小测 | ✅ DONE | 2026-07-11 18:00 | 14/14 PASSED（commit b71b497）|

---

## 🚧 IN_PROGRESS

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| XIAOQIAN-WEBAUTO-FINGERPRINT-011 | Spider checkpoint 暂停恢复 | ✅ DONE | 小千 commit `deb0ae3`，7/7 PASSED |

---

## ✅ DONE

### XIAOQIAN-WEBAUTO-TASKLIST-T014 — Edg UA 移除（fingerprint_gen.py）
- **任务来源**：TASKLIST.md T-014
- **目标**：从 `windows_chrome_120` 模板移除 Edg UA（Edg + Google Inc. vendor 错配，智谱风控穿帮）
- **验证**：`grep -c "Edg" Core/Profile/fingerprint_gen.py = 0`
- **完成时间**：2026-07-09 17:58
- **commit**：`5a55f56` on `feat/webauto`（humanizer 优化后）

### XIAOQIAN-WEBAUTO-TASKLIST-T010 — Proxy 认证三元组（NetworkConfig）
- **任务来源**：TASKLIST.md T-010
- **目标**：`get_playwright_proxy()` 返回 `(proxy_url, username, password)` 三元组
- **验证**：8 个测试全过（`test_profile_roundtrip.py` + `test_fingerprint_statistical.py`）
- **完成时间**：2026-07-09 17:58
- **commit**：`5a55f56` on `feat/webauto`

### XIAOQIAN-WEBAUTO-TASKLIST-T063 — warmup calibrate() 修复
- **任务来源**：TASKLIST.md T-063
- **目标**：`BrowserOrchestrator.warmup` 中 `TimeSync.sync()` → `calibrate()`（dead code 修复）
- **验证**：mock 断言 `calibrate_called=True`, `sync_called=False`
- **完成时间**：2026-07-09 17:58
- **commit**：`5a55f56` on `feat/webauto`

### XIAOQIAN-WEBAUTO-AUDIT-001 — 审计 ShopAuto TASKS.md 是否真有 webauto 任务
- **责任人**：小千
- **完成时间**：2026-07-07 17:55
- **验证命令**：`grep -rin "WEBAUTO\|webauto" /mnt/f/Project/ShopAuto/docs/agent/TASKS.md`
- **结果**：0 个匹配，确认无需迁移
- **commit**：`d3adf2e`（本文件更新）

---

## ⏸️ BLOCKED

（暂无）

---

## 📝 任务取消记录

| 原 ID | 任务 | 取消原因 |
|-------|------|---------|
| XIAOQIAN-WEBAUTO-INIT-REVIEW-002 | Review 110 tracked 文件 + 拆分策略 | 老大拍板"架构不用看了"，已取消 |

---

## 📝 Fingerprint Browser 任务详情

### XIAOQIAN-WEBAUTO-FINGERPRINT-001 — Profile 数据类 + 目录结构
- **目标**：建立 `Core/Profile/` 模块基础（profile.py + fingerprint_gen.py + store.py + pool.py + orchestrator.py）
- **依赖**：无
- **验收**：单元测试 Profile.to_dict() / from_dict() YAML roundtrip 通过
- **截止**：2026-07-08 00:30
- **状态**：🚧 IN_PROGRESS（代码已写完，待测试）

### XIAOQIAN-WEBAUTO-FINGERPRINT-002 — 指纹生成器
- **目标**：实现 `FingerprintGenerator`，生成统计一致的浏览器指纹
- **依赖**：无（独立模块）
- **验收**：
  1. 同 seed 生成的 Canvas/WebGL/Audio 输出一致
  2. 不同 seed 生成不同指纹
  3. **统计一致性检查（7项关联）**：UA / Platform / Vendor / Locale / Timezone / Screen Resolution / Hardware Concurrency 必须相互匹配（例如 "Chrome 120 on Windows" 不可能 locale=zh-CN）
- **截止**：2026-07-08 00:30
- **状态**：🚧 IN_PROGRESS（代码已写完，待测试）

### XIAOQIAN-WEBAUTO-FINGERPRINT-003 — ProfileStore 持久化
- **目标**：实现 CRUD + import/export，支持 YAML 配置文件
- **依赖**：001
- **验收**：`test_profile_store.py` CRUD 单元测试通过
- **截止**：2026-07-08 00:30
- **状态**：⏳ PENDING

### XIAOQIAN-WEBAUTO-FINGERPRINT-004 — BrowserOrchestrator 编排器
- **目标**：实现多 Profile 共用单 Chromium 进程的 BrowserContext 管理
- **依赖**：001, 003
- **验收**：
  1. 3 个 Profile 并发创建 BrowserContext，Cookie 100% 隔离
  2. **max_concurrent 限制**：超过 max_concurrent 的请求排队，不超限
  3. **内存监控**：单 Chromium 进程内存超阈值（如 2GB）时拒绝新 Context 并报警
- **截止**：2026-07-08 00:30
- **状态**：⏳ PENDING

### XIAOQIAN-WEBAUTO-FINGERPRINT-005 — ProfilePool 池
- **目标**：实现 acquire/release + 5 种策略（round_robin/random/sticky/least_used/health_based）
- **依赖**：001
- **验收**：
  1. 并发 acquire/release 100 次无死锁，状态正确
  2. **cooldown 防风控**：归还 Profile 后进入 cooldown（可配置时长），cooldown 期内不可再借
- **截止**：2026-07-08 00:30
- **状态**：⏳ PENDING

### XIAOQIAN-WEBAUTO-FINGERPRINT-006 — 整合 AntiDetect + BrowserProfile
- **目标**：Profile.fingerprint.canvas_seed 强制同步到 AntiDetectConfig
- **依赖**：002, 003, 004
- **验收**：同 Profile 二次启动，Canvas hash 完全一致
- **截止**：2026-07-08 12:00
- **状态**：⏳ PENDING

### XIAOQIAN-WEBAUTO-FINGERPRINT-007 — 集成测试 + Cookie 隔离
- **目标**：`Tests/test_isolation.py` 验证 Profile 间 Cookie 完全隔离
- **依赖**：004, 005
- **验收**：Profile A 的 Cookie 在 Profile B 中完全不可见
- **截止**：2026-07-08 12:00
- **状态**：⏳ PENDING

### XIAOQIAN-WEBAUTO-FINGERPRINT-008 — profile_manager.py CLI
- **目标**：`webauto profile` 命令：list / create / delete / warmup / export
- **依赖**：001, 003
- **验收**：CLI 命令可正常运行，help 输出正确
- **截止**：2026-07-08 12:00
- **状态**：⏳ PENDING

---

## 📝 P1 备选任务（ADR-002 P1 阶段）

> 以下任务属于 P1 阶段，在 P0（001~008）全部通过验收后启动。
> 具体截止时间待 P0 完成后由大白协调老大确认。

### XIAOQIAN-WEBAUTO-FINGERPRINT-009 — curl_cffi TLS 指纹升级
- **目标**：升级 `Core/Fetchers/http.py`，用 `curl_cffi` 替换 `httpx`，实现 TLS 指纹模拟
- **依赖**：004（Orchestrator 验收通过）
- **验收**：
  - HTTP 模式下，sannysoft.com TLS 检测项 60%+ passed
  - 支持 impersonate chrome120 / chrome124 / firefox120 指纹池切换
- **对应 ADR-002 章节**：4.6 升级 HTTP Fetcher (TLS 指纹)
- **状态**：⏳ P1 备选

### XIAOQIAN-WEBAUTO-FINGERPRINT-010 — AntiDetect seed 强制同步测试
- **目标**：验证 `profile.apply_to_anti_detect()` 正确将 `fingerprint.canvas_seed` 同步到 `AntiDetectConfig`，防止"各自独立生成 seed"风险（ADR-002 风险 #6）
- **依赖**：006（整合 AntiDetect 验收通过）
- **验收**：
  - `assert anti_detect_config.fingerprint_seed == profile.fingerprint.canvas_seed`
  - 同 Profile 二次启动，AntiDetect 噪声 byte-identical
- **对应 ADR-002 章节**：7. 风险与缓解，风险 #6
- **commit**: `a4dd874` "fix: orchestrator 调用 apply_to_antidetect 实现 seed 强制同步"
- **测试**: `Tests/test_antidetect_profile_sync.py` 7项字段同步全过
- **状态**：✅ DONE (2026-07-09 18:34)

### XIAOQIAN-WEBAUTO-FINGERPRINT-011 — Spider checkpoint 暂停恢复
- **目标**：Spider 引擎支持中途 kill 重启后从 checkpoint 继续（不重复爬取）
- **依赖**：004, 005（Profile 池 + Orchestrator 验收通过）
- **验收**：
  - Spider 爬取 N 个页面后 `kill -9`，重启能从断点续跑
  - 已爬 URL 不重复，checkpoint 文件完整
- **对应 ADR-002 章节**：6.2 P1 Roadmap，#18 Spider 暂停恢复
- **状态**：⏳ P1 备选

---

## 📝 ADR-002 状态记录

| ADR | 标题 | 状态 | Accepted Date | Accepted by |
|-----|------|------|---------------|-------------|
| ADR-002 | 指纹浏览器集成架构规划与实现方案 | ✅ Accepted | 2026-07-07 | 大白（基于老大 23:37 拍板） |

---

*最后更新：2026-07-08 00:40（小千：TASKS v1.4 — 3 修订 + 3 P1 备选 task + ADR-002 Accepted）*

---

## 📋 2026-07-11 08:34 新任务（第五批，一锅端 Phase 3 P1）

### XIAOQIAN-WEBAUTO-T022 — 代理轮换（Profile-level 失败剔除）
- **任务来源**：TASKLIST.md T-022（Phase 3 P1 提升）
- **目标**：Profile 借出后连续 N 次 HTTP 失败 → 自动 cooldown/banned + 切换下一个 Proxy
- **验收**：连续失败触发 ban + Pool 自动路由到健康 Proxy
- **截止**：2026-07-12 22:00
- **状态**：✅ DONE（2026-07-11 09:37，38 测试全过，commit f271338 pushed）
- **派活人**：大白（skill v1.3，含 multi-search-engine + humanizer）
- **skill_used（目标）**：multi-search-engine, humanizer

### XIAOQIAN-WEBAUTO-T023 — geoip.py IP 地理推断 + timezone 匹配
- **任务来源**：TASKLIST.md T-023（Phase 3 P1 提升）
- **目标**：`geoip.py` 实现 IP → (country, city, timezone, locale) 推断，Profile 自动匹配
- **验收**：`ip2geoinfo("8.8.8.8")` → tz="America/Los_Angeles"
- **截止**：2026-07-12 22:00
- **状态**：✅ DONE（2026-07-11 09:37，38 测试全过，commit f271338 pushed）
- **派活人**：大白（skill v1.3，含 multi-search-engine + humanizer）
- **skill_used（目标）**：multi-search-engine, humanizer

### XIAOQIAN-WEBAUTO-T064 — Store.save 原子写 + Pool 内存态 + 定期 flush
- **任务来源**：TASKLIST.md T-064（Phase 3）
- **目标**：`Store.save` 原子写（os.rename） + Pool 内存态 + 定期 flush
- **验收**：100 借还/秒 YAML 不损坏 + IO 不阻塞
- **截止**：2026-07-12 22:00
- **状态**：⏳ PENDING（待 T022/T023 完成后派）
- **派活人**：大白（skill v1.3，含 multi-search-engine + humanizer）
- **skill_used（目标）**：multi-search-engine, humanizer

### XIAOQIAN-WEBAUTO-T068 — test_profile_from_dict_edge_cases
- **任务来源**：TASKLIST.md T-068（Phase 3）
- **目标**：`test_profile_from_dict_edge_cases.py` Profile 边界输入覆盖
- **验收**：所有边界 case 测试全过
- **截止**：2026-07-12 22:00
- **状态**：⏳ PENDING（待 T022/T023 完成后派）
- **派活人**：大白（skill v1.3，含 multi-search-engine）
- **skill_used（目标）**：multi-search-engine, humanizer

### XIAOQIAN-WEBAUTO-T070 — .gitignore 加 .pytest_cache/ + .claude/
- **任务来源**：TASKLIST.md T-070（Phase 3）
- **目标**：.gitignore 加 `.pytest_cache/` + `.claude/` + `__pycache__/`
- **验收**：`git status --ignored` 显示正确忽略
- **截止**：2026-07-12 22:00
- **状态**：⏳ PENDING（待 T022/T023 完成后派）
- **派活人**：大白（skill v1.3）
- **skill_used（目标）**：无（简单任务）

---

## 📋 2026-07-09 18:07 新任务（第三批）

### XIADOU-WEBAUTO-DOCS-001 — T-041 ADR迁移路径 + T-042 deprecation note
- **任务来源**：TASKLIST.md T-041 + T-042
- **目标**：
  - T-041：ADR 文档"BrowserProfile → Profile 迁移路径"
  - T-042：`Core/Profile/__init__.py` 顶部加 DeprecationWarning
- **验收**：ADR 文件存在 + deprecation note 编译通过
- **截止**：2026-07-10 22:00
- **状态**：🟡 IN_PROGRESS（已派活 xiaodou，accepted 18:07）
- **派活人**：大白（skill v1.3 规范）
- **skill_used（目标）**：humanizer, multi-search-engine

### XIAOQIAN-WEBAUTO-PHASE2-001 — T-059 锁机制重写 + T-011 apply_to_antidetect
- **任务来源**：TASKLIST.md T-059 + T-011
- **目标**：
  - T-059：`BrowserOrchestrator` per-profile lock，5账号真并发
  - T-011：`Profile.apply_to_antidetect` 同步7项字段
- **验收**：mock 测试证明真并发 + 7项字段单元测试全过
- **截止**：2026-07-10 18:00
- **状态**：✅ DONE
  - T-059: orchestrator per-profile lock → 38/38 测试全过（commit `dc2fa0a`）
  - T-011: apply_to_antidetect seed 同步 → 7项字段同步测试全过（commit `a4dd874`）
- **派活人**：大白（skill v1.3 规范，含 humanizer + multi-search-engine）
- **skill_used**：multi-search-engine, humanizer


### ❌ XIADOU-WEBAUTO-DOCS-001 — 撤回（2026-07-09 18:11）
- **撤回原因**：T-041/T-042 是技术活（ADR + deprecation note），不应派给文档 BA 小豆
- **处理**：大白撤回，改派小千

### XIAOQIAN-WEBAUTO-PHASE2-002 — T-041 ADR + T-042 deprecation（追加）
- **任务来源**：TASKLIST.md T-041 + T-042
- **目标**：ADR-003 迁移路径文档 + BrowserProfile deprecation note
- **截止**：2026-07-10 18:00（同 PHASE2-001）
- **状态**：✅ DONE（2026-07-10 23:30 大白补登）
  - **真实情况**：commit `fc14fbe`（小千 2026-07-09 18:19 已完成）
  - ADR-003-Profile-Migration.md（151 行）✅
  - Core/Profile/__init__.py 顶部 DeprecationWarning ✅
  - 之前 OVERDUE 标错因小千 session FAILED 大白忘记补登
  - Author 字段 ADR 里写"小豆"是历史混淆，实际由 Agent-小千提交

## 📋 2026-07-09 18:55 第四批派活

### XIAOQIAN-WEBAUTO-FINGERPRINT-003 — ProfileStore 持久化（CRUD+import/export）
- **任务来源**：TASKLIST.md T-003
- **目标**：Core/Profile/store.py + test_profile_store.py
- **验收**：CRUD 测试全过 + YAML roundtrip 一致
- **截止**：2026-07-10 18:00
- **状态**：🟡 IN_PROGRESS（小千接活）
- **skill**：multi-search-engine（查YAML最佳实践）+ humanizer（commit润色）

### XIADOU-WEBAUTO-T030-001 — README+STATUS 智谱章节更新
- **任务来源**：TASKLIST.md T-030
- **目标**：README 智谱快速开始 + STATUS.md 智谱进度表
- **验收**：文档结构清晰，有运行示例
- **截止**：2026-07-10 22:00
- **状态**：✅ DONE（2026-07-09 19:00）
  - README 智谱快速开始（Step 1-4 + 多账号）
  - STATUS.md 智谱进度跟踪表（Phase 2/3/4）
  - commit: 小豆本地 worklog/2026-07-10.md
- **skill**：multi-search-engine（查README结构）+ humanizer（润色）

## 📋 2026-07-09 21:05 第五批派活

### XIAOQIAN-WEBAUTO-T057 — browser_args + extensions 消费

- **任务**：将 browser_args 和 extensions 从 Profile 配置消费到 BrowserContext
- **状态**：✅ DONE（2026-07-09 21:05）
  - browser_args 注入 + 去重
  - extensions 传入 new_context
  - 6/6 测试全过，36 passed
  - commit: `2b563b7`
- **验收**：args 注入 chromium launch + extensions 加载 + 测试全过
- **截止**：2026-07-10 18:00
- **skill**：multi-search-engine（查 Playwright extensions）+ humanizer

### XIAOQIAN-WEBAUTO-T066 — Profile.ban() + archive()

- **任务**：Profile 增加 ban()（标记封禁）+ archive()（归档不删除）
- **状态**：✅ DONE（2026-07-09 21:35）
  - ban()/archive()/restore() 三方法 + 持久化
  - Pool release() 终态保护
  - 21/21 测试全过，44 passed
  - commit: `d059172`
- **验收**：ban 后 acquire 拒绝 + archive 后 list 不出现 + 恢复功能
- **截止**：2026-07-10 18:00
- **skill**：multi-search-engine（查 Playwright ban）+ humanizer

### XIAOQIAN-WEBAUTO-T009 — Examples 多账号抢购示例

- **任务**：Examples/ 目录写多账号抢购示例，3 Profile 并发
- **状态**：✅ DONE（2026-07-09 21:50）
  - example_multi_account_rushbuy.py（3账号/独立fingerprint/proxy/storage）
  - smoke test 11/11 全过
  - commit: `23baab1`

### XIAOQIAN-WEBAUTO-T012 — Playwright E2E orchestrator 测试

- **任务**：Playwright 真实浏览器 E2E 测试 orchestrator 多 Profile 隔离
- **状态**：✅ DONE（2026-07-09 22:05）
  - 7/7 E2E 用例全过（cookie/localStorage/Context 实例/fingerprint）
  - Bug 修复：new_context() 不支持 user_data_dir，改用内部 _profile_id
  - commit: `3eba23e`

### XIAOQIAN-WEBAUTO-T013 — Playwright E2E ProfilePool 测试

- **任务**：Playwright E2E 测试 ProfilePool 并发 acquire/release + 策略
- **状态**：✅ DONE（2026-07-09 22:10）
  - 11/11 E2E 全过（并发 acquire/release + 5 策略 + cooldown/timeout/banned）
  - Bug fix：new_context() 过滤 _profile_id + timeout 改用 asyncio.Event()
  - commit: `db63af8`

### XIAOCE-WEBAUTO-T045 — test_orchestrator.py 智谱5账号并发

- **任务**：Tests/test_orchestrator.py（3 Profile 隔离 + max_concurrent + 内存监控）
- **状态**：✅ DONE（2026-07-10 00:20）
  - 7/7 PASSED，连跑 3 次 21/21 全过，无 flaky
  - 环境修补：.venv-fix 补装 pytest + pytest-asyncio
  - commit: `b71b497`
- **截止**：2026-07-11 18:00
- **skill**：multi-search-engine + session-logs + humanizer

### XIAOCE-WEBAUTO-T046 — test_pool.py 智谱5账号并发

- **任务**：Tests/test_pool.py（并发 acquire/release + cooldown）
- **状态**：✅ DONE（2026-07-10 00:20）
  - 14/14 PASSED（基础借还 + cooldown + 5 策略 + 100 并发无死锁）
  - 3 次连跑 21/21 全过，无 flaky
  - commit: `b71b497`
- **截止**：2026-07-11 18:00
- **skill**：multi-search-engine + session-logs + humanizer
