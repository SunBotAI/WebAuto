# WebAuto TASKS v1.4（独立任务管理）

> **本文件是 WebAuto 项目唯一的任务状态记录。**
> **跟 ShopAuto 的 `ShopAuto/docs/agent/TASKS.md` 完全独立。**
> **不在本文件记录 ShopAuto 任务。**

---

## 📋 任务状态总览

| ID | 任务 | 责任人 | 状态 | 截止 | 验收标准 |
|----|------|--------|------|------|----------|
| XIAOQIAN-WEBAUTO-AUDIT-001 | 审计 ShopAuto TASKS 是否真有 webauto 任务 | 小千 | ✅ DONE | 2026-07-07 22:00 | audit 结论：ShopAuto 当前 TASKS.md 0 个 WEBAUTO 匹配，无需迁移 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-001 | Core/Profile/ 目录 + profile.py 数据类 | 小千 | 🚧 IN_PROGRESS | 2026-07-08 00:30 | Profile 数据类 YAML roundtrip 测试通过 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-002 | fingerprint_gen.py 指纹生成器 | 小千 | 🚧 IN_PROGRESS | 2026-07-08 00:30 | 同 seed 的 Canvas/WebGL/Audio 输出一致 + **统计一致性检查（7项关联）** |
| XIAOQIAN-WEBAUTO-FINGERPRINT-003 | store.py 本地持久化 CRUD+import/export | 小千 | ⏳ PENDING | 2026-07-08 00:30 | CRUD 单元测试通过 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-004 | orchestrator.py 浏览器编排器 | 小千 | ⏳ PENDING | 2026-07-08 00:30 | 3 个 Profile 创建隔离 BrowserContext + **max_concurrent + 内存监控** |
| XIAOQIAN-WEBAUTO-FINGERPRINT-005 | pool.py Profile 池（借/还/轮换） | 小千 | ⏳ PENDING | 2026-07-08 00:30 | 并发 acquire/release 100 次无死锁 + **cooldown 防风控** |
| XIAOQIAN-WEBAUTO-FINGERPRINT-006 | 整合 AntiDetect + BrowserProfile 到 Profile | 小千 | ⏳ PENDING | 2026-07-08 12:00 | profile.fingerprint.canvas_seed 影响 AntiDetect 噪声 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-007 | 集成测试 + Cookie 隔离验证 | 小千 | ⏳ PENDING | 2026-07-08 12:00 | 2 个 Profile Cookie 100% 隔离 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-008 | profile_manager.py CLI（增删改查 + warmup） | 小千 | ⏳ PENDING | 2026-07-08 12:00 | CLI 命令 list/create/delete/warmup 可用 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-009 | curl_cffi TLS 指纹升级 Core/Fetchers/http.py | 小千 | ⏳ P1 备选 | 待定 | HTTP 模式过 sannysoft 检测 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-010 | AntiDetect seed 强制同步测试 | 小千 | ⏳ P1 备选 | 待定 | profile.apply_to_anti_detect() seed == fingerprint.canvas_seed |
| XIAOQIAN-WEBAUTO-FINGERPRINT-011 | Spider checkpoint 暂停恢复 | 小千 | ⏳ P1 备选 | 待定 | Spider 中途 kill 重启能续跑 |

---

## 🚧 IN_PROGRESS

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| XIAOQIAN-WEBAUTO-FINGERPRINT-001 | Core/Profile/ 目录 + profile.py 数据类 | 🚧 IN_PROGRESS | 代码已 commit `15439d1`，待测试 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-002 | fingerprint_gen.py 指纹生成器 | 🚧 IN_PROGRESS | 代码已 commit `15439d1`，待测试 + 统计一致性验收 |

---

## ✅ DONE

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
- **状态**：⏳ P1 备选

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
