# WebAuto TASKS v1.5（独立任务管理）

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
| XIAOQIAN-WEBAUTO-FINGERPRINT-001 | Core/Profile/ 目录 + profile.py 数据类 | 小千 | ✅ DONE | 2026-07-09 17:55 | 56/56 测试全过 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-002 | fingerprint_gen.py 指纹生成器 | 小千 | ✅ DONE | 2026-07-09 17:55 | 14/14 statistical + 7/7 roundtrip |
| XIAOQIAN-WEBAUTO-FINGERPRINT-003 | store.py 本地持久化 CRUD+import/export | 小千 | ✅ DONE | 2026-07-09 18:55 | 20/20 测试 + YAML roundtrip |
| XIAOQIAN-WEBAUTO-FINGERPRINT-004 | orchestrator.py 浏览器编排器 | 小千 | ✅ DONE | 2026-07-09 19:10 | 38/38 测试全过 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-005 | pool.py Profile 池 | 小千 | ✅ DONE | 2026-07-09 19:35 | 14/14 测试 + cooldown + 5 策略 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-006 | 整合 AntiDetect + BrowserProfile 到 Profile | 小千 | ✅ DONE | 2026-07-09 19:50 | 50/50 测试 + 7项字段seed同步 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-007 | 集成测试 + Cookie 隔离验证 | 小千 | ✅ DONE | 2026-07-09 20:05 | 77/77 测试 + Cookie 隔离 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-008 | profile_manager.py CLI | 小千 | ✅ DONE | 2026-07-09 20:35 | 18/18 测试 + 6 命令 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-009 | curl_cffi TLS 指纹升级 | 小千 | ✅ DONE | 2026-07-10 15:50 | impersonate 池全通 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-010 | AntiDetect seed 强制同步测试 | 小千 | ✅ DONE | 2026-07-09 18:34 | seed 强制同步 + 7项字段同步 |
| XIAOQIAN-WEBAUTO-FINGERPRINT-011 | Spider checkpoint 暂停恢复 | 小千 | ✅ DONE | 2026-07-11 00:05 | 7/7 PASSED |
| XIAOCE-WEBAUTO-T045 | test_orchestrator.py 智谱5账号并发 | 小测 | ✅ DONE | 2026-07-11 18:00 | 7/7 PASSED |
| XIAOCE-WEBAUTO-T046 | test_pool.py 智谱5账号并发 | 小测 | ✅ DONE | 2026-07-11 18:00 | 14/14 PASSED |
| XIAOQIAN-WEBAUTO-T092 | profile_backend bulk_update_tags / bulk_set_status | 小千 | ✅ DONE | 2026-07-12 | 10个id一次性加tag，YAML原子写 |
| XIAOYUE-WEBAUTO-T094 | 合并 profile_panel+proxy_panel 入 webauto_web (7860) | 小月 | ✅ DONE | 2026-07-12 | 7860单端口所有功能 |
| XIAOYUE-WEBAUTO-T095 | 7860 Profile自动采集工作流 | 小月 | ✅ DONE | 2026-07-12 | 验证码后自动采集指纹 |
| XIAOYUE-WEBAUTO-T096 | 标准Profile配置模板 | 小月 | ✅ DONE | 2026-07-12 | 新建Profile可选模板一键填充 |
| XIAOQIAN-WEBAUTO-T097 | 代理池策略可视化配置 | 小千 | ✅ DONE | 2026-07-12 | Proxy Tab可配池策略+可视化状态 |
| **T-075'** | Tools/profile_web.py（单文件 http.server + 内嵌 HTML，~30行） | 小月 | ✅ DONE（commit 0c8e1bf）| 2026-07-13 | 浏览器打开 localhost:8000 看到账号列表 + 4 按钮 |
| **T-076'** | Tools/proxy_web.py（单文件 http.server + 内嵌 HTML，~30行） | 小月 | ✅ DONE（commit 0c8e1bf）| 2026-07-13 | 浏览器打开 localhost:8001 看到代理列表 + 健康状态 + 一键恢复按钮|
| **T-114** 🔥🔥 | 增强 webauto_web.py：把 console.py 完整版（618行）逻辑搬进 `_build_console_tab()`，7860 入口看到 4 Tab（Console完整版/凭证/Profile/Proxy） | 小月 | PENDING | 2026-07-13 | `python Tools/webauto_web.py` 启动 → localhost:7860 看到 4 Tab，Console Tab 有完整版抢购控制台 |
| **T-115** 🔥🔥 | 删除 6 个独立入口文件：console.py / credential_panel.py / profile_panel.py / proxy_panel.py / profile_web.py / proxy_web.py（后端不动） | 小月 | PENDING | 2026-07-13 | `ls Tools/*.py` 不再有这 6 个文件 |
| **T-116** 🔥🔥 | 验证端口唯一性：webauto_web.py 单独启动后 7860 能正常 listen | 小月 | PENDING | 2026-07-13 | `curl http://localhost:7860/` 返回 HTTP 200 |
| **T-117** 🔥🔥 | README.md 启动文档统一：只剩 `python Tools/webauto_web.py` 一个入口 | 小豆 | ✅ DONE（commit 695ca24）| 2026-07-13 | README 启动命令只有 1 行，指向 webauto_web.py 7860 |

---

## 🚧 IN_PROGRESS

（无）

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
- T-089 ✅ README MCP 章节 + docs/ 文档体系

### v1.6 测试收尾 — 小测
- T-088 ✅ test_mcp_server.py（40/40，commit 85a6c7b，大白兜底代 push）

### v1.7 合并+自动化 — 小千/小月
- T-092 ✅ profile_backend 批量操作（commit fca34c3）
- T-094 ✅ 合并三端口入 7860（commit dfb4ce6）
- T-095 ✅ Profile 自动采集工作流（commit 9106fb0）
- T-096 ✅ 标准配置模板（commit b632182）
- T-097 ✅ 代理池策略可视化（commit 67cd25c）

### v1.6.2 补做（发现漏项 2026-07-12）— 小千
- T-085 ✅ MCP pydantic 输入校验（commit 7f925d0，10 个 BaseModel）
- T-086 ✅ MCP 输出标准化三元组（commit 7f925d0，24 tools 全改完）

*所有 commit 均已 push 到 feat/webauto，skill_used 详见各 worklog*
