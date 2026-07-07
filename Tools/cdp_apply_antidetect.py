r"""cdp_apply_antidetect.py - 把 AntiDetect 注入浏览器 (跨平台连接)。

两个模式:

  A) launch 模式: 自己起 chromium (跟 cdp_launch.py 一样), 但不做其他
     .venv/bin/python Tools/cdp_apply_antidetect.py launch --url <URL>

  B) attach 模式: 连接已经打开的 chromium (你手动启的、或 cdp_launch.py hold 启的)
     .venv/bin/python Tools/cdp_apply_antidetect.py attach --cdp http://localhost:9222

A 模式适合一次性验证 stealth (跟 stealth-test 一样)。
B 模式适合调试已登录的会话: cdp_launch.py hold 启后长开, 别人 attach 注入。

注: AntiDetect 注入一次后, 对该 tab 立刻生效。Tab reload 后还能生效是因为
    ctx.add_init_script() 也注册了 init script, 每次新 document 自动跑。
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


STEALTH_PROBE_JS = """(() => {
    const c = document.createElement('canvas');
    c.width = 200; c.height = 50;
    const ctx = c.getContext('2d');
    ctx.font = '14px Arial';
    ctx.fillText('probe', 10, 30);
    let canvasHash = '?';
    try { canvasHash = c.toDataURL().slice(0, 60); } catch(e) {}

    let audioHash = '?';
    try {
        const AC = window.OfflineAudioContext || window.AudioContext;
        if (AC) {
            const oac = new AC(1, 44100, 44100);
            const comp = oac.createDynamicsCompressor();
            comp.threshold.value = -24; comp.knee.value = 30;
            comp.ratio.value = 12; comp.attack.value = 0.003; comp.release.value = 0.25;
            audioHash = [comp.threshold.value, comp.knee.value, comp.ratio.value,
                         comp.attack.value, comp.release.value].join(',');
        }
    } catch(e) {}

    return {
        ua: navigator.userAgent,
        webdriver: navigator.webdriver,
        hardwareConcurrency: navigator.hardwareConcurrency,
        deviceMemory: navigator.deviceMemory,
        pluginsLen: (navigator.plugins && navigator.plugins.length) || 0,
        mimeTypesLen: (navigator.mimeTypes && navigator.mimeTypes.length) || 0,
        languages: navigator.languages,
        intlTz: new Intl.DateTimeFormat().resolvedOptions().timeZone,
        canvasFirst60: canvasHash,
        audioHash: audioHash,
        userAgentData: navigator.userAgentData
            && navigator.userAgentData.brands
            ? navigator.userAgentData.brands.map(b => b.brand + '/' + b.version).join(',')
            : null,
    };
})()"""


def probe_stealth(page):
    info = page.evaluate(STEALTH_PROBE_JS)
    print()
    print(f"  UA                  = {info['ua'][:80]}")
    print(f"  webdriver           = {info['webdriver']!r}")
    print(f"  hardwareConcurrency = {info['hardwareConcurrency']}")
    print(f"  deviceMemory        = {info['deviceMemory']}")
    print(f"  plugins length      = {info['pluginsLen']} (期望 2)")
    print(f"  mimeTypes length    = {info['mimeTypesLen']} (期望 1)")
    print(f"  languages           = {info['languages']}")
    print(f"  Intl timezone       = {info['intlTz']}")
    print(f"  userAgentData       = {info['userAgentData']}")
    print(f"  canvas[:60]         = {info['canvasFirst60']}")
    print(f"  audio hash          = {info['audioHash']}")
    print()

    checks = [
        ("navigator.webdriver 已遮",          info["webdriver"] in (None, "undefined")),
        ("hardwareConcurrency 已设",          isinstance(info["hardwareConcurrency"], int)),
        ("deviceMemory 已设",                 isinstance(info["deviceMemory"], (int, float))),
        ("plugins length == 2",               info["pluginsLen"] == 2),
        ("UA 不含 HeadlessChrome",            "HeadlessChrome" not in (info["ua"] or "")),
        ("userAgentData 含 Chromium",         info["userAgentData"] and "Chromium" in info["userAgentData"]),
    ]
    score = 0
    for label, ok in checks:
        print(f"  [{'OK'   if ok else 'FAIL'}] {label}")
        if ok:
            score += 1
    total = len(checks)
    print(f"\n  stealth score: {score}/{total}")
    return score, total


def cmd_launch(args):
    """Launch 模式: 启 chromium, 注入 AntiDetect, probe"""
    print(f"[launch] 启 chromium (headless={args.headless})")
    from playwright.sync_api import sync_playwright
    from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector

    cfg = AntiDetectConfig(fingerprint_seed=args.fingerprint_seed)
    js = AntiDetectInjector(cfg).get_inject_script()

    with sync_playwright() as p:
        if args.persistent:
            from pathlib import Path
            userdata = args.userdata_dir or str(Path.home() / ".cache" / "webauto" / "chromium")
            Path(userdata).mkdir(parents=True, exist_ok=True)
            ctx = p.chromium.launch_persistent_context(
                userdata,
                headless=args.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx.add_init_script(js)
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        else:
            browser = p.chromium.launch(
                headless=args.headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context()
            ctx.add_init_script(js)
            page = ctx.new_page()

        page.goto(args.url, wait_until="domcontentloaded", timeout=30000)
        print(f"[launch] 当前: {page.url}")
        print(f"[launch] 标题: {page.title()}")

        probe_stealth(page)

        ctx.close()
    return 0


def cmd_attach(args):
    """Attach 模式: 连 CDP, 注入 AntiDetect"""
    print(f"[attach] 连接 {args.cdp}")
    try:
        ver = json.loads(urllib.request.urlopen(args.cdp + "/json/version", timeout=3)
                         .read().decode("utf-8"))
        print(f"[attach] Browser: {ver.get('Browser')}")
    except Exception as e:
        print(f"[FAIL] {args.cdp}: {e}")
        return 1

    from playwright.sync_api import sync_playwright
    from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector

    cfg = AntiDetectConfig(fingerprint_seed=args.fingerprint_seed)
    js = AntiDetectInjector(cfg).get_inject_script()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0]
        ctx.add_init_script(js)
        for i, page in enumerate(ctx.pages):
            print(f"\n[inject] tab {i}: {page.url}")
            probe_stealth(page)
        browser.close()
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="AntiDetect 注入 + stealth probe (跨平台)",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_launch = sub.add_parser("launch", help="自己起 chromium")
    p_launch.add_argument("--url", default="https://example.com")
    p_launch.add_argument("--headless", action="store_true")
    p_launch.add_argument("--persistent", action="store_true")
    p_launch.add_argument("--userdata-dir", default=None)
    p_launch.add_argument("--fingerprint-seed", type=int, default=42)
    p_launch.set_defaults(func=cmd_launch)

    p_attach = sub.add_parser("attach", help="连接已开 CDP")
    p_attach.add_argument("--cdp", default="http://localhost:9222")
    p_attach.add_argument("--fingerprint-seed", type=int, default=42)
    p_attach.set_defaults(func=cmd_attach)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main() or 0)
