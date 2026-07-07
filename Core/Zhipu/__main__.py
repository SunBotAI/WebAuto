"""命令行入口。

支持若干子命令：

    python -m grabber grab   --config config.yaml   # 执行抢购
    python -m grabber check  --config config.yaml   # 仅检查登录态 / 配置
    python -m grabber sync   --config config.yaml   # 仅做 NTP 同步自检
    python -m grabber store  --config config.yaml --name 主账号
                                                       # 交互式录入凭证到加密库
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from typing import Optional

from Core.Zhipu import __version__
from Core.Zhipu.config import load_config
from Core.Zhipu.crypto import SecretStore
from Core.Zhipu.logger import get_logger, setup_logger
from Core.Zhipu.orchestrator import Orchestrator, sync_time
from Core.Zhipu.session import SessionManager

log = get_logger()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="grabber",
        description="智谱 AI GLM Coding 套餐抢购脚本 "
        f"(v{__version__})  仅供个人学习研究使用",
    )
    p.add_argument(
        "-c", "--config", default="config.yaml", help="配置文件路径"
    )
    p.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="日志级别",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # 为每个子命令同样挂上 -c/--config 与 --log-level，允许「子命令在前、
    # 全局参数在后」的写法（argparse 默认只允许全局参数在前）。
    # 使用 SUPPRESS 作为默认值：子命令未显式给出该参数时，不覆盖父解析器
    # 已设置的值，从而两种参数顺序都生效。
    def _add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "-c",
            "--config",
            default=argparse.SUPPRESS,
            help="配置文件路径（覆盖全局 -c）",
        )
        sp.add_argument(
            "--log-level",
            default=argparse.SUPPRESS,
            choices=["DEBUG", "INFO", "WARNING", "ERROR"],
            help="日志级别（覆盖全局 --log-level）",
        )

    sp = sub.add_parser("grab", help="执行抢购")
    _add_common(sp)

    sp = sub.add_parser("check", help="检查配置与登录态（不实际下单）")
    _add_common(sp)

    sp = sub.add_parser("sync", help="NTP 时间同步自检")
    _add_common(sp)

    store = sub.add_parser("store", help="交互式录入账号凭证到加密库")
    _add_common(store)
    store.add_argument("--name", required=True, help="账号别名")
    store.add_argument("--phone", default=None, help="手机号")

    return p


def main(argv: Optional[list[str]] = None) -> int:
    args = _build_parser().parse_args(argv)

    # 父解析器的 -c/--config default="config.yaml"、--log-level default="INFO"；
    # 子命令同名参数使用 SUPPRESS，仅在显式给出时覆盖父值。
    # 因此无论「全局参数在前」还是「子命令在前」，args.config 始终是生效值。
    config_path = args.config
    log_level = args.log_level
    setup_logger(level=log_level)

    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        log.error(str(e))
        return 2
    except RuntimeError as e:
        log.error(str(e))
        return 2

    if args.command == "grab":
        return asyncio.run(_cmd_grab(config))
    if args.command == "check":
        return asyncio.run(_cmd_check(config))
    if args.command == "sync":
        return _cmd_sync(config)
    if args.command == "store":
        return _cmd_store(config, args)
    log.error(f"未知命令: {args.command}")
    return 2


# ---------------------------------------------------------------------------
# 子命令实现
# ---------------------------------------------------------------------------


async def _cmd_grab(config) -> int:
    orch = Orchestrator(config)
    summary = await orch.run()
    return 0 if summary.any_success else 1


async def _cmd_check(config) -> int:
    """仅校验配置、加密库、各账号登录态。"""
    log.info("==== 配置自检 ====")
    log.info(
        f"目标: {config.target_plan.value} / {config.billing_cycle.value} / "
        f"拼好模={config.use_pinhaomo}"
    )
    log.info(f"触发时间: {config.target_time} (offset {config.time_offset_ms}ms)")
    log.info(f"启用账号: {[a.name for a in config.enabled_accounts]}")

    try:
        store = SecretStore(config.secret_store, ask=True)
        store.load()
        log.success("加密凭证库可正常解密")
    except Exception as e:  # noqa: BLE001
        log.error(f"加密凭证库异常: {e}")
        return 3

    mgr = SessionManager(config, store)
    sessions = []
    for a in config.enabled_accounts:
        client = mgr.build_client(a)
        from Core.Zhipu.session import Session

        sessions.append(Session(account=a, client=client))

    ok_count = 0
    try:
        flags = await asyncio.gather(*(mgr.check_alive(s) for s in sessions))
        for s, ok in zip(sessions, flags):
            if ok:
                ok_count += 1
        log.info(f"登录态有效账号: {ok_count}/{len(sessions)}")
    finally:
        await asyncio.gather(*(s.aclose() for s in sessions))

    return 0 if ok_count == len(sessions) else 1


def _cmd_sync(config) -> int:
    log.info(f"==== NTP 同步自检 ({config.ntp_server}) ====")
    ts = sync_time(config)
    drift = abs(ts.offset_s) * 1000
    log.info(
        f"偏移: {ts.offset_s * 1000:+.1f}ms | 绝对漂移 {drift:.1f}ms | "
        f"阈值 {config.ntp_max_drift_ms}ms"
    )
    return 0 if drift <= config.ntp_max_drift_ms else 1


def _cmd_store(config, args) -> int:
    """交互式把账号凭证写入加密库。"""
    log.info(f"==== 录入账号凭证: {args.name} ====")
    print(f"为账号 [{args.name}] 录入凭证（输入留空则跳过该字段）")
    token = getpass.getpass("Token（隐藏输入）: ").strip() or None
    cookie = getpass.getpass("Cookie（隐藏输入）: ").strip() or None
    phone = args.phone or input("手机号: ").strip() or None

    if not token and not cookie:
        log.error("token 和 cookie 至少需要录入一个")
        return 2

    store = SecretStore(config.secret_store, ask=True)
    store.upsert_account(
        {"name": args.name, "token": token, "cookie": cookie, "phone": phone}
    )
    log.success(f"账号 [{args.name}] 凭证已加密保存到 {config.secret_store}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
