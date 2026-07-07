"""fetch hook 不能改写 method (2026-07-06 修复)

之前 const options = { ...(init || {}) } 在 init 是 undefined 或不含 method 时,
导致 fetch 退回 GET, captcha 等 POST 接口被服务端 405 拒绝.
现在用 new Request(input, finalInit) 合并保留 method.
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector


def test_no_get_fallback_code():
    """inject script 里不能有 'GET fallback' 反模式."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    # 老 bug 模式: const options = { ...(init || {}) }
    assert "{ ...(init || {}) }" not in script, \
        "fetch hook 仍在用 spread operator 复制 init, 会让 method 退回 GET"
    # 新修法: 用 new Request(input, finalInit) 合并
    assert "new Request(input, finalInit)" in script, \
        "缺少 new Request(input, finalInit) 合并, fetch method 会丢"


def test_method_preserved_at_runtime():
    """运行时: 各种 method 都能保留到 Network 层."""
    from playwright.sync_api import sync_playwright
    cfg = AntiDetectConfig()
    js = AntiDetectInjector(cfg).get_inject_script()
    captured = []
    with sync_playwright() as p:
        ctx = p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-dev-shm-usage']).new_context()
        ctx.add_init_script(js)
        page = ctx.new_page()
        def handle(route, request):
            captured.append(request.method)
            route.fulfill(status=200, body='ok')
        page.route('**/*', handle)
        page.goto('https://bigmodel.cn', wait_until='domcontentloaded', timeout=30000)
        page.wait_for_load_state('networkidle', timeout=10000)
        page.evaluate("""(async () => {
            try { await fetch('/a', { method: 'PUT' }); } catch(e){}
            try { await fetch(new Request('/b', { method: 'DELETE' })); } catch(e){}
            try { await fetch(new Request('/c', { method: 'POST', body: 'x' })); } catch(e){}
            try { await fetch('/d'); } catch(e){}
        })()""")
        page.wait_for_timeout(1500)
        ctx.close()
    # 至少 PUT/DELETE/POST/GET 都出现过 (顺序不重要, 但都应保留)
    assert 'PUT' in captured, f"PUT 没保留: {captured}"
    assert 'DELETE' in captured, f"DELETE 没保留: {captured}"
    assert 'POST' in captured, f"POST 没保留: {captured}"
    assert 'GET' in captured, f"GET 没保留: {captured}"


if __name__ == "__main__":
    test_no_get_fallback_code()
    test_method_preserved_at_runtime()
    print("OK: 2 passed")
