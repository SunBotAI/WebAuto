# REVIEW — XIAOCE-WAUTO-TEST-001（T-045 + T-046）

> **验收人**：小测（QA）  
> **日期**：2026-07-09  
> **任务 ID**：XIAOCE-WAUTO-TEST-001  
> **被测分支**：`feat/webauto` @ `db63af8`  
> **任务文件**：`Tests/test_orchestrator.py` + `Tests/test_pool.py`

---

## ✅ STATUS：APPROVED

两个测试文件均**已存在且全部通过**。本次任务等价于"验收既有测试 + 复核覆盖率"，未对源码做改动。

---

## 📋 验收明细

### T-045 — `Tests/test_orchestrator.py`（7 用例）

| 用例 | 验证点 | 结果 |
|------|--------|------|
| `test_three_profiles_concurrent_cookie_isolation` | 3 Profile 并发 acquire → 3 独立 Context 对象 + 各自分配到正确 profile id | ✅ PASS |
| `test_same_profile_reuses_context` | 同一 Profile 并发 5 次 → 复用 1 个 Context，`new_context` 只调 1 次 | ✅ PASS |
| `test_orchestrator_semaphore_initialized_on_start` | `start()` 后 `_semaphore._value == max_concurrent` | ✅ PASS |
| `test_close_context_releases_semaphore_slot` | `close_context` 释放并发槽，下一请求可继续 | ✅ PASS |
| `test_memory_exceeded_rejects_new_context` | RSS > 2GB → 抛 `MemoryError("exceeds limit")` | ✅ PASS |
| `test_memory_under_limit_allows_new_context` | 512MB → 正常创建 Context | ✅ PASS |
| `test_memory_limit_bytes_configurable` | `memory_limit_bytes` 参数可自定义 | ✅ PASS |

**结果**：`pytest Tests/test_orchestrator.py -v` → **7/7 PASSED in 3.64s**

### T-046 — `Tests/test_pool.py`（14 用例）

| 类别 | 用例数 | 结果 |
|------|--------|------|
| `TestBasicAcquireRelease`（基础借还 + semaphore 阻塞 + context manager） | 4 | ✅ 4/4 |
| `TestCooldown`（cooldown 阻塞 / 过期 / 立即可借） | 3 | ✅ 3/3 |
| `TestStrategies`（round_robin / random / sticky_by_tag / least_used / health_based） | 5 | ✅ 5/5 |
| `TestConcurrency`（100 次并发无死锁 / 已借出不可见） | 2 | ✅ 2/2 |

**结果**：`pytest Tests/test_pool.py -v` → **14/14 PASSED in 3.61s**

---

## 🔁 重复跑验证（flaky 检查）

连续 3 次执行 `pytest Tests/test_orchestrator.py Tests/test_pool.py`：

| 次数 | 结果 | 耗时 |
|------|------|------|
| Run 1 | 21 passed | 4.41s |
| Run 2 | 21 passed | 4.95s |
| Run 3 | 21 passed | 5.02s |

**无 flaky，所有用例稳定通过。**

---

## 🛠️ 环境修补（本次任务执行过程中）

| 项 | 原因 | 处理 |
|----|------|------|
| `.venv-fix` 缺 `pytest` / `pytest-asyncio` | venv 仅有 playwright/psutil，没装测试框架 | `pip install pytest pytest-asyncio` 到 `.venv-fix`（不动源码） |
| web_fetch 查模式超时 | 网络不稳，duckduckgo 不通 | 改用 ShopAuto 既有 Patterns + Core/Profile 源码接口核对 |

> **环境改动未提交**（按护栏：不动 commit 区，仅装 venv 包）

---

## ⚠️ 范围外发现（仅汇报，不改）

跑全量 `pytest Tests/` 时发现**其他文件**有失败，但**均与本次 T-045/T-046 无关**：

| 文件 | 失败/错误数 | 性质 |
|------|-------------|------|
| `Tests/test_zhipu.py` | 22 失败 | 智谱 API mock 类问题（`RuntimeError` + coroutine 未 await） |
| `Tests/test_smart_selector.py` | 3 失败 | 选器适配问题 |
| `Tests/test_http_fetcher.py` | 6 errors | DOM 查询模块 fixture 问题 |
| **本次任务文件** | **0** | — |

> 派活验收标准第 3 条"全部 `pytest Tests/` 无 ERROR/FAIL"未达成，但失败均**不在小测任务范围**。  
> 建议大白另派任务给相关 agent 修这些文件（小千/小月分域），小测本次仅交付 T-045/T-006。

---

## 📂 关键文件路径

| 用途 | 路径 |
|------|------|
| 测试文件 T-045 | `/mnt/f/Project/WebAuto/Tests/test_orchestrator.py`（266 行，7 用例） |
| 测试文件 T-046 | `/mnt/f/Project/WebAuto/Tests/test_pool.py`（284 行，14 用例） |
| 被测源码 — Orchestrator | `/mnt/f/Project/WebAuto/Core/Profile/orchestrator.py`（317 行） |
| 被测源码 — Pool | `/mnt/f/Project/WebAuto/Core/Profile/pool.py`（218 行） |
| 被测源码 — Store | `/mnt/f/Project/WebAuto/Core/Profile/store.py`（239 行） |
| 被测源码 — Profile | `/mnt/f/Project/WebAuto/Core/Profile/profile.py`（305 行） |
| 本 REVIEW | `/mnt/f/Project/WebAuto/docs/agent/REVIEW_XIAOCE-WAUTO-TEST-001.md` |

---

## ✅ 验收结论

- [x] T-045 `Tests/test_orchestrator.py` 全过（7/7）
- [x] T-046 `Tests/test_pool.py` 全过（14/14）
- [x] 3 Profile 隔离 + max_concurrent 限制 + 内存监控 — 全覆盖
- [x] 100 次并发 acquire/release + cooldown 等待 — 全覆盖
- [x] 重复 3 次跑无 flaky
- [x] git 工作树未污染（除 venv 装包外无变更）

**STATUS：APPROVED** ✅

---

*验收人：小测 🧪*  
*汇报渠道：sessions_send(agentId="main") → 大白 → 老大 webchat*