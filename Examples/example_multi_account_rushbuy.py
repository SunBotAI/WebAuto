"""
Examples/example_multi_account_rushbuy.py — 多账号并发抢购示例

演示：
1. ProfilePool 管理多个 Profile 的借还生命周期
2. 3 个账号真正并发启动（各自独立的 Chromium Context + Cookie）
3. 每个账号独立操作（不同 IP / 不同指纹 / 不同标签页）
4. 如何扩展到更多账号

扩展到更多账号：
- 只需在 PROFILES 列表里加更多 Profile 配置
- ProfilePool 的 max_concurrent 控制最大并发数
- 建议 max_concurrent = 5（太多账号同时抢容易被风控）
"""

import asyncio
import sys
from pathlib import Path
from datetime import datetime

# 添加 WebAuto 根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile import Profile, ProfileStatus, FingerprintConfig, NetworkConfig
from Core.Profile.store import ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy
from Core.Profile.orchestrator import BrowserOrchestrator


# ============== 配置区 ==============

# 目标抢购时间（北京时间）
RUSH_TIME = "2026-07-15 10:00:00"

# NTP 提前量（毫秒）：比抢购时间早多少开始触发
ADVANCE_MS = 200

# 每个账号并发标签页数
TABS_PER_ACCOUNT = 1

# 是否用 headless 模式（第一次跑建议 False，看浏览器）
HEADLESS = False

# 抢购目标页面
TARGET_URL = "https://www.example.com/product/flash-sale"

# =========================================


def create_profiles(base_dir: Path) -> list[Profile]:
    """
    创建 3 个示例 Profile（对应 3 个账号）。

    每个 Profile 有独立指纹、独立代理、独立 storage_dir。
    实际使用时替换成真实的代理 IP 和账号信息。
    """
    configs = [
        {
            "id": "account-001",
            "name": "账号-A",
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
            "screen": (1920, 1080),
            "proxy_url": "http://localhost:7890",   # 替换为实际代理
            "proxy_username": None,
            "proxy_password": None,
        },
        {
            "id": "account-002",
            "name": "账号-B",
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
            "screen": (1920, 1080),
            "proxy_url": "http://localhost:7890",
            "proxy_username": None,
            "proxy_password": None,
        },
        {
            "id": "account-003",
            "name": "账号-C",
            "locale": "zh-CN",
            "timezone": "Asia/Shanghai",
            "screen": (1920, 1080),
            "proxy_url": "http://localhost:7890",
            "proxy_username": None,
            "proxy_password": None,
        },
    ]

    profiles = []
    for cfg in configs:
        fp = FingerprintConfig(
            locale=cfg["locale"],
            timezone=cfg["timezone"],
            screen_resolution=cfg["screen"],
            platform="Linux x86_64",
            vendor="Google Inc.",
        )
        net = NetworkConfig(
            proxy_url=cfg["proxy_url"],
            proxy_username=cfg["proxy_username"],
            proxy_password=cfg["proxy_password"],
            geoip_country="CN",
        )
        p = Profile(
            id=cfg["id"],
            name=cfg["name"],
            fingerprint=fp,
            network=net,
            tags=["rushbuy", "flash-sale"],
        )
        profiles.append(p)

    return profiles


async def account_worker(
    pool: ProfilePool,
    orchestrator: BrowserOrchestrator,
    account_id: str,
    rush_ts: float,
):
    """
    单个账号的抢购流程。

    1. 从池子借出 Profile
    2. 等待到抢购时间
    3. 打开标签页，执行抢购操作
    4. 释放 Profile 回池子
    """
    log_prefix = f"[{account_id}]"

    # 1. 借 Profile（会等待直到有空闲槽位）
    print(f"{log_prefix} 等待借出 Profile...")
    profile = await pool.acquire(timeout=60.0)
    print(f"{log_prefix} 借到 Profile: {profile.id}（{profile.name}）")

    try:
        # 2. 获取浏览器 Context（每个 Profile 独立 Cookie / storage）
        ctx = await orchestrator.get_context(profile)
        page = await ctx.new_page()

        # 3. 访问目标页面
        print(f"{log_prefix} 访问目标页面...")
        await page.goto(TARGET_URL, wait_until="domcontentloaded", timeout=15000)
        await asyncio.sleep(0.5)

        # 4. 等待到抢购时间
        from Core.TimeSync import TimeSync
        ts = TimeSync()
        await ts.calibrate()
        now = ts.server_now
        wait_ms = (rush_ts - now) * 1000
        if wait_ms > 0:
            print(f"{log_prefix} 距抢购还有 {wait_ms:.0f}ms，等待中...")
            await ts.sleep_until_server_time(rush_ts)

        # 5. 抢购！点击购买按钮
        print(f"{log_prefix} 🚀 开始抢购！")
        try:
            # 通用购买按钮选择器，实际按目标站点调整
            btn = page.locator(
                'button:has-text("立即购买"), '
                'button:has-text("马上抢"), '
                'button:has-text("立即订阅")'
            ).first
            await btn.click(timeout=3000, force=True)
            print(f"{log_prefix} ✅ 按钮已点击")
        except Exception as e:
            print(f"{log_prefix} 点击按钮失败: {e}")

        # 6. 截图保存结果
        ts_str = datetime.now().strftime("%H%M%S")
        screenshot_path = f"screenshot_{account_id}_{ts_str}.png"
        await page.screenshot(path=screenshot_path, full_page=True)
        print(f"{log_prefix} 📸 截图: {screenshot_path}")

    except asyncio.TimeoutError:
        print(f"{log_prefix} ⚠️ 借 Profile 超时（60s）")

    except Exception as e:
        print(f"{log_prefix} ❌ 异常: {e}")

    finally:
        # 6. 归还 Profile（不是关闭！保留 Cookie 和登录态）
        await pool.release(profile)
        print(f"{log_prefix} ✅ Profile 已归还")


async def main():
    print("=" * 60)
    print("🔥 多账号并发抢购示例")
    print("=" * 60)

    # 0. 解析抢购时间
    rush_dt = datetime.strptime(RUSH_TIME, "%Y-%m-%d %H:%M:%S")
    rush_ts = rush_dt.timestamp()
    print(f"⏰ 抢购时间: {RUSH_TIME}")
    print(f"🎯 提前量: {ADVANCE_MS}ms")

    # 1. 初始化 Store + 创建 Profile 池
    base_dir = Path(__file__).parent.parent / ".profiles_multi_account"
    base_dir.mkdir(exist_ok=True)
    store = ProfileStore(base_dir=base_dir)

    profiles = create_profiles(base_dir)
    for p in profiles:
        if store.get(p.id) is None:
            store.create(p)
            print(f"✅ 创建 Profile: {p.id}（{p.name}）")
        else:
            print(f"   已有 Profile: {p.id}")

    # 2. 创建 ProfilePool（最多 5 个并发，LEAST_USED 策略）
    pool = ProfilePool(
        store,
        strategy=AcquireStrategy.LEAST_USED,
        max_concurrent=5,
    )
    print(f"\n✅ ProfilePool 初始化完成，共 {len(profiles)} 个账号")

    # 3. 创建 BrowserOrchestrator（共享一个 Chromium 进程）
    orchestrator = BrowserOrchestrator(
        store=store,
        headless=HEADLESS,
        max_concurrent=5,
    )

    try:
        # 4. 启动 orchestrator
        print("\n🚀 启动浏览器...")
        await orchestrator.start()
        print("✅ 浏览器启动成功")

        # 5. 启动多个账号的并发任务
        print(f"\n🏃 启动 {len(profiles)} 个账号并发抢购任务...")
        tasks = [
            account_worker(pool, orchestrator, p.id, rush_ts)
            for p in profiles
        ]

        await asyncio.gather(*tasks, return_exceptions=True)

        print("\n" + "=" * 60)
        print("✅ 全部账号抢购流程结束，请查看截图")
        print("=" * 60)

    finally:
        # 6. 清理资源
        await orchestrator.close()
        print("✅ 浏览器已关闭")


# ============== 扩展指南 ==============
#
# 扩展到更多账号只需：
#
# 1. 在 create_profiles() 中添加更多账号配置：
#    {
#        "id": "account-004",
#        "name": "账号-D",
#        "locale": "zh-CN",
#        ...
#    }
#
# 2. 如果需要更多并发，调整 max_concurrent：
#    pool = ProfilePool(store, max_concurrent=10)
#
# 3. 注意事项：
#    - 建议 max_concurrent ≤ 5（太多同时抢容易被风控）
#    - 不同账号用不同代理 IP（同一个 IP 多账号容易被识别）
#    - 抢购前先单独测试每个账号的登录态是否正常
#    - 可以给不同账号打不同 tags，用 STICKY_BY_TAG 策略绑定任务
#
# 4. 用 sticky 策略绑定任务和账号：
#    pool = ProfilePool(store, strategy=AcquireStrategy.STICKY_BY_TAG)
#    profile = await pool.acquire(tag="grab-task-001")
#    # 同一 tag 总是拿到同一个 Profile
#
# =========================================


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已退出")
    except Exception as e:
        print(f"\n❌ 异常退出: {e}")
        import traceback
        traceback.print_exc()
