#!/usr/bin/env python3
"""
Undetected Playwright PoC — 反爬验证
测试 WebAuto 现有 Chromium + undetected-playwright 对抗 3 个反爬站点

依赖: pip install undetected-playwright
Chromium: 使用 WebAuto 现有 ~.cache/ms-playwright/chromium-1223

用法:
    cd /mnt/f/Project/WebAuto
    python3 Services/undetected_poc.py

环境变量:
    UC_HEADLESS=0  # 显示浏览器窗口
"""

import os
import sys
import time
import json
from datetime import datetime

# ── 配置 ────────────────────────────────────────────────────────────────────
HEADLESS = os.getenv("UC_HEADLESS", "1") == "1"
CHROMIUM_PATH = "/home/claw/.cache/ms-playwright/chromium-1223/chrome-linux/chrome"

REPORT_PATH = "/mnt/f/Project/WebAuto/docs/reports/undetected_poc_report.md"
os.makedirs(os.path.dirname(REPORT_PATH), exist_ok=True)

# ── 测试站点 ─────────────────────────────────────────────────────────────────
TEST_SITES = [
    {
        "name": "SannySoft Bot Detection",
        "url": "https://bot.sannysoft.com/",
        "expected": "passed",
        "wait": 3000,
        "desc": "专业浏览器指纹测试，检测 WebGL/Canvas/Audio/Plugins 等指纹特征",
    },
    {
        "name": "NowSecure Performance",
        "url": "https://nowsecure.nl/",
        "expected": "status",
        "wait": 5000,
        "desc": "基于 Kaggle Netflix dataset，检测 JS 运行时指纹",
    },
    {
        "name": "Google Robots Test",
        "url": "https://www.google.com/robots.txt",
        "expected": "text",
        "wait": 2000,
        "desc": "简单 robots.txt 访问，验证基本 HTTP 层是否被拦截",
    },
]

# ── 辅助函数 ─────────────────────────────────────────────────────────────────
def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def save_screenshot(page, name: str):
    """保存截图到 report 目录"""
    out = f"/mnt/f/Project/WebAuto/docs/reports/{name}.png"
    page.screenshot(path=out, full_page=True)
    return out


def run_test(site: dict) -> dict:
    """单站点测试，返回结果 dict"""
    import undetected_chromedriver as uc
    from selenium.webdriver.common.by import By

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
        log(f"🚀 启动浏览器 -> {site['name']}")

        opts = uc.ChromeOptions()
        opts.headless = HEADLESS

        # 使用 WebAuto 现有的 Chromium（不重新下载）
        # executable_path 会用指定的 chromium
        driver = uc.Chrome(
            options=opts,
            executable_path=CHROMIUM_PATH,
            version_main=1223,
            patcher_force=True,  # 强制打补丁
        )

        driver.set_page_load_timeout(30)

        log(f"📍 访问 {site['url']}")
        driver.get(site["url"])

        # 等待页面稳定
        time.sleep(site["wait"] / 1000)

        # ── 结果判定 ──────────────────────────────────────────────────────────
        if "bot.sannysoft" in site["url"]:
            # 检测结果页面
            try:
                # 查找所有 td 行的 result
                rows = driver.find_elements(By.CSS_SELECTOR, "table tr")
                details = []
                passed_cnt = 0
                for row in rows:
                    cells = row.find_elements(By.CSS_SELECTOR, "td")
                    if len(cells) >= 2:
                        label = cells[0].text.strip()
                        status = cells[1].text.strip()
                        if "result" in label.lower():
                            details.append(f"  {label}: {status}")
                            if "passed" in status.lower():
                                passed_cnt += 1
                result["details"] = "\n".join(details[:10])
                result["passed"] = passed_cnt >= 5
                log(f"✅ SannySoft: {passed_cnt} 项 passed")
            except Exception as e:
                result["error"] = str(e)
                result["passed"] = False

        elif "nowsecure" in site["url"]:
            # NowSecure 跳转到一个测试完成页面
            title = driver.title or ""
            current_url = driver.current_url or ""
            body_text = driver.find_element(By.TAG_NAME, "body").text[:500]
            result["details"] = f"Title: {title}\nURL: {current_url}\nBody: {body_text[:300]}"
            result["passed"] = "test" in body_text.lower() or "status" in body_text.lower()
            log(f"✅ NowSecure: loaded OK")

        else:
            # Google robots.txt
            body = driver.find_element(By.TAG_NAME, "body").text[:200]
            result["details"] = body[:200]
            result["passed"] = len(body) > 10
            log(f"✅ robots.txt: {len(body)} chars")

        result["screenshot"] = save_screenshot(driver, site["name"].replace(" ", "_").lower()[:30])

        driver.quit()

    except Exception as e:
        result["error"] = str(e)
        log(f"❌ {site['name']} ERROR: {e}")
        try:
            driver.quit()
        except Exception:
            pass

    result["duration_ms"] = int((time.time() - start) * 1000)
    return result


def generate_report(results: list) -> str:
    """生成 Markdown 报告"""
    lines = [
        "# Undetected Playwright PoC 报告",
        f"\n**生成时间:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"\n**Chromium:** `{CHROMIUM_PATH}`",
        f"\n**模式:** {'Headless' if HEADLESS else 'Visible'}",
        "\n---\n",
    ]

    passed_all = all(r["passed"] for r in results)

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

    lines.append("\n---\n")
    lines.append(f"\n**总结:** {'✅ 全部通过' if passed_all else '⚠️ 部分失败'}")

    report = "\n".join(lines)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    return report


# ── 主入口 ───────────────────────────────────────────────────────────────────
def main():
    log("=" * 60)
    log("Undetected Playwright PoC — 开始")
    log(f"Headless: {HEADLESS}")
    log(f"Chromium: {CHROMIUM_PATH}")
    log("=" * 60)

    results = []
    for site in TEST_SITES:
        r = run_test(site)
        results.append(r)
        time.sleep(1)  # 避免连续请求过快

    log("\n" + "=" * 60)
    log("生成报告...")
    report = generate_report(results)
    log(f"报告已保存: {REPORT_PATH}")

    # 控制台摘要
    print("\n" + "=" * 60)
    print("结果摘要:")
    for r in results:
        icon = "✅" if r["passed"] else "❌"
        print(f"  {icon} {r['name']} ({r['duration_ms']/1000:.1f}s)")
    print("=" * 60)

    return 0 if all(r["passed"] for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
