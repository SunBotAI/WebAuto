r"""WSL 内 chromium 持久化 - 4 种常用模式。

4 个独立子命令(独立场景,按需调用):

  first-run   第一次跑: 启 + 让你手动登录 bigmodel.cn (10 分钟窗口)
  visit       日常用: 复用已登录 userdata, 长开 5 分钟做手动操作
  stealth-test 跑 5 个公开检测站, 给 stealth 自检报告
  hold        永久挂着 (1h), 别的脚本可以通过 CDP 端口 attach

用法:
    # Step 1: 第一次登录 (headed, 10 分钟)
    .venv/bin/python Examples/wsl_persistent_browser.py first-run

    # Step 2: 之后复用 (headed, 5 分钟)
    .venv/bin/python Examples/wsl_persistent_browser.py visit

    # Step 3: stealth 自检 (headless, 不需要登录)
    .venv/bin/python Examples/wsl_persistent_browser.py stealth-test

    # 选项: --hold-minutes N 覆盖默认时长
    .venv/bin/python Examples/wsl_persistent_browser.py visit --hold-minutes 30
"""
import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

USERDATA_DIR = Path.home() / ".cache/ms-playwright/chromium-userdata"


def launch_chromium(p, *, headless=False, persistent=True, fingerprint_seed=42):
    """启一个 chromium, 默认带 AntiDetect 注入。"""
    from Core.AntiDetect import AntiDetectInjector, AntiDetectConfig
    cfg = AntiDetectConfig(fingerprint_seed=fingerprint_seed)
    js = AntiDetectInjector(cfg).get_inject_script()

    if persistent:
        ctx = p.chromium.launch_persistent_context(
            str(USERDATA_DIR),
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
            viewport={"width": 1920, "height": 1080},
        )
    else:
        browser = p.chromium.launch(
            headless=headless,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        ctx = browser.new_context(viewport={"width": 1920, "height": 1080})
    ctx.add_init_script(js)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    return ctx, page


def wait_seconds(secs, label="", page=None, watch_for=None):
    """wait + watch, 缩短时显示进度, watch_for 字符串出现就提前结束。"""
    print(f"[{label}] 等待 {secs}s (你在浏览器手动操作)")
    for i in range(secs):
        time.sleep(1)
        if i % 10 == 0:
            print(f"\r  [{secs - i}s left]", end="", flush=True)
        if watch_for and page is not None:
            try:
                if watch_for in (page.url or ""):
                    print(f"\n[{label}] 检测到成功页: {page.url}")
                    return True
            except Exception:
                pass
    print()
    return False


# ---- 4 个命令 ----

def cmd_first_run(args, p):
    """第一次跑: 登录 bigmodel.cn"""
    print("[first-run] 启 headed chromium + 持久 userdata + AntiDetect")
    ctx, page = launch_chromium(p, headless=False)
    print(f"[first-run] userdata 目录: {USERDATA_DIR}")
    print(f"[first-run] 打开 https://bigmodel.cn/glm-coding")
    page.goto("https://bigmodel.cn/glm-coding",
              wait_until="domcontentloaded", timeout=30000)
    print()
    print("=" * 60)
    print("请在弹出的浏览器窗口完成登录:")
    print("  1) 点击右上角登录按钮")
    print("  2) 输入手机号 + 短信验证码")
    print("  3) 中文点选验证码 (按提示顺序点击 4 个汉字)")
    print("  4) 登录成功后会到套餐页或用户中心")
    print("=" * 60)
    print()

    secs = args.hold_minutes * 60
    wait_seconds(secs, "first-run", page=page,
                 watch_for="/user-center")
    print(f"[first-run] 结束 (userdata 已保存, 下次直接 'visit')")
    ctx.close()
    return 0


def cmd_visit(args, p):
    """日常: 复用 userdata"""
    print("[visit] 启 headed chromium + 复用 userdata")
    ctx, page = launch_chromium(p, headless=False)
    page.goto("https://bigmodel.cn/glm-coding",
              wait_until="domcontentloaded", timeout=30000)
    print(f"[visit] 当前页: {page.url}")
    print(f"[visit] 标题: {page.title()}")
    print()
    wait_seconds(args.hold_minutes * 60, "visit", page=page)
    ctx.close()
    return 0


def cmd_stealth_test(args, p):
    """跑 5 个公开检测站"""
    print("[stealth-test] 启 headless chromium + AntiDetect")
    print("[stealth-test] 跑 5 个公开检测站 ...")
    ctx, page = launch_chromium(p, headless=True)

    targets = [
        ("bot.sannysoft.com",    "https://bot.sannysoft.com",
         "经典 webdriver / plugins / languages 检测"),
        ("creepjs",              "https://abrahamjuliot.github.io/creepjs/",
         "2024+ 综合 stealth 检测 (业界最难之一)"),
        ("fingerprintjs",        "https://fingerprintjs.github.io/fingerprintjs/",
         "FingerprintJS 官方 demo"),
        ("browserleaks-canvas",  "https://browserleaks.com/canvas",
         "Canvas 指纹 hash"),
        ("browserleaks-webgl",   "https://browserleaks.com/webgl",
         "WebGL 渲染器 / vendor"),
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
                intlLang: new Intl.DateTimeFormat().resolvedOptions().locale,
                containsHeadlessChrome: navigator.userAgent.includes('HeadlessChrome'),
                userAgentDataBrands: navigator.userAgentData
                    && navigator.userAgentData.brands
                    ? navigator.userAgentData.brands.map(b => b.brand).join(',')
                    : null,
                hasChromeObj: !!window.chrome,
                pwInitScripts: window.__pwInitScripts,
            }))()""")

            checks = [
                ("webdriver 已遮",   info["webdriver"] in (None, "undefined")),
                ("hardwareConcurrency 数值合理", isinstance(info["hardwareConcurrency"], int) and 4 <= info["hardwareConcurrency"] <= 32),
                ("deviceMemory 数值合理", isinstance(info["deviceMemory"], (int, float)) and info["deviceMemory"] in (4, 8, 16)),
                ("UA 不含 HeadlessChrome", not info["containsHeadlessChrome"]),
                ("userAgentData 有 chromium", info["userAgentDataBrands"] and "Chromium" in info["userAgentDataBrands"]),
                ("plugins length == 2", info["pluginsLen"] == 2),
            ]
            passed = sum(1 for _, ok in checks if ok)
            total = len(checks)
            total_score += passed
            total_total += total

            print(f"    score: {passed}/{total}")
            print(f"    UA: {info['ua'][:80]}")
            for label, ok in checks:
                mark = "[OK]  " if ok else "[FAIL]"
                print(f"      {mark} {label}")
        except Exception as e:
            print(f"    ERROR: {e}")
            total_total += 1

    print()
    print(f"=== 总计: {total_score}/{total_total} ({(total_score/total_total*100) if total_total else 0:.0f}%) ===")
    ctx.close()
    return 0


def cmd_hold(args, p):
    """永久挂着, 别的脚本可 attach"""
    print("[hold] 启 chromium (headed) + 持久 userdata")
    print(f"[hold] userdata: {USERDATA_DIR}")
    ctx, page = launch_chromium(p, headless=False)
    page.goto("about:blank")
    print("[hold] ready. 你可以手动操作这个窗口")
    print(f"[hold] 保持 {args.hold_minutes} 分钟")
    wait_seconds(args.hold_minutes * 60, "hold", page=page)
    ctx.close()
    return 0


def main():
    parser = argparse.ArgumentParser(description="WSL persistent chromium driver")
    parser.add_argument("command",
                        choices=["first-run", "visit", "stealth-test", "hold"],
                        help="操作模式")
    parser.add_argument("--hold-minutes", type=int, default=10,
                        help="窗口保持多少分钟")
    args = parser.parse_args()

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        if args.command == "first-run":
            return cmd_first_run(args, p)
        if args.command == "visit":
            return cmd_visit(args, p)
        if args.command == "stealth-test":
            return cmd_stealth_test(args, p)
        if args.command == "hold":
            return cmd_hold(args, p)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
