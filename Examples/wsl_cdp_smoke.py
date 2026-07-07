r"""WSL 内 chromium 自动化 - smoke 测试。

用法:
    # 1. 先确保 chromium 装了 (playwright install chromium 已自动)
    # 2. 第一次跑会让你手动登录 bigmodel.cn (弹窗、短信、点选验证码)
    # 3. 登录态会保存到 ~/.cache/ms-playwright (chromium userdata)
    # 4. 之后用 'persistent' mode 复用 userdata,跳过登录

    # 单跑 smoke (无头模式,debug 基线)
    .venv/bin/python Examples/wsl_cdp_smoke.py

    # 复用 userdata (有头模式,登录态保留)
    .venv/bin/python Examples/wsl_cdp_smoke.py --persistent --headed
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="WSL Chromium smoke test")
    parser.add_argument("--headed",      action="store_true",
                        help="有头模式(headless=False),便于第一次手动登录")
    parser.add_argument("--persistent",  action="store_true",
                        help="用持久 userdata dir,保留登录态 / AntiDetect fingerprint")
    parser.add_argument("--userdata-dir", default=None,
                        help="自定义 userdata 路径 (默认 ~/.cache/ms-playwright/chromium-userdata)")
    parser.add_argument("--target", default="https://bigmodel.cn",
                        help="打开的 URL (默认 bigmodel.cn)")
    parser.add_argument("--stealth", action="store_true",
                        help="注入我们的 AntiDetect (Core/AntiDetect.py)")
    parser.add_argument("--probe", action="store_true",
                        help="读 navigator / cookies 等指纹")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright

    userdata = args.userdata_dir or str(Path.home() / ".cache/ms-playwright/chromium-userdata")

    print(f"[INFO] Headless: {not args.headed}")
    print(f"[INFO] Persistent userdata: {args.persistent}")
    print(f"[INFO] Userdata dir: {userdata}")
    print(f"[INFO] Target URL: {args.target}")
    print(f"[INFO] Stealth inject: {args.stealth}")
    print()

    with sync_playwright() as p:
        try:
            if args.persistent:
                ctx = p.chromium.launch_persistent_context(
                    userdata,
                    headless=not args.headed,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                    viewport={"width": 1920, "height": 1080},
                )
                # persistent_context 直接返回一个 context,没有独立 browser
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
            else:
                browser = p.chromium.launch(
                    headless=not args.headed,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                ctx = browser.new_context(
                    viewport={"width": 1920, "height": 1080},
                )
                page = ctx.new_page()
                browser_obj = browser
        except Exception as e:
            print(f"[FAIL] Chromium 启动失败: {e}")
            print(f"       再跑一次 .venv/bin/python -m playwright install chromium")
            return 1

        # ---- 注入 AntiDetect ----
        if args.stealth:
            from Core.AntiDetect import AntiDetectInjector, AntiDetectConfig
            cfg = AntiDetectConfig(fingerprint_seed=42)
            inj = AntiDetectInjector(cfg)
            js = inj.get_inject_script()
            ctx.add_init_script(js)
            print(f"[INFO] AntiDetect inject script (stable seed 42) queued for new docs")
            print(f"[INFO] script length: {len(js)} bytes")

        # ---- 导航 ----
        print(f"[INFO] 打开 {args.target} ...")
        page.goto(args.target, wait_until="domcontentloaded", timeout=30000)

        # ---- probe ----
        if args.probe:
            info = page.evaluate("""(() => {
                const c = document.createElement('canvas');
                c.width = 200; c.height = 50;
                const ctx2d = c.getContext('2d');
                ctx2d.font = '14px Arial';
                ctx2d.fillText('probe', 10, 30);
                let canvasHash = '?';
                try { canvasHash = c.toDataURL().slice(0, 60); } catch(e) {}
                return {
                    url: location.href,
                    title: document.title,
                    ua: navigator.userAgent,
                    webdriver: navigator.webdriver,
                    hardwareConcurrency: navigator.hardwareConcurrency,
                    deviceMemory: navigator.deviceMemory,
                    pluginsLen: (navigator.plugins && navigator.plugins.length) || 0,
                    intlTz: new Intl.DateTimeFormat().resolvedOptions().timeZone,
                    canvasFirst60: canvasHash,
                    cookies: document.cookie,
                };
            })()""")
            print()
            print("=" * 60)
            print("[PROBE] 当前页面状态")
            print("=" * 60)
            for k, v in info.items():
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                print(f"  {k:24s} = {v_str}")
            print()

        # ---- 保持打开 ----
        if args.headed:
            print("[INFO] Headed mode, 浏览器窗口 30s 内关闭")
            print("       这段时间: 你可以手动操作(登录 / 验证码)")
            import time
            for i in range(30):
                time.sleep(1)
                print(f"\r  [waiting {30-i}s]", end="", flush=True)
            print()
        else:
            print("[INFO] headless, 1s 后关闭")

        try:
            ctx.close()
        except Exception:
            pass
        if not args.persistent:
            try:
                browser_obj.close()
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
