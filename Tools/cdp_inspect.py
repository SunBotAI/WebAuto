r"""CDP inspect 工具:attach 到 Windows Chrome 后实时抓网络请求.

需求场景:你在 Chrome 上手动操作智谱页面(F12 看不到,
或者想批量抓一批请求),WSL 这里实时打印所有 API 请求 + 响应。

## 准备
先启动 Chrome DevTools:
    bash Tools/cdp_launch.sh

## 用法
    # 抓接下来 60 秒的所有网络请求
    .venv-fix/bin/python Tools/cdp_inspect.py --duration 60

    # 只关心智谱相关 URL
    .venv-fix/bin/python Tools/cdp_inspect.py --filter bigmodel.cn --duration 30

    # 实时输出到终端,完成后还能存 JSON
    .venv-fix/bin/python Tools/cdp_inspect.py --duration 30 --output /tmp/requests.json

    # 包含响应 body(便于调试 payload 结构)
    .venv-fix/bin/python Tools/cdp_inspect.py --filter bigmodel.cn --include-body --duration 30

输出格式(每行一条请求):
    [POST 200] https://bigmodel.cn/api/biz/customer/getCustomerInfo  235ms  body_len=421
"""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def _print(msg: str, color: str) -> None:
    """带 ANSI 颜色的 print。"""
    print(f"{color}{msg}\033[0m", flush=True)


async def run(args) -> int:
    from playwright.async_api import async_playwright

    requests_log = []
    pending: dict[str, dict] = {}  # url -> request_log entry,等 response 填状态

    def matches(url: str) -> bool:
        if not args.url_filter:
            return True
        return args.url_filter in url

    def on_request(request):
        if not matches(request.url):
            return
        entry = {
            "method": request.method,
            "url": request.url,
            "timestamp": time.time(),
            "type": "request",
        }
        requests_log.append(entry)
        pending[request.url] = entry
        _print(f"→ {request.method:6s} {request.url[:120]}", "\033[36m")

    async def on_response(response):
        if not matches(response.url):
            return
        try:
            status = response.status
        except Exception:
            status = "?"
        # 找对应 entry
        entry = pending.pop(response.url, None)
        if entry is None:
            return
        latency = int((time.time() - entry["timestamp"]) * 1000)
        entry["status"] = status
        entry["latency_ms"] = latency

        body_len = 0
        if args.include_body or args.save_body or args.save_dir:
            try:
                body = await response.body()
                body_len = len(body)
                entry["body_len"] = body_len
                if args.include_body:
                    try:
                        entry["body_preview"] = body[:500].decode("utf-8", errors="replace")
                    except Exception:
                        pass
                if args.save_body:
                    try:
                        entry["body"] = body.decode("utf-8", errors="replace")
                    except Exception:
                        pass
                if args.save_dir:
                    try:
                        save_dir = Path(args.save_dir)
                        save_dir.mkdir(parents=True, exist_ok=True)
                        path_part = response.url.split("://", 1)[-1]
                        path_part = path_part.replace("/", "_").replace("?", "_")[:60]
                        fname = save_dir / (
                            f"{int(time.time()*1000)}_{entry.get('method', '')}_{path_part}.json"
                        )
                        fname.write_text(
                            json.dumps({
                                "request":  {"method": entry.get("method"), "url": entry.get("url")},
                                "response": {
                                    "status":     entry.get("status"),
                                    "latency_ms": entry.get("latency_ms"),
                                    "body_len":   body_len,
                                    "body":       body.decode("utf-8", errors="replace"),
                                },
                            }, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                    except Exception as e:
                        entry["save_error"] = str(e)
            except Exception:
                pass

        color = "\033[32m" if 200 <= status < 300 else "\033[31m"
        _print(f"← {status} {response.url[:120]}  {latency}ms  body={body_len}",
               color)

    print(f"连接到 {args.cdp} ...", end=" ", flush=True)
    try:
        async with async_playwright() as p:
            browser = await p.chromium.connect_over_cdp(args.cdp)
            print("OK")

            ctx = browser.contexts[0]
            page = ctx.pages[0] if ctx.pages else await ctx.new_page()
            page.on("request", on_request)
            page.on("response", lambda r: asyncio.create_task(on_response(r)))

            print(f"\n开始监听 {page.url}")
            print(f"filter: {args.url_filter or '(all)'}")
            print(f"duration: {args.duration}s ({'无限' if args.duration == 0 else '自动结束'})")
            print(f"include-body: {args.include_body}")
            print("---")

            start = time.time()
            try:
                while True:
                    elapsed = time.time() - start
                    if args.duration and elapsed > args.duration:
                        break
                    await asyncio.sleep(0.5)
            except KeyboardInterrupt:
                print("\n[用户中断]")

            await browser.close()
    except Exception as e:
        print(f"\n❌ 连不上: {e}")
        print("确认 Chrome 已启动 DevTools:")
        print("  bash Tools/cdp_launch.sh")
        return 1

    print(f"\n--- 共 {len(requests_log)} 个请求")
    if args.output:
        Path(args.output).write_text(
            json.dumps(requests_log, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"已保存到 {args.output}")
    return 0




# 预设:preset 一键匹配
_PRESETS = {
    "bigmodel": "bigmodel.cn",
    "zhipu":    "zhipu",
    "cred":     "credential",
    "purchase": "/api/biz/",
    "captcha":  "captcha",
    "static":   "static.",
}
def main():
    parser = argparse.ArgumentParser(description="实时抓 Chrome 网络请求")
    parser.add_argument(
        "--cdp", default="http://localhost:9222",
        help="Chrome DevTools URL",
    )
    parser.add_argument(
        "--filter", dest="url_filter", default=None,
        help="URL 子串过滤(只显示包含此串的请求)",
    )
    parser.add_argument(
        "--preset", choices=list(_PRESETS.keys()), default=None,
        help="预设过滤关键词(覆盖 --filter): " + ", ".join(_PRESETS.keys()),
    )
    parser.add_argument(
        "--duration", type=int, default=60,
        help="抓取时长(秒),0 = 无限",
    )
    parser.add_argument(
        "--output", default=None,
        help="完成后写 JSON 到此文件",
    )
    parser.add_argument(
        "--include-body", action="store_true",
        help="包含响应 body 前 500 字符(调试用,性能略差)",
    )
    parser.add_argument(
        "--save-body", action="store_true",
        help="把响应 body 完整写到 --output 的 JSON(大小不设限,需要时再开)",
    )
    parser.add_argument(
        "--save-dir", default=None,
        help="把每个请求 + body 单独存到该目录(自动创建)",
    )
    args = parser.parse_args()

    if args.preset:
        args.url_filter = _PRESETS[args.preset]

    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()