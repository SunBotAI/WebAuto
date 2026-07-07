"""
智谱 GLM Coding Plan 抢购脚本
整合 WebAuto 三大核心能力：
  1. NTP 高精度时间同步（±0.1ms）
  2. 反检测注入（6 项自动化特征全隐藏）
  3. 验证码自动识别点击（自动安装 OCR 依赖）

使用前准备：
  1. 手动在浏览器登录 bigmodel.cn，导出 cookies
  2. 点击一次购买按钮，抓包拿到目标商品的 productId
  3. 配置 RUSH_TIME 抢购时间
"""
import asyncio
import json
from datetime import datetime
from typing import List, Dict

# 添加父目录到路径
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from Core.WebAuto import WebAuto, WebAutoConfig
from Core.TimeSync import create_timesync
from Core.CaptchaSolver import CaptchaSolver


# ============== 配置区 - 请修改 ==============
RUSH_TIME = "2026-06-30 10:00:00"  # 抢购时间（北京时间）
PRODUCT_ID = "glm-coding-lite"       # 商品ID，请自行替换
ADVANCE_MS = 100                     # 提前多少毫秒开始触发
CONCURRENCY = 3                       # 并发标签页数量（不要开太多，风控）
ENABLE_CAPTCHA = True                 # 是否启用自动验证码识别
HEADLESS = False                      # 建议第一次用有头模式调试

# 浏览器 Cookies（从你登录的浏览器导出）
# 格式: [{"name": "xxx", "value": "xxx", "domain": ".bigmodel.cn"}, ...]
COOKIES: List[Dict] = [
    # 在这里粘贴你的 cookies
    # {"name": "session_id", "value": "xxx", "domain": ".bigmodel.cn"},
]
# =============================================


async def rush_worker(auto: WebAuto, worker_id: int, target_ts: float):
    """抢购工作线程（每个标签页一个）"""
    page = await auto.context.new_page()
    log_prefix = f"[Worker {worker_id}]"
    
    try:
        # 1. 访问抢购页面预热
        print(f"{log_prefix} 正在访问抢购页面...")
        await page.goto("https://bigmodel.cn/glm-coding", wait_until="domcontentloaded")
        await asyncio.sleep(1)
        
        # 2. 等待到目标时间
        now = auto.time.server_now
        wait_ms = (target_ts - now) * 1000
        print(f"{log_prefix} 等待中，距抢购还有 {wait_ms:.0f}ms")
        await auto.time.sleep_until_server_time(target_ts)
        
        # 3. 到点了！点击购买按钮
        print(f"{log_prefix} 🚀 开始抢购！")
        buy_btn = page.locator('button:has-text("立即订阅"), button:has-text("购买"), button:has-text("订阅")').first
        
        try:
            await buy_btn.click(timeout=2000, force=True)
            print(f"{log_prefix} 已点击购买按钮")
        except Exception as e:
            print(f"{log_prefix} 点击按钮失败: {e}，尝试 JS 直接点击")
            await page.evaluate("document.querySelector('button').click()")
        
        # 4. 处理验证码
        if ENABLE_CAPTCHA:
            try:
                # 等待验证码 iframe 出现（最多等 3 秒）
                iframe = page.wait_for_selector(
                    'iframe[src*="captcha"], iframe[src*="geetest"]',
                    timeout=3000
                )
                
                if iframe:
                    print(f"{log_prefix} 检测到验证码，正在自动识别...")
                    result = await auto.captcha.solve_from_page(page)
                    
                    if result.success:
                        await auto.captcha.click_points(page, result)
                        print(f"{log_prefix} ✅ 验证码点击完成")
                    else:
                        print(f"{log_prefix} ❌ 验证码识别失败")
                        
            except Exception as e:
                print(f"{log_prefix} 无验证码或验证码处理超时: {e}")
        
        # 5. 确认购买/支付
        try:
            confirm_btn = page.locator(
                'button:has-text("确认"), button:has-text("立即支付"), button:has-text("提交")'
            ).first
            if await confirm_btn.is_enabled():
                await confirm_btn.click(timeout=1000)
                print(f"{log_prefix} ✅ 已点击确认按钮")
        except:
            pass
        
        # 6. 保存截图
        timestamp = datetime.now().strftime("%H%M%S")
        await page.screenshot(path=f"rush_{worker_id}_{timestamp}.png", full_page=True)
        print(f"{log_prefix} ✅ 截图已保存")
        
    except Exception as e:
        print(f"{log_prefix} ❌ 异常: {e}")
        timestamp = datetime.now().strftime("%H%M%S")
        await page.screenshot(path=f"rush_{worker_id}_error_{timestamp}.png", full_page=True)
        
    finally:
        # 不要自动关页面，方便你看结果
        pass


async def main():
    print("=" * 60)
    print("🧠 智谱 GLM Coding Plan 自动抢购脚本")
    print("=" * 60)
    
    # 1. 解析抢购时间
    target_dt = datetime.strptime(RUSH_TIME, "%Y-%m-%d %H:%M:%S")
    target_ts = target_dt.timestamp()
    print(f"⏰ 配置的抢购时间: {RUSH_TIME}")
    
    # 2. 初始化 WebAuto
    config = WebAutoConfig(
        headless=HEADLESS,
        anti_detect=True,
        enable_captcha_solver=ENABLE_CAPTCHA,
        enable_time_sync=True
    )
    
    async with WebAuto(config) as auto:
        # 3. 时间同步（关键！）
        print("\n🕒 正在同步服务器时间...")
        ts = await create_timesync()
        auto.time = ts  # 注入到 auto 对象
        
        server_now = datetime.fromtimestamp(ts.server_now)
        local_now = datetime.now()
        offset_ms = ts.stats.offset_ms if ts.stats else 0
        print(f"   本地时间: {local_now}")
        print(f"   服务器时间: {server_now}")
        print(f"   时间偏差: {offset_ms:+.1f}ms")
        print(f"   NTP 抖动: {ts.stats.jitter_ms:.1f}ms" if ts.stats else "")
        
        # 4. 注入 cookies
        if COOKIES:
            print(f"\n🍪 正在注入 {len(COOKIES)} 个 cookies...")
            await auto.context.add_cookies(COOKIES)
            print("✅ Cookies 注入完成")
        else:
            print("\n⚠️  警告: 未配置 cookies，请手动在浏览器登录！")
            print("   请在弹出的浏览器里先登录账号，按回车键继续...")
            input()
        
        # 5. 倒计时
        wait_seconds = target_ts - ts.server_now
        if wait_seconds > 0:
            print(f"\n⏳ 倒计时: {wait_seconds:.0f} 秒")
            # 每 30 秒打印一次剩余时间
            while wait_seconds > 1:
                wait_seconds = target_ts - ts.server_now
                if int(wait_seconds) % 30 == 0:
                    print(f"   剩余 {wait_seconds:.0f} 秒")
                await asyncio.sleep(1)
        else:
            print("\n⚠️  抢购时间已过，直接开始！")
        
        # 6. 提前一点点开始
        trigger_ts = target_ts - ADVANCE_MS / 1000
        print(f"\n🎯 将在 {ADVANCE_MS}ms 前开始触发抢购")
        
        # 7. 启动多个并发 worker
        print(f"\n🚀 启动 {CONCURRENCY} 个并发抢购线程...")
        tasks = [
            rush_worker(auto, i, trigger_ts)
            for i in range(CONCURRENCY)
        ]
        
        await asyncio.gather(*tasks)
        
        print("\n" + "=" * 60)
        print("✅ 抢购流程已完成，请检查浏览器窗口！")
        print("=" * 60)
        print("\n💡 提示:")
        print("  1. 如果没抢到，可以试试把 ADVANCE_MS 调大/调小")
        print("  2. 不要连续多天用同一个账号猛抢，容易风控")
        print("  3. CONCURRENCY 不要超过 5，否则容易被封")
        print("\n按 Ctrl+C 退出...")
        
        # 保持浏览器不关闭
        while True:
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 已退出")
    except Exception as e:
        print(f"\n❌ 异常退出: {e}")
        import traceback
        traceback.print_exc()
