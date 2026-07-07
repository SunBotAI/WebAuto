#!/usr/bin/env python3
"""
Stealth Playwright PoC — 反爬验证
使用 WebAuto 现有 Chromium + 完整 stealth JS evasions

用法:
    cd /mnt/f/Project/WebAuto
    python3 Services/stealth_poc.py

环境变量:
    STEALTH_HEADLESS=0  # 显示浏览器窗口
"""

import os
import sys
import time
from datetime import datetime

# ── 配置 ─────────────────────────────────────────────────────────────────────
HEADLESS = os.getenv("STEALTH_HEADLESS", "1") == "1"
CHROMIUM_PATH = "/home/claw/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome"
REPORT_DIR = "/mnt/f/Project/WebAuto/docs/reports"
REPORT_PATH = os.path.join(REPORT_DIR, "stealth_poc_report.md")
os.makedirs(REPORT_DIR, exist_ok=True)

# ── 测试站点 ─────────────────────────────────────────────────────────────────
TEST_SITES = [
    {
        "name": "SannySoft Bot Detection",
        "url": "https://bot.sannysoft.com/",
        "wait": 5000,
        "desc": "专业浏览器指纹测试",
    },
    {
        "name": "BrowserLeaks Canvas",
        "url": "https://browserleaks.com/canvas",
        "wait": 4000,
        "desc": "Canvas fingerprint 检测",
    },
    {
        "name": "IPRoyal Proxy Check",
        "url": "https://iproyal.com/check",
        "wait": 3000,
        "desc": "IP/代理检测",
    },
]

# ── Stealth JS Evasions ──────────────────────────────────────────────────────
# 每个脚本是一个独立的 JS 片段，通过 add_init_script 注入

STEALTH_SCRIPTS = [

    # 0. User Agent 伪装 (必须在最前面，覆盖 HeadlessChrome/149)
    """
    (function() {
        var realUA = 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36';
        Object.defineProperty(navigator, 'userAgent', {
            get: function() { return realUA; },
            set: function(v) { Object.getOwnPropertyDescriptor(navigator, 'userAgent').set.call(this, realUA); },
            configurable: true,
            enumerable: true
        });
        // Also override appVersion for good measure
        Object.defineProperty(navigator, 'appVersion', {
            get: function() { return realUA; },
            configurable: true,
            enumerable: true
        });
    })();
    """,

    # 1. 移除 webdriver 标志 (彻底删除，不只是设 false)
    """
    (function() {
        // 完全删除 navigator.webdriver 属性
        try {
            delete Object.getPrototypeOf(navigator).webdriver;
        } catch(e) {}
        // 也清理可能存在的 automation 标志
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
        delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
        delete window.navigator.webdriver;
    })();
    """,

    # 2. navigator.plugins / mimeTypes — 5 个插件 (SannySoft 检测 Plugins Length === 5)
    # Chrome 默认有 ~5 个插件，所以我们需要模拟一个接近真实浏览器的列表
    """
    (function() {
        var _plugins = [
            { name: 'Chrome PDF Plugin', description: 'Portable Document Format', filename: 'internal-pdf-viewer' },
            { name: 'Chrome PDF Viewer', description: 'Portable Document Format', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai' },
            { name: 'Native Client', description: '', filename: 'internal-nacl-plugin' },
            { name: 'Chrome Quick Share', description: '', filename: 'quick-share' },
            { name: 'Google Update', description: '', filename: 'GoogleUpdate' }
        ];
        _plugins.namedItem = function(n) { return this.find(function(p){ return p.name === n; }) || null; };
        _plugins.item = function(i) { return this[i] || null; };
        _plugins.__proto__ = PluginArray.prototype;

        var _mimeTypes = [
            { type: 'application/pdf', suffixes: 'pdf', description: 'pdf', enabledPlugin: _plugins[0] },
            { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client', enabledPlugin: _plugins[2] }
        ];
        _mimeTypes.namedItem = function(t) { return this.find(function(m){ return m.type === t; }) || null; };
        _mimeTypes.item = function(i) { return this[i] || null; };
        _mimeTypes.__proto__ = MimeTypeArray.prototype;

        Object.defineProperty(navigator, 'plugins', { get: function() { return _plugins; }, configurable: true, enumerable: true });
        Object.defineProperty(navigator, 'mimeTypes', { get: function() { return _mimeTypes; }, configurable: true, enumerable: true });
    })();
    """

    # 3. chrome.loadTimes / chrome.csi
    """
    (function() {
        if (!window.chrome) window.chrome = {};
        window.chrome.loadTimes = function() {
            return {
                connectionInfo: 'h2',
                documentId: '0.' + Math.random().toString(36).slice(2),
                documentReadyState: 'complete',
                incomingCount: 0,
                isBackground: false,
                isFirstPaintInNonEmptyDocument: true,
                isMainFrame: true,
                isMarimba: false,
                navigationType: 'Other',
                newVolumeReading: 0,
                outgoingCount: 0,
                paintedWidth: 1920,
                rawheadersTime: 0.001,
                requestTime: (performance.now ? performance.now() : Date.now()) / 1000 - 0.1,
                startTime: (performance.now ? performance.now() : Date.now()) / 1000 - 0.2,
                wasAlternateProtocolAvailable: false,
                wasFetchedViaH2Proxy: false,
                wasNpnNegotiated: false,
                wasSpdyNegotiated: false,
                wasTlsResumed: false
            };
        };
        window.chrome.csi = function() { return { onloadT: Date.now(), pageT: Date.now() }; };
    })();
    """,

    # 4. WebGL vendor/renderer 伪装
    # 核心: 劫持 getExtension，返回假的 WEBGL_debug_renderer_info
    """
    (function() {
        var FAKE_VENDOR = 'Intel Inc.';
        var FAKE_RENDERER = 'Intel Iris OpenGL Engine';
        var VENDOR_PARAM = 37445;
        var RENDERER_PARAM = 37446;

        function makeFakeDebugInfo(ctx) {
            return {
                UNMASKED_VENDOR_WEBGL: VENDOR_PARAM,
                UNMASKED_RENDERER_WEBGL: RENDERER_PARAM,
                getParameter: function(p) {
                    if (p === VENDOR_PARAM) return FAKE_VENDOR;
                    if (p === RENDERER_PARAM) return FAKE_RENDERER;
                    return ctx.getParameter(p);
                }
            };
        }

        // Stub getExtension for all WebGLRenderingContext instances
        var _origGetExt = WebGLRenderingContext.prototype.getExtension;
        WebGLRenderingContext.prototype.getExtension = function(name) {
            if (name === 'WEBGL_debug_renderer_info') {
                return makeFakeDebugInfo(this);
            }
            return _origGetExt.call(this, name);
        };

        // Also handle WebGL2
        if (typeof WebGL2RenderingContext !== 'undefined') {
            var _origGetExt2 = WebGL2RenderingContext.prototype.getExtension;
            WebGL2RenderingContext.prototype.getExtension = function(name) {
                if (name === 'WEBGL_debug_renderer_info') {
                    return makeFakeDebugInfo(this);
                }
                return _origGetExt2.call(this, name);
            };
        }

        // And intercept getContext so any new contexts get the stub
        var _origGetContext = HTMLCanvasElement.prototype.getContext;
        HTMLCanvasElement.prototype.getContext = function(type) {
            var ctx = _origGetContext.call(this, type);
            if (ctx && (type === 'webgl' || type === 'webgl2')) {
                var _origExt = ctx.getExtension.bind(ctx);
                ctx.getExtension = function(name) {
                    if (name === 'WEBGL_debug_renderer_info') {
                        return makeFakeDebugInfo(ctx);
                    }
                    return _origExt(name);
                };
            }
            return ctx;
        };
    })();
    """,

    # 5. navigator.hardwareConcurrency / deviceMemory
    """
    Object.defineProperty(navigator, 'hardwareConcurrency', { get: function() { return 8; }, configurable: true });
    Object.defineProperty(navigator, 'deviceMemory', { get: function() { return 8; }, configurable: true });
    """,

    # 6. chrome.runtime 清理
    """
    (function() {
        if (typeof chrome !== 'undefined' && chrome.runtime) {
            try { Object.defineProperty(chrome.runtime, 'id', { get: function() { return undefined; }, configurable: true }); } catch(e) {}
        }
    })();
    """,

    # 7. permissions.query 模拟
    """
    (function() {
        if (navigator.permissions && navigator.permissions.query) {
            var _origQuery = navigator.permissions.query.bind(navigator.permissions);
            navigator.permissions.query = function(query) {
                return _origQuery(query).then(function(result) {
                    Object.defineProperty(result, 'state', {
                        get: function() {
                            if (query.name === 'notifications') return 'default';
                            if (query.name === 'geolocation') return 'prompt';
                            if (query.name === 'camera') return 'prompt';
                            if (query.name === 'microphone') return 'prompt';
                            return 'granted';
                        },
                        configurable: true
                    });
                    return result;
                }).catch(function(e) { return e; });
            };
        }
    })();
    """,

    # 8. window.outerdimensions
    """
    (function() {
        try {
            Object.defineProperty(window, 'outerWidth', { get: function() { return 1920; }, configurable: true });
            Object.defineProperty(window, 'outerHeight', { get: function() { return 1080; }, configurable: true });
            Object.defineProperty(window, 'screenX', { get: function() { return 0; }, configurable: true });
            Object.defineProperty(window, 'screenY', { get: function() { return 0; }, configurable: true });
            Object.defineProperty(window, 'screenTop', { get: function() { return 0; }, configurable: true });
            Object.defineProperty(window, 'screenLeft', { get: function() { return 0; }, configurable: true });
        } catch(e) {}
    })();
    """,

    # 9. Notification permission
    """
    Object.defineProperty(Notification, 'permission', { get: function() { return 'default'; }, configurable: true });
    """,

    # 10. languages (SannySoft 检测 zh-CN，需要 en-US)
    """
    Object.defineProperty(navigator, 'languages', {
        get: function() { return ['en-US', 'en']; },
        configurable: true,
        enumerable: true
    });
    Object.defineProperty(navigator, 'language', {
        get: function() { return 'en-US'; },
        configurable: true,
        enumerable: true
    });
    """,
]

# ── 辅助函数 ─────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def save_screenshot(page, name: str) -> str:
    safe = name.replace(" ", "_").lower()[:40]
    out = os.path.join(REPORT_DIR, f"{safe}.png")
    page.screenshot(path=out, full_page=True)
    return out


def run_test(site: dict) -> dict:
    from playwright.sync_api import sync_playwright

    result = {
        "name": site["name"],
        "url": site["url"],
        "passed": False,
        "error": None,
        "details": "",
        "screenshot": None,
        "duration_ms": 0,
    }

    start = time.time()

    try:
        log(f"🚀 {site['name']}")

        with sync_playwright() as p:
            browser = p.chromium.launch(
                executable_path=CHROMIUM_PATH,
                headless=HEADLESS,
                args=[
                    # 关键: 移除 headless 自动化标志（webdriver 检测核心）
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--no-first-run",
                    "--no-zygote",
                    "--window-size=1920,1080",
                    # 禁用 WebGL SwiftShader (强制使用真实驱动)
                    "--disable-gpu",
                ],
            )

            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )

            for i, script in enumerate(STEALTH_SCRIPTS):
                context.add_init_script(script)
            log(f"  injected {len(STEALTH_SCRIPTS)} stealth scripts")

            page = context.new_page()
            page.set_default_timeout(30000)

            page.goto(site["url"], wait_until="domcontentloaded", timeout=30000)
            time.sleep(site["wait"] / 1000)

            # ── 站点结果判定 ────────────────────────────────────────────────
            if "bot.sannysoft" in site["url"]:
                try:
                    rows = page.query_selector_all("table tr")
                    lines = []
                    passed = 0
                    for row in rows:
                        cells = row.query_selector_all("td")
                        if len(cells) >= 2:
                            label = cells[0].inner_text().strip()
                            status = cells[1].inner_text().strip()
                            if status in ("passed", "failed"):
                                icon = "✅" if status == "passed" else "❌"
                                lines.append(f"  {icon} {label}: {status}")
                                if status == "passed":
                                    passed += 1
                    result["details"] = "\n".join(lines[:20])
                    # 通过条件: 60% 以上 passed
                    total = passed + sum(1 for l in lines if l.startswith("  ❌"))
                    result["passed"] = total > 0 and passed >= total * 0.6
                    log(f"  {'✅' if result['passed'] else '❌'} SannySoft: {passed}/{total} passed")
                except Exception as e:
                    result["error"] = str(e)

            elif "browserleaks" in site["url"]:
                try:
                    title = page.title()
                    body = page.inner_text("body")[:400]
                    result["details"] = f"Title: {title}\n{body[:300]}"
                    result["passed"] = len(body) > 30
                    log(f"  {'✅' if result['passed'] else '❌'} BrowserLeaks loaded")
                except Exception as e:
                    result["error"] = str(e)

            else:
                # 通用: 能拿到非空 body 即通过
                try:
                    body = page.inner_text("body")[:300]
                    result["details"] = body[:300]
                    result["passed"] = len(body) > 10
                    log(f"  {'✅' if result['passed'] else '❌'} loaded {len(body)} chars")
                except Exception as e:
                    result["error"] = str(e)

            result["screenshot"] = save_screenshot(page, site["name"])
            context.close()
            browser.close()

    except Exception as e:
        result["error"] = str(e)
        log(f"  ❌ ERROR: {e}")
        try:
            context.close()
            browser.close()
        except Exception:
            pass

    result["duration_ms"] = int((time.time() - start) * 1000)
    return result


def generate_report(results: list) -> str:
    lines = [
        "# Stealth Playwright PoC 报告",
        f"\n**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n**Chromium:** `{CHROMIUM_PATH}`",
        f"\n**模式:** {'Headless' if HEADLESS else 'Visible'}",
        f"\n**Stealth evasions:** {len(STEALTH_SCRIPTS)} 个 JS 脚本",
        "\n---\n",
    ]
    for r in results:
        status = "✅ PASSED" if r["passed"] else "❌ FAILED"
        lines.append(f"\n## {r['name']} — {status}")
        lines.append(f"\n**URL:** {r['url']}")
        lines.append(f"\n**耗时:** {r['duration_ms']/1000:.1f}s")
        if r["error"]:
            lines.append(f"\n**错误:** `{r['error']}`")
        if r["details"]:
            lines.append(f"\n**详情:**\n```\n{r['details']}\n```")
        if r["screenshot"]:
            lines.append(f"\n**截图:** `{r['screenshot']}`")

    passed = sum(1 for r in results if r["passed"])
    lines.append(f"\n---\n\n**总结:** {passed}/{len(results)} 通过")

    report = "\n".join(lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    return report


# ── 主入口 ───────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("Stealth Playwright PoC 开始")
    log(f"Chromium: {CHROMIUM_PATH}")
    log("=" * 60)

    if not os.path.exists(CHROMIUM_PATH):
        print(f"❌ Chromium 不存在: {CHROMIUM_PATH}")
        return 1

    results = []
    for site in TEST_SITES:
        r = run_test(site)
        results.append(r)
        time.sleep(1)

    generate_report(results)
    log(f"报告: {REPORT_PATH}")

    print("\n" + "=" * 60)
    print("结果:")
    for r in results:
        print(f"  {'✅' if r['passed'] else '❌'} {r['name']} ({r['duration_ms']/1000:.1f}s)")
    print("=" * 60)

    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
