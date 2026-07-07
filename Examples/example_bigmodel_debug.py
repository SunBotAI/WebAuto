r"""真站调试示例: 边测边开发智谱 GLM Coding 抢购调试脚本。

注意: 这个示例 **假设你已经**:
    1. 在 Windows 上跑了 Tools\cdp_launch.bat (默认 reuse userdata)
    2. 在新 Chrome 里已经登录 bigmodel.cn 且保持窗口开着
    3. 你想在 WSL 这里一边开发调试脚本,一边 attach 到已登录 Chrome 实时操作

调试的 4 类操作:

1. demo_smoke_cdp()          WSL 连上 Chrome,打印 fingerprint + cookie 调试基线
2. demo_extract_token()      把已登录 Chrome 的 cookie / token 抽出来,
                              写到 examples/.secrets/bigmodel_session.json,
                              HttpFetcher 后续可直接复用
3. demo_apply_stealth()      在已登录 Chrome tab 上叠加 AntiDetect 注入,
                              跑 9 项 stealth 自检(看我们反检测在真站效果)
4. demo_quick_purchase()     端到端:登录弹窗→套餐页→preview API→
                              check API → 输出 pay_url(不真下单,只到 dry-run)

前置依赖:
    pip install playwright httpx pydantic loguru ntplib
    playwright install chromium

WARN: 真站调试是 **让代码改一遍、跑一遍、看一眼** 的循环,不直接对真实抢购 API 重发请求。
      涉及到抢预约链路时,只在开抢前以外的时段走 preview+check,真实下单链路不要在调试里跑。
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# ---- (1) CDP 连接 helper ----
CDP_DEFAULT = "http://localhost:9222"


def _connect_cdp(cdp=CDP_DEFAULT):
    """连上你已经开起来的 Chrome DevTools,返回 (browser, ctx, page)。"""
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.connect_over_cdp(cdp)
    ctx = browser.contexts[0]
    page = next((p for p in ctx.pages if "bigmodel.cn" in (p.url or "")), ctx.pages[0])
    return pw, browser, ctx, page


# ---- (2) 各 demo ----

def demo_smoke_cdp():
    """Demo 1: WSL 连上你已登录 Chrome,确认可读 fingerprint / cookies。

    期望: 如果你登录了且 cookie 还在,会看到 bigmodelJwt / acw_tc 等。
    """
    print("\n=== Demo 1: CDP smoke (读 Chrome tab 现状) ===")
    pw, browser, ctx, page = _connect_cdp()

    info = page.evaluate("""(() => ({
        url: location.href,
        title: document.title,
        ua: navigator.userAgent,
        webdriver: navigator.webdriver,
        cookies: document.cookie,
        intlTz: new Intl.DateTimeFormat().resolvedOptions().timeZone,
        lang: document.documentElement.lang,
    }))()""")
    print(json.dumps(info, indent=2, ensure_ascii=False))

    # CDP 拿所有 cookie (含 HttpOnly)
    cdp = ctx.new_cdp_session(page)
    cookies = cdp.send("Network.getCookies").get("cookies", [])
    bm_cookies = [c for c in cookies
                  if "bigmodel" in c.get("domain", "")
                  or "zhipu" in c.get("domain", "")]
    print(f"\n[OK] bigmodel 系 cookie: {len(bm_cookies)}")
    for c in bm_cookies:
        tag = "⭐" if "jwt" in c["name"].lower() else "  "
        print(f"  {tag} {c['name']:24s} domain={c['domain']} httpOnly={c['httpOnly']}")

    browser.close()
    pw.stop()


def demo_extract_token():
    """Demo 2: 把已登录 Chrome 的 cookie+token 抽到 JSON。

    下次你只需要把 HttpFetcher 的 cookie 喂进去就能跑 API,不需要再开 Chrome。
    """
    print("\n=== Demo 2: 抽 cookie+token (给 HttpFetcher 用) ===")
    from Tools.cdp_token_extract import main as extract_main
    out_path = ROOT / "examples" / ".secrets" / "bigmodel_session.json"
    # 调用工具,直接传参数避免 argparse
    sys.argv = ["cdp_token_extract.py",
                "--output", str(out_path),
                "--show-header"]
    # 这里用 main() 跑会重启 argparse,直接调用内部逻辑更干净:
    # 借用 cdp_token_extract 的逻辑: 接 cdp + 抽 cookie + 写文件
    print("(用 Tools/cdp_token_extract.py 的逻辑,写到 {})".format(out_path))

    # 复用 cdp_token_extract 的核心代码(简化版)
    pw, browser, ctx, page = _connect_cdp()
    cdp = ctx.new_cdp_session(page)
    cookies = cdp.send("Network.getCookies").get("cookies", [])
    cookies = [c for c in cookies
               if "bigmodel" in c.get("domain", "") or "zhipu" in c.get("domain", "")]
    cookies_by_domain = {}
    for c in cookies:
        cookies_by_domain.setdefault(c["domain"], {})[c["name"]] = c["value"]
    cookie_header = "; ".join(f"{k}={v}" for d in cookies_by_domain.values() for k, v in d.items())

    ls = page.evaluate("() => JSON.stringify(localStorage)")
    ss = page.evaluate("() => JSON.stringify(sessionStorage)")
    result = {
        "pageUrl":         page.url,
        "extractedAt":     page.evaluate("() => new Date().toISOString()"),
        "cookies":         cookies_by_domain,
        "cookies_header":  cookie_header,
        "localStorage":    json.loads(ls) if ls else {},
        "sessionStorage":  json.loads(ss) if ss else {},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n[OK] 写到 {out_path}")
    print(f"     含 {len(cookie_header)} 字符 Cookie header + "
          f"{sum(len(v) for v in cookies_by_domain.values())} 个 cookie + "
          f"{len(result['localStorage'])} 个 localStorage 项")
    print(f"     ⭐ token 类:")
    for dom, kvs in cookies_by_domain.items():
        for k in kvs:
            if "jwt" in k.lower() or "acw_tc" in k.lower():
                print(f"       {dom} {k} (已保存到 JSON,不值)")
    print()
    print("提示: 读出来 JSON 后,可以喂给 HttpFetcher:")
    print("      fetch = HttpFetcher(config={")
    print(f"          'cookies_header': '...' (从 {out_path.name}.cookies_header 读),")
    print("      })")

    browser.close()
    pw.stop()


def demo_apply_stealth():
    """Demo 3: 在已登录 Chrome tab 注入 AntiDetect,跑 9 项 stealth 自检。"""
    print("\n=== Demo 3: AntiDetect 注入 + stealth 自检 ===")
    from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector
    pw, browser, ctx, page = _connect_cdp()

    cfg = AntiDetectConfig()
    cfg.fingerprint_seed = 12345  # 让你多次跑的结果一致
    injector = AntiDetectInjector(cfg)
    js = injector.get_inject_script()
    page.evaluate("() => { " + js + " }")

    probe = """(() => {
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
            ua:                 navigator.userAgent,
            webdriver:          navigator.webdriver,
            hardwareConcurrency: navigator.hardwareConcurrency,
            deviceMemory:       navigator.deviceMemory,
            pluginsLen:         (navigator.plugins && navigator.plugins.length) || 0,
            mimeTypesLen:       (navigator.mimeTypes && navigator.mimeTypes.length) || 0,
            languages:          navigator.languages,
            intlTz:             new Intl.DateTimeFormat().resolvedOptions().timeZone,
            canvasFirst60:      canvasHash,
            audioHash:          audioHash,
            userAgentData:      navigator.userAgentData
                                    && navigator.userAgentData.brands
                                    ? navigator.userAgentData.brands.map(b => b.brand + '/' + b.version).join(',')
                                    : null,
        };
    })()"""
    info = page.evaluate(probe)

    print()
    print("--- stealth probe ---")
    for k, v in info.items():
        if isinstance(v, str) and len(v) > 100:
            v = v[:100] + "..."
        print(f"  {k:24s} = {v}")
    print()

    checks = [
        ("navigator.webdriver 已遮",   info["webdriver"] in (None, "undefined")),
        ("hardwareConcurrency 已设",   isinstance(info["hardwareConcurrency"], int)),
        ("deviceMemory 已设",          isinstance(info["deviceMemory"], (int, float))),
        ("plugins length == 2",        info["pluginsLen"] == 2),
        ("UserAgent 不含 HeadlessChrome", "HeadlessChrome" not in (info["ua"] or "")),
        ("userAgentData 有 Chromium",  info["userAgentData"] and "Chromium" in info["userAgentData"]),
    ]
    for label, ok in checks:
        print(f"  [{'OK' if ok else 'FAIL'}] {label}")
    print(f"\n  本次 stealth score: "
          f"{sum(1 for _, ok in checks if ok)}/{len(checks)}")

    browser.close()
    pw.stop()


async def demo_quick_purchase(dry_run=True):
    """Demo 4: 端到端 preview+check,但不真下单(dry-run 模式)。

    用演示 session.json 里的 cookie喂给 HttpFetcher,跑一次 preview 拿 bizId,
    然后 check 校验,看服务端返回什么。不调 createBankOrder 就不会真下单。
    """
    print("\n=== Demo 4: preview+check 端到端(dry-run) ===")

    # 1) 加载 session
    session_path = ROOT / "examples" / ".secrets" / "bigmodel_session.json"
    if not session_path.exists():
        print(f"[ERR] 没找到 {session_path}, 先跑 demo_extract_token()")
        return
    session = json.loads(session_path.read_text(encoding="utf-8"))
    cookie_header = session["cookies_header"]
    page_url = session["pageUrl"]
    print(f"[OK] 加载 session, {len(cookie_header)} 字符 Cookie,page {page_url}")

    # 2) 用 HttpFetcher 调 preview(智谱 GLM Coding 的 preview 端点)
    from Core.Fetchers.http import HttpFetcher
    from Core.Zhipu.constants import PATH_PREVIEW, PATH_CHECK, PATH_BATCH_PREVIEW, BASE_URL

    fetcher = HttpFetcher(config={
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "headers": {
            "Cookie": cookie_header,
            "Origin": BASE_URL,
            "Referer": page_url,
        },
    })
    await fetcher.init()
    try:
        # 3) preview: 试 MAX 包年 (tuple 是 (Plan, Cycle) → productId)
        from Core.Zhipu.constants import PRODUCT_ID_REFERENCE
        from Core.Zhipu.config import Plan, BillingCycle
        plan = Plan.MAX
        cycle = BillingCycle.YEARLY
        product_id = PRODUCT_ID_REFERENCE.get((plan.value, cycle.value))
        if not product_id:
            print(f"[ERR] PRODUCT_ID_REFERENCE 里没有 ({plan.value}, {cycle.value})")
            return
        preview_url = f"{BASE_URL}{PATH_PREVIEW}"
        # preview body 形态参考 GlmCodingGrabber 抓的真实请求(我们就照搬字段)
        body = {
            "productId": product_id,
            "count":     1,
            "couponId":  None,
        }
        print(f"\n[REQ] POST {preview_url}")
        print(f"      body: {json.dumps(body, ensure_ascii=False)}")

        resp = await fetcher.post(preview_url, json=body)
        body_preview = resp.text[:400] if hasattr(resp, "text") else str(resp)[:400]
        print(f"[RESP] status={resp.status_code}  body[:400]: {body_preview}")

        # 4) 简化抽取 bizId
        try:
            data = resp.json() if hasattr(resp, "json") else json.loads(resp.text)
            biz_id = (data.get("data") or {}).get("bizId") or data.get("bizId")
        except Exception as e:
            biz_id = None
            data = {}
            print(f"[WARN] preview resp 不是 JSON: {e}")

        if biz_id:
            print(f"\n[OK] preview 拿到 bizId: {biz_id[:8]}...")

            # 5) check: 验证 bizId
            check_url = f"{BASE_URL}{PATH_CHECK}"
            check_body = {"bizId": biz_id}
            print(f"\n[REQ] POST {check_url}")
            print(f"      body: {json.dumps(check_body, ensure_ascii=False)}")
            check_resp = await fetcher.post(check_url, json=check_body)
            print(f"[RESP] status={check_resp.status_code}  body[:400]: "
                  f"{(check_resp.text if hasattr(check_resp,'text') else str(check_resp))[:400]}")

            if dry_run:
                print("\n[DRY-RUN] 拿到 bizId 通过 check 就停止。不调 createBankOrder。")
                print("         真下单请去掉 dry_run 参数,但 **慎重**,会影响账号风控画像。")
        else:
            print("\n[INFO] preview 没返回 bizId -- 看完 resp body 就停。")
            print("       (可能是 cookie 失效 / 套餐下架 / 接口字段变了)")
    finally:
        await fetcher.close()


async def main():
    """4 个 demo 全部跑一遍(按需注释)。"""
    demo_smoke_cdp()
    demo_extract_token()
    demo_apply_stealth()
    await demo_quick_purchase(dry_run=True)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "only-smoke":
        demo_smoke_cdp()
    else:
        asyncio.run(main())
