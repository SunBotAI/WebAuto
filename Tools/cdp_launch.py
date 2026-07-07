r"""cdp_launch.py - 跨平台 Chromium 启动器(WSL/Linux/macOS/Windows 一致)。

用法:
    # 自动检测 OS, 默认 reuse userdata 保留登录态
    python Tools/cdp_launch.py first-run                       # headed, 手动登 bigmodel.cn
    python Tools/cdp_launch.py clean-ui                         # 清理已运行的 Chromium 里的浮动 UI
    python Tools/cdp_launch.py visit                           # headed, 5 分钟复用
    python Tools/cdp_launch.py stealth-test                    # headless, 跑 5 检测站
    python Tools/cdp_launch.py hold --hold-minutes 30          # 长开

    # 选项:
    python Tools/cdp_launch.py --mode ephemeral first-run      # 不要持久 userdata (临时)
    python Tools/cdp_launch.py --headless stealth-test         # stealth-test 用 headless 默认
    python Tools/cdp_launch.py --fingerprint-seed 12345 first-run

为什么存在:
    我们以前有 cdp_launch.bat / .ps1 / .sh 三套分别 cmd / PowerShell / bash 调用,
    跨 OS 麻烦。这一个 Python 文件替代三者。Python 的 pathlib / subprocess 都是跨平台。
"""
import argparse
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def detect_os() -> str:
    """Return 'wsl' | 'linux' | 'macos' | 'windows'.

    WSL detection: Linux kernel + '/proc/sys/fs/binfmt/misc/WSLInterop' exists
    """
    s = platform.system().lower()
    if s == "linux":
        if Path("/proc/sys/fs/binfmt/misc/WSLInterop").exists():
            return "wsl"
        return "linux"
    if s == "darwin":
        return "macos"
    if s == "windows":
        return "windows"
    return s


def default_userdata_dir() -> Path:
    """跨平台 userdata 默认路径。

    - WSL/Linux/macOS:  ~/.cache/webauto/chromium
    - Windows:          %LOCALAPPDATA%\\webauto\\chromium
    env var WEBAUTO_USERDATA 可覆盖
    """
    env = os.environ.get("WEBAUTO_USERDATA")
    if env:
        return Path(env)
    os_name = detect_os()
    if os_name == "windows":
        base = Path(os.environ.get("LOCALAPPDATA", "~\\AppData\\Local"))
        return base / "webauto" / "chromium"
    return Path.home() / ".cache" / "webauto" / "chromium"


def find_chromium_executable(p) -> str | None:
    """让 playwright 找它下载好的 chromium。

    返回 playwright 期望格式的可执行路径, None 表示用默认(playwright 自己决定)。
    跨平台一致 —— playwright 内部会按 OS 选正确的 chromium binary 路径。
    """
    try:
        # playwright 1.40+ exposes this; older fallback below
        from playwright._impl._driver import compute_driver_executable
        return None  # 让 playwright 自己挑
    except Exception:
        return None


def _install_capture(page, log_path):
    """把 page 的 request/response/console/pageerror 写到 jsonl 文件.

    用途: 调试反爬 / 验证 API 调用 (如 bigmodel.cn 中文点选 captcha 提交 405).
    """
    import json as _json
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    fp = open(log_path, 'a', encoding='utf-8', buffering=1)  # line-buffered

    def _w(obj):
        try:
            fp.write(_json.dumps(obj, ensure_ascii=False, default=str) + '\n')
        except Exception as e:
            fp.write(_json.dumps({"_err": str(e)}) + '\n')

    def on_request(req):
        _w({"t": "request", "ms": int(time.time() * 1000), "method": req.method,
             "url": req.url, "headers": dict(req.headers) if req.headers else {},
             "resource_type": req.resource_type,
             "post_data": (req.post_data[:500] if req.post_data else None)})

    def on_response(resp):
        try:
            # 抓 response body 可能抛错 (e.g. 304, redirect), catch 住
            _w({"t": "response", "ms": int(time.time() * 1000),
                 "status": resp.status, "url": resp.url,
                 "headers": dict(resp.headers) if resp.headers else {},
                 "ok": resp.ok})
        except Exception as e:
            _w({"t": "response_err", "err": str(e), "url": resp.url})

    def on_request_failed(req):
        _w({"t": "request_failed", "url": req.url, "method": req.method,
             "failure": req.failure})

    def on_console(msg):
        _w({"t": "console", "type": msg.type, "text": msg.text})

    def on_pageerror(err):
        _w({"t": "pageerror", "err": str(err)})

    page.on("request", on_request)
    page.on("response", on_response)
    page.on("requestfailed", on_request_failed)
    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    print(f"[capture] installed -> {log_path}")


def cmd_first_run(args, p, ctx, page):
    """第一次跑: headed,打开 bigmodel.cn,让你手动登录"""
    target = args.url
    print(f"[first-run] 打开 {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=30000)
    print(f"[first-run] 当前: {page.url}")
    print(f"[first-run] 标题: {page.title()}")
    print()
    print("=" * 60)
    print("在弹出的浏览器窗口完成登录:")
    print("  1) 登录入口触发弹窗")
    print("  2) 输入手机号 + 短信验证码")
    print("  3) 中文点选验证码 (按提示顺序点击 4 个汉字)")
    print("  4) 登录成功后会到套餐页 / 用户中心")
    print("=" * 60)

    secs = args.hold_minutes * 60
    print(f"[first-run] 保持 {secs}s ...")
    success = False
    for i in range(secs):
        time.sleep(1)
        if i % 30 == 0:
            print(f"\r  [{secs - i}s left]", end="", flush=True)
        try:
            if i > 60 and "/user-center" in (page.url or "") or "套餐" in (page.title() or ""):
                print(f"\n[first-run] 看起来登录成功: {page.url}")
                success = True
                if i > 120:  # 至少 2 分钟才判
                    break
        except Exception:
            pass
    print()
    print(f"[first-run] 关闭 (userdata 已保存到 {ctx._impl_obj.args[0] if hasattr(ctx, '_impl_obj') else '持久目录'})")
    return 0


def cmd_visit(args, p, ctx, page):
    """日常: 复用 userdata + 自动开 url"""
    target = args.url
    print(f"[visit] 打开 {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=30000)
    print(f"[visit] 当前: {page.url}")
    print(f"[visit] 标题: {page.title()}")
    print()
    secs = args.hold_minutes * 60
    print(f"[visit] 保持 {secs}s ...")
    for i in range(secs):
        time.sleep(1)
        if i % 30 == 0:
            print(f"\r  [{secs - i}s left]", end="", flush=True)
    print()
    return 0


def cmd_stealth_test(args, p, ctx, page):
    """跑 5 个公开 stealth 检测站"""
    print("[stealth-test] 跑 5 个公开检测站 ...")
    targets = [
        ("bot.sannysoft",       "https://bot.sannysoft.com",
         "经典 webdriver / plugins 检测"),
        ("creepjs",             "https://abrahamjuliot.github.io/creepjs/",
         "2024+ 综合 stealth 检测"),
        ("fingerprintjs",       "https://fingerprintjs.github.io/fingerprintjs/",
         "FingerprintJS 官方 demo"),
        ("browserleaks-canvas", "https://browserleaks.com/canvas",
         "Canvas 指纹"),
        ("browserleaks-webgl",  "https://browserleaks.com/webgl",
         "WebGL vendor/renderer"),
    ]

    total_score = 0
    total_total = 0
    for name, url, desc in targets:
        print(f"\n  → {name}  ({url})")
        print(f"    {desc}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=20000)
            time.sleep(2)
            info = page.evaluate("""(() => ({
                webdriver: navigator.webdriver,
                ua: navigator.userAgent,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemory: navigator.deviceMemory,
                pluginsLen: (navigator.plugins && navigator.plugins.length) || 0,
                mimeTypesLen: (navigator.mimeTypes && navigator.mimeTypes.length) || 0,
                intlTz: new Intl.DateTimeFormat().resolvedOptions().timeZone,
                containsHeadlessChrome: navigator.userAgent.includes('HeadlessChrome'),
                userAgentDataBrands: navigator.userAgentData
                    && navigator.userAgentData.brands
                    ? navigator.userAgentData.brands.map(b => b.brand).join(',')
                    : null,
            }))()""")
            checks = [
                ("webdriver 已遮", info["webdriver"] in (None, "undefined")),
                ("hardwareConcurrency 合理", isinstance(info["hardwareConcurrency"], int) and 4 <= info["hardwareConcurrency"] <= 32),
                ("deviceMemory 在 {{4,8,16}}", info["deviceMemory"] in (4, 8, 16)),
                ("UA 不含 HeadlessChrome", not info["containsHeadlessChrome"]),
                ("userAgentData 含 Chromium", info["userAgentDataBrands"] and "Chromium" in info["userAgentDataBrands"]),
                ("plugins length == 2", info["pluginsLen"] == 2),
            ]
            passed = sum(1 for _, ok in checks if ok)
            total = len(checks)
            total_score += passed
            total_total += total

            print(f"    score: {passed}/{total}")
            print(f"    UA: {info['ua'][:80]}")
            for label, ok in checks:
                print(f"      [{'OK' if ok else 'FAIL'}] {label}")
        except Exception as e:
            print(f"    ERROR: {e}")
            total_total += 1

    print()
    if total_total:
        pct = total_score / total_total * 100
    else:
        pct = 0
    print(f"=== 总计: {total_score}/{total_total} ({pct:.0f}%) ===")
    return 0


def cmd_hold(args, p, ctx, page):
    """长开, 别的脚本可以 attach"""
    print(f"[hold] 保持 {args.hold_minutes} 分钟, 你可以手动操作窗口")
    secs = args.hold_minutes * 60
    for i in range(secs):
        time.sleep(1)
        if i % 30 == 0:
            print(f"\r  [{secs - i}s left]", end="", flush=True)
    print()
    return 0


def cmd_clean_ui(args, p, ctx, page):
    """清理已运行 Chromium 里的浮动 UI panel (挡按钮的那块 🛡️ WebAuto 浮窗)

    复用同一个 userdata 启动新的 Chromium (persistent context),
    init script 注入 __shopauto_removeShadowPanel() 立即调用。
    因为 init script 在每次新页面创建前注入, 所以新打开的页面天然干净。
    """
    target = args.url
    print(f"[clean-ui] 打开 {target}")
    page.goto(target, wait_until="domcontentloaded", timeout=30000)
    print(f"[clean-ui] 当前: {page.url}")
    print(f"[clean-ui] 标题: {page.title()}")

    # 在每个 frame 里主动调一次 remove API (覆盖已经存在的浮动 div)
    cleaned = 0
    try:
        for frame in page.frames:
            try:
                removed = frame.evaluate("""(() => {
                    if (typeof window.__shopauto_removeShadowPanel === 'function') {
                        return window.__shopauto_removeShadowPanel('__shopauto_panel');
                    }
                    // 老版本注入的 div, 直接走 DOM 兜底删
                    const host = document.getElementById('__shopauto_panel');
                    if (host && host.parentNode) {
                        host.parentNode.removeChild(host);
                        return true;
                    }
                    return false;
                })()""")
                if removed:
                    cleaned += 1
            except Exception:
                pass
    except Exception as e:
        print(f"[clean-ui] frame walk 异常: {e}")
    print(f"[clean-ui] 清理浮动 panel: {cleaned} 个 frame")

    secs = args.hold_minutes * 60
    print(f"[clean-ui] 保持 {secs}s, 你可以继续操作浏览器 ...")
    for i in range(secs):
        time.sleep(1)
        if i % 30 == 0:
            print(f"\r  [{secs - i}s left]", end="", flush=True)
    print()
    return 0


def launch_and_dispatch(args, p):
    """启浏览器(跨平台),然后 dispatch 到具体命令"""
    from Core.AntiDetect import AntiDetectInjector, AntiDetectConfig
    cfg = AntiDetectConfig(
        fingerprint_seed=args.fingerprint_seed,
        # 默认彻底不注入任何浮动 UI (2026-07-06: AntiDetect 不再 auto-create).
        # 旧 --enable-shadow-panel 已废弃, 改成 enable_panel flag, 默认 False.
        # 即使 True 也只是暴露 create API, 真实面板仍需手动 __shopauto_createShadowPanel() 调.
        enable_shadow_panel=args.enable_panel,
    )
    js = AntiDetectInjector(cfg).get_inject_script()

    userdata_dir = str(args.userdata_dir)
    print()
    print(f"[INFO] 平台:    {detect_os()}")
    print(f"[INFO] Userdata: {userdata_dir}")
    print(f"[INFO] 模式:    {args.mode}")
    print(f"[INFO] Headed:  {not args.headless}")
    print(f"[INFO] URL:     {args.url}")
    print(f"[INFO] Hold:    {args.hold_minutes} min")
    print(f"[INFO] FP seed: {args.fingerprint_seed}")
    print()

    headless = args.headless or args.command not in ("first-run", "visit", "hold", "clean-ui")
    if args.command in ("first-run", "visit", "hold", "clean-ui"):
        headless = args.headless  # 让命令行控制

    if args.mode == "ephemeral":
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
        ctx.add_init_script(js)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
    else:
        # persistent (default) -- userdata 自动复用
        Path(userdata_dir).mkdir(parents=True, exist_ok=True)
        ctx = p.chromium.launch_persistent_context(
            userdata_dir,
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1920, "height": 1080},
        )
        ctx.add_init_script(js)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

    # 装 network / console 抓包 (如指定 --capture-network)
    if args.capture_network:
        _install_capture(page, args.capture_network)
        print(f"[INFO] capture on: {args.capture_network}", flush=True)

    try:
        if args.command == "first-run":
            return cmd_first_run(args, p, ctx, page)
        if args.command == "visit":
            return cmd_visit(args, p, ctx, page)
        if args.command == "stealth-test":
            return cmd_stealth_test(args, p, ctx, page)
        if args.command == "hold":
            return cmd_hold(args, p, ctx, page)
        if args.command == "clean-ui":
            return cmd_clean_ui(args, p, ctx, page)
    finally:
        try:
            ctx.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        description="Cross-platform Chromium driver (Linux/macOS/Windows/WSL)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("command",
                        choices=["first-run", "visit", "stealth-test", "hold", "clean-ui"],
                        help="操作模式")
    parser.add_argument("--mode", default="persistent",
                        choices=["persistent", "ephemeral"],
                        help="userdata 是否持久 (默认 persistent)")
    parser.add_argument("--userdata-dir", default=None,
                        help="userdata 路径 (默认 ~/.cache/webauto/chromium 或 LOCALAPPDATA/webauto/chromium)")
    parser.add_argument("--url", default="https://bigmodel.cn/glm-coding",
                        help="要打开的 URL")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式")
    parser.add_argument("--hold-minutes", type=int, default=10,
                        help="窗口保持分钟数")
    parser.add_argument("--fingerprint-seed", type=int, default=42,
                        help="AntiDetect stable seed")
    parser.add_argument("--enable-panel", action="store_true",
                        help="(已废弃) 仅控制 AntiDetect 是否默认 auto-create panel, 默认永不 auto-create")
    parser.add_argument("--capture-network", default=None,
                        help="把 page 的 request/response/console 写到指定文件 (jsonl 格式), 用于调试反爬")
    args = parser.parse_args()

    if args.userdata_dir is None:
        args.userdata_dir = default_userdata_dir()

    # 验证 playwright 已装 + chromium 已下
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERR] playwright 没装. 跑: pip install playwright")
        sys.exit(1)

    with sync_playwright() as p:
        try:
            return launch_and_dispatch(args, p)
        except Exception as e:
            print(f"[ERR] launch_and_dispatch failed: {e}")
            print(f"      可能 chromium 没装. 跑: python -m playwright install chromium")
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
