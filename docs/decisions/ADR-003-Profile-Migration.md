# ADR-003: BrowserProfile → Profile 迁移路径

**Status:** Accepted
**Date:** 2026-07-10
**Author:** 小豆
**Task:** XIAODOU-WEBAUTO-DOCS-001 / T-041

---

## Context

项目里同时存在两个指纹配置模块：

- `Core/BrowserProfile/` — 最早写的，3 个文件，只覆盖指纹持久化
- `Core/Profile/` — 后来重构的，6 个文件，把指纹 + 网络 + 状态 + 池化 + 编排全部收拢

两套 API 长期并存会让调用方困惑，也不利于维护。决定让 `Core/Profile` 当唯一标准，`Core/BrowserProfile` 废弃。

## 迁移原因

`Core/BrowserProfile` 的问题：

1. **数据模型太窄** — 只有指纹，没有代理配置、没有生命周期状态、没有池化支持
2. **字段命名不一致** — `locale` / `timezone_id` / `color_scheme` 和新 API 体系不对齐
3. **没有 ProfileStatus** — 不知道一个 profile 是 ready / running / cooldown / banned
4. **Orchestrator / Pool 缺失** — 没有编排层，单 profile 手动管理

`Core/Profile` 的优势：

- `Profile` = FingerprintConfig + NetworkConfig + ProfileStatus + tags，一站式
- `ProfilePool` + `AcquireStrategy` 支持多账号轮换
- `BrowserOrchestrator` 管理浏览器生命周期
- `FingerprintGenerator` 可以按策略生成新指纹
- 和 `AntiDetect` 深度整合，7 项字段全量同步

## 迁移步骤

### Step 1 — 找到所有 import

```bash
grep -rn "from Core.BrowserProfile\|from Core import BrowserProfile\|import Core.BrowserProfile" /mnt/f/Project/WebAuto --include="*.py"
```

需要迁移的文件逐个改 import。

### Step 2 — 数据模型对照

| BrowserProfile 字段 | Profile / FingerprintConfig 字段 | 说明 |
|---|---|---|
| `profile_id` | `Profile.id` | 重命名 |
| `label` | `Profile.name` | 重命名 |
| `fingerprint_seed` | `Profile.fingerprint.canvas_seed` | 路径变深一层 |
| `hardware` (cores/memoryGB/dpr/screenW/screenH/colorDepth) | `Profile.fingerprint.hardware_concurrency` 等 | 拆分到多个字段 |
| `viewport` (width/height) | `Profile.fingerprint.screen_resolution` | 格式不同 |
| `locale` | `Profile.fingerprint.locale` | 直接映射 |
| `timezone_id` | `Profile.fingerprint.timezone` | 直接映射 |
| `user_agent` | `Profile.fingerprint.user_agent` | 直接映射 |
| `accept_language` | — | Profile 目前没有这个字段（待补 T-048） |
| `color_scheme` | — | Profile 目前没有这个字段（待补 T-048） |
| `created_at / updated_at` | `Profile` 内部维护 | 通过 ProfileStore 自动处理 |

**Proxy 配置**：`BrowserProfile` 没有 proxy 概念，迁移后可通过 `Profile.network.proxy_url` 补上。

### Step 3 — ProfileStore 替换

```python
# Before
from Core.BrowserProfile import BrowserProfile, ProfileStore
store = ProfileStore()
bp = store.get_or_create("my-profile", seed=12345)

# After
from Core.Profile import Profile, ProfileStore
store = ProfileStore()
p = store.get_or_create("my-profile", seed=12345)
```

`ProfileStore` 的 API 基本兼容（`load / save / list_ids / get_or_create / delete`），但内部存储结构不同（Profile 存的是完整 Profile JSON，不是 BrowserProfile JSON）。**迁移后需要重建 profile 文件**，旧的 `.json` 无法直接复用。

### Step 4 — apply 方法替换

```python
# Before
bp.apply_to_anti_detect_config(cfg)

# After
profile.apply_to_antidetect(cfg)
```

`apply_to_antidetect` 会同步 7 项字段（比旧版 `apply_to_anti_detect_config` 更完整）。

### Step 5 — Playwright 参数

```python
# Before
kwargs = bp.apply_to_playwright_kwargs()

# After
# Profile 不直接提供 apply_to_playwright_kwargs，改为在 BrowserOrchestrator 里处理
# 或手动构造：
kwargs = {
    "viewport": {"width": profile.fingerprint.screen_resolution[0],
                 "height": profile.fingerprint.screen_resolution[1]},
    "locale": profile.fingerprint.locale,
    "timezone_id": profile.fingerprint.timezone,
    "user_agent": profile.fingerprint.user_agent,
}
```

### Step 6 — 删除 import alias（可选，等 T-048 确认）

迁移完成后，在 `Core/BrowserProfile/__init__.py` 顶部加 `DeprecationWarning`，提示用户迁移到新 API。

## 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 旧 profile JSON 无法直接复用 | 中 | 写迁移脚本（不在本 ADR 范围，列入 T-048） |
| `accept_language` / `color_scheme` 新 Profile 没有 | 低 | T-048 补充字段 |
| 已有代码大量引用 BrowserProfile | 高 | T-048 阶段统一替换，本次只写文档 |
| `ProfilePool` / `AcquireStrategy` 需要调用方改写逻辑 | 中 | 提供 `AcquireStrategy` 用法示例（见附录） |

## 回滚方案

迁移过程中如果发现严重问题：

- **T-041/T-042 阶段**（文档 + deprecation note）：无风险，纯文档，直接 revert
- **T-048 阶段**（实际迁移脚本）：先在测试分支做，验证通过再合入 main

回滚步骤：`git revert <commit>` 即可，Profile 和 BrowserProfile 互相独立，不存在数据破坏。

## 附录：AcquireStrategy 示例

```python
from Core.Profile import ProfilePool, AcquireStrategy

pool = ProfilePool.from_store()  # 从 ProfileStore 加载所有 profile

# 顺序使用（不指定策略）
with pool.acquire() as profile:
    profile.apply_to_antidetect(cfg)
    ...

# 指定策略（轮换 / 随机 / 最少使用）
with pool.acquire(strategy=AcquireStrategy.ROUND_ROBIN) as profile:
    ...
```

---

*生成：XIAODOU-WEBAUTO-DOCS-001 / T-041 | 2026-07-10*
