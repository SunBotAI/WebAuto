r"""智谱登录弹窗中文点选验证码 - 采集工具。

动机:
    调试/改进 CaptchaSolver 时,本地需要一批真实样张。
    智谱 GLM Coding 登录弹窗触发验证码时,人工点完,我们就把:
        - 验证码 popup 截图
        - 弹出时的提示文字 ("请按顺序点击: 张三 李四 王五 赵六")
        - DOM 中提示区的 outerHTML
        - 时间戳 + URL
        保存到 Examples/.captcha_samples/captcha_<时间戳>_<id>/

    一份会话拿到 20+ 张就够做小批量回归了。

用法:
    # 1. 在 Windows 启动 Chrome DevTools 模式
    #    Tools\\cdp_launch.bat                  (reuse,保留登录)
    # 2. 在那个 Chrome 里手动登 bigmodel.cn
    # 3. 在 WSL 启采集器 -- 它会等你触发弹窗 + 完成点选
    .venv/bin/python Examples/captcha_collect.py

    # 自定义保存目录 + 期望采集张数
    .venv/bin/python Examples/captcha_collect.py --output-dir /path/to/samples --target-count 30

工作机制:
    - attach 到所有 tab,对每个 tab 装 MutationObserver 监控
      关注点选验证码的 DOM 标记(智谱的 DOM 一般带有 .captcha-dialog / [data-captcha] 一类)
    - 检测到弹窗元素 mount,自动截屏 + 抓 outerHTML
    - 检测到弹窗消失(captcha 被关),把这次采集打成一组(目录):
        <output-dir>/<timestamp>_<id>/
            prompt.png
            outer.html
            meta.json
    - 当凑够 --target-count 张后,自动停下

注意:
    - 采集完会马上停(不打扰你), 不需要反复重登
    - 采到 30 张就能训练 PaddleOCR 的 Finetune 或者 ddddocr 的对照
    - 这是离线采集,采集器不会自动去登录、不会触发任何网络异常
      你的 bigmodel 账号风控画像不会被影响
"""
import argparse
import json
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# 启发式: 智谱中文点选验证码的 DOM 标记关键词(实际可能不同,可手动改)
_CAPTCHA_POPUP_SELECTORS = [
    "[class*='captcha']",
    "[class*='verify']",
    "[data-captcha]",
    "[id*='captcha']",
    "[role='dialog'][aria-label*='验']",
    ".nc_scale_panel",        # 阿里云滑块(也用,智谱偶尔用滑块而非点选)
    ".geetest_radar",         # 极验(可能)
]


def capture_sample(page, out_dir: Path) -> bool:
    """尝试抓一次 captcha 弹窗截图 + DOM,保存到 out_dir/<timestamp>/。

    返回 True 表示抓到了, False 表示没找到弹窗元素。
    """
    probe = """(() => {
        // 在所有 selectors 里找一个看起来像验证码 popup 的元素
        for (const sel of %s) {
            const el = document.querySelector(sel);
            if (el) {
                const r = el.getBoundingClientRect();
                if (r.width > 100 && r.height > 100 && r.top > 0) {
                    return {
                        found: true,
                        selector: sel,
                        x: r.x, y: r.y, w: r.width, h: r.height,
                        outerHTML: el.outerHTML.slice(0, 4000),
                        promptText: (el.innerText || el.textContent || '').trim().slice(0, 500),
                    };
                }
            }
        }
        return { found: false };
    })()""" % json.dumps(_CAPTCHA_POPUP_SELECTORS)

    info = page.evaluate(probe)
    if not info.get("found"):
        return False

    ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    sample_dir = out_dir / f"captcha_{ts}"
    sample_dir.mkdir(parents=True, exist_ok=True)

    (sample_dir / "meta.json").write_text(
        json.dumps({
            "capturedAt": datetime.utcnow().isoformat() + "Z",
            "url":        page.url,
            "promptText": info.get("promptText", ""),
            "selector":   info.get("selector"),
            "box":        {"x": info["x"], "y": info["y"],
                           "w": info["w"],  "h": info["h"]},
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (sample_dir / "outer.html").write_text(info["outerHTML"], encoding="utf-8")

    # 截屏
    try:
        png_path = sample_dir / "screenshot.png"
        page.screenshot(
            path=str(png_path),
            clip={
                "x": max(0, info["x"] - 30),
                "y": max(0, info["y"] - 30),
                "width":  min(1920, info["w"] + 60),
                "height": min(1080, info["h"] + 60),
            },
        )
        print(f"  [CAPTURED] {sample_dir.name}/ (PNG {png_path.stat().st_size//1024} KB)")
    except Exception as e:
        print(f"  [WARN] screenshot 失败: {e}")

    return True


def main():
    p = argparse.ArgumentParser(description="智谱登录弹窗中文点选验证码 - 采集")
    p.add_argument("--cdp",  default="http://localhost:9222")
    p.add_argument("--match", default="bigmodel.cn",
                   help="URL 子串匹配要 attach 的 tab")
    p.add_argument("--all-tabs", action="store_true")
    p.add_argument("--output-dir",
                   default=str(Path(__file__).parent / ".captcha_samples"),
                   help="保存根目录")
    p.add_argument("--target-count", type=int, default=30,
                   help="目标采集张数,到了自动停")
    p.add_argument("--poll-interval", type=float, default=1.5,
                   help="轮询 DOM 间隔(秒)")
    p.add_argument("--timeout", type=int, default=3600,
                   help="总超时(秒),默认 1 小时")
    args = p.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 验证 CDP 在监听
    try:
        ver = json.loads(
            urllib.request.urlopen(args.cdp + "/json/version", timeout=3)
            .read().decode("utf-8")
        )
        print(f"[OK] DevTools: {ver.get('Browser')}")
    except Exception as e:
        print(f"[FAIL] {args.cdp}: {e}")
        print("       先在 Windows 跑 Tools\\cdp_launch.bat")
        return 1

    targets = json.loads(
        urllib.request.urlopen(args.cdp + "/json", timeout=3).read().decode("utf-8")
    )
    tabs = [t for t in targets if t.get("type") == "page"]
    if args.all_tabs:
        selected = tabs
    else:
        selected = [t for t in tabs if args.match in (t.get("url") or "")]
        if not selected:
            print(f"[FAIL] 没匹配 '{args.match}' 的 tab")
            return 1
    print(f"[INFO] 监控 tab 数: {len(selected)}")

    from playwright.sync_api import sync_playwright

    print(f"[INFO] 监控方式: 每 {args.poll_interval}s 扫一次 DOM,")
    print(f"        找 {len(_CAPTCHA_POPUP_SELECTORS)} 个候选 selector,")
    print(f"        找到 captcha popup 自动截图 + 抓 DOM")
    print(f"        保存到: {out_dir}")
    print(f"        目标张数: {args.target_count},  总超时: {args.timeout}s")
    print()
    print("[INFO] 现在你在 Chrome 里**手动操作触发验证码,然后手动点完** --")
    print("       采集器纯被动监控,不会主动干扰。")
    print()

    captured_count = 0
    start_time = time.time()
    last_capture_per_tab: dict[str, float] = {}  # 防止 1 次弹窗抓 30 张

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0]

        try:
            while captured_count < args.target_count:
                elapsed = time.time() - start_time
                if elapsed > args.timeout:
                    print(f"[STOP] 超过 {args.timeout}s 超时")
                    break

                for tab in selected:
                    target_url = tab.get("url", "")
                    page = None
                    for pg in ctx.pages:
                        if pg.url == target_url or target_url in (pg.url or ""):
                            page = pg
                            break
                    if page is None:
                        continue

                    tab_id = tab.get("id", target_url)
                    last_ts = last_capture_per_tab.get(tab_id, 0)
                    # 同一弹窗不重复抓(60s 内)
                    if time.time() - last_ts < 60:
                        continue

                    if capture_sample(page, out_dir):
                        captured_count += 1
                        last_capture_per_tab[tab_id] = time.time()
                        print(f"  已采集: {captured_count}/{args.target_count}")
                        if captured_count >= args.target_count:
                            break

                # 拉长间隔到用户配置
                time.sleep(args.poll_interval)

        except KeyboardInterrupt:
            print("\n[用户中断]")

        browser.close()

    print()
    print(f"[DONE] 共采集 {captured_count} 张,保存到 {out_dir}")
    print(f"        提示: 下一步用 Examples/captcha_collect_clean.py (待写) 标注")
    print(f"        再用 captcha_solver_train.py 做微调")


if __name__ == "__main__":
    sys.exit(main() or 0)
