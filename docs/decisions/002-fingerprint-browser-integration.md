# ADR-002: 指纹浏览器集成架构规划与实现方案

**Status:** Accepted
**Accepted Date:** 2026-07-07
**Accepted by:** 大白（基于老大 23:37 拍板）
**Date:** 2026-07-07
**Author:** 小千
**Context:** WebAuto 项目已有 StealthFetcher + AntiDetect 注入 + BrowserProfile,但仍受限于"单浏览器单指纹"模式——多账号场景下,每个账号需要独立的浏览器实例 + 独立的持久化指纹 + 独立的 Cookie 隔离 + 独立的代理通道。本次 ADR 提出"指纹浏览器(Fingerprint Browser)"完整架构,把 WebAuto 从"反检测工具"升级为"多账号隔离自动化平台"。

---

## 目录

1. [背景与现状](#1-背景与现状)
2. [参考项目横向对比](#2-参考项目横向对比)
3. [架构总览](#3-架构总览)
4. [核心模块设计](#4-核心模块设计)
5. [数据模型与持久化](#5-数据模型与持久化)
6. [实现 Roadmap](#6-实现-roadmap)
7. [风险与缓解](#7-风险与缓解)
8. [验收标准](#8-验收标准)

---

## 1. 背景与现状

### 1.1 现有能力盘点

WebAuto 已在 `Core/AntiDetect.py` (1030 行) + `Core/BrowserProfile/` (3 文件) + `Core/Fetchers/stealth.py` (13KB) 中实现了：

| 能力 | 现状 | 文件 |
|------|------|------|
| WebDriver 标志隐藏 | ✅ | AntiDetect._webdriver_mask_script |
| Canvas/WebGL 指纹随机化 | ✅ (1030 行覆盖) | AntiDetect._fingerprint_random / _fingerprint_v2 |
| AudioContext 稳态指纹 | ✅ | AntiDetect._audio_stable_script |
| PluginArray/MimeType 真实化 | ✅ | AntiDetect._realistic_plugins_script |
| Locale/Hardware 一致性 | ✅ | AntiDetect._consistent_hardware_script |
| Fetch/XHR hook + JSON 篡改 | ✅ | AntiDetect._fetch_hook_script |
| 请求指纹随机化 | ✅ | AntiDetect.random_request_id / random_timestamp |
| BrowserProfile 持久化 | ✅ | BrowserProfile/profile.py + store.py |
| NTP 时间同步 | ✅ | Core/TimeSync.py |
| 验证码识别 (PP-OCRv6) | ✅ | Core/CaptchaSolver.py |
| 4 种 Fetcher 模式 | ✅ | Core/Fetchers/ (http/stealth/browser/human) |
| 3 个 PoC 反检测引擎 | ✅ | Services/{cloakbrowser,stealth,undetected}_poc.py |

### 1.2 现状不足(为什么需要"指纹浏览器")

虽然单实例反检测能力已经很强,但生产场景的需求是 **多账号隔离 + 长时持久化**:

| 痛点 | 当前局限 | 业务影响 |
|------|----------|----------|
| 多账号同浏览器 | 同一 BrowserContext 共享 Cookie 池,多账号风控 | 一个账号被封会牵连其他账号 |
| 指纹随机但不稳定 | 同 Profile 二次启动可能变化 (cache miss) | 被指纹系统标记"可疑" |
| 持久化弱 | 没有启动即恢复,关浏览器即丢态 | 抢购前 5 秒不能花 30 秒初始化 |
| 代理绑定松散 | Fetcher.set_proxy 单实例绑死,账号级代理难 | 多地区账号无法精准定位 |
| 浏览器实例管理缺失 | 每次都新建 Chromium,无复用 | 资源浪费 + 启动慢 |
| 隔离的代理 + 指纹 + Cookie 三件套没有统一抽象 | 用户需要手动串 | 配置复杂度高 |

### 1.3 目标定义

把 WebAuto 升级为 **"指纹浏览器编排平台"**,对外提供与 AdsPower / Multilogin / GoLogin 同等级的多账号隔离能力,同时保持 WebAuto 现有优势(代码级可控 + 反检测深度 + NTP 抢购精度)。

---

## 2. 参考项目横向对比

调研 GitHub 上 Star 数最高的 8 个相关项目,吸收各自的护城河设计:

### 2.1 完整对比表

| 项目 | Star | 定位 | 借鉴点 | 局限 |
|------|------|------|--------|------|
| **[multilogin/manifest-v3](https://github.com/multilogin/ml-core)** (商业, ~5k) | 企业级指纹浏览器 | 多账号隔离 + 浏览器指纹池 + 持久化 | 商业闭源,但其 API 暴露的设计模式值得参考 |
| **[AdsPower/local-api](https://github.com/AdsPower/local-api)** (~3k) | 本地 API 模式 | 每个 Profile = 独立浏览器实例 + 独立代理 + 独立 Cookie | 闭源 |
| **[gologinapp/browser](https://github.com/gologinapp/gologin)** (~2k) | 多 Profile 浏览器 | Profile = Chromium + Proxy + Canvas/WebGL/Audio/Plugin 完整指纹 | Profile 序列化标准格式 (Cloudflare 兼容) |
| **[Scrapling/scrapling](https://github.com/D4Vinci/Scrapling)** (~7.5k) | 高级 Web 爬虫框架 | Fetcher 抽象 + 自适应选择器 + TLS 指纹 + Turnstile 绕过 | 浏览器模式弱 |
| **[CloakBrowser/cloakbrowser](https://github.com/CloakBrowser)** (~1.5k) | C++ 级 Stealth Chromium | drop-in Playwright 替换,无需脚本注入 | 单实例,没有多 Profile |
| **[undetected-chromedriver](https://github.com/ultrafunkamsterdam/undetected-chromedriver)** (~10k) | Selenium/CDP 反检测 | CDP patcher 替换关键方法 (`cdc_adoQpoasnfa76pfcZLmcfl_Array`) | Selenium API,Playwright 时代略陈旧 |
| **[puppeteer-extra/puppeteer-extra](https://github.com/berstend/puppeteer-extra)** (~7k) | Stealth 插件系统 | 插件化反检测 (stealth/recaptcha/block-resources) | Puppeteer 生态 |
| **[nodriver/nodriver](https://github.com/ultrafunkamsterdam/nodriver)** (~3k) | Async CDP 无驱动 | 异步 CDP 客户端 + 反检测 | 没有多 Profile 抽象 |
| **BetaStreetOmnis/xhs_ai_publisher** (~2k) | 小红书自动化 | `_is_creator_logged_in()` 探活 API 模式 | 单站点 |
| **gxagxagx/jimeng-browser-automation** | 即梦 AI 自动化 | 二维码截图落盘 + DOM 兜底 | 单站点 |
| **Spanky96/glm-coding-grabber** (413⭐) | 智谱抢购 | fetch hook + ddddocr + 并发 | 单业务 |
| **OLmatter/glm-coding-helper** (398⭐) | 智谱抢购 | 油猴注入 + 本地 OCR + 多窗口 | 油猴限定 |
| **qtaxm/glm-rush** (373⭐) | 智谱抢购 | Python 并发 + 反检测 + NTP | 单业务 |

### 2.2 关键设计模式提炼

从这些项目提炼出 6 个核心设计模式:

#### 模式 1: Profile 即一切 (from GoLogin / AdsPower)

```
Profile = {
    fingerprint: { canvas_seed, webgl_vendor, audio_seed, hardware, locale, ... },
    network: { proxy_url, proxy_username, proxy_password, geoip },
    cookies: [...],
    local_storage: {...},
    extensions: [...],
    browser_args: [...],
    startup_scripts: [...],
}
```

**为什么:** 用户的业务单位是"账号",账号 = 一个指纹 + 一个代理 + 一组 Cookie + 一批脚本。所有这些必须在 Profile 级别捆绑,跨 Profile 完全隔离。

#### 模式 2: Profile 持久化到本地 (from all fingerprint browsers)

```
~/.cache/webauto/profiles/<profile_id>/
├── fingerprint.json       # 稳定指纹 (Canvas/WebGL/Audio seed)
├── cookies.json           # Netscape 格式
├── local-storage.json     # localStorage / sessionStorage / indexedDB
├── extensions/            # 解压后的 Chrome 扩展
├── proxy.txt              # 当前代理 (含密码)
├── user-data/             # Chromium User Data Directory
└── meta.yaml              # 标签/创建时间/最后使用/状态
```

**为什么:** 关浏览器后必须能秒级恢复,否则抢购场景下"启动 30 秒"就是失败的同义词。

#### 模式 3: Profile 隔离的 BrowserContext (from Playwright + GoLogin)

**不**用 Playwright 的 `browser.new_context()` (它共享 User Data),而是:
```python
context = await browser.new_context(
    user_data_dir=f"~/.cache/webauto/profiles/{profile_id}/user-data",
    viewport=profile.viewport,
    user_agent=profile.ua,
    locale=profile.locale,
    timezone_id=profile.timezone,
    proxy=profile.proxy,
)
```

**为什么:** 真实 Chrome 的 `user-data-dir` 是隔离 Cookie/Storage/IndexedDB/Cache 的最干净手段,胜过任何软件级隔离。

#### 模式 4: TLS 指纹 (from Scrapling + curl_cffi)

HTTP 模式下不能只是 httpx,必须用 `curl_cffi` (curl-impersonate) 模拟 Chrome 的 TLS handshake + ALPN + HTTP/2 settings:

```python
from curl_cffi import requests
r = requests.get(url, impersonate="chrome120", proxies={"https": proxy_url})
```

**为什么:** 90% 的反爬系统在 TLS 握手阶段就拒绝非真实浏览器的 ClientHello (JA3 指纹)。

#### 模式 5: 启动时批量预热 (from Scrapling + GoLogin)

```python
async def bootstrap(profile_ids: list[str]):
    # 1. 并发启动所有 Profile 的 Chromium
    tasks = [asyncio.create_task(launch(p)) for p in profile_ids]
    # 2. 等所有 BrowserContext ready 后,再统一做 NTP 校时
    contexts = await asyncio.gather(*tasks)
    # 3. 校时
    await timesync.sync_batch([c.page for c in contexts])
```

**为什么:** 抢购场景下,目标时间是 T,提前 T-30s 必须全部就绪。

#### 模式 6: Profile 池化 + 轮换 (from Scrapling Spider)

```python
class ProfilePool:
    def __init__(self, profiles: list[Profile], strategy="round_robin"):
        ...
    async def acquire(self) -> Profile:
        # round_robin / random / sticky / health_based
    async def release(self, profile: Profile):
        # 标记 cooldown 或直接放回池子
```

**为什么:** 100 个账号的爬取任务不应该开 100 个 Chromium,而是按需借/还。

### 2.3 WebAuto vs 参考项目

| 维度 | WebAuto (现状) | AdsPower (商业) | Scrapling (开源) | CloakBrowser (开源) |
|------|----------------|-----------------|------------------|---------------------|
| 多 Profile | ❌ | ✅ | ❌ | ❌ |
| 反检测深度 | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| 持久化 | ✅ (JSON) | ✅ (云同步) | ❌ | ❌ |
| NTP 抢购 | ✅ | ❌ | ❌ | ❌ |
| 验证码 OCR | ✅ (PP-OCRv6) | ❌ | ❌ | ❌ |
| HTTP 模式 | ✅ | ❌ | ✅ | ❌ |
| 代码可定制 | ⭐⭐⭐⭐⭐ | ❌ 闭源 | ⭐⭐⭐⭐ | ⭐⭐⭐ |
| 开源/可控 | ✅ | ❌ | ✅ | ✅ |

**结论:** WebAuto 在反检测深度、NTP 抢购、OCR 验证码上有护城河,只需补齐 **"多 Profile 隔离 + 持久化 + 启动预热"** 三件套,就能与商业指纹浏览器并驾齐驱,同时保持代码级可控的优势。

---

## 3. 架构总览

### 3.1 四层架构图

```
┌──────────────────────────────────────────────────────────────────────┐
│                       Layer 4: 业务编排层                            │
│                                                                       │
│   ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│   │ Spider 引擎 │  │ 抢购调度器  │  │ MCP 服务    │  │ CLI 工具 │ │
│   │ (并发爬取)  │  │ (NTP 校时)  │  │ (AI 调用)   │  │ (管理)   │ │
│   └─────────────┘  └─────────────┘  └─────────────┘  └──────────┘ │
├──────────────────────────────────────────────────────────────────────┤
│                       Layer 3: Profile 编排层                        │
│                                                                       │
│   ┌──────────────────┐  ┌──────────────────┐  ┌────────────────┐   │
│   │ ProfilePool      │  │ BrowserOrchestr  │  │ ProfileStore   │   │
│   │ (借/还/轮换)     │  │ ator (生命周期)  │  │ (本地持久化)   │   │
│   └──────────────────┘  └──────────────────┘  └────────────────┘   │
├──────────────────────────────────────────────────────────────────────┤
│                       Layer 2: 反检测注入层                          │
│                                                                       │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌─────────────┐ │
│   │AntiDetect  │  │BrowserProf │  │TLS 指纹    │  │Humanizer    │ │
│   │(JS 注入)   │  │ile(指纹)   │  │(HTTP 模式) │  │(鼠标轨迹)   │ │
│   └────────────┘  └────────────┘  └────────────┘  └─────────────┘ │
├──────────────────────────────────────────────────────────────────────┤
│                       Layer 1: 底层执行层                             │
│                                                                       │
│   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐              │
│   │ Playwright   │  │ curl_cffi    │  │ PP-OCRv6     │              │
│   │ + Chromium   │  │ (HTTP+TLS)   │  │ ddddocr      │              │
│   └──────────────┘  └──────────────┘  └──────────────┘              │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 数据流

```
┌──────────┐    ┌──────────────┐    ┌────────────────┐    ┌─────────────┐
│ 用户/AI  │───>│ 配置声明     │───>│ ProfilePool    │───>│ BrowserCtx  │
│          │    │ (YAML/JSON)  │    │ .acquire()     │    │ (隔离实例)  │
└──────────┘    └──────────────┘    └────────────────┘    └─────────────┘
                       │                                            │
                       v                                            v
              ┌──────────────────┐                        ┌──────────────┐
              │ Profile 模板     │                        │ 业务执行     │
              │ (指纹/代理/标签) │<───── 持久化/恢复 ─────│ (购/爬/自测) │
              └──────────────────┘                        └──────────────┘
```

### 3.3 文件结构(新增部分)

```
WebAuto/
├── Core/
│   ├── Profile/                    # NEW: Profile 编排层
│   │   ├── __init__.py
│   │   ├── profile.py              # Profile 数据类 (指纹/代理/标签/...)
│   │   ├── pool.py                 # ProfilePool (借/还/轮换)
│   │   ├── store.py                # ProfileStore (本地持久化)
│   │   ├── orchestrator.py         # BrowserOrchestrator (生命周期)
│   │   ├── fingerprint_gen.py      # 指纹生成器 (Canvas/WebGL/Audio seed)
│   │   ├── geoip.py                # IP 地理推断 + timezone 匹配
│   │   └── templates/              # 内置 Profile 模板
│   │       ├── windows_chrome_120.json
│   │       ├── macos_safari_17.json
│   │       └── mobile_android.json
│   ├── Fetchers/
│   │   ├── http.py                 # 升级: 接 curl_cffi (TLS 指纹)
│   │   ├── stealth.py              # 升级: 接 ProfilePool
│   │   ├── browser.py              # 升级: 接 ProfileStore.user_data_dir
│   │   └── human.py                # 升级: 接 Profile.humanizer
│   ├── AntiDetect.py               # 升级: profile-aware 指纹种子
│   ├── BrowserProfile/             # 与 Core/Profile 整合 (保留作为底层)
│   └── ...
├── Services/                        # 服务化封装
│   ├── fingerprint_api.py          # NEW: HTTP API (Profile CRUD + 启动)
│   └── ...
├── Tools/
│   ├── profile_manager.py          # NEW: CLI 管理 Profile (增删改查)
│   └── ...
├── Tests/
│   ├── test_profile_pool.py        # NEW
│   ├── test_browser_orchestrator.py# NEW
│   ├── test_fingerprint_gen.py     # NEW
│   └── test_isolation.py            # NEW: 验证 Profile 间 Cookie 隔离
└── docs/
    └── decisions/
        └── 002-fingerprint-browser-integration.md  # 本文档
```

---

## 4. 核心模块设计

### 4.1 Profile 数据模型 (`Core/Profile/profile.py`)

```python
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List, Dict
from pathlib import Path

class ProfileStatus(Enum):
    READY = "ready"           # 已配置可启动
    RUNNING = "running"       # 正在使用中
    COOLDOWN = "cooldown"     # 暂时休息 (防风控)
    BANNED = "banned"         # 已封禁
    ARCHIVED = "archived"     # 归档不再用

@dataclass
class NetworkConfig:
    """代理 + 网络"""
    proxy_url: Optional[str] = None              # "http://user:pass@host:port"
    proxy_type: str = "http"                     # http | socks5
    geoip_country: Optional[str] = None          # "US" | "CN" | ...
    dns_over_https: bool = True

@dataclass
class FingerprintConfig:
    """指纹配置 (与 BrowserProfile 整合)"""
    user_agent: str
    platform: str                                # "Win32" | "MacIntel" | "Linux x86_64"
    vendor: str                                  # "Google Inc." | "Apple Computer, Inc."
    locale: str                                  # "en-US"
    timezone: str                                # "America/New_York"
    screen_resolution: tuple                     # (1920, 1080)
    color_depth: int = 24
    hardware_concurrency: int = 8
    device_memory: int = 8
    canvas_seed: int                             # 随机但持久
    webgl_vendor: str                            # "Intel Inc."
    webgl_renderer: str                          # "Intel Iris OpenGL Engine"
    audio_seed: int
    plugins: List[Dict]                          # PluginArray 内容
    fonts: List[str]                             # 自定义字体白名单
    webdriver: bool = False                      # 永远是 False
    headless_sanitize: bool = True               # 清理 HeadlessChrome UA

@dataclass
class Profile:
    """一个完整的账号配置 = 指纹 + 网络 + 标签 + 状态"""
    id: str                                      # 唯一标识, 如 "workstation-01"
    name: str                                    # 人类可读, 如 "主账号"
    tags: List[str] = field(default_factory=list) # ["抢购", "vip", "test"]

    fingerprint: FingerprintConfig = field(default_factory=lambda: FingerprintConfig(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        platform="Linux x86_64",
        vendor="Google Inc.",
        locale="en-US",
        timezone="America/New_York",
        screen_resolution=(1920, 1080),
    ))
    network: NetworkConfig = field(default_factory=NetworkConfig)

    # 运行期状态
    status: ProfileStatus = ProfileStatus.READY
    cooldown_until: Optional[float] = None       # unix 时间戳
    last_used: Optional[float] = None

    # 持久化路径
    storage_dir: Optional[Path] = None           # ~/.cache/webauto/profiles/{id}/

    # 启动参数
    browser_args: List[str] = field(default_factory=list)
    extensions: List[str] = field(default_factory=list)  # 扩展路径

    # 反检测脚本 (覆盖全局 AntiDetect)
    custom_scripts: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """序列化 (用于 JSON / YAML)"""

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        """反序列化"""

    def apply_to_anti_detect(self, cfg: "AntiDetectConfig") -> None:
        """把 fingerprint 同步到 AntiDetectConfig"""

    def get_playwright_proxy(self) -> Optional[dict]:
        """返回 Playwright new_context 的 proxy 字段"""

    def get_user_data_dir(self) -> Path:
        """返回持久化的 User Data Directory"""
```

**关键设计:**

1. **`fingerprint_seed` 必须持久**: 同一 Profile 多次启动,fingerprint 必须 byte-identical,否则指纹系统能识别"同一人但换了指纹"的可疑行为。

2. **`status` 字段防止过载**: 抢购场景后,某些账号可能被风控标记,自动降级到 `COOLDOWN`。

3. **`storage_dir` 是 Profile 唯一标识之外的物理隔离单位**: Cookie/Storage/IndexedDB 全在这里。

### 4.2 Profile 存储 (`Core/Profile/store.py`)

```python
class ProfileStore:
    """Profile 本地持久化"""

    DEFAULT_DIR = Path.home() / ".cache/webauto/profiles"

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or self.DEFAULT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def create(self, profile: Profile) -> Path:
        """创建 Profile (分配 storage_dir)"""

    def get(self, profile_id: str) -> Profile:
        """读取 Profile 配置"""

    def list_all(self) -> List[Profile]:
        """列出所有 Profile"""

    def save(self, profile: Profile) -> None:
        """更新 Profile 配置 (不重启浏览器)"""

    def delete(self, profile_id: str, *, wipe_storage: bool = True) -> None:
        """删除 Profile (含 user-data 目录)"""

    def get_or_create(self, profile_id: str, **defaults) -> Profile:
        """便捷方法"""

    def export(self, profile_id: str, target_zip: Path) -> None:
        """导出 Profile 包 (含 user-data) - 跨机器迁移用"""

    def import_(self, source_zip: Path, new_id: Optional[str] = None) -> Profile:
        """导入 Profile 包"""
```

**目录布局:**

```
~/.cache/webauto/profiles/workstation-01/
├── config.yaml          # Profile 配置 (人类可读)
├── fingerprint.json     # 指纹数据 (机器可读)
├── cookies.json         # Netscape 格式 cookies
├── local-storage.json   # localStorage / sessionStorage
├── user-data/           # Chromium User Data Directory
│   ├── Default/
│   │   ├── Cookies
│   │   ├── Local Storage/
│   │   ├── IndexedDB/
│   │   └── ...
│   └── ...
└── meta.json            # 标签/创建时间/最后使用/状态
```

### 4.3 指纹生成器 (`Core/Profile/fingerprint_gen.py`)

```python
class FingerprintGenerator:
    """生成符合统计规律的"真实"指纹"""

    def __init__(self, seed: Optional[int] = None):
        self.rng = random.Random(seed)

    def generate(self, template: Optional[str] = None) -> FingerprintConfig:
        """
        生成一个完整指纹
        template: "windows_chrome_120" | "macos_safari_17" | "mobile_android"
                  None = 随机选
        """

    @staticmethod
    def from_real_browser(profile: "LiveBrowserProfile") -> FingerprintConfig:
        """从一个真实浏览器的 profile.json 导入 (GoLogin 兼容)"""

    def mutate(self, fp: FingerprintConfig, *, keep_seed: bool = True) -> FingerprintConfig:
        """微调某个字段 (e.g. 改 UA 但保留 canvas_seed)"""
```

**核心: 指纹必须符合"统计一致性"**

| 关联约束 | 示例 |
|----------|------|
| UA + Platform + Vendor | UA 说 "Chrome 120 Windows" → platform 必须是 "Win32" |
| Locale + Timezone + Intl | locale="en-US" + timezone="America/New_York" (不能 locale="zh-CN" + timezone="UTC") |
| Screen + Hardware | 1920×1080 屏幕常见于 8 核 / 8GB |
| Canvas + WebGL + Audio | 三个 seed 必须能产生"看起来一致"的输出 (基于同一 PRNG) |
| Plugins + MimeTypes | plugins 数量和 mimeTypes 数量匹配 |
| Fonts | 必须包含 OS 自带的字体 (Windows: Arial/Calibri; macOS: Helvetica) |

**算法:**

```python
def generate_canvas_seed(self, hardware: HardwareConfig) -> int:
    """基于 hardware 推导 canvas seed,确保 'statistically consistent'"""
    # 同一 hardware,canvas seed 应该稳定
    h = hashlib.sha256(f"{hardware.cpu}|{hardware.gpu}|{hardware.os}".encode())
    return int.from_bytes(h.digest()[:4], "big")
```

### 4.4 Profile 池 (`Core/Profile/pool.py`)

```python
class AcquireStrategy(Enum):
    ROUND_ROBIN = "round_robin"
    RANDOM = "random"
    STICKY_BY_TAG = "sticky_by_tag"  # 同一任务用同一 Profile
    LEAST_USED = "least_used"
    HEALTH_BASED = "health_based"     # 优先选 cooldown 已结束的

class ProfilePool:
    """并发场景下借/还 Profile 的池子"""

    def __init__(
        self,
        store: ProfileStore,
        *,
        strategy: AcquireStrategy = AcquireStrategy.LEAST_USED,
        max_concurrent: int = 10,
        on_acquire_timeout: float = 30.0,
    ):
        self.store = store
        self.strategy = strategy
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._in_use: Dict[str, float] = {}  # profile_id -> acquire_time

    async def acquire(
        self,
        *,
        tag: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Profile:
        """异步借一个 Profile"""

    async def release(self, profile: Profile, *, cooldown: float = 0) -> None:
        """归还,可选 cooldown (防风控)"""

    async def __aenter__(self) -> "Profile":
        return await self.acquire()

    async def __aexit__(self, *exc):
        await self.release(self._current)

    @asynccontextmanager
    async def context(self, **kwargs) -> AsyncIterator[Profile]:
        """上下文管理器"""
        p = await self.acquire(**kwargs)
        try:
            yield p
        finally:
            await self.release(p)
```

**关键: 防风控的 cooldown 策略**

```python
async def release(self, profile: Profile, *, cooldown: float = 0):
    profile.last_used = time.time()
    if cooldown > 0:
        profile.status = ProfileStatus.COOLDOWN
        profile.cooldown_until = time.time() + cooldown
    self.store.save(profile)
```

### 4.5 浏览器编排器 (`Core/Profile/orchestrator.py`)

```python
class BrowserOrchestrator:
    """管理 Profile ↔ BrowserContext 的生命周期"""

    def __init__(
        self,
        store: ProfileStore,
        *,
        headless: bool = True,
        chromium_path: Optional[str] = None,
        max_concurrent: int = 5,
    ):
        self.store = store
        self.headless = headless
        self.chromium_path = chromium_path or self._default_chromium()
        self.max_concurrent = max_concurrent
        self._browser: Optional[Browser] = None
        self._contexts: Dict[str, BrowserContext] = {}

    async def start(self) -> None:
        """启动共享的 Chromium 进程 (所有 Profile 复用同一进程)"""

    async def stop(self) -> None:
        """关闭所有 Context 和 Browser"""

    async def get_context(self, profile: Profile) -> BrowserContext:
        """
        为 Profile 创建 (或复用) BrowserContext
        - user_data_dir = profile.storage_dir / "user-data"
        - 注入 AntiDetect 脚本
        - 应用 fingerprint / network
        """
        if profile.id in self._contexts:
            return self._contexts[profile.id]

        if self._browser is None:
            await self.start()

        context = await self._browser.new_context(
            user_data_dir=str(profile.get_user_data_dir()),
            viewport={"width": profile.fingerprint.screen_resolution[0],
                      "height": profile.fingerprint.screen_resolution[1]},
            user_agent=profile.fingerprint.user_agent,
            locale=profile.fingerprint.locale,
            timezone_id=profile.fingerprint.timezone,
            proxy=profile.get_playwright_proxy(),
            color_scheme="light",
            # ... 其他字段
        )

        # 注入反检测脚本
        await self._inject_anti_detect(context, profile)

        self._contexts[profile.id] = context
        profile.status = ProfileStatus.RUNNING
        return context

    async def warmup(self, profiles: List[Profile], *, ntp_sync: bool = True) -> None:
        """
        批量预热:并发启动所有 Profile,可选 NTP 校时
        用于抢购场景 (目标时间前 T-30s)
        """

    async def _inject_anti_detect(self, context: BrowserContext, profile: Profile):
        """注入 Profile 专属的反检测脚本"""
        # 1. 基础 AntiDetect (继承全局配置)
        base_injector = AntiDetectInjector(AntiDetectConfig(
            fingerprint_seed=profile.fingerprint.canvas_seed,
            # ... 应用 profile.fingerprint
        ))
        await context.add_init_script(base_injector.get_inject_script())

        # 2. Profile 专属脚本
        for script in profile.custom_scripts:
            await context.add_init_script(script)
```

**关键设计: 共享 Chromium 进程**

```python
# ✅ 正确: 一个 Chromium 进程管理多个 Profile
browser = await p.chromium.launch(...)
context_alice = await browser.new_context(user_data_dir=".../alice")
context_bob   = await browser.new_context(user_data_dir=".../bob")

# ❌ 错误: 每个 Profile 一个 Chromium (内存爆炸)
browser_alice = await p.chromium.launch(...)
browser_bob   = await p.chromium.launch(...)
```

这是 AdsPower / GoLogin 内部的核心优化,WebAuto 必须遵守。

### 4.6 升级 HTTP Fetcher (TLS 指纹) — `Core/Fetchers/http.py`

借鉴 Scrapling 的 TLS 指纹实现,把 httpx 替换为 `curl_cffi`:

```python
class HttpFetcher(BaseFetcher):
    """HTTP 模式 Fetcher,使用 curl_cffi 模拟真实浏览器 TLS 握手"""

    def __init__(self, config: Optional[Dict] = None):
        super().__init__(config)
        self._session: Optional["CurlSession"] = None
        self._impersonate: str = config.get("impersonate", "chrome120")
        self._proxy_pool: List[str] = config.get("proxy_pool", [])

    async def init(self):
        from curl_cffi import requests
        self._session = requests.AsyncSession(
            impersonate=self._impersonate,
            proxies=self._get_current_proxy(),
        )

    async def get(self, url: str, **kwargs) -> FetcherResponse:
        proxy = self._rotate_proxy()
        self._session.proxies = {"https": proxy, "http": proxy}
        response = await self._session.get(url, **kwargs)
        return FetcherResponse(
            url=url,
            status=response.status_code,
            headers=dict(response.headers),
            content=response.content,
            text=response.text,
        )

    def _rotate_proxy(self) -> str:
        if not self._proxy_pool:
            return None
        return random.choice(self._proxy_pool)
```

### 4.7 升级 Stealth Fetcher (Profile-aware)

```python
class StealthFetcher(BaseFetcher):
    """隐形模式 Fetcher,可选 Profile-aware"""

    def __init__(
        self,
        config: Optional[Dict] = None,
        *,
        profile: Optional[Profile] = None,
        orchestrator: Optional[BrowserOrchestrator] = None,
    ):
        super().__init__(config)
        self.profile = profile
        self.orchestrator = orchestrator

    async def init(self):
        if self.orchestrator and self.profile:
            # Profile-aware 模式
            self._context = await self.orchestrator.get_context(self.profile)
            self._page = await self._context.new_page()
        else:
            # 向后兼容:无 Profile 模式
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            # 注入默认反检测
            injector = AntiDetectInjector(AntiDetectConfig())
            await self._context.add_init_script(injector.get_inject_script())
```

---

## 5. 数据模型与持久化

### 5.1 Profile YAML 格式(用户编辑用)

```yaml
# ~/.cache/webauto/profiles/workstation-01/config.yaml
id: workstation-01
name: 主账号
tags: [抢购, vip, daily]

fingerprint:
  user_agent: "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
  platform: Linux x86_64
  vendor: Google Inc.
  locale: en-US
  timezone: America/New_York
  screen_resolution: [1920, 1080]
  color_depth: 24
  hardware_concurrency: 8
  device_memory: 8
  canvas_seed: 1749382743
  webgl_vendor: Intel Inc.
  webgl_renderer: Intel Iris OpenGL Engine
  audio_seed: 2983746523
  plugins:
    - { name: "Chrome PDF Plugin", filename: "internal-pdf-viewer" }
    - { name: "Chrome PDF Viewer", filename: "mhjfbmdgcfjbbpaeojofohoefgiehjai" }
    - { name: "Native Client", filename: "internal-nacl-plugin" }
  fonts: [Arial, Calibri, Times New Roman, Courier New]
  webdriver: false
  headless_sanitize: true

network:
  proxy_url: "http://user:pass@residential.proxy.io:8080"
  proxy_type: http
  geoip_country: US
  dns_over_https: true

browser_args:
  - "--disable-blink-features=AutomationControlled"
  - "--no-sandbox"

extensions: []  # 暂无

custom_scripts:
  - |
    // 用户自定义 JS 注入
    console.log('profile-specific script loaded');
```

### 5.2 持久化策略

| 数据 | 存储位置 | 格式 | 备份策略 |
|------|----------|------|----------|
| Profile 配置 | `config.yaml` | YAML | git 仓库 (跨机器同步) |
| 指纹 | `fingerprint.json` | JSON | 同上 |
| Cookies | `user-data/Default/Cookies` | SQLite (Chromium 原生) | 不备份 (高频变动) |
| localStorage | `user-data/Default/Local Storage/` | Chromium 原生 | 不备份 |
| IndexedDB | `user-data/Default/IndexedDB/` | Chromium 原生 | 不备份 |
| 元数据 | `meta.json` | JSON | 同 config.yaml |

**关键: 不要手工解析 `user-data/` 内的 SQLite / leveldb 文件**。直接复用 Chromium 的原生持久化机制,通过 `user_data_dir` 参数让 Playwright 帮我们管理。

### 5.3 跨机器同步

- **方案 A: 全量包导出**: `profile_manager.py export workstation-01 alice.zip` → 包含 user-data + config.yaml。简单但慢。
- **方案 B: 配置 + 单独 Cookie**: config.yaml 走 git,Cookie 单独加密同步。麻烦但灵活。
- **方案 C: 云同步(预留)**: 未来对接 S3 / Dropbox。架构层保留 hook (`ProfileStore.add_remote_sync()`)。

---

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

## 7. 风险与缓解

| # | 风险 | 等级 | 影响 | 缓解 |
|---|------|------|------|------|
| 1 | Chromium user-data 目录的跨版本兼容性 | 中 | 升级 Chromium 后旧 user-data 可能损坏 | 检测到版本不匹配时,自动备份 + 重建 |
| 2 | 多 Profile 共享 Chromium 进程的内存压力 | 中 | 100 个 Context 可能 OOM | max_concurrent 默认 5,可配置;监控内存 |
| 3 | Profile 持久化的 Cookie 失效 | 低 | 长时间不用的账号 token 过期 | cooldown 时自动检测登录态,失效 → status=BANNED |
| 4 | 指纹生成器生成"过于真实"的指纹被标记 | 低 | 罕见,但 0.1% 概率 | 提供 `from_real_browser` 导入真实 profile.json |
| 5 | curl_cffi 与 Python 3.12 兼容性 | 中 | HTTP 模式可能报错 | requirements 固定版本 + CI 测试 |
| 6 | AntiDetect 与 Profile 指纹不一致 | 高 | Canvas seed 不同 → 同 Profile 二次启动指纹变了 | Profile.apply_to_anti_detect 强制同步 seed |
| 7 | 多账号风控关联 | 高 | 同 IP 同指纹的多个账号被识别为同人 | 强制每 Profile 不同代理 + 不同 fingerprint_seed |
| 8 | 反检测脚本被目标网站针对性检测 | 中 | 长期维护成本 | 提供 fallback 引擎 (Stealth/CloakBrowser/undetected) 切换 |
| 9 | 第三方库 (curl_cffi / playwright) 重大变更 | 中 | API 断裂 | 依赖锁定版本 + 集成测试 |
| 10 | 法律/合规风险 | 中 | 多账号绕过风控可能违反 ToS | README 写明仅供技术研究,使用风险自负 |

**特别关注风险 6:**

```python
# ✅ 正确: Profile 强制同步 seed 到 AntiDetect
profile.apply_to_anti_detect(anti_detect_config)
assert anti_detect_config.fingerprint_seed == profile.fingerprint.canvas_seed

# ❌ 错误: 各自独立生成 seed
anti_detect_config.fingerprint_seed = random.randint(0, 2**32)  # 每次都变!
```

---

## 8. 验收标准

### 8.1 P0 验收(2 周后)

#### 功能验收

- [ ] **Profile CRUD**: create / read / update / delete / list / export / import 全部可用
- [ ] **持久化**: 关闭 WebAuto 后,重启能秒级恢复 Cookie / localStorage
- [ ] **Cookie 隔离**: Profile A 的 Cookie 在 Profile B 中不可见 (反之亦然)
- [ ] **指纹稳定**: 同 Profile 二次启动,sannysoft 的 Canvas hash 完全一致
- [ ] **并发**: 5 个 Profile 并发启动 BrowserContext,总耗时 < 10s
- [ ] **CLI**: `webauto profile list` / `create` / `delete` / `warmup` 命令可用
- [ ] **示例**: `Examples/example_fingerprint_browser.py` 跑通 2 账号并发抢购

#### 性能验收

| 指标 | 目标 |
|------|------|
| Profile 创建 (含 user-data) | < 1s |
| Profile 启动 BrowserContext | < 3s (含反检测注入) |
| 5 Profile 并发启动 | < 10s |
| Profile 持久化 save/load | < 100ms |
| Cookie 隔离验证 | 100% (0 泄漏) |

#### 反检测验收

- [ ] **sannysoft.com**: 60%+ 检测项 passed
- [ ] **browserleaks.com/canvas**: Canvas hash 与 Profile 持久值一致
- [ ] **browserleaks.com/webgl**: WebGL vendor/renderer 与 Profile 配置一致
- [ ] **creepjs**: 无 "HeadlessChrome" 残留字眼

### 8.2 P1 验收(4 周后)

- [ ] **curl_cffi TLS**: HTTP 模式过 sannysoft 检测
- [ ] **Spider 并发**: 100 URL × 3 Profile 端到端爬取,Cookie 全隔离
- [ ] **代理轮换**: 5 个代理池自动轮换,失败自动剔除
- [ ] **暂停恢复**: Spider 中途 kill,重启能从 checkpoint 继续
- [ ] **MCP**: 通过 MCP 调用 Profile CRUD + 启动

### 8.3 P2 验收(3 个月后)

- [ ] **行为学习**: 录制一段用户操作 → 重放时通过 creepjs 行为检测
- [ ] **健康监控**: Profile 自动 cooldown 准确率 > 95%
- [ ] **Web UI**: 浏览器管理 Profile 可视化面板可用

---

## 9. 附录:示例代码 (P0 完成后)

```python
# Examples/example_fingerprint_browser.py

import asyncio
from Core.Profile import Profile, ProfileStore, ProfilePool
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.pool import AcquireStrategy

async def main():
    # 1. 准备多个 Profile
    store = ProfileStore()

    for i in range(3):
        profile = Profile(
            id=f"account-{i}",
            name=f"账号 {i}",
            tags=["抢购", "vip"],
            fingerprint=...,
            network=...,
        )
        store.create(profile)

    # 2. 启动浏览器编排器 (共享 Chromium)
    orchestrator = BrowserOrchestrator(store, headless=True)
    await orchestrator.start()

    # 3. 创建 Profile 池
    pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED)

    # 4. 批量预热
    profiles = store.list_all()
    await orchestrator.warmup(profiles, ntp_sync=True)

    # 5. 并发抢购 (每个任务借用一个 Profile)
    async def grab(profile: Profile, target_url: str):
        async with pool.context() as p:
            context = await orchestrator.get_context(p)
            page = await context.new_page()
            await page.goto(target_url)
            # ... 抢购逻辑
            return f"{p.name}: success"

    tasks = [grab(p, "https://...") for p in profiles]
    results = await asyncio.gather(*tasks)
    print(results)

    await orchestrator.stop()

asyncio.run(main())
```

---

## 10. 参考资料

| 来源 | URL | 借鉴点 |
|------|-----|--------|
| Scrapling (7.5k⭐) | https://github.com/D4Vinci/Scrapling | Fetcher 抽象 + 自适应选择器 + TLS |
| GoLogin (2k⭐) | https://github.com/gologinapp/gologin | Profile 数据模型 + 持久化格式 |
| CloakBrowser (1.5k⭐) | https://github.com/CloakBrowser | C++ 级 stealth,drop-in 替换 |
| undetected-chromedriver (10k⭐) | https://github.com/ultrafunkamsterdam/undetected-chromedriver | CDP patcher 模式 |
| puppeteer-extra (7k⭐) | https://github.com/berstend/puppeteer-extra | 插件化反检测 |
| nodriver (3k⭐) | https://github.com/ultrafunkamsterdam/nodriver | 异步 CDP |
| curl_cffi | https://github.com/yifeikong/curl_cffi | TLS 指纹 |
| Playwright Persistence | https://playwright.dev/python/docs/persistent-contexts | user_data_dir 模式 |
| Chromium Headless | https://chromium.googlesource.com/chromium/src/+/master/headless/ | Headless 检测原理 |
| CreepJS | https://abrahamjuliot.github.io/creepjs/ | 浏览器指纹检测工具 |
| Bot.sannysoft | https://bot.sannysoft.com/ | 反检测验证 |
| BrowserLeaks | https://browserleaks.com/ | Canvas/WebGL 指纹检测 |

---

**变更日志:**

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-07 | v0.1 | 初稿,基于 ADR-001 的模块拆分原则扩展到指纹浏览器 |