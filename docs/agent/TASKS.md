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
| XIAOQIAN-WEBAUTO-T092 | profile_backend bulk_update_tags / bulk_set_status | 小千 | 🟡 PENDING | 2026-07-16 | 10个id一次性加tag，YAML原子写 |
| XIAOYUE-WEBAUTO-T094 | 合并 profile_panel+proxy_panel 入 webauto_web (7860)，停7862/7863 | 小月 | 🟡 PENDING | 2026-07-16 | 7860单端口跑完所有功能 |
| XIAOYUE-WEBAUTO-T095 | 7860 Profile自动采集工作流（浏览器打开URL→输验证码→自动抓指纹入池）| 小月 | 🟡 PENDING | 2026-07-17 | 手动验证码后系统自动完成指纹采集 |
| XIAOYUE-WEBAUTO-T096 | 标准Profile配置模板（从测试提取有效配置为预设）| 小月 | 🟡 PENDING | 2026-07-17 | 新建Profile可选"标准模板"一键填充 |
| XIAOQIAN-WEBAUTO-T097 | 代理池策略可视化配置（geoip路由/失败切换/健康检测间隔）| 小千 | 🟡 PENDING | 2026-07-17 | 7860 Proxy Tab可配池策略+可视化状态 |

---

## 🚧 IN_PROGRESS（v1.7 合并+自动化）

| ID | 任务 | 责任人 | 状态 | 截止 |
|----|------|--------|------|------|
| T-092 | bulk_update_tags / bulk_set_status | 小千 | ✅ DONE（2026-07-11, commit fca34c3） | 2026-07-16 |
| T-094 | 合并三端口入7860 | 小月 | 🟡 PENDING | 2026-07-16 |
| T-095 | Profile自动采集工作流 | 小月 | 🟡 PENDING | 2026-07-17 |
| T-096 | 标准配置模板 | 小月 | 🟡 PENDING | 2026-07-17 |
| T-097 | 代理池策略可视化 | 小千 | 🟡 PENDING | 2026-07-17 |

---

## ✅ DONE（全量汇总）

### Fingerprint Browser 阶段（F-001~011）— 小千
- F-001~008 ✅ Core/Profile + orchestrator + pool + fingerprint_gen + store + CLI
- F-009 ✅ curl_cffi TLS 升级
- F-010/011 ✅ AntiDetect seed 同步 + Spider checkpoint

### Phase 3 P1 一锅端 — 小千
- T-014 ✅ Edg UA 移除 | T-010 ✅ Proxy 认证三元组 | T-063 ✅ warmup calibrate()
- T-022 ✅ 代理轮换 | T-023 ✅ geoip.py | T-064 ✅ Store 原子写 | T-068 ✅ 边界测试 | T-070 ✅ .gitignore

### 测试验收 — 小测
- T-045 ✅ test_orchestrator（7/7）| T-046 ✅ test_pool（14/14）| T-047 ✅ test_antidetect（13+3 skip）| T-053 ✅ E2E 隔离（6/6）| T-078 ✅ Gradio Client（28/28）

### v1.6 Web+MCP 后端 — 小千
- T-074 ✅ requirements.txt（mcp/pydantic）
- T-071 ✅ profile_backend.py（8 函数，20 tests）
- T-072 ✅ proxy_backend.py（CRUD+health，18 tests）
- T-073 ✅ service_registry.py（单例，16 tests）
- T-090 ✅ Pool set_strategy/max_concurrent 热切换
- T-091 ✅ Pool get_status() + Profile.uncooldown()
- T-093 ✅ lifecycle() 优雅退出（flush task）
- T-081 ✅ mcp_server.py（24 tools，FastMCP）
- T-087 ✅ MCP 双传输（stdio + http://7864）

### v1.6 Gradio 前端 — 小月
- T-075 ✅ profile_panel（7862，三 Tab）
- T-076 ✅ proxy_panel（7863，三 Tab）
- T-077 ✅ 统一导航（7860 四 Tab）

### v1.6 文档 — 小豆
- T-082 ✅ profile 8 tool schema | T-083 ✅ proxy 8 tool schema | T-084 ✅ pool 8 tool schema
- T-089 ✅ README MCP 章节 + docs/ 文档体系（ARCHITECTURE/MODULES/QUICKSTART）

### v1.6 测试收尾 — 小测
- T-088 ✅ test_mcp_server.py（40/40，commit 85a6c7b，大白兜底代 push）

### v1.7 合并+自动化（2026-07-12 新）— 小千/小月
- T-092 ⏳ profile_backend 批量操作（bulk_update_tags/set_status）
- T-094 ⏳ 合并三端口入 7860，停 7862/7863
- T-095 ⏳ Profile 自动采集工作流（浏览器→验证码→自动抓指纹）
- T-096 ⏳ 标准配置模板（从测试提取有效配置）
- T-097 ⏳ 代理池策略可视化配置

*所有 commit 均已 push 到 feat/webauto，skill_used 详见各 worklog*

