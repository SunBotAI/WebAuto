"""智谱 AI GLM Coding 套餐抢购示例.

展示 WebAuto 项目里集成好的 Zhipu 子包怎么用:

  1. 单账号、HTTP 直调(只跑一次下单链路)
  2. 多账号并发(N 个账号同时抢)
  3. NTP 校时 + 准点触发

用法:
  1. cp config.example.yaml config.yaml
  2. 编辑 config.yaml 填入 token / cookie (从浏览器 F12 抓)
  3. .venv-fix/bin/python Examples/zhipuai_grab.py
"""
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Zhipu import (
    ApiClient, BigModelApi, GrabScheduler, Orchestrator,
    BASE_URL, PATH_BATCH_PREVIEW, PATH_PREVIEW, PATH_CHECK,
    PRODUCT_ID_REFERENCE,
    ZhipuError, SoldOutError, AuthError, NetworkError,
)
from Core.Zhipu.config import AppConfig, Account, Plan, BillingCycle, load_config


async def demo_single_account():
    """单账号直接调 run_preview_check_chain()(qtaxm 模式,推荐)。"""
    print("\n=== Demo: 单账号 qtaxm preview+check 模式 ===")

    cfg = AppConfig(
        accounts=[Account(name="demo", phone="138xxxxxxxx", token="YOUR_TOKEN")],
        target_plan=Plan.MAX,
        target_plans=[Plan.MAX, Plan.PRO],   # 降级优先级
        billing_cycle=BillingCycle.YEARLY,
        pay_channel="alipay",
    )
    client = ApiClient(cfg, token="YOUR_TOKEN", account_name="demo")
    api = BigModelApi(client, cfg)

    print(f"目标: {cfg.target_plan.value} / {cfg.billing_cycle.value}")
    print(f"base_url: {BASE_URL}")
    print(f"preview 端点: {PATH_PREVIEW}")
    print(f"check 端点:   {PATH_CHECK}")
    print(f"MAX 包年 productId: {PRODUCT_ID_REFERENCE[('MAX', 'YEARLY')]}")

    try:
        # qtaxm 模式:preview 拿 bizId → check 校验 → EXPIRE 自动重试 → 下单
        order = await api.run_preview_check_chain()
        print(f"\n✅ 抢购成功!")
        print(f"   orderNo = {order.order_id}")
        print(f"   bizId   = {order.biz_id[:8]}...")
        print(f"   pay_url = {order.pay_url}")
        print(f"   选中套餐: tier={order.raw.get('_selected_tier')} "
              f"period={order.raw.get('_selected_period')} "
              f"实付 {order.raw.get('_selected_pay_amount')} 元")
    except SoldOutError as e:
        print(f"\n❌ 售罄: {e}")
    except AuthError as e:
        print(f"\n🔒 登录态失效: {e}")
    except NetworkError as e:
        print(f"\n🌐 网络错误: {e}")
    finally:
        await client.aclose()


async def demo_multi_account_concurrent():
    """多账号并发抢购(Semaphore + gather)。"""
    print("\n=== Demo: 多账号并发抢购 ===")
    print("需要多个账号的 token 才能跑(此处用 fake token 仅演示结构)")

    cfg = AppConfig(
        accounts=[
            Account(name=f"acc{i}", phone=f"1380000000{i}", token=f"fake-{i}")
            for i in range(3)
        ],
        target_plan=Plan.MAX,
        target_plans=[Plan.MAX, Plan.PRO],   # MAX 抢不到降级 PRO
        billing_cycle=BillingCycle.YEARLY,
        pay_channel="alipay",
        max_concurrent=3,
    )

    print(f"账号数: {len(cfg.accounts)}, 并发上限: {cfg.max_concurrent}")
    print(f"降级优先级: {[p.value for p in cfg.target_plans]}")

    # 真实场景里用 scheduler.run(sessions),这里只演示构造
    from Core.TimeSync import create_timesync
    try:
        ts = await create_timesync(samples=3)
        print(f"\nNTP 已校时: offset={ts.stats.offset_ms:+.1f}ms")
        scheduler = GrabScheduler(cfg, ts)
        print(f"Scheduler 实例化 OK: {type(scheduler).__name__}")
    except Exception as e:
        print(f"\n(NTP 失败,跳过 scheduler 演示: {e})")


async def demo_ntp_trigger():
    """NTP 校时 + 准点触发演示。"""
    print("\n=== Demo: NTP 校时 ===")
    from Core.TimeSync import create_timesync

    ts = await create_timesync(samples=3)
    print(f"已选最快 NTP: {ts.stats.ntp_server}")
    print(f"时钟偏移: {ts.stats.offset_ms:+.1f}ms")
    print(f"采样抖动: {ts.stats.jitter_ms:.1f}ms")
    print(f"网络延迟: {ts.stats.latency_avg_ms:.1f}ms")

    # 计算下次开售时间(假设 30 秒后)
    target_ts = ts.server_now + 30
    print(f"\n下一触发时间戳: {target_ts:.3f}")
    print("(实际抢购时把 target_ts 换成服务器开售时间戳)")


async def demo_cli_subcommands():
    """展示 CLI 子命令路径(实际执行用 python -m Core.Zhipu <sub>)。"""
    print("\n=== Demo: CLI 子命令 ===")
    print("""
# NTP 自检
python -m Core.Zhipu sync

# 配置自检(不实际下单,只验证登录态)
python -m Core.Zhipu check -c config.yaml

# 录入凭证到加密库(交互式,需要 GLM_GRABBER_KEY 环境变量)
GLM_GRABBER_KEY="your-passphrase" python -m Core.Zhipu store --name "主账号" --phone "138xxxxxxxx"

# 执行抢购(到点自动开火)
python -m Core.Zhipu grab -c config.yaml
    """)


async def main():
    print("=" * 60)
    print("智谱 AI GLM Coding 套餐抢购 - WebAuto Zhipu 子包演示")
    print("=" * 60)

    # 1. 演示业务接口端点
    await demo_single_account()
    # 2. 多账号并发结构
    await demo_multi_account_concurrent()
    # 3. NTP 校时
    await demo_ntp_trigger()
    # 4. CLI 用法
    await demo_cli_subcommands()

    print("\n" + "=" * 60)
    print("所有 demo 完成!")
    print("注意:真实抢购需要从浏览器 F12 抓 token/cookie 才能登录")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())