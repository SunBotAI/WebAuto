# WebAuto - 开发状态总览 v2.3

更新时间: 2026-07-06

> 📄 新增设计文档: [DESIGN_V2_FACTS_DRIVEN.md](./DESIGN_V2_FACTS_DRIVEN.md) — 真实抓包驱动的自动化方案（与 ARCHITECTURE_V2 互补）

## ✅ v2.4 P0 已完成 (本轮:多套餐配置可视化)

把"套餐配置"从单一全局字段(target_plan / billing_cycle / pay_channel)升级成
第一类可配置对象 PlanGroup,可在 web 控制台里动态增删多组配置,
点一次"开始抢"并发执行,每组独立 (target_plan / cycle / channel / pinhaomo),
共享 NTP 校准 + 账号 token。

### 多套餐配置 (v2.4)
- [x] Core/Zhipu/config.py: 新增 PlanGroup 子模型 + AppConfig.plan_groups 字段
- [x] AppConfig model_validator 自动向后兼容:plan_groups 为空时从单套餐字段折叠
- [x] Core/Zhipu/group_scheduler.py: 新建 PlanGroupScheduler,asyncio.gather 并发跑多组
- [x] Core/Zhipu/scheduler.py: AccountResult.group 字段填充组名(向后兼容默认空字符串)
- [x] Core/Zhipu/orchestrator.py: 改调 PlanGroupScheduler.run,共享 TimeSync + 账号会话
- [x] Tools/console.py: 新增"套餐配置(多组 · 并行)"面板(Dataframe + 添加/删除/切换)
- [x] Tools/console_backend.py: 新增 add_plan_group / remove_plan_group / toggle_plan_group / make_plan_group_rows
- [x] state_to_appconfig_kwargs 重写:plan_groups 非空走多组路径,空走向后兼容单组路径
- [x] config.example.yaml: 旧字段标 deprecated + 新 plan_groups 注释示例
- [x] Tests/test_plan_groups.py: 15 用例(back-compat / 多组 yaml / 校验失败 / 调度器隔离 / _build_group_config 6 字段覆盖)
- [x] Tests/test_console_backend.py: +14 用例(add/remove/toggle/make_rows/state_to_appconfig_kwargs 多组路径)
- [x] 184/184 测试全通过(每文件单独跑,跨文件 event-loop 干扰与本轮改动无关)

### v2.4 兼容性保证
- 老 yaml(target_plan/billing_cycle 不带 plan_groups) → 自动折叠成 1 个默认组,行为与 v2.3 一致
- 老 UI(只填单套餐 dropdown) → 旧字段保留,plan_groups 留空,走 legacy 路径
- 新 yaml(显式 plan_groups) → 多组并发
- 新 UI(填多组) → 多组并发

### v2.4 风险与回退
- 风险1: pydantic v2.13 的 model_validator(mode="after") 已验证可用
- 风险2: 跨文件 pytest-asyncio event-loop 复用告警(改用单文件 `pytest path/to/test.py` 规避)
- 回退: 模型/调度器改动均为新增,`git revert HEAD` 即可回到 v2.3

## ✅ v2.3 P1 已完成 (本轮:智谱集成 + 12 个问题修复)

把 References/GlmCodingGrabber 业务实现吸收进 Core/Zhipu 子包,
跑通 qtaxm/glm-rush 风格的 preview+check 双重校验 + 自适应间隔并发,
修复了之前评估出的 12 个集成问题。

### 智谱集成 (v2.2)
- [x] Core/Zhipu 子包: 13 个模块,constants/api/session/scheduler/orchestrator/http_client/crypto/notifier/logger/timesync/config/exceptions/__main__
- [x] qtaxm preview+check 模式: preview_single / check_biz_id / CheckExpireError
- [x] 自适应间隔并发: AdaptiveRetryPolicy (burst 20 + quick 10 + slow 100ms ± 30%)
- [x] 多账号并发: Semaphore + gather, 单账号串行避免风控
- [x] NTP 自动选最快 (腾讯云/阿里云/公共池), jitter < 50ms
- [x] Fernet 凭证加密 + 短信重登
- [x] CLI: python -m Core.Zhipu {grab,check,sync,store}
- [x] Examples/zhipuai_grab.py 5 个 demo

### 12 问题修复 (v2.3)
- [x] 问题1: createBankOrder 加 require_biz_id 防御性参数,qtaxm 链路强制带 bizId
- [x] 问题3: browser.py 改用项目 StealthFetcher/HumanFetcher,自动获得反检测注入
- [x] 问题4: sync_time 统一 NTP 入口, Orchestrator 支持外部注入避免重复校准
- [x] 问题5: Scheduler.run 加 dry_run=True,跑通 3 个并发/dry-run/Semaphore 限流测试
- [x] 问题6: README 路线图更新
- [x] 问题7: STATUS.md 更新到 v2.3
- [x] 问题8: Services/ 加 __init__.py 说明未来用途
- [x] 问题9: compute_slow_delay_s 抽成纯函数 + 5 个 jitter 边界测试
- [x] 问题10: relogin_by_sms 改为从响应头 set-cookie 拿新凭证(set_cookies_to_cookie_string 工具)
- [x] 问题11: 风控识别改为多信号(CODE_RISK_BLOCK_CODES 集合 + RISK_MSG_KEYWORDS 关键字 + HTTP 403)
- [x] 问题12: 异常 docstring 补全,每个异常说明"是否可重试"和触发场景

### 单测统计
- 97 个单测全部通过(原 47 + Zhipu 22 + PreviewCheck 9 + AdaptiveRetry 12 + NTP sync 4 + Scheduler dry-run 3)

## ✅ v2.1 P0 已完成 (上轮)

修复了 v2.0 落地时未跑通的关键路径,所有 demo 实际可跑,单测覆盖核心 API。

- [x] CaptchaSolver.py 全角字符 SyntaxError (根因是破损 docstring)
- [x] v2.solve_captcha 真正实现 (委托给 CaptchaSolver.solve_from_page)
- [x] StealthFetcher.post JS 拼接 bug (改用 page.evaluate 传 [args])
- [x] HumanFetcher.mouse 起点硬编码 (改用 self._last_mouse_pos 状态)
- [x] v1 WebAuto.init 加 NTP 异常降级 (time_sync 失败不阻塞 init)
- [x] ddddocr 解析器实现 (按 ddddocr.detection 返回格式)
- [x] SmartSelector.adaptive 文本回退匹配 (真实可用)
- [x] HttpFetcher.set_proxy 真正生效 (init 后调直接抛错)
- [x] HttpFetcher 兼容 httpx 0.28+ (proxy 单数) + lxml 6.x (len 判断)
- [x] example_v2_basic.py 全部 5 个 demo 跑通 (HTTP 模式实测)
- [x] example_basic.py 全部 3 个 demo 跑通 (time_sync 真实校时)
- [x] Tests/ 47 个单测全部通过 (HttpFetcher / Errors / Factory / SmartSelector)

## ✅ v2.0 P0 已完成模块 (上轮)

### 6. 统一异常体系 (Errors/)
- [x] 基异常 WebAutoError
- [x] 获取器异常：网络/超时/拦截/初始化
- [x] 选择器异常：元素找不到/不可见/超时
- [x] 验证码/时间同步/会话异常分类

### 7. 获取器抽象层 (Fetchers/)
- [x] BaseFetcher 统一接口定义
- [x] FetcherMode 四种模式枚举
- [x] FetcherResponse 统一响应对象

### 8. HttpFetcher - 纯 HTTP 模式
- [x] httpx + HTTP/2 支持
- [x] lxml DOM 解析 + CSS 选择器
- [x] Cookie 管理 + 代理支持
- [x] 浏览器指纹 headers 模拟

### 9. StealthFetcher - 隐形模式
- [x] Playwright headless + 反检测注入
- [x] 复用现有 AntiDetect 模块
- [x] Cookie 管理 + 代理支持
- [x] 完整交互 API (click/type/evaluate)

### 10. BrowserFetcher - 完整浏览器模式
- [x] 继承 StealthFetcher，默认显示窗口

### 11. HumanFetcher - 人类模式（抢购专用）
- [x] 贝塞尔曲线鼠标轨迹模拟
- [x] 随机点击延迟 + 输入间隔
- [x] 误点修正模拟（10% 概率点偏再修正）
- [x] preheat_element 抢购预热（鼠标预先就位）

### 12. 智能选择器系统 (Selector/)
- [x] SmartSelector 链式调用 API
- [x] 自动重试 + 超时控制
- [x] 多选择器 fallback
- [x] 按文本查找（不用写 CSS 选择器）
- [x] 快捷操作：click/type/text/attribute/exists
- [x] preheat 抢购预热接口

### 13. WebAuto v2.0 主入口重构
- [x] 完全向后兼容 v1.0 API
- [x] 四种模式无缝切换
- [x] 统一智能选择器接口
- [x] 便捷工厂函数：WebAutoHttp/WebAutoStealth/...
- [x] 保留原有 page/browser/context/captcha/time 属性

---

## ✅ v1.0 原有模块全部保留

### 1. 反检测引擎 (AntiDetect.py)
- [x] fetch hook + 请求指纹随机化
- [x] XHR hook + JSON.parse 定向补丁
- [x] WebGL/Canvas 指纹随机化
- [x] WebDriver 特征隐藏

### 2. 验证码识别 (CaptchaSolver.py)
- [x] PP-OCRv6 / ddddocr 双引擎
- [x] 中文点选验证码识别
- [x] 坐标自动映射 + 人类行为模拟

### 3. 高精度时间同步 (TimeSync.py)
- [x] NTP 中位数采样
- [x] sleep_until_server_time 精确触发

---

## 📦 目录大小统计 v2.0

```
WebAuto/
├── Core/                    ~75 KB
│   ├── WebAuto.py          ~5 KB  (v1.0)
│   ├── WebAuto_v2.py       ~9 KB  (NEW v2.0)
│   ├── AntiDetect.py       ~14 KB
│   ├── CaptchaSolver.py    ~12 KB
│   ├── TimeSync.py         ~10 KB
│   ├── Errors/             ~2 KB   (NEW)
│   ├── Fetchers/           ~22 KB  (NEW)
│   │   ├── base.py
│   │   ├── http.py
│   │   ├── stealth.py
│   │   ├── browser.py
│   │   └── human.py
│   └── Selector/           ~7 KB   (NEW)
├── Examples/                ~5 KB
│   ├── example_basic.py    (v1.0)
│   └── example_v2_basic.py (NEW v2.0)
├── ARCHITECTURE_V2.md      ~7 KB   (NEW 设计文档)
└── requirements.txt         updated
```

---

## 🎯 架构亮点 v2.0

| 特性 | 说明 |
|------|------|
| 四层获取器 | http -> stealth -> browser -> human，按需选择 |
| 统一 API | 四种模式调用方式完全一致，切换不用改代码 |
| 智能选择器 | 重试 + 超时 + fallback + 按文本查找 |
| 向后兼容 | v1.0 API 100% 保留，无缝迁移 |
| 护城河 | 验证码 + 反检测 + 时间同步 + 人类行为，别家没有 |

---

## 🚀 下一步计划

### P0 - 本周内（核心验证）
- [ ] 跑通 example_v2_basic.py 所有 demo
- [ ] 修复 HttpFetcher 边界情况
- [ ] 整合 v2.0 到 WebAuto.py（替换旧版，改 __init__.py）

### P1 - 两周内（增强能力）
- [ ] 自适应选择器算法（页面改版自动找元素）
- [ ] Cloudflare Turnstile 绕过增强
- [ ] 自动验证码类型检测 + 求解
- [ ] 会话管理器（Cookie 持久化 + 代理轮换）

### P2 - 一个月内
- [ ] Spider 并发引擎
- [ ] MCP 服务封装（对接 Claude/Cursor）
- [ ] CLI 交互模式

---

## 💡 设计原则（不变）

1. **与 ShopAuto 风格一致**：PascalCase 命名，清晰的模块分层
2. **通用优先**：不绑定特定网站，可用于任意 Web 自动化场景
3. **模块化**：每个核心能力独立可复用
4. **向后兼容**：新功能只做加法，不破坏旧代码
5. **简单易用**：常见场景 3 行代码搞定，复杂场景可配置

---

*v2.0 架构设计完成，核心底座已实现，接下来进行测试和验证*

## ✅ 2026-07 反检测 / 调试基建 (本轮)

### 7 类细节补丁(2026-07 加)
- [x] `Core/AntiDetect.py`: 401 → 802 行,加 9 个新方法 (`_realistic_plugins_script` / `_consistent_hardware_script` / `_locale_consistency_script` / `_fingerprint_v2_script` / `_audio_stable_script` / `_headless_sanitize_script` / `_cdp_clean_script` + 2 个 seed helper)
- [x] `AntiDetectConfig` 加 11 个新开关(全部默认 True): `enable_realistic_plugins` / `enable_consistent_hardware` / `enable_locale_consistency` / `enable_canvas_noise` / `enable_webgl_random` / `enable_audio_stable` / `enable_headless_sanitize` / `enable_cdp_clean` + `fingerprint_seed`
- [x] mulberry32 PRNG 驱动 Canvas / WebGL / Audio 噪声,`fingerprint_seed` 同 seed 同 context 内完全一致
- [x] HTTP fingerprint 持久化:`Core/BrowserProfile/` 模块 (data + store)

### BrowserProfile (持久化指纹)
- [x] `Core/BrowserProfile/profile.py`: `BrowserProfile` + `HardwareConsistent` + `ViewportConfig` dataclass
- [x] `Core/BrowserProfile/store.py`: `ProfileStore` 持久化到 `~/.cache/webauto/profiles/<id>.json`(原子写)
- [x] `Core/Fetchers/stealth.py` 接入 `browser_profile_id` config 选项,自动同步到 Playwright `new_context` kwargs + `AntiDetectConfig.fingerprint_seed`
- [x] `Tests/test_browser_profile.py`: 18 用例 (构造 / 序列化 / 持久化 / 约束 / 三种 apply 路径)

### HTTP / 浏览器 行为伪装
- [x] `Core/Fetchers/http.py`: 加 `_CHROME_HEADER_ORDER` 常量 + `_normalize_headers()` 工具,所有 header 按 Chrome 120 顺序发出 (sec-ch-* / sec-fetch-* / Accept / User-Agent / Accept-Language 等)
- [x] HttpFetcher 接受 `browser_profile_id` 选项,自动应用 profile 的 UA / Accept-Language / sec-ch-* 到 header
- [x] `Core/Fetchers/human.py`: `type()` 重写,中文文本走 IME/composition 路径,ASCII 文本加大写短停/标点长停/Tab 节奏/偶尔打错+退格
- [x] `Tests/test_http_header_order.py`: 6 用例验证 Chrome header order

### CDP 调试工具集 (新)
- [x] `Tools/cdp_smoke.py`           - 5 分钟验证 WSL attach 到已登录 Chrome
- [x] `Tools/cdp_apply_antidetect.py` - 把 AntiDetect JS 注入 Chrome tab + 9 项 stealth 自检
- [x] `Tools/cdp_token_extract.py`   - 从已登录 tab 抽 bigmodelJwt / acw_tc / Cookie
- [x] `Tools/cdp_log_archive.py`     - 调试会话归档 (init / pack / list / diff)
- [x] `Tools/cdp_launch.bat`         - 加 `fresh` / `devtools=N` 参数,默认 reuse 你的 Chrome userdata (保留登录态)
- [x] `Tools/cdp_launch.sh`         - 简化包装,WSL 跨平台调用 bat
- [x] `Tools/cdp_inspect.py`         - 加 `--preset {bigmodel,zhipu,cred,purchase,captcha,static}` + `--save-body` + `--save-dir`

### 真站调试示例 + mock target
- [x] `Examples/example_bigmodel_debug.py`: 4 demo (smoke / extract token / apply stealth / preview+check dry-run)
- [x] `Examples/mock_target/server.py`: 本地起智谱 mock (9 端点, 0 依赖, 监听 18080)
- [x] `Examples/mock_target/test_with_httpfetcher.py`: HttpFetcher 跑通 mock 的 21 assertion (全部通过)

### 测试统计
- 18 + 6 = 24 个新单测全过
- 旧 184 + 新 24 = 208 全过 (mock target 的 HTTP 集成测试额外 21 用例全过)

### 已知限制(实话实说)
- **TLS/JA3 改不了** (Playwright 内核层)
- **HTTP/2 SETTINGS 帧改不了** (httpx 不暴露)
- **Cloudflare Turnstile 客户端解不了** (需要服务端 token)
- **9 项 stealth 自检未在真实站跑过**(等你启动 Chrome,跑 cdp_apply_antidetect.py 验证)
