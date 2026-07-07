r"""CDP token extract: 把 bigmodel.cn 登录态从 Chrome 抽出来给 HttpFetcher 用。

动机:
    调试 HttpFetcher / Core/Zhipu 时,不再需要每次开 Chrome 重发请求。
    直接把已登录 Chrome 的 cookie / token 抽出来 → JSON / HTTP header 格式导出。

用法:
    # 看 bigmodel.cn tab 有哪些相关 cookie / token(打印,不导出)
    .venv/bin/python Tools/cdp_token_extract.py

    # 导出成 JSON 到 /tmp/bigmodel_token.json
    .venv/bin/python Tools/cdp_token_extract.py --output /tmp/bigmodel_token.json

    # 同时打印 HTTP Cookie header 格式(可粘贴给 curl / httpx)
    .venv/bin/python Tools/cdp_token_extract.py --show-header

    # 抽所有 domain 下的 cookie(不光是 bigmodel.cn)
    .venv/bin/python Tools/cdp_token_extract.py --all-domains

输出 JSON 结构:
    {
      "cookies": {
        "bigmodel.cn": {"bigmodelJwt": "...", "acw_tc": "...", ...},
        ".bigmodel.cn": {...},
      },
      "cookies_header": "bigmodelJwt=xxx; acw_tc=yyy; ...",
      "localStorage":  {...},   # bigmodel.cn 下所有
      "sessionStorage": {...},
      "pageUrl":       "https://bigmodel.cn/glm-coding",
      "extractedAt":    1720000000.123,
    }

注意:
    - Cookie 值 **完整导出**(你自己保存到本地)
    - 不要 commit 到 git
    - 用 --show-header 时打印的也是完整 cookie
"""
import argparse
import datetime
import json
import os
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# 智谱 bigmodel 系的核心 cookie 名(优先级排序)
_KEY_COOKIE_HINTS = (
    "bigmodeljwt", "bigmodel_jwt", "jwt",
    "acw_tc",       # 阿里云 WAF 风控
    "authorization",
    "x-auth-token",
)


def main():
    parser = argparse.ArgumentParser(description="CDP cookie/token 抽取")
    parser.add_argument("--cdp",         default="http://localhost:9222", help="CDP endpoint URL")
    parser.add_argument("--match",       default="bigmodel.cn",           help="URL 子串匹配哪个 tab")
    parser.add_argument("--output",       default=None,                    help="写到 JSON 文件")
    parser.add_argument("--show-header", action="store_true",             help="打印 HTTP Cookie header 格式")
    parser.add_argument("--all-domains",  action="store_true",             help="抽所有 domain 的 cookie,不光是 bigmodel.cn")
    args = parser.parse_args()

    # 验证 CDP 在监听
    try:
        version = json.loads(
            urllib.request.urlopen(args.cdp + "/json/version", timeout=3)
            .read().decode("utf-8")
        )
        print(f"[OK] DevTools 在监听: {version.get('Browser')}")
    except Exception as e:
        print(f"[FAIL] 连不上 {args.cdp}: {e}")
        return 1

    targets = json.loads(urllib.request.urlopen(args.cdp + "/json", timeout=3).read().decode("utf-8"))
    tabs = [t for t in targets if t.get("type") == "page" and args.match in (t.get("url") or "")]
    if not tabs:
        print(f"[FAIL] 没匹配 '{args.match}' 的 tab。")
        for t in [t for t in targets if t.get("type") == "page"]:
            print(f"  - {t.get('title', '')[:40]:40s} | {t.get('url', '')[:60]}")
        return 1

    tab = tabs[0]
    print(f"[OK] 匹配 tab: {tab.get('title')}")
    print(f"     URL:      {tab.get('url')}")
    print()

    # 这里仅打印 user-facing 安全提示,不动 args.output 逻辑。

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0]

        # 找到 attach 的 page
        page = None
        for pg in ctx.pages:
            if tab.get("url") in (pg.url or ""):
                page = pg
                break
        if page is None and ctx.pages:
            page = ctx.pages[0]
        if page is None:
            print("[FAIL] attach 上去了但没 page")
            browser.close()
            return 1

        # 用 CDP 直接取所有 cookie(包括 HttpOnly)
        cdp = ctx.new_cdp_session(page)
        cookies_resp = cdp.send("Network.getCookies")
        cookies = cookies_resp.get("cookies", [])

        # 过滤
        if not args.all_domains:
            cookies = [c for c in cookies
                       if "bigmodel" in c.get("domain", "")
                       or "zhipu" in c.get("domain", "")]
        cookies_by_domain = {}
        for c in cookies:
            cookies_by_domain.setdefault(c["domain"], {})[c["name"]] = c["value"]

        # localStorage + sessionStorage
        ls_raw = page.evaluate("() => JSON.stringify(localStorage)")
        ss_raw = page.evaluate("() => JSON.stringify(sessionStorage)")
        local_storage = json.loads(ls_raw) if ls_raw else {}
        session_storage = json.loads(ss_raw) if ss_raw else {}

        # 找 jwt 类 token
        url_resp = page.evaluate("() => location.href")
        url_title = page.title()

        # 组装 HTTP Cookie header
        # 把所有 bigmodel.cn(以及 .bigmodel.cn)下的 cookie 拼成单字符串
        cookie_parts = []
        for dom, kvs in cookies_by_domain.items():
            for k, v in kvs.items():
                cookie_parts.append(f"{k}={v}")
        cookie_header = "; ".join(cookie_parts)

        result = {
            "pageUrl":       url_resp,
            "pageTitle":     url_title,
            "extractedAt":   datetime.datetime.utcnow().isoformat() + "Z",
            "cookies":       cookies_by_domain,
            "cookies_header": cookie_header,
            "localStorage":  local_storage,
            "sessionStorage": session_storage,
        }

        # 打印精简版
        print(f"[READ] 共 {sum(len(v) for v in cookies_by_domain.values())} 个 cookie "
              f"from {len(cookies_by_domain)} 个 domain")
        for dom in sorted(cookies_by_domain.keys()):
            print(f"  {dom}:")
            for k, v in sorted(cookies_by_domain[dom].items()):
                # 关键 cookie 高亮
                tagged = ""
                if any(h in k.lower() for h in _KEY_COOKIE_HINTS):
                    tagged = "  ⭐(关键 token)"
                # value 截短显示
                shown = v if len(v) <= 40 else v[:37] + "..."
                print(f"    {k:24s} = {shown}{tagged}")
        print()
        if local_storage:
            print(f"[READ] localStorage 共 {len(local_storage)} key")
            for k, v in sorted(local_storage.items())[:10]:
                if any(h in k.lower() for h in _KEY_COOKIE_HINTS):
                    shown = v if len(v) <= 60 else v[:57] + "..."
                    print(f"    ⭐ {k:24s} = {shown}")
        if session_storage:
            print(f"[READ] sessionStorage 共 {len(session_storage)} key")
            for k, v in sorted(session_storage.items())[:10]:
                shown = v if len(v) <= 60 else v[:57] + "..."
                print(f"    {k:24s} = {shown}")

        if args.show_header:
            print()
            print("[HEADER] Cookie: " + cookie_header[:300] +
                  ("..." if len(cookie_header) > 300 else ""))

        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(result, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            print()
            print(f"[OK] 写到 {output_path}")
            print(f"     (含 {len(cookie_header)} 字符的 Cookie header,"
                  f" {sum(len(v) for v in cookies_by_domain.values())} 个 cookie)")

        # 安全提示
        print()
        print("[安全提示] 上面写的 / 打印的 cookie 包含完整登录 token,等同于明文密码。")
        print("          不要 commit 到 git,不要传到 IM。")

        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
