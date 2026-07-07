"""Playwright 自动化扫码登录 bigmodel.cn.

设计:
- 启动 Chromium(headful 让用户看到浏览器进程)
- 打开登录页,自动切换到扫码 tab
- 截图二维码给 UI 显示
- 轮询检测登录态(URL 变化 / localStorage / cookies)
- 登录成功后从 context.cookies() + localStorage 抽取 token
- 调 BigModelApi.get_customer_info() 验证
- 返回 dict 准备落盘

Usage (脚本)::

    result = asyncio.run(auto_login_capture("主账号", "138xxxxxxxx"))
    if result["success"]:
        print("✅", result["message"], result["user_id"])

Usage (Gradio)::

    backend = CredentialBackend()
    asyncio.run(backend.auto_login_with_capture("主账号", "138xxxxxxxx"))
"""
from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class AutoLoginProgress:
    """扫码登录进度回调数据,gradio 轮询展示。"""
    stage: str = "init"           # init / qrcode_ready / waiting_scan / login_detected / verifying / done / error
    message: str = ""             # 给 UI 显示的状态文字
    qrcode_b64: str = ""          # base64 编码的二维码 PNG(给 gradio Image 组件)
    account_name: str = ""
    error: str = ""


DEFAULT_LOGIN_URL = "https://bigmodel.cn/passport/login"
DEFAULT_TIMEOUT_SEC = 120
POLL_INTERVAL_SEC = 1.0

# JWT 可能在 localStorage 或 cookie 里,智谱历史上用过:
#   localStorage: "bigmodel_token_production" / "atlas_t"
#   cookie: "bigmodel_token_production" / "atlas_t"
JWT_LS_KEYS = ("bigmodel_token_production", "atlas_t")
JWT_COOKIE_NAMES = ("bigmodel_token_production", "atlas_t")


def _looks_like_login_url(url: str) -> bool:
    """判断当前 URL 是否还是登录页(未跳转)。"""
    if not url:
        return True
    lower = url.lower()
    return (
        "/passport/login" in lower
        or "/login" in lower
        or "/signin" in lower
    )


def _extract_jwt_from_cookies(cookies: list[dict]) -> str:
    """从 cookies 列表里找 JWT,返回 raw token(去掉可能的多余引号)。"""
    for c in cookies:
        name = c.get("name", "")
        if name in JWT_COOKIE_NAMES:
            val = c.get("value", "")
            # URL 解码(cookie value 通常是 URL encoded)
            from urllib.parse import unquote
            return unquote(val)
    return ""


def _build_cookie_string(cookies: list[dict]) -> str:
    """把 playwright cookies 列表合并成 HTTP Cookie header 字符串。"""
    pairs = []
    for c in cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if name and value:
            pairs.append(f"{name}={value}")
    return "; ".join(pairs)


def _filter_bigmodel_cookies(cookies: list[dict]) -> list[dict]:
    """只保留 bigmodel.cn 域名的 cookie。"""
    return [
        c for c in cookies
        if "bigmodel.cn" in c.get("domain", "") or "bigmodel.cn" in c.get("url", "")
    ]


async def _screenshot_to_b64(locator) -> str:
    """截取元素截图,转 base64(给 gradio.Image 用)。失败返回空。"""
    try:
        png_bytes = await locator.screenshot()
        return base64.b64encode(png_bytes).decode("ascii")
    except Exception:
        return ""


async def _full_page_screenshot_b64(page) -> str:
    """整页截图(二维码元素定位失败时兜底)。"""
    try:
        png_bytes = await page.screenshot(full_page=False)
        return base64.b64encode(png_bytes).decode("ascii")
    except Exception:
        return ""


async def auto_login_capture(
    account_name: str,
    phone: str = "",
    *,
    login_url: str = DEFAULT_LOGIN_URL,
    timeout_sec: int = DEFAULT_TIMEOUT_SEC,
    headless: bool = False,
    progress_callback: Optional[Callable[[AutoLoginProgress], None]] = None,
) -> dict[str, Any]:
    """Playwright 扫码登录主流程。

    Args:
        account_name: 本地账号名(给 SecretStore 标识用)。
        phone: 手机号(可选,仅记录)。
        login_url: 登录页 URL(默认 bigmodel.cn/passport/login)。
        timeout_sec: 扫码等待超时秒数(默认 120s)。
        headless: 是否无头模式。默认 False,让用户看到浏览器。
        progress_callback: 进度回调,UI 用。每阶段触发一次。

    Returns:
        {success: bool, message, token, cookie, user_id, qrcode_b64, error}
    """
    from playwright.async_api import async_playwright

    progress = AutoLoginProgress(account_name=account_name)
    qrcode_b64 = ""

    def emit(stage: str, message: str):
        progress.stage = stage
        progress.message = message
        if progress_callback:
            progress_callback(progress)

    emit("init", "正在启动浏览器...")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=headless,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )

            # 注入反检测(智谱可能拦截自动化)
            try:
                from Core.AntiDetect import inject_anti_detect
                await inject_anti_detect(context)
            except Exception as e:
                # 不致命,继续流程
                emit("init", f"反检测注入失败(继续): {e}")

            page = await context.new_page()
            emit("init", "打开登录页...")
            await page.goto(login_url, wait_until="domcontentloaded", timeout=30000)

            # 自动切到扫码登录 tab(如果显示账密)
            try:
                qr_tab = page.get_by_text("扫码登录", exact=False).first
                if await qr_tab.is_visible(timeout=2000):
                    await qr_tab.click()
            except Exception:
                pass  # 默认就是扫码登录

            # 等二维码出现
            await asyncio.sleep(1.5)

            # 尝试截二维码元素,失败截全页
            qr_locator = None
            for selector in (
                '[class*="qrcode"]',
                'canvas',
                'img[alt*="二维码"]',
                'img[alt*="qrcode"]',
                '.qrcode',
                '#qrcode',
            ):
                try:
                    loc = page.locator(selector).first
                    if await loc.is_visible(timeout=500):
                        qr_locator = loc
                        break
                except Exception:
                    continue

            if qr_locator:
                qrcode_b64 = await _screenshot_to_b64(qr_locator)
            if not qrcode_b64:
                # 兜底:全页截图
                qrcode_b64 = await _full_page_screenshot_b64(page)
            progress.qrcode_b64 = qrcode_b64

            emit("qrcode_ready", "✅ 浏览器已打开,请用智谱 App 扫码登录")

            # 轮询检测登录态
            # 借鉴 xhs_ai_publisher 的 _is_creator_logged_in() 模式:
            # 发一个登录态专属的 API 请求,看返回码判断登录,比轮询 URL 更准
            start = asyncio.get_event_loop().time()
            detected = False
            while asyncio.get_event_loop().time() - start < timeout_sec:
                await asyncio.sleep(POLL_INTERVAL_SEC)
                elapsed = int(asyncio.get_event_loop().time() - start)
                if elapsed % 10 == 0:  # 每 10s 更新一次状态
                    emit("waiting_scan", f"等待扫码... ({elapsed}s / {timeout_sec}s)")

                # 检测 1(借鉴 xhs):智谱专属的 getCustomerInfo API 探活
                #   这是最可靠的方法:用户用账密/扫码登录后,这个 API 立刻返回 200
                try:
                    api_response = await page.evaluate(
                        """async () => {
                            try {
                                const r = await fetch(
                                    '/api/biz/customer/getCustomerInfo',
                                    { credentials: 'include' }
                                );
                                return { status: r.status };
                            } catch (e) {
                                return { error: String(e) };
                            }
                        }"""
                    )
                    if isinstance(api_response, dict) and api_response.get("status") == 200:
                        detected = True
                        emit(
                            "login_detected",
                            "智谱 getCustomerInfo 返回 200,确认登录成功",
                        )
                        break
                except Exception:
                    pass

                if detected:
                    break

                # 检测 2:URL 变化(登录成功跳走)
                if not _looks_like_login_url(page.url):
                    detected = True
                    emit("login_detected", f"检测到登录成功(URL 跳转): {page.url}")
                    break

                # 检测 3:localStorage 里有 JWT
                try:
                    for k in JWT_LS_KEYS:
                        val = await page.evaluate(f"() => localStorage.getItem({k!r})")
                        if val and len(val) > 20:  # JWT 至少几十字节
                            detected = True
                            emit("login_detected", f"检测到 localStorage[{k}] 已有 JWT")
                            break
                except Exception:
                    pass

                if detected:
                    break

                # 检测 4:cookies 里有 JWT
                try:
                    cookies = await context.cookies()
                    if _extract_jwt_from_cookies(cookies):
                        detected = True
                        emit("login_detected", "检测到 cookie 已有 JWT")
                        break
                except Exception:
                    pass

            if not detected:
                emit("error", f"扫码登录超时({timeout_sec}s 未检测到登录)")
                await browser.close()
                return {
                    "success": False,
                    "message": f"扫码登录超时({timeout_sec} 秒未检测到登录)",
                    "token": "",
                    "cookie": "",
                    "user_id": "",
                    "qrcode_b64": qrcode_b64,
                    "error": "timeout",
                }

            # 登录成功 → 抽取凭证
            emit("verifying", "登录成功,正在抽取凭证...")

            # 给页面一点时间完成跳转和写 cookie
            await asyncio.sleep(1.5)

            cookies = await context.cookies()
            bigmodel_cookies = _filter_bigmodel_cookies(cookies)
            cookie_str = _build_cookie_string(bigmodel_cookies)

            # JWT 优先从 cookie 抽,再从 localStorage
            token = _extract_jwt_from_cookies(bigmodel_cookies)
            if not token:
                for k in JWT_LS_KEYS:
                    try:
                        v = await page.evaluate(f"() => localStorage.getItem({k!r})")
                        if v and len(v) > 20:
                            token = v
                            break
                    except Exception:
                        continue

            await browser.close()

            if not token and not cookie_str:
                return {
                    "success": False,
                    "message": "登录成功但未抽到 token 或 cookie",
                    "token": "",
                    "cookie": "",
                    "user_id": "",
                    "qrcode_b64": qrcode_b64,
                    "error": "no_credentials",
                }

            return {
                "success": True,
                "message": f"已抽取凭证(token_len={len(token)}, cookie_count={len(bigmodel_cookies)})",
                "token": token,
                "cookie": cookie_str,
                "user_id": "",
                "qrcode_b64": qrcode_b64,
                "error": "",
            }

    except ImportError as e:
        emit("error", f"playwright 未安装: {e}")
        return {
            "success": False,
            "message": f"playwright 未安装,请先 pip install playwright && playwright install chromium",
            "token": "",
            "cookie": "",
            "user_id": "",
            "qrcode_b64": "",
            "error": str(e),
        }
    except Exception as e:  # noqa: BLE001
        import traceback
        emit("error", f"扫码流程异常: {e}")
        return {
            "success": False,
            "message": f"扫码流程异常: {e}",
            "token": "",
            "cookie": "",
            "user_id": "",
            "qrcode_b64": qrcode_b64,
            "error": str(e),
            "traceback": traceback.format_exc(),
        }