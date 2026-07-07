"""
WebAuto 基础使用示例
演示：反检测注入 + 验证码识别 + 高精度时间同步
"""
import asyncio
import sys
from pathlib import Path

# 添加 WebAuto 根目录到路径
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.WebAuto import WebAuto, WebAutoConfig
from Core.CaptchaSolver import CaptchaSolver
from Core.AntiDetect import inject_anti_detect
from Core.TimeSync import create_timesync


async def demo_anti_detect():
    """演示反检测注入"""
    print("\n=== Demo: Anti-Detect Injection ===")
    
    async with WebAuto(WebAutoConfig(headless=False)) as auto:
        await auto.goto("https://bot.sannysoft.com/")
        print("✅ Anti-detect injected, check browser for results")
        await asyncio.sleep(5)


async def demo_time_sync():
    """演示时间同步"""
    print("\n=== Demo: Time Sync ===")
    
    ts = await create_timesync(samples=5)
    print(f"✅ Calibrated: offset={ts.stats.offset_ms:+.1f}ms")
    
    # 演示倒计时 3 秒
    print("Countdown 3s...")
    await ts.countdown(3.0)
    print("✅ Done!")


async def demo_captcha_solver():
    """演示验证码识别（需要实际验证码页面测试）"""
    print("\n=== Demo: Captcha Solver ===")
    
    solver = CaptchaSolver()
    await solver.init()
    print("✅ OCR engine initialized")
    
    # 这里可以加载测试验证码图片进行测试
    # test_img = Path("test_captcha.png").read_bytes()
    # result = await solver.solve_chinese_click(test_img, "你好世界")
    # print(f"Result: {result}")


async def main():
    print("🚀 WebAuto Demo Suite")
    
    # 1. 时间同步演示（最快）
    await demo_time_sync()
    
    # 2. 验证码识别演示
    # await demo_captcha_solver()
    
    # 3. 反检测演示（需要浏览器）
    # await demo_anti_detect()
    
    print("\n✅ All demos completed!")


if __name__ == "__main__":
    asyncio.run(main())
