# WebAuto TaskList v1.6（完整任务列表）

> **本文件是 WebAuto 项目的完整任务列表（合并 TASKS v1.4 + ADR-002 Roadmap + 方案审查发现 + v1.6 Web/MCP 适配）。**
> **跟 TASKS.md 的关系**：TASKS.md 是"任务状态跟踪"（DONE / IN_PROGRESS / PENDING），本文件是"完整任务清单 + 估时 + 依赖"。
> **最后更新**：2026-07-11

---

## 🎯 项目当前目标

**智谱多账号套餐抢购**：5 个智谱账号在不同 IP + 不同浏览器指纹下，于 T 时刻（精确 NTP 同步）并发抢同一套餐，账号间 Cookie/Storage 完全隔离，风控账号自动 cooldown/banned。

---

## 任务统计

| 类别 | 数量 | 总估时 |
|------|------|--------|
| 🔥 **智谱优先**（多账号抢购核心闭环，跨 P0/P1 提升） | **29 项** | **~55 h** ≈ **9 工作日** |
| 🔴 P0 通用（非智谱相关，重要但不阻塞智谱） | 10 项 | ~19 h |
| 🟢 P1（非智谱相关） | 7 项 | ~35 h |
| 🔵 P2（3 个月，行为学习/健康监控/云同步） | 10 项 | ~76 h |
| 📊 文档/可观测性（含二轮审查 12 项补丁） | 16 项 | ~10 h |
| 🆕 **v1.6 精简版**（🔥 优先 9 项，老大调高） | **9 项** | **~16 h** ≈ **2 工作日** |
| 🟡 **v1.6 备选**（过度工程版，14 项，等 SaaS 时再做） | 14 项 | ~2 h（实际大部分已取消） |
| 🔥🔥 **v1.9 合并 Web 页面到 7860 单端口**（2026-07-12 老大指令，**优先级最高**） | **4 项** | **~4.5 h** ≈ **1 工作日** |
| 🆕 **v1.7 合并端口 + 自动采集**（2026-07-12，5 项） | **5 项** | **~15 h** ≈ **2 工作日** |
| ~~🔥🔥 v1.8 FastAPI 统一改造~~（2026-07-12 撤回，老大改主意） | ~~10 项~~ | ~~12h~~ |
| **合计** | **106 项** | **~272 h** |

**🔥 智谱优先工时 ~55h ≈ 9 个工作日**——完成这一块即可跑通 5 账号并发抢购 demo。

**🆕 v1.6 精简版 ~16h ≈ 2 工作日**——完成这一块即可让 Profile 池 + 代理池有"几个按钮的 web 页面"（用 **FastAPI** 单端口 7860）。**这是老大 7-12 拍板的统一方案**。

**🟡 v1.6 备选 ~2h ≈ 0.3 工作日**——保留作为 SaaS 化的参考实现，等真要做企业级配置平台时再启用（大部分已取消）。

**🔥🔥 v1.8 FastAPI 统一改造（撤回）**——老大 7-12 拍板"先不改 FastAPI"，改为 v1.9 "合并 Web 页面到 7860 单端口"（保留 Gradio + stdlib http.server 实现，只合并入口）。

**🔥🔥 v1.9 合并 Web 页面到 7860 ~4.5h ≈ 1 工作日**（**优先级最高，老大 7-12 拍板**）——保留现有 webauto_web.py 4 Tab，**把 console.py(7861) + profile_web.py(8000) + proxy_web.py(8001) 也合并进 7860**，作为所有 web 配置页面的唯一访问地址。端口从 7 个 → 2 个（7860 web + 7864 MCP）。

---

## 🔥 智谱优先（必做，阻塞"5 账号并发智谱抢购"目标）

> **已按"是否能跑通智谱抢购"重排**：跨 P0/P1 提升，所有智谱场景下需要的任务前置到这里。

### Phase 1 — Profile 数据底座（已完成，可直接复用）

| ID | 任务 | 来源 | 状态 | 验收 |
|----|------|------|------|------|
| **T-001** | `Core/Profile/profile.py` 数据类 | TASKS F-001 | ✅ DONE | YAML roundtrip 通过 |
| **T-002** | `fingerprint_gen.py` 指纹生成器 | TASKS F-002 | ✅ DONE | 同 seed 一致 + 7 项统计一致性 |
| **T-003** | `ProfileStore` 持久化 CRUD + import/export | TASKS F-003 | ✅ DONE | CRUD 单元测试通过（27/27 ✓） |

### Phase 2 — 智谱抢购核心闭环（必做）

| ID | 任务 | 智谱场景作用 | 估时 | 状态 | 依赖 |
|----|------|--------------|------|------|------|
| **T-014** | `fingerprint_gen.py` 移除 windows_chrome_120 模板里的 Edg UA（vendor 错配） | 智谱风控查 UA+vendor，Edg+Google Inc. 直接穿帮 | 15 min | ✅ DONE | T-002 |
| **T-010** | `NetworkConfig.get_playwright_proxy` 拆 username/password | 5 账号不同住宅代理，必须带认证 | 30 min | ✅ DONE | T-001 |
| **T-063** | `BrowserOrchestrator.warmup` `TimeSync.sync()` → `calibrate()`（dead code） | T-30s NTP 预热真生效 | 15 min | ✅ DONE | T-004 |
| **T-059** | `BrowserOrchestrator` 锁机制重写（per-profile lock） | 5 账号真并发启动，不是串行 | 2 h | ✅ DONE | T-004 |
| **T-011** | `Profile.apply_to_antidetect` 同步 7 项字段 | 智谱 zh-CN/Asia/Shanghai 一致，否则风控 | 2 h | ✅ DONE | T-006 |
| **T-006** | 整合 AntiDetect + BrowserProfile 到 Profile | canvas_seed 真的影响 AntiDetect 噪声 | 4 h | ✅ DONE | T-002/T-003/T-004 |
| **T-012** | `ProfilePool.cooldown` 真等待语义 | 风控后自动休息 30 分钟再借 | 1 h | ✅ DONE | T-005 |
| **T-013** | `BrowserOrchestrator` max_concurrent + 内存监控 | 5 并发不 OOM | 1.5 h | ✅ DONE | T-004 |
| **T-057** | 消费 `profile.browser_args` + `profile.extensions` | 智谱场景下 `--disable-blink-features` 等生效 | 2 h | ✅ DONE | T-004 |
| **T-007** | 集成测试 + Cookie 隔离验证 | 智谱 5 账号 Cookie 100% 隔离 | 4 h | ✅ DONE | T-004/T-005 |
| **T-008** | `profile_manager.py` CLI | 创建 5 个智谱 Profile（`webauto profile create`） | 4 h | ✅ DONE | T-001/T-003 |
| **T-009** | Examples 多账号抢购示例（智谱场景） | 智谱多账号跑的入口（`Examples/example_fingerprint_browser.py`） | 1 h | ✅ DONE | 全部 |
| **T-062** | 搬入 ADR §9 示例代码到 `Examples/example_fingerprint_browser.py` | 与 T-009 合并 | 1 h | ✅ DONE | — |
| **T-045** ⚡ | `Tests/test_orchestrator.py`（3 Profile 隔离 + max_concurrent + 内存监控） | 智谱 5 账号并发 BrowserContext 单测 | 4 h | ⏳ | T-004/T-013 |
| **T-046** ⚡ | `Tests/test_pool.py`（并发 100 次 acquire/release + cooldown 等待） | 智谱 5 账号借还池子单测 | 3 h | ⏳ | T-005/T-012 |

### Phase 3 — 智谱风控收尾（建议一起做）

| ID | 任务 | 智谱场景作用 | 估时 | 依赖 |
|----|------|--------------|------|------|
| **T-066** | `Profile.ban()` / `Profile.archive()` 方法 + 健康监控触发 | 智谱封号自动 BANNED | 2 h | ✅ DONE | T-005 |
| **T-064** | `Store.save` 原子写 + `Pool` 内存态 + 定期 flush | 智谱 100 借还/秒防 YAML 损坏 + IO 阻塞 | 3 h | T-003/T-005 |
| **T-022** ⚡ | 代理轮换（Profile-level 失败剔除） | 智谱多账号 × 多代理池（P1 提升） | 4 h | T-004 |
| **T-023** ⚡ | `geoip.py` IP 地理推断 + timezone 匹配 | 智谱账号按 IP 配 zh-CN/Asia/Shanghai（P1 提升） | 3 h | — |
| **T-028** ⚡ | AntiDetect seed 强制同步测试 | 智谱 sannysoft 60%+ 通过验收（P1 提升） | 2 h | ✅ DONE | T-011 |
| **T-068** | `test_profile_from_dict_edge_cases` | Profile 边界输入覆盖 | 1 h | ✅ DONE | — |
| **T-070** | `.gitignore` 加 `.pytest_cache/` + `.claude/` | 跨机器协同防误 commit | 15 min | ✅ DONE | — |

### Phase 4 — 智谱 P1 增强（提升抢购成功率）

| ID | 任务 | 智谱场景作用 | 估时 | 依赖 |
|----|------|--------------|------|------|
| **T-020** ⚡ | `curl_cffi` TLS 指纹（HTTP 模式过 sannysoft） | 智谱走 HTTP 模式必备 | 6 h | T-004 |
| **T-021** ⚡ | TLS 指纹池（chrome120/chrome124/firefox120） | 智谱 HTTP 模式指纹轮换 | 4 h | T-020 |
| **T-030** ⚡ | 文档更新（README + STATUS 智谱章节） | 用户看得到智谱 demo | 2 h | 全部 |
| **T-047** ⚡ | `Tests/test_antidetect_profile_sync.py`（apply_to_antidetect 同步 7 项 + canvas_hash 稳定） | 智谱场景下 AntiDetect 同步单测 | 4 h | T-011 |
| **T-053** ⚡ | 跨 Profile 隔离 E2E 测试（mock server / 真站二选一拍板 + 实施） | 智谱 5 账号 Cookie 端到端隔离测试 | 4 h | T-007 |

> ⚡ = 从 P0/P1 提升到"智谱优先"

**Phase 1~4 完成 = 23 项 + 6 项 P1 提升 = 智谱多账号抢购全栈能力**

### 🔥 修复顺序（按性价比 + 依赖）

```
T-014 (15m) → T-010 (30m) → T-063 (15m) → T-059 (2h) → T-011 (2h)
  → T-006 (4h) → T-008 (4h) → T-013 (1.5h) → T-057 (2h)
  → T-012 (1h) → T-066 (2h) → T-064 (3h) → T-068 (1h) → T-070 (15m)
  → T-045 (4h) → T-046 (3h) → T-047 (4h) → T-053 (4h)
  → T-007 (4h) → T-009/T-062 (2h)
  → [Phase 4] T-022 (4h) → T-023 (3h) → T-028 (2h)
  → [Phase 4] T-020 (6h) → T-021 (4h) → T-030 (2h)
```

**预计 9 个工作日完成智谱优先全栈（55h）**。

---

## 🔴 P0 通用（非智谱相关，重要但不阻塞智谱）

> 这些是 Profile 通用底座，智谱场景暂不需要，但跨业务（如抢茅台、小红书多账号）会用到。

| ID | 任务 | 估时 | 智谱场景 |
|----|------|------|----------|
| **T-004** | `BrowserOrchestrator` 编排器（基础版） | 8 h | 部分（Phase 2 已用其基础） |
| **T-005** | `ProfilePool` 池（基础版） | 4 h | 部分 |
| **T-015** | Chromium user-data 跨版本兼容 | 2 h | ❌ |
| **T-016** | `export/import` 测 `custom_scripts` 跨机器保留 | 30 min | ❌ |
| **T-017** | `pool.acquire` `timeout=None` 走默认 30s 的回归测试 | 20 min | ❌ |
| **T-018** | `apply_to_antidetect` 命名统一 | 5 min | ❌ |
| **T-019** | `FingerprintConfig` 默认 UA 改 windows_chrome_120 | 10 min | ❌ |
| **T-065** | `add_init_script` 顺序调整 | 30 min | ❌ |
| **T-069** | `_default_chromium` 加 Windows / macOS 路径分支 | 1 h | ❌（智谱在 WSL/Linux 跑） |
| **T-058** | Profile context LRU 淘汰 | 3 h | ❌（智谱 5 账号不需 LRU） |

---

## 🟢 P1（非智谱相关）

| ID | 任务 | 估时 | 备注 |
|----|------|------|------|
| **T-025** | Spider 引擎并发 Profile | 8 h | 智谱不爬商品 |
| **T-026** | Spider checkpoint 暂停恢复 | 4 h | 同上 |
| **T-027** | MCP 服务暴露 Profile 管理 | 4 h | 智谱用 CLI 足够 |
| **T-029** | 集成测试（100 商品 × 3 Profile） | 6 h | 智谱不爬 |
| **T-060** | 扩展加载机制 | 6 h | 智谱不需要扩展 |
| **T-067** | `_default_firefox()` | 3 h | 智谱只跑 Chromium |
| **T-024** | Humanizer 升级 Profile-aware | 4 h | 智谱用现有 HumanFetcher |

---

## 🔵 P2（3 个月，行为学习/健康监控/云同步）

| ID | 任务 | 估时 | 备注 |
|----|------|------|------|
| **T-031** | Profile 模板市场（10 种 OS+Browser） | 6 h | 现有 6 种够用 |
| **T-032** | 行为学习（真实浏览器录制→重放） | 12 h | 智谱不录制 |
| **T-033** | 验证码自适应（Profile 维度识别率统计） | 8 h | 智谱 OCR 已 DONE |
| **T-034** | Profile 健康监控（自动 cooldown） | 6 h | 智谱场景简化版（T-066 已部分覆盖） |
| **T-035** | 云同步 hook（S3/Dropbox） | 6 h | 智谱本地够 |
| **T-036** | Web UI（Gradio 面板） | 8 h | CLI 够 |
| **T-037** | Selenium/CDP 兼容 | 8 h | 智谱用 Playwright |
| **T-038** | 性能优化（Chromium 启动 < 2s） | 8 h | 智谱 5 账号可接受 |
| **T-039** | 文档站（MkDocs） | 6 h | — |
| **T-040** | `from_real_browser_json` 解析器 | 8 h | 智谱不需要 |

---

## 📊 文档/可观测性（含二轮审查 12 项补丁）

> 二轮审查 M-1~M-15 提议的 12 项补充任务（T-045~056 + 部分已在智谱优先），从对话补全入文档。

### 智谱相关文档项（已在智谱优先体现）

| ID | 任务 | 估时 |
|----|------|------|
| **T-041** | ADR 补"BrowserProfile → Profile 迁移路径" | 1 h |
| **T-042** | `Core/Profile/__init__.py` 顶部加 BrowserProfile deprecation note | 15 min |
| **T-043** | `ProfileStore.get_metrics()` 5 项指标（启动耗时/失败次数/隔离命中率/池等待/cooldown 命中） | 2 h |
| **T-044** | TASKS F-011 任务归属从 `Core/Profile/` 改到 `Core/Spider/` | 5 min（仅文档） |
| **T-054** | README 加合规说明（仅供技术研究 / 风险自负） | 30 min |

### 跨业务测试任务（二轮审查补充）

| ID | 任务 | 估时 | 备注 |
|----|------|------|------|
| **T-048** | `BrowserProfile` ↔ `Core/Profile/profile.py` 体系合并/废弃决策 + 迁移脚本 | 4 h | P0 通用 |
| **T-049** | 4 个 Fetcher（http/stealth/browser/human）迁移到 `Core/Profile` | 6 h | P0 通用 |
| **T-050** | 反检测引擎 fallback 切换层（Stealth / CloakBrowser / undetected） | 6 h | P1 |
| **T-051** | ADR §5.3 跨机器同步方案拍板（A/B/C 选一 + 实施） | 4 h | P1 |
| **T-052** | `FingerprintGenerator.mutate` 单元测试（keep_seed / not keep_seed 两路径） | 1 h | P0 测试 |
| **T-055** | 风险监控 task：Cookie 失效自动检测 + 依赖锁定 + CI | 4 h | P0 收尾 |

> T-045/046/047/053/068/070 已上移到"智谱优先"section。

---

## 🎯 智谱场景验收清单

完成"🔥 智谱优先"全部 29 项后能勾完：

- [ ] 5 个智谱账号 Profile 创建（CLI `webauto profile create`）
- [ ] 5 个独立代理（带 username/password 认证）
- [ ] 5 个 BrowserContext 真并发启动（不是串行）
- [ ] 5 个独立 user-data 目录，Cookie 100% 隔离
- [ ] 5 个独立指纹（Canvas hash byte-identical 跨重启）
- [ ] sannysoft 检测 60%+ 通过
- [ ] NTP 校时真生效（T-30s 预热）
- [ ] 风控账号自动 cooldown 30 分钟
- [ ] 多账号并发抢同一套餐 demo 跑通
- [ ] 智谱 HTTP 模式过 TLS 指纹检测（curl_cffi）
- [ ] 智谱 HTTP 模式指纹池（chrome120/chrome124/firefox120）
- [ ] `test_orchestrator.py` / `test_pool.py` / `test_antidetect_profile_sync.py` 三套单测全过
- [ ] 跨 Profile E2E 隔离测试通过

---

## 优先级判定原则（智谱目标版）

- **🔥 智谱优先不可砍**：智谱多账号抢购是当前唯一业务目标，所有相关任务前置
- **🔴 P0 通用**：智谱不直接用，但跨业务会用到（不做不阻塞当前目标）
- **🟢 P1**：通用增强，不阻塞智谱
- **🔵 P2**：3 个月以后再说

---

## 来源索引

- **TASKS v1.4**：XIAOQIAN-WEBAUTO-FINGERPRINT-001 ~ 011（11 个）
- **ADR-002 Roadmap**：P0 11 项 + P1 9 项 + P2 9 项（29 个，部分与 TASKS 重叠）
- **方案审查报告**（2026-07-09）：15 个问题，编号 #1 ~ #15
- **第二轮审查**（2026-07-09）：12 个补充项 M-1 ~ M-15（→ T-045/046/047/048/049/050/051/052/053/054/055/056）
- **第三轮审查**（2026-07-09）：7 项补充 M-16 ~ M-22
- **第四轮审查**（2026-07-09）：10 项 M-23 ~ M-33 + T-061 撤销
- **v1.4 重排**（2026-07-09）：🔥 智谱优先 section 重组（提升 T-022/T-023/T-028/T-030 到智谱 P1，T-070 上移到智谱收尾）
- **v1.5 补全**（2026-07-09）：补入二轮审查 12 项 → 72 项总任务

---

## 修订记录

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-09 | v1.0 | 初稿（44 项） |
| 2026-07-09 | v1.1 | 二轮审查讨论（56 项，但未写入文件） |
| 2026-07-09 | v1.2 | 三轮审查（52 项） |
| 2026-07-09 | v1.3 | 四轮审查 + T-061 撤销（60 项） |
| 2026-07-09 | v1.4 | 🔥 智谱优先重排（提升 T-022/T-023/T-028/T-030 + T-070） |
| 2026-07-09 | **v1.5** | **补全 12 项二轮审查任务**（T-045 ~ T-056）→ **72 项**完整 |
| 2026-07-11 | **v1.6** | **新增两块"Web 配置 + MCP 适配"任务（T-071 ~ T-089，共 19 项）** → **91 项**完整 |
| 2026-07-11 | **v1.6.1** | **标记优先**：🔥 8 项 / 🟢 7 项 / 🟡 4 项（老大指令："标记优先"） |
| 2026-07-11 | **v1.6.2** | **补漏 + 验证**：发现 4 项遗漏（Pool 热切换 / 状态查询 / 批量操作 / 生命周期管理），新增 T-090~T-093，🔥 8 → 11，🟢 7 → 8（老大指令："检查优先标记"） |
| 2026-07-11 | **v1.6** | **调整原表**：🔥 优先 11 项 → 🔥 精简版 9 项（~16h）。砍掉 MCP 24 tool + Gradio 三 Tab + 鉴权 + 审计 + 单端口导航 + 双传输，保留 backend + Pool 热切换/状态/批量/生命周期。T-075/T-076 从 Gradio 6h → 单文件 stdlib HTTP 1h（老大指令："python 本身就不用编译 web 页面为什么不能直接放执行按钮？"） |
| 2026-07-12 | **v1.8 撤回** | 老大 7-12 拍板"先不改 FastAPI"，改为"合并 web 页面保留为端口作为所有 web 配置页面访问地址"。FastAPI 路线作废，下面改为 v1.9 合并任务（仍在 TODO 状态，不开干） |
| 2026-07-12 | **v1.9** | **🔥🔥合并 Web 页面到 7860 单端口，优先级调为最高**：新增 T-114~T-117（4 项，~4.5h）。增强 webauto_web.py（搬 console.py 完整版进 Tab 1），删 6 个独立入口文件（console.py / credential_panel.py / profile_panel.py / proxy_panel.py / profile_web.py / proxy_web.py），解决 7860 端口冲突，更新 README 启动文档。端口 7 → 2（7860 + 7864）。**老大 7-12 拍板调整优先级**。|

---

## 🔥 v1.6 优先项（2026-07-11 老大指令："标记优先"）

> **老大原话（2026-07-11）**：
> - "标记优先。"
> - "检查一下啊任务有没有遗漏，优先标记这块的任务。"
> - "python 本身就不用编译 web 页面为什么不能直接放执行按钮？"
> - "工业级 saas，就是页面给点 console 执行指令？开玩笑吧?"
> - "不要重新写，要新增调整完善的 tasklist 继续并且调高优先级"
>
> **v1.6 调整思路**：原 v1.6 的 23 项（含 Gradio 面板 + MCP 24 tool + 鉴权 + 审计 + 单端口导航 + 双传输 = 过度工程化 SaaS 化）。按老大"几个按钮的页面"指示，**砍掉装饰层，保留功能层**：
> - ✅ **保留**：backend 抽离 + Pool 热切换/状态查询/批量/生命周期管理（真功能需求）
> - ❌ **砍掉**：MCP 整套协议（HTTP API 本身就是接口）/ Gradio 三 Tab（单文件 stdlib HTTP 就够）/ 鉴权审计（127.0.0.1 本地无需）/ 单端口导航（独立端口各自起）/ 双传输（HTTP 就是 HTTP）
> - 🔼 **简化**：T-075/T-076 最初 Gradio 6h → 7-11 改 stdlib http.server 1h → **7-12 改 FastAPI router 1h**（详见 v1.8，单端口 7860 统一）
>
> **调整后 = 9 项，~16h ≈ 2 工作日**（1 人即可，4 人并发 1 天）

### 🔍 v1.6 补漏审计（基于 ProfilePool 代码扫描）

> 老大要求"检查遗漏"——重读 `Core/Profile/pool.py` 后发现 **4 项遗漏**，都已并入精简版：

| # | 遗漏点 | 当前代码状态 | 补救 → ID |
|---|--------|--------------|-----------|
| 1 | **Pool 构造参数无法热切换** | `strategy` / `max_concurrent` 都是 `__init__` 参数，没有 setter | **T-090**（🔥） |
| 2 | **Pool 实时状态没有查询 API** | 只有 `_is_available()` / `_in_use` 私有 dict | **T-091**（🔥） |
| 3 | **Profile.cooldown 无法手动解除** | `cooldown_until` 只被动检测，没有 `uncooldown()` setter | 合并入 **T-091** |
| 4 | **没有批量启用/禁用 Profile** | 只有单条 create/delete | **T-092**（🔥） |
| 5 | **Pool `_flush_task` / lifecycle 没人管** | Web/MCP server 关闭时没人调 `pool.stop()` | **T-093**（🔥） |

### 🔥 优先 9 项（精简版——**老大调高优先级**）

> **7-12 更新**：T-075'/T-076' 路径由 v1.8 "FastAPI 单端口统一路由" **撤回**，改为 v1.9 "合并到 webauto_web.py 7860 单端口"（保留 Gradio 实现）。详见 v1.9。**老大指令："合并 web 页面保留为端口作为所有 web 配置页面访问地址"**。

| 顺序 | ID | 任务 | 估时 | 解锁什么 |
|------|----|------|------|---------|
| 1 | **T-071** | `Tools/profile_backend.py` 业务后端（list/get/create/update/delete/warmup/import/export） | 3 h | T-075'/T-092 |
| 2 | **T-072** | `Tools/proxy_backend.py` 业务后端（CRUD + health + 批量启用/禁用 + 失效剔除） | 4 h | T-076' |
| 3 | **T-073** | `Tools/service_registry.py` 共享单例（ProfileStore/Pool/ProxyStore/ProxyHealthStore） | 1 h | FastAPI 单进程共享 |
| 4 | **T-075'** | `Tools/profile_web.py`：合并进 `webauto_web.py` 7860 端口（v1.9 T-108，Gradio Tab 形式）。**保留 profile_backend.py 业务逻辑不动** | 1 h | **Profile 池 Web 配置完成** |
| 5 | **T-076'** | `Tools/proxy_web.py`：合并进 `webauto_web.py` 7860 端口（v1.9 T-109，Gradio Tab 形式）。**保留 proxy_backend.py 业务逻辑不动** | 1 h | **代理池 Web 配置完成** |
| 6 | **T-090** | Pool 增 `set_strategy()` / `set_max_concurrent()` 热切换 + 持久化到 `pool.yaml` | 2 h | Web 能改策略/并发 |
| 7 | **T-091** | Pool 增 `get_status()` + Profile 增 `uncooldown()`（profile_backend 暴露给前端） | 2 h | Web 能显示状态/手动解锁 |
| 8 | **T-092** | profile_backend 增 `bulk_update_tags()` / `bulk_set_status()`（支持一次改 50 个账号） | 1 h | Web 能批量操作 |
| 9 | **T-093** | ServiceRegistry 增 `lifecycle()` ctxmgr（退出自动 `pool.stop()` + `flush()`，防数据丢失） | 1 h | 退出不丢数据 |

**🔥 关键路径合计 ~16 h ≈ 2 工作日**（4 人并发 1 天：T-071/T-072/T-090/T-091 并行 → T-073+T-093 → T-075'/T-076' → T-092）

**完成标志**：
- `python Tools/webauto_web.py` 启动后浏览器打开 `localhost:7860`，看到 4~6 Tab（含 Console 完整版 + 凭证 + Profile + Proxy）
- 端口只剩 7860（Web 入口）+ 7864（MCP，独立）
- 删除 6 个独立入口文件：`console.py` / `credential_panel.py` / `profile_panel.py` / `proxy_panel.py` / `profile_web.py` / `proxy_web.py`（详见 v1.9 T-108~T-113）

### 🟡 备选 14 项（v1.6 过度工程版降级——等真要做 SaaS 时再做）

> **何时启用**：未来如果老大要做"多用户远程访问 + 权限分级 + 操作审计 + IDE/Claude 通过 MCP 调"，再回来做。
>
> **直接复用 v1.6 精简版**：T-071/T-072/T-073 backend 已经做完，前端换成 Gradio + MCP 时不用重写 backend。

| 顺序 | ID | 任务 | 估时 | 触发时机 |
|------|----|------|------|---------|
| 10 | **T-074** | `requirements.txt` 加 `mcp>=1.0,<2.0` + pydantic | 30 min | 真做 MCP 时 |
| 11 | **T-075** | ~~Gradio 面板~~ → **被 T-075' 替代**（v1.6 精简版够用） | — | — |
| 12 | **T-076** | ~~Gradio 面板~~ → **被 T-076' 替代** | — | — |
| 13 | **T-081** | ~~mcp_server.py 24 tool~~ → **取消**（HTTP API 本身就是接口） | — | — |
| 14 | **T-082/T-083/T-084** | ~~MCP 21 tool schema + 文档~~ → **取消**（Python 函数本来就有类型） | — | — |
| 15 | **T-085** | ~~MCP pydantic 输入校验~~ → **取消**（JSON 直接传） | — | — |
| 16 | **T-086** | ~~success/data/error 三元组输出标准化~~ → **取消** | — | — |
| 17 | **T-087** | ~~stdio/http 双传输~~ → **取消**（HTTP 就是 HTTP） | — | — |
| 18 | **T-088** | ~~test_mcp_server.py 25 用例~~ → **简化**为 test_profile_web.py（直接调函数） | 1 h | 写完 T-075' 后 |
| 19 | **T-077** | ~~单端口 4 Tab 导航~~ → **取消**（独立端口各自起） | — | — |
| 20 | **T-079** | ~~鉴权~~ → **取消**（127.0.0.1 本地无必要） | — | — |
| 21 | **T-080** | ~~审计日志~~ → **取消**（同上） | — | — |
| 22 | **T-078** | ~~test_web_panels.py 10 用例~~ → **取消**（test_profile_web.py 已覆盖） | — | — |
| 23 | **T-089** | ~~README MCP 集成章节~~ → **简化**为 README 一行 `python Tools/profile_web.py` | 30 min | 写完 T-075'/T-076' 后 |

**🟡 合计 ~2 h ≈ 15 分钟～1 小时**（真要做 SaaS 时启用，大部分已取消）

---


## 🆕 v1.6 任务明细（按 ID 顺序）

> 下面是 v1.6 的 19 项任务完整说明（保留原顺序，便于阅读）。优先标记见上节 🔥/🟢/🟡。

### Phase A — 公共底座（T-071 ~ T-074）

> **老大原话（2026-07-11）**："我发现账号池没有 web 页面可以配置，ip 代理池也是，给两块任务基于项目现状和任务列表完善一下所有能 web 配置调用，同步支持 mcpai 调用，先创建 tasklist。"
>
> **现状盘点**（基于代码扫描 2026-07-11）：
> | 模块 | CLI | Web | MCP |
> |------|-----|-----|-----|
> | 智谱抢购控制台（Tools/console.py） | ❌ | ✅ 7861 | ❌ |
> | 智谱凭证管理（Tools/credential_panel.py） | ❌ | ✅ 7860 | ❌ |
> | **Profile 池**（profile_manager.py + Core/Profile/） | ✅ Click 8 子命令 | ❌ **缺** | ❌ **缺** |
> | **代理池**（Core/ProxyPool/proxy.py + health.py） | ❌ **连 CLI 都没** | ❌ **缺** | ❌ **缺** |
> | Profile 池（运行时借/还） | ✅（Pool.acquire/release） | ❌ | ❌ |
>
> **目标**：
> 1. **Web 化**：把"配置"类操作（Profile / Proxy / Pool 策略）都暴露到 Gradio Web 面板，参考 `credential_panel.py` 的三 Tab 风格
> 2. **MCP 化**：同一套后端业务逻辑同时暴露为 MCP tools（FastMCP / mcpai 兼容），让 IDE / Claude / Cursor 能直接调
> 3. **复用**：先抽业务 backend（类似 `console_backend.py` / `credential_backend.py`），Web 和 MCP 都调它，不要双写

### 任务拆分（23 项，T-071 ~ T-093，含 v1.6.2 补漏 4 项）

#### Phase A — 公共底座（T-071 ~ T-074，4 项，先做）

| ID | 优先 | 任务 | 估时 | 依赖 | 验收 |
|----|------|------|------|------|------|
| **T-071** | 🔥 2 | `Tools/profile_backend.py` 业务后端：包 ProfileStore / Pool / ProxyStore，公开纯函数 `list / get / create / update / delete / warmup / import / export`（与 profile_manager.py 一致，但做成纯函数好让 Web / MCP 共用） | 3 h | — | 单测覆盖 8 个公开函数 |
| **T-072** | 🔥 3 | `Tools/proxy_backend.py` 业务后端：代理 CRUD + health 报表（ProxyHealthStore）+ 批量启用/禁用 + 失效剔除（连续失败 N 次自动 cooldown）。**这块连 CLI 都没有** | 4 h | — | 单测覆盖 CRUD + health 切换 |
| **T-073** | 🔥 4 | `Tools/service_registry.py` 共享服务注册中心：持有 ProfileStore / ProfilePool / ProxyStore / ProxyHealthStore 单例，给 Web（多 Tab）和 MCP（多 tool）共享同一份内存状态 | 2 h | T-071/T-072 | 注册/拿取单测 |
| **T-074** | 🔥 1 | `requirements.txt` 加 `mcp>=1.0,<2.0`（官方 MCP SDK）+ `pydantic>=2.5`（已锁 v2.13 兼容）+ 文档说明 mcpai 调用约定 | 30 min | — | pip install 干净，README 写一段 |

#### Phase B — Web 面板（T-075 ~ T-080，6 项）

| ID | 优先 | 任务 | 估时 | 依赖 | 验收 |
|----|------|------|------|------|------|
| **T-075** | 🔥 6 | `Tools/profile_panel.py` Gradio 面板：Tab 1 Profile 列表 + 创建/编辑/删除 + 指纹预览；Tab 2 借/还池子（手动模拟 acquire/release + 显示实时 `get_status()`）；Tab 3 导入/导出 JSON | 6 h | T-071/T-073/T-090/T-091 | 启动 `python -m Tools.profile_panel` 能开 7862 端口，三 Tab 都跑通 |
| **T-076** | 🔥 7 | `Tools/proxy_panel.py` Gradio 面板：Tab 1 代理列表 + 单条增删改 + 批量导入（粘贴 http://user:pass@host:port 一行一条）；Tab 2 健康面板（state 图标 + 失败次数 + 延迟 + 一键恢复 cooldown）；Tab 3 用法展示（自动生成 Playwright proxy 三元组示例） | 6 h | T-072/T-073 | 启动 7863 端口，三 Tab 跑通 |
| **T-077** | 🟢 18 | 把 `console.py` / `credential_panel.py` / `profile_panel.py` / `proxy_panel.py` 整合成统一导航：用 `gr.Tab` 顶层 Tab 或 iframe 嵌入，统一启动 `python Tools/webauto_web.py --port 7860` | 3 h | T-075/T-076 | 单端口 7860 四个 Tab 都能进 |
| **T-078** | 🟡 3 | Web 面板测试：`Tests/test_web_panels.py` — 模拟 Gradio Client 调用关键 endpoint（list/create/delete/warmup），不需要真起 gradio server | 4 h | T-075/T-076 | ≥10 用例通过 |
| **T-079** | 🟡 1 | Web 面板权限：环境变量 `WEBAUTO_WEB_AUTH_TOKEN`，启用后所有写操作（create/update/delete/warmup）要带 token；只读操作不要求 | 2 h | T-075/T-076 | 启用 token 后，无 token 的写请求 401 |
| **T-080** | 🟡 2 | Web 面板日志：在 Tools/logs/ 下写 web_audit.log（谁在什么时候改了哪个 profile/proxy），方便审计（依赖 T-079，否则审计可被绕过） | 2 h | T-075/T-076/T-079 | 改一次 profile 后日志出现一条记录 |

#### Phase C — MCP 适配（T-081 ~ T-089，9 项）

| ID | 优先 | 任务 | 估时 | 依赖 | 验收 |
|----|------|------|------|------|------|
| **T-081** | 🔥 10 | `Tools/mcp_server.py` MCP 服务入口：用 mcp SDK 注册 Profile / Proxy / Pool 三组 tools，每个 tool 直接调对应 backend（profile_backend / proxy_backend），不做业务逻辑 | 4 h | T-071/T-072/T-073/T-090/T-091/T-093 | `python Tools/mcp_server.py` 能起 stdio MCP server，Claude Desktop 配 mcp config 后能看到 21+ tools |
| **T-082** | 🟢 12 | MCP tools 清单（profile_backend 暴露 8 个）：`profile_list` / `profile_get` / `profile_create` / `profile_update` / `profile_delete` / `profile_warmup` / `profile_export` / `profile_import` | 2 h | T-081 | 8 tool schema 文档化 |
| **T-083** | 🟢 13 | MCP tools 清单（proxy_backend 暴露 8 个）：`proxy_list` / `proxy_get` / `proxy_create` / `proxy_update` / `proxy_delete` / `proxy_health_check` / `proxy_bulk_import` / `proxy_reset_health` | 2 h | T-081 | 8 tool schema 文档化 |
| **T-084** | 🟢 14 | MCP tools 清单（pool 暴露 **8** 个，v1.6.2 新增 3 个）：`pool_acquire` / `pool_release` / `pool_status` / `pool_ban` / `pool_cooldown` + `pool_set_strategy` / `pool_set_max_concurrent` / `pool_uncooldown_profile` | 3 h | T-081/T-090/T-091 | 8 tool schema 文档化 |
| **T-085** | 🟢 15 | MCP tool 输入校验：用 pydantic model 严格定义每个 tool 的 input schema（参数名 / 类型 / 必填 / 范围），错误输入返回结构化错误（不是 500） | 3 h | T-082/T-083/T-084 | 错误输入示例：缺字段返回清晰错误 |
| **T-086** | 🟢 16 | MCP tool 输出标准化：所有 tool 返回 `{"success": bool, "data": ..., "error": str|None}` 三元组，方便 LLM 解析 | 1 h | T-082/T-083/T-084 | 成功 / 失败两条路径都对 |
| **T-087** | 🔥 11 | `Tools/mcp_server.py` 双传输模式：`--transport stdio`（默认，给 Claude Desktop）+ `--transport http --port 7864`（HTTP，给 mcpai / 自建 client） | 2 h | T-081 | stdio + http 都跑通 |
| **T-088** | 🟢 17 | MCP 服务测试：`Tests/test_mcp_server.py` — 用 `mcp.ClientSession` 起 in-memory transport，调每个 tool 验证返回；错误路径也要测（覆盖 21+ tools） | 4 h | T-081~T-087 | ≥25 用例通过 |
| **T-089** | 🟡 4 | README 新增"MCP 集成"章节：Claude Desktop / Cursor 配 mcp.json 示例 + 截图位置 + 21+ tools 一览表 | 2 h | T-081~T-087 | README 渲染正确，截图齐全 |

#### Phase D — 运行时控制增强（v1.6.2 补漏，T-090 ~ T-093，4 项）

> 老大指令："检查一下啊任务有没有遗漏" → 重读 ProfilePool 代码后发现 Pool 构造参数无 setter、状态无查询、生命周期无人管理、批量操作缺失。新增 4 项任务补上这些洞。

| ID | 优先 | 任务 | 估时 | 依赖 | 验收 |
|----|------|------|------|------|------|
| **T-090** | 🔥 8 | **Pool 热切换**：在 `Core/Profile/pool.py` 增 `set_strategy()` / `set_max_concurrent()` 方法 + 持久化到 `~/.cache/webauto/pool.yaml`（启动时读 / 改时写）。Semaphore 重建要线程安全（用 `asyncio.Lock` 串行） | 2 h | — | 单测：set 后 list_all 后下一次 acquire 用新策略；改并发数生效 |
| **T-091** | 🔥 9 | **Pool 状态查询 + Profile 手动解锁**：Pool 增 `get_status()` 返回 `{total, ready, running, cooldown, banned, in_use_ids, current_strategy, max_concurrent, acquire_wait_count}`；Profile 增 `uncooldown()` 把 `cooldown_until=None` 并 status 改 READY。profile_backend 暴露 `get_pool_status()` / `uncooldown_profile(id)` | 2 h | — | 单测：5 个 profile 借出 2 个后 get_status() 正确反映；uncooldown 后立即可借 |
| **T-092** | 🟢 19 | **批量操作**：profile_backend 增 `bulk_update_tags(ids, add_tags=[], remove_tags=[])` / `bulk_set_status(ids, status)`，MCP 暴露 `profile_bulk_update` tool（一次改 50 个账号） | 2 h | T-071/T-081 | 单测：传 10 个 id 一次性加 tag，YAML 原子写 |
| **T-093** | 🔥 5 | **生命周期管理**：ServiceRegistry 增 `@asynccontextmanager async def lifecycle()`，进入时建 Pool + 启动 flush task，退出时 `await pool.stop()` + `await pool.flush()`。Web / MCP server 启动 / 关闭时用此 ctxmgr | 1 h | T-073 | 单测：with lifecycle() 退出后 flush task done、YAML 已落盘 |

### 修复顺序（v1.6.2 修订版依赖图）

```
T-074 (30m,装依赖)
  ├→ T-071 (3h,profile backend) ─┐
  ├→ T-072 (4h,proxy backend) ──┤
  └→ T-090 (2h,Pool 热切换) ─────┼→ T-073 (2h,服务注册)
      T-091 (2h,Pool 状态查询) ───┤
                                  ↓
                            T-093 (1h,生命周期管理)
                                  ├→ T-075 (6h,profile 面板,T-090/T-091 必须在 T-075 前完成)
                                  ├→ T-076 (6h,proxy 面板)
                                  ├→ T-081 (4h,mcp 入口,依赖 T-090/T-091/T-093)
                                  ├→ T-087 (2h,双传输)
                                  └→ T-077 (3h,统一导航,依赖 T-075/T-076)
T-082/T-083/T-084 (各 2~3h,tools 清单,T-084 依赖 T-090/T-091)
  ├→ T-085 (3h,输入校验)
  ├→ T-086 (1h,输出标准化)
  └→ T-088 (4h,mcp 测试 ≥25 用例)

🟡 收尾(可跳):
  T-079 (2h,鉴权) → T-080 (2h,审计,依赖 T-079)
  T-078 (4h,面板测试)
  T-089 (2h,文档)
  T-092 (2h,批量操作,可与 T-082~T-088 并行)
```

**🔥 关键路径合计 ~32.5h ≈ 5 工作日**（4 人并发：T-071/T-072/T-074/T-090/T-091 并行 → T-073+T-093 → T-075/T-076/T-081/T-092 并行 → T-087/T-088 → T-077/T-079/T-080/T-089）。

**全 23 项总工时 ~62h ≈ 8 工作日**。

### 验收清单（v1.6.2 完成后能勾完）

- [ ] `python Tools/profile_panel.py` 启动 7862 端口，三 Tab 全跑通
- [ ] `python Tools/proxy_panel.py` 启动 7863 端口，三 Tab 全跑通
- [ ] `python Tools/webauto_web.py --port 7860` 单端口四 Tab（智谱抢购 / 凭证 / Profile / Proxy）
- [ ] **v1.6.2** Web 面板能切换"借出策略"（random / round_robin / least_used / health_based / sticky）+ 改并发数
- [ ] **v1.6.2** Web 面板顶部实时显示池状态：`5 RUNNING / 2 COOLDOWN / 1 BANNED`
- [ ] **v1.6.2** 风控误判账号能通过 Web 面板手动 uncooldown
- [ ] **v1.6.2** 50 个账号能批量加 tag（`profile_bulk_update` tool / Web 复选框）
- [ ] **v1.6.2** Web/MCP server 优雅退出（lifecycle ctxmgr，flush task 干净停）
- [ ] 启用 `WEBAUTO_WEB_AUTH_TOKEN` 后写操作鉴权生效（🟡 T-079）
- [ ] `python Tools/mcp_server.py` stdio 模式跑通，Claude Desktop 配置后能看到 **24 个 tools**（v1.6.2: 8 + 8 + 8）
- [ ] HTTP 模式 `python Tools/mcp_server.py --transport http --port 7864` 跑通
- [ ] `pytest Tests/test_web_panels.py Tests/test_mcp_server.py` 全过
- [ ] README 写 MCP 集成章节（配 mcp.json 示例）

### 与既有任务的关系

- **T-027**（P1 "MCP 服务暴露 Profile 管理"，4h）→ 合并入 T-081/T-082，估时复用
- **T-036**（P2 "Web UI Gradio 面板"，8h）→ 拆成 T-075 + T-076 + T-077，估时复用
- **T-051**（P1 "ADR §5.3 跨机器同步方案"）→ 与 v1.6 无冲突，独立推进
- **T-051 不阻塞**——v1.6 的 Web/MCP 主要服务单机本地，云同步是另一个维度

### 风险与回退

- **风险 1**：gradio 6.x + mcp SDK 1.x 是否兼容（mcp SDK 当前未在 requirements）→ T-074 装完后先做一次最小集成测试
- **风险 2**：MCP HTTP 传输与现有 console.py / credential_panel.py 端口冲突 → T-087 默认 7864 避开 7860/7861/7862/7863
- **风险 3（v1.6.2 新）**：T-090 重建 Semaphore 时如果有 in-flight acquire 会死锁 → 必须 `await pool.flush()` + 等待 `_in_use` 空才能换并发数；先实现 set_strategy（只换 self.strategy 不动 Semaphore），set_max_concurrent 加显式 `flush_and_wait` 开关
- **风险 4（v1.6.2 新）**：T-093 lifecycle ctxmgr 异常路径（at_exit / KeyboardInterrupt）→ 用 `try/finally` 包 `pool.stop()`，MCP stdio 模式监听 SIGTERM
- **回退**：T-081 ~ T-093 均为新增（不动 Core/Profile/profile.py / pool.py，只在 pool.py 末尾追加方法），失败 git revert HEAD 不影响生产路径

### 优先级判定（v1.6 修订——**老大调高精简版优先级**）

> 详见 v1.6 优先项段（行 250）的两张表：
> - 🔥 **优先 9 项**（精简版，老大推荐先做）
> - 🟡 **备选 14 项**（过度工程版，等 SaaS 需求时再做，大部分已取消）

#### 🔥 精简版 9 项总结

- T-071/T-072/T-073：backend 业务抽离
- T-075'/T-076'：单文件 Python HTTP + 内嵌 HTML（替代原 Gradio）
- T-090/T-091/T-093：Pool 热切换 + 状态查询 + lifecycle
- T-092：批量操作

#### 🟡 备选 14 项汇总

- 11 项原 🔥 必做：T-074（装 mcp）/ T-075/T-076（Gradio）/ T-077/T-081/T-087（MCP 入口 + 双传输 + 单端口）
- 8 项原 🟢 二轮：T-077/T-082~T-086/T-088/T-092（MCP 21 tool + schema + 校验 + 输出标准化 + 测试）
- 4 项原 🟡 收尾：T-079/T-080/T-078/T-089（鉴权 / 审计 / Web 测试 / README MCP 章节）

#### 何时启用备选

- 多用户远程访问（非 127.0.0.1）
- 权限分级（不同用户不同账号）
- 操作审计（谁什么时候改了什么）
- 让 IDE / Claude / Cursor 通过 MCP 协议直接调（不走 HTTP）

#### 复用关系

v1.6 精简版 backend（T-071/T-072/T-073）= v1.6 备选的 backend。差异只在"前端用啥"：精简版 stdlib HTTP / 备选 Gradio + MCP。

---

### v1.6.3 — 实际完成状态（2026-07-11 23:38 汇总）

**22 ✅ DONE / 1 ⏳ T-092 漏做 / 1 🟡 T-088 大白兜底 commit**

| ID | 任务 | 状态 | 备注 |
|----|------|------|------|
| T-071 | profile_backend.py（8 函数，20 tests）| ✅ | commit 42287f3 |
| T-072 | proxy_backend.py（CRUD+health，18 tests）| ✅ | commit 42287f3 |
| T-073 | service_registry.py（单例，16 tests）| ✅ | commit 29b1448 |
| T-074 | requirements.txt（mcp/pydantic）| ✅ | commit 42287f3 |
| T-075 | profile_panel 7862（三 Tab）| ✅ | commit 0066c80 |
| T-076 | proxy_panel 7863（三 Tab）| ✅ | commit 0066c80 |
| T-077 | webauto_web 7860（四 Tab 导航）| ✅ | commit 0066c80 |
| T-078 | test_web_panels.py（28/28 PASS）| ✅ | commit bdb5e20 |
| T-081 | mcp_server.py（24 tools）| ✅ | commit 8d07361 |
| T-082 | MCP profile 8 tool schema 文档 | ✅ | commit a7d5682 |
| T-083 | MCP proxy 8 tool schema 文档 | ✅ | commit a7d5682 |
| T-084 | MCP pool 8 tool schema 文档 | ✅ | commit a7d5682 |
| T-087 | MCP 双传输（stdio + http://7864）| ✅ | commit 8d07361 |
| T-088 | test_mcp_server.py（40/40 PASS）| ✅ 🟡 | commit 85a6c7b（**大白兜底代 commit**，小测 session exec 通道死锁）|
| T-089 | README MCP 章节 + docs/ 文档体系 | ✅ | commit 3e0df7f |
| T-090 | Pool set_strategy/max_concurrent 热切换 | ✅ | commit 42287f3 |
| T-091 | Pool get_status() + Profile.uncooldown() | ✅ | commit 42287f3 |
| T-093 | lifecycle() 优雅退出（3 tests）| ✅ | commit 29b1448 |
| T-047 | test_antidetect_profile_sync.py（13+3 skip）| ✅ | commit 7bc7929 |
| T-053 | test_profile_isolation_e2e.py（6/6 PASS）| ✅ | commit 7bc7929 |
| T-022 | 代理轮换（38 tests）| ✅ | commit f271338 |
| T-023 | geoip.py IP 地理推断 | ✅ | commit f271338 |
| T-064 | Store.save 原子写 | ✅ | commit 1095899 |
| T-068 | 边界测试（35 tests）| ✅ | commit c55b60c |
| T-070 | .gitignore 补充 | ✅ | commit c55b60c |
| **T-092** | **bulk_update_tags / bulk_set_status** | **⏳ 未做** | **漏项，profile_backend 批量操作未实现** |

**大白兜底记录**：T-088 小测 session exec 通道死锁（pytest 进程残留导致），大白 23:38 代为 `pytest 40/40 PASS` + `git commit` + `git push`，commit 含"操作人: 小测 / 工具: 大白代 commit"footer。

### v1.7 — 合并端口 + 自动化采集（2026-07-12 新）

**背景**：老大反馈现有 7860/7862/7863 三端口割裂，Profile/Proxy 面板各自独立，操作路径不连贯。目标：单一 7860 入口 + 自动采集 + 标准模板 + 代理池可视化。

| ID | 任务 | 估时 | 依赖 | 验收标准 |
|----|------|------|------|----------|
| T-092 | profile_backend 增 `bulk_update_tags()` / `bulk_set_status()` | 2h | T-071 | 单测：10 个 id 一次性加 tag，YAML 原子写 |
| **T-094** 🔥 ✅ | ~~合并 profile_panel.py + proxy_panel.py 入 webauto_web.py (7860)，停 7862/7863~~ → **已完成（commit dfb4ce6，已停7862/7863进程）** | 3h | T-075/T-076 | ✅ |
| **T-095** 🔥 ✅ | ~~7860 新增 Profile 自动采集工作流~~ → **已完成（commit 9106fb0，Core/Profile/fingerprint_collector.py）** | 6h | T-094 | ✅ |
| **T-096** ✅ | ~~标准 Profile 配置模板~~ → **已完成（commit b632182，模板A/B）** | 2h | T-095 | ✅ |
| **T-097** ✅ | ~~代理池策略可视化配置~~ → **已完成（commit 67cd25c，geoip路由+健康检测+可视化Tab5）** | 4h | T-076 | ✅ |

**冲突检测**：
- T-095 自动采集依赖 Playwright 浏览器控制，与 T-022/T-023 proxy_rotator 共享 Playwright 实例，需避免端口冲突
- T-096 模板数据从 Tests/test_antidetect_profile_sync.py 提取，确保 UA/Canvas/TLS 组合仍然有效

**负责人**：[T-094/T-095/T-096 → 小月] / [T-092/T-097 → 小千]

---

### 🔥🔥 v1.9 — 合并 Web 页面到 7860 单端口（2026-07-12 老大指令，**优先级最高**）

**老大指令原话**：
> "哪算了，先不改了；只合并 web 页面保留为端口作为所有 web 配置页面访问地址。"

**目标**：用户**只访问一个地址** `http://localhost:7860`，就能看到所有 web 配置页面（账号池 / 代理池 / 凭证 / 抢购控制台）。其它端口全部废弃。

**当前 7 个端口 / 8 个文件现状**：

| 端口 | 文件 | 行数 | 实现 | 实际状态 |
|------|------|------|------|---------|
| **7860** | `webauto_web.py` | 335 | Gradio 4 Tab（Console + 凭证 + Profile + Proxy）| ✅ 已经是统一入口 |
| **7860** | `credential_panel.py` | 417 | Gradio 单页 | ❌ 跟 webauto_web 端口冲突，**已被 inlined 进 webauto_web**（独立文件可删） |
| **7861** | `console.py` | 618 | Gradio 完整版抢购（多账号 + 套餐 + 倒计时） | 独立，需合并 |
| **7862** | `profile_panel.py` | 592 | Gradio 单 Profile 面板 | v1.7 T-094 说已停，**代码仍在**（独立文件可删） |
| **7863** | `proxy_panel.py` | 623 | Gradio 单 Proxy 面板 | v1.7 T-094 说已停，**代码仍在**（独立文件可删） |
| **7864** | `mcp_server.py` | 872 | MCP 24 tool | ⚠️ `mcp` 包未装 → 不能跑（独立保留）|
| **8000** | `profile_web.py` | 280 | stdlib http.server | v1.6 精简版产物，**功能已被 profile_tab.py 覆盖**（独立文件可删） |
| **8001** | `proxy_web.py` | 307 | stdlib http.server | v1.6 精简版产物，**功能已被 proxy_panel_tab.py 覆盖**（独立文件可删） |

### 📦 v1.9 文件归属表（彻底明确）

| 文件 | 处理 | 归属 TASK |
|------|------|-----------|
| `Tools/webauto_web.py` | **保留并增强**（增 Tab）| T-114 增强 |
| `Tools/profile_tab.py` | **保留**（788 行，被 webauto_web import）| T-114 增强 |
| `Tools/proxy_panel_tab.py` | **保留**（700 行，被 webauto_web import）| T-114 增强 |
| `Tools/console_backend.py` | **保留**（业务后端）| 不动 |
| `Tools/credential_backend.py` | **保留**（业务后端）| 不动 |
| `Tools/profile_backend.py` | **保留**（业务后端，T-071/T-090/T-091 已 DONE）| 不动 |
| `Tools/proxy_backend.py` | **保留**（业务后端，T-072/T-097 已 DONE）| 不动 |
| `Tools/service_registry.py` | **保留**（T-073/T-093 已 DONE）| 不动 |
| `Tools/mcp_server.py` | **保留**（MCP 服务，独立端口 7864）| T-105 保留 |
| `Tools/console.py` | ❌ **删除**（618 行 Gradio 完整版 → 逻辑已搬到 webauto_web Console Tab）| T-115 |
| `Tools/credential_panel.py` | ❌ **删除**（417 行 Gradio → 已被 inlined 进 webauto_web 凭证 Tab）| T-115 |
| `Tools/profile_panel.py` | ❌ **删除**（592 行 Gradio → 已被 webauto_web Profile Tab 替代）| T-115 |
| `Tools/proxy_panel.py` | ❌ **删除**（623 行 Gradio → 已被 webauto_web Proxy Tab 替代）| T-115 |
| `Tools/profile_web.py` | ❌ **删除**（280 行 stdlib HTTP → 功能已被 profile_tab.py 覆盖）| T-115 |
| `Tools/proxy_web.py` | ❌ **删除**（307 行 stdlib HTTP → 功能已被 proxy_panel_tab.py 覆盖）| T-115 |

### 🟡 v1.9 任务清单（4 项，~4.5 h）—— **🔥🔥 优先级最高（老大 7-12 拍板）**

| ID | 优先级 | 任务 | 估时 | 依赖 | 验收 |
|----|--------|------|------|------|------|
| **T-114** | 🔥🔥 | **增强 `Tools/webauto_web.py`**：把 `Tools/console.py`（618 行）的完整版抢购控制台逻辑（多账号 + 套餐 + 倒计时 + 开始抢）搬到 webauto_web 现有的 `_build_console_tab()` 简化版，替换为完整版。**确保 7860 入口打开后看到 4 个 Tab：Console（完整版）/ 凭证 / Profile / Proxy**，所有功能可用 | 2 h | T-071/T-072 已 DONE | `python Tools/webauto_web.py` 启动 → `localhost:7860` 看到 4 Tab，Console Tab 有完整版抢购控制台 |
| **T-115** | 🔥🔥 | **删除 6 个独立入口文件**：`Tools/console.py` `Tools/credential_panel.py` `Tools/profile_panel.py` `Tools/proxy_panel.py` `Tools/profile_web.py` `Tools/proxy_web.py`（业务后端不动）| 15 min | T-114 | `ls Tools/*.py` 不再有这 6 个文件 |
| **T-116** | 🔥🔥 | **验证端口唯一性**：`Tools/webauto_web.py` 单独启动后，7860 能正常 listen（之前 `credential_panel.py` 抢同一端口已删，没竞争者） | 15 min | T-115 | `python Tools/webauto_web.py` 启动后 `curl http://localhost:7860/` 返回 HTTP 200 |
| **T-117** | 🔥🔥 | **README.md 启动文档统一**：把"启动 `Tools/credential_panel.py` → localhost:7860"改成"启动 `Tools/webauto_web.py` → localhost:7860"，把其它 4 个独立入口的启动方式（`console.py` 7861 / `profile_panel.py` 7862 / `proxy_panel.py` 7863 / `profile_web.py` 8000 / `proxy_web.py` 8001）全部删掉或改为"已合并到 7860" | 30 min | T-115 | README 启动命令只剩 1 行：`python Tools/webauto_web.py` |

**🟡 总估时 ~3 h ≈ 0.5 工作日**（1 人即可）

### 完成标志

- `python Tools/webauto_web.py` 启动后，浏览器打开 `http://localhost:7860` 看到 4 Tab：
  - **Tab 1 Console**：完整版抢购控制台（账号 + 套餐 + 倒计时 + 开始抢，从 console.py 搬来）
  - **Tab 2 凭证**：token 粘贴 + SMS 登录 + 账号列表（已 inlined）
  - **Tab 3 Profile**：账号池 + 4 按钮（profile_tab.py 788 行）
  - **Tab 4 Proxy**：代理池 + 健康状态 + 一键恢复（proxy_panel_tab.py 700 行）
- 端口只剩 **2 个**：7860（Web 入口）+ 7864（MCP，独立）
- README 启动命令只剩 1 行
- 删除 6 个文件：`console.py` / `credential_panel.py` / `profile_panel.py` / `proxy_panel.py` / `profile_web.py` / `proxy_web.py`

### v1.8 FastAPI 改造的处置

- v1.8 整段（T-098~T-107）**作废**，保留作为历史记录
- 老大 7-12 拍板："先不改 FastAPI"
- 未来如果真要做 FastAPI，再起一个 v2.x 任务

### v1.9 文档同步清单（同步要做）

v1.9 T-117 之外，TASKLIST.md 里**还有 7 处文档需要同步**：

| 文档 | 现状 | v1.9 后改 |
|------|------|---------|
| `README.md:533-554` | "凭证管理面板(Gradio) → 启动 `Tools/credential_panel.py` → localhost:7860" | 改成"启动 `Tools/webauto_web.py` → localhost:7860" |
| `docs/reports/console_frontend_audit_2026-07-10.md:35` | "前端: `Tools/console.py`(单页 Gradio 7861)+ `Tools/credential_panel.py`(凭证 7860)" | 改成"前端: `Tools/webauto_web.py`（Gradio 7860 单端口 4 Tab）" |
| `docs/reports/console_frontend_audit_2026-07-10.md:40-41` | `.venv/bin/python Tools/console.py --port 7861` | 改成 `Tools/webauto_web.py` |
| `docs/decisions/002-fingerprint-browser-integration/06-实现-Roadmap.md:47` | "27 \| Web UI (Gradio 面板) \| 8h" | 改成 "Web UI (Gradio `Tools/webauto_web.py` 7860)" |
| `docs/decisions/002-fingerprint-browser-integration.md` | 引用 "Gradio 面板" | 加注 "v1.9 已合并到 webauto_web.py 7860 单端口" |
| `STATUS.md` | **整个文件已被删除** | 重建 STATUS.md v2.5 |
| `docs/agent/TASKS.md` | v1.4 顶部任务状态表停在 2026-07-08 | 加 v1.6/v1.7/v1.8/v1.9 任务状态段 |

### v1.9 完整任务（含文档同步）

实际要做的事：

```
T-114  增强 webauto_web.py（搬 console.py 完整版进 Tab 1）       2 h
T-115  删除 6 个独立入口文件                                    15 min
T-116  验证端口唯一性                                          15 min
T-117  README.md 启动文档统一                                  30 min
+ 同步 docs/reports/console_frontend_audit + ADR-002 06-Roadmap  30 min
+ 重建 STATUS.md v2.5                                         30 min
+ 更新 docs/agent/TASKS.md                                     30 min
─────────────────────────────────────────────────────────────────
合计 ~4.5 h ≈ 1 工作日（1 人）
```

---

*最后更新：2026-07-12（v1.6 精简 9 项 + 🟡备选 14 项 + 🔥🔥v1.9 合并 7860 单端口 4 项 T-114~T-117 优先级最高 + v1.7 合并端口 5 项 + v1.8 FastAPI 撤回，106 项总任务）*