# 核心模块参考

> WebAuto 各核心模块的 API 速查。

---

## WebAuto 主入口

### 基础用法

```python
from Core.WebAuto import WebAuto, WebAutoConfig

config = WebAutoConfig(
    headless=False,
    anti_detect=True,
    enable_captcha_solver=True,
    enable_time_sync=True,
    browser_type="chromium"
)

async with WebAuto(config) as auto:
    await auto.goto("https://example.com")
```

### v2 四种模式

```python
from Core.WebAuto_v2 import WebAutoHttp, WebAutoStealth, WebAutoHuman

async with WebAutoHttp() as auto:       # 纯 HTTP，最快
    ...

async with WebAutoStealth() as auto:   # 隐形浏览器
    ...

async with WebAutoHuman() as auto:     # 抢购专用
    ...
```

---

## AntiDetect — 反检测注入

```python
from Core.AntiDetect import inject_anti_detect

# Playwright 页面一键注入
await inject_anti_detect(page)

# 或带配置
from Core.AntiDetect import AntiDetectInjector, AntiDetectConfig
injector = AntiDetectInjector(AntiDetectConfig())
await injector.inject(page)
```

---

## CaptchaSolver — 验证码识别

```python
from Core.CaptchaSolver import CaptchaSolver

solver = CaptchaSolver()
await solver.init()

# 从图片识别
result = await solver.solve_chinese_click(image_bytes, "你好世界")

# 从 Playwright 页面自动识别
result = await solver.solve_from_page(page)
await solver.click_points(page, result)
```

---

## TimeSync — 时间同步

```python
from Core.TimeSync import create_timesync

ts = await create_timesync(samples=5)
print(f"时钟偏移: {ts.stats.offset_ms:+.1f}ms")

# 等待到指定服务器时间
await ts.sleep_until_server_time(target_timestamp)

# 倒计时
await ts.countdown(10.0)
```

---

## Profile — 浏览器配置

```python
from Core.Profile.store import ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy

store = ProfileStore()
pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED, max_concurrent=5)

# 列出所有 Profile
profiles = store.list_all()

# 创建 Profile
from Core.Profile.profile import Profile, FingerprintConfig, NetworkConfig
profile = Profile(
    id="profile-001",
    name="US 账号池",
    tags=["us", "residential"],
    fingerprint=FingerprintConfig(user_agent="...", viewport=(1920, 1080)),
    network=NetworkConfig(proxy_url="http://user:pass@host:port")
)
store.create(profile)

# 借还
async with pool.context(tag="grab") as profile:
    # use profile
    pass
# 自动归还

# 手动借还
profile = await pool.acquire(tag="grab", timeout=30)
await pool.release(profile, cooldown=60)
```

---

## ProxyPool — 全局代理池

```python
from Core.ProxyPool.proxy import Proxy
from Core.ProxyPool.health import ProxyHealthStore

# 添加代理
proxy = Proxy(
    id="proxy-001",
    url="http://user:pass@103.72.145.67:3000",
    region="US",
    tags=["residential"]
)

# 健康检查
from Core.ProxyPool.health import ProxyHealthState
health_store = ProxyHealthStore()
record = health_store.get("proxy-001")
print(record.is_available())  # True/False
```

---

## Zhipu — 智谱抢购

```python
from Core.Zhipu import ApiClient, BigModelApi
from Core.Zhipu.config import AppConfig, Account

cfg = AppConfig(
    accounts=[Account(name="主账号", phone="138xxxxxxxx", token="***")],
    target_plan="Max",
    target_plans=["Max", "Pro"],
    billing_cycle="yearly",
    pay_channel="alipay",
)
api = BigModelApi(client, cfg)

try:
    order = await api.run_purchase_chain()
    print(f"下单成功: orderNo={order.order_id}")
except SoldOutError:
    print("全部售罄")
```

---

## 关键数据路径

| 数据 | 默认路径 |
|------|---------|
| Profile 配置 | `~/.cache/webauto/profiles/<profile_id>/` |
| 代理健康 | `~/.cache/webauto/proxies/proxy_health.json` |
| 智谱凭证 | `.secrets.enc`（项目根目录） |
| 临时文件 | `tempfile.gettempdir()` |

---

*最后更新：2026-07-14*
