"""Playwright 自动化登录 bigmodel.cn.

支持两种流程(由调用方选择):

1) auto_login_capture() — 微信扫码登录
   - 打开首页,点"登录/注册"
   - 切到"微信扫码登录"tab(注意:不是智谱 App,2026-07 现状)
   - 截二维码给 UI
   - 轮询登录态
   - 抽 token / cookie

2) phone_login_capture() — 手机号 + 短信码(主流路径)
   - 打开首页,点"登录/注册"
   - 输手机号 → 点"获取验证码" → 触发腾讯防水墙点选弹窗
   - **暂停**,等用户在面板上看到 captcha 截图后用鼠标点过汉字
   - 验证码过 → 智谱下发短信到手机
   - 暂停,等用户在面板输入 6 位短信码
   - 自动点"登录/注册" → 抽 token / cookie

两个流程都基于 Playwright + Core.AntiDetect;验证码厂商:腾讯防水墙
(turing.captcha.qcloud.com),验证类型:按顺序点击图片里的汉字(2026-07 现状)。

设计原则:
- 抢登录是**分钟级窗口**的事:整套流程在用户配合下 30-60s 能完成,
  抢购前 1-2 分钟启动浏览器,登录完成 → 立即进入抢购
- token / cookie 抽到后**持久化 storage state**,下次启动秒进
- 用户手动点汉字/手输短信码:稳,胜过任何打码平台的成本/失败率


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
from pathlib import Path


@dataclass
class AutoLoginProgress:
    """扫码登录进度回调数据,gradio 轮询展示。"""
    stage: str = "init"           # init / qrcode_ready / waiting_scan / login_detected / verifying / done / error
    message: str = ""             # 给 UI 显示的状态文字
    qrcode_b64: str = ""          # base64 编码的二维码 PNG(给 gradio Image 组件)
    account_name: str = ""
    error: str = ""


DEFAULT_HOME_URL = "https://bigmodel.cn/"
DEFAULT_LOGIN_URL = DEFAULT_HOME_URL  # 兼容老调用
DEFAULT_TIMEOUT_SEC = 120
POLL_INTERVAL_SEC = 1.0

# JWT 可能在 localStorage 或 cookie 里,智谱历史上用过:
#   localStorage: "bigmodel_token_production" / "atlas_t"
#   cookie: "bigmodel_token_production" / "atlas_t"
JWT_LS_KEYS = ("bigmodel_token_production", "atlas_t")
JWT_COOKIE_NAMES = ("bigmodel_token_production", "atlas_t")

# 腾讯防水墙点选验证的标识(2026-07 抓包确认)
TCaptcha_HOST = "turing.captcha.qcloud.com"
TCaptcha_POPUP_SELECTOR = ".tencent-captcha-dy__popup-type, #tCaptchaDyContent"
TCaptcha_IMAGE_SELECTOR = ".tencent-captcha-dy__image-area img"
TCaptcha_PROMPT_SELECTOR = ".tencent-captcha-dy__header-text"  # "请依次点击:部 埃 棵"
TCaptcha_CONFIRM_SELECTOR = ".tencent-captcha-dy__btn-true, .tencent-captcha-dy__btn-block"
TCaptcha_LOADING_TEXT = "加载失败"  # 出现则需用户点刷新


async def _capture_captcha_screenshot(page) -> str:
    """截腾讯防水墙点选弹窗,转 base64 给 UI。返回 "" 表示弹窗未出现。"""
    try:
        loc = page.locator(TCaptcha_POPUP_SELECTOR).first
        if not await loc.is_visible(timeout=2000):
            return ""
        png = await loc.screenshot()
        import base64
        return base64.b64encode(png).decode()
    except Exception:
        return ""


async def _wait_captcha_passed(page, timeout_sec: int = 180) -> str:
    """轮询等腾讯点选通过。返回 "passed" / "timeout" / "closed"。
    用户在浏览器里点完汉字 + 点"确定"后,弹窗会自动消失;
    我们的轮询条件:弹窗不可见 或 DOM 里 captcha 容器消失。
    """
    import asyncio
    start = asyncio.get_event_loop().time()
    while asyncio.get_event_loop().time() - start < timeout_sec:
        try:
            loc = page.locator(TCaptcha_POPUP_SELECTOR).first
            if not await loc.is_visible(timeout=500):
                return "passed"
        except Exception:
            return "passed"
        await asyncio.sleep(0.6)
    return "timeout"


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


async def phone_login_capture(
    account_name: str,
    phone: str,
    sms_code_provider,                       # async () -> str,  从面板拉短信码
    captcha_done_event,                      # asyncio.Event,  外部确认"点选已过"
    *,
    home_url: str = DEFAULT_HOME_URL,
    timeout_sec: int = 180,
    headless: bool = False,
    progress_callback=None,
) -> dict:
    """手机号 + 短信码 登录主流程(2026-07 主流路径)。

    Args:
        account_name: 本地账号名(给 SecretStore 标识)。
        phone: 11 位国内手机号,会自动选 +86 国家码。
        sms_code_provider: async callable,返回用户在面板输入的 6 位短信码;
                          返回空字符串视为取消。
        captcha_done_event: asyncio.Event,UI 检测到"用户已过 captcha"时 set();
                            或者用 event.wait() 替代也行,这里为兼容 gradio
                            同步回调走 Event 通道。
        home_url: 智谱首页 URL。
        timeout_sec: 总超时秒数(默认 180s = 3 分钟,够点汉字+收短信+输码)。
        headless: 是否无头。False 让用户看到浏览器、方便点汉字。
        progress_callback: 进度回调。

    Returns:
        {success, message, token, cookie, user_id, captcha_b64, sms_sent, error}
    """
    from playwright.async_api import async_playwright
    import asyncio
    import base64, io

    progress = AutoLoginProgress(account_name=account_name)
    captcha_b64 = ""

    def emit(stage: str, message: str):
        progress.stage = stage
        progress.message = message
        if progress_callback:
            progress_callback(progress)

    emit("init", "启动浏览器...")
    browser = None  # 给 finally 用
    try:
        async with async_playwright() as p:
            import tempfile, os
            # 每次启动用临时 user-data-dir,避免复用旧 cookie 导致智谱跳过验证码
            ud = tempfile.mkdtemp(prefix="wa-zhipu-")
            browser = await p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox", "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
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
                ignore_https_errors=True,
            )
            try:
                from Core.AntiDetect import AntiDetectInjector
                await AntiDetectInjector().inject(context)
            except Exception as e:
                emit("init", f"反检测注入失败(继续): {e}")

            page = await context.new_page()

            # 1. 打开首页
            emit("home_loading", "打开智谱首页...")
            try:
                await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as e:
                await browser.close()
                return {"success": False, "stage": "error",
                        "message": f"打开首页失败: {e}",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": "", "sms_sent": False, "error": str(e)}

            # 2. 点"登录 / 注册"
            emit("opening_login", "click login/register btn at top right"),
            try:
                await page.get_by_text("登录 / 注册", exact=True).first.click(timeout=5000)
            except Exception as e:
                await browser.close()
                return {"success": False, "stage": "error",
                        "message": f"找不到'login/register' button not found: {e}",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": "", "sms_sent": False, "error": str(e)}

            await page.wait_for_timeout(1500)  # 等弹窗动画

            # 3. 输手机号 + 选 +86
            emit("filling_phone", f"填写手机号 {phone[:3]}****{phone[-4:]}...")
            try:
                # +86 是默认,但有时是 input 形式,这里用 placeholder 锁
                phone_in = page.locator('input[placeholder="请输入手机号"]').first
                await phone_in.click()
                await phone_in.fill("")
                await phone_in.type(phone, delay=20)
            except Exception as e:
                await browser.close()
                return {"success": False, "stage": "error",
                        "message": f"填手机号失败: {e}",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": "", "sms_sent": False, "error": str(e)}

            # 4. 点"获取验证码" — 触发腾讯防水墙点选
            emit("sending_sms", "点'get code' (trigger tencent captcha)...")
            try:
                await page.get_by_text("获取验证码", exact=True).first.click(timeout=3000)
            except Exception as e:
                await browser.close()
                return {"success": False, "stage": "error",
                        "message": f"点获取验证码失败: {e}",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": "", "sms_sent": False, "error": str(e)}

            # 5. 等腾讯点选弹窗出现
            # 注:不在这里做长轮询 — 长轮询会让我们在 12s 里反复触发风控,
            # 用户在浏览器里点完汉字后,弹窗消失会被 _wait_captcha_passed 捕获。
            # 2.5s 够 dy-jy3.js + 弹层首屏渲染,不够的化以全屏截图兜底。
            await page.wait_for_timeout(2500)
            captcha_b64 = await _capture_captcha_screenshot(page)
            if not captcha_b64:
                # 弹窗没出现 — 可能手机号已注册/被风控,或者页面已登录
                emit("captcha_missing", "未检测到腾讯点选弹窗(可能手机号已注册 / 已登录 / 被风控)")
                # 给个全屏截图便于排查
                try:
                    png = await page.screenshot()
                    captcha_b64 = base64.b64encode(png).decode()
                except Exception:
                    pass
                await browser.close()
                return {"success": False, "stage": "captcha_missing",
                        "message": "未检测到腾讯点选弹窗,请检查手机号/网络/智谱风控",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": False,
                        "error": "captcha_not_appeared"}

            emit("captcha_ready",
                 "请在浏览器里**按顺序点汉字**,点完会自己消失; 验证码下发到手机后请在面板填 6 位码")
            progress.captcha_b64 = captcha_b64  # 给 UI 一张

            # 6. 轮询:等 captcha 消失(用户点完了)或超时
            result = await _wait_captcha_passed(page, timeout_sec=timeout_sec)
            if result != "passed":
                await browser.close()
                return {"success": False, "stage": "captcha_timeout",
                        "message": f'tencent captcha not passed ({result})',
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": False,
                        "error": result}
            emit("sms_sent", "点选已通过,短信已下发到手机")

            # 7. 轮询拉短信码(用户在面板输入)
            emit("waiting_sms", "waiting for 6-digit sms code in panel...")
            try:
                code = await asyncio.wait_for(sms_code_provider(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                await browser.close()
                return {"success": False, "stage": "sms_timeout",
                        "message": "等待短信码超时(180s)",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": True,
                        "error": "sms_timeout"}
            if not code or not code.strip():
                await browser.close()
                return {"success": False, "stage": "sms_cancelled",
                        "message": "用户取消输入短信码",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": True,
                        "error": "cancelled"}
            code = code.strip()
            emit("sms_filled", f"已收到短信码,长度 {len(code)}")

            # 8. 填短信码
            try:
                sms_in = page.locator('input[placeholder="请输入验证码"]').first
                await sms_in.click()
                await sms_in.fill("")
                await sms_in.type(code, delay=20)
            except Exception as e:
                await browser.close()
                return {"success": False, "stage": "error",
                        "message": f"填短信码失败: {e}",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": True,
                        "error": str(e)}

            # 9. 点"登录 / 注册"
            emit("submitting", "submitting login...")
            try:
                # 弹窗里有"登录 / 注册"按钮(大蓝),不是 header 上那个
                submit = page.locator(
                    'button:has-text("登录 / 注册"):not(:has-text("微信"))'
                ).first
                await submit.click(timeout=5000)
            except Exception as e:
                # fallback: 用文本定位
                try:
                    await page.get_by_text("登录 / 注册", exact=True).last.click()
                except Exception as e2:
                    await browser.close()
                    return {"success": False, "stage": "error",
                            "message": f"click login button failed: {e2}",
                            "token": "", "cookie": "", "user_id": "",
                            "captcha_b64": captcha_b64, "sms_sent": True,
                            "error": str(e2)}

            # 10. 等登录态
            emit("verifying", "登录成功,抽 token...")
            start = asyncio.get_event_loop().time()
            detected = False
            while asyncio.get_event_loop().time() - start < 30:
                await asyncio.sleep(1.0)
                try:
                    api_resp = await page.evaluate(
                        """async () => {
                            try {
                                const r = await fetch(
                                    '/api/biz/customer/getCustomerInfo',
                                    { credentials: 'include' }
                                );
                                return { status: r.status };
                            } catch (e) { return { error: String(e) }; }
                        }"""
                    )
                    if isinstance(api_resp, dict) and api_resp.get("status") == 200:
                        detected = True
                        break
                except Exception:
                    pass
            if not detected:
                # 兜底: 直接看 cookies / localStorage
                cookies = await context.cookies()
                if _extract_jwt_from_cookies(cookies):
                    detected = True

            if not detected:
                await browser.close()
                return {"success": False, "stage": "login_failed",
                        "message": "提交后未检测到登录态(可能短信码错误/已过期)",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": True,
                        "error": "no_login_state"}

            # 11. 抽凭证
            await page.wait_for_timeout(1500)
            cookies = await context.cookies()
            bigmodel_cookies = _filter_bigmodel_cookies(cookies)
            cookie_str = _build_cookie_string(bigmodel_cookies)
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

            # 12. 持久化 storage state 备用
            try:
                state_path = f"data/profiles/{account_name}_storage.json"
                Path(state_path).parent.mkdir(parents=True, exist_ok=True)
                await context.storage_state(path=state_path)
            except Exception:
                pass

            await browser.close()

            if not token and not cookie_str:
                return {"success": False, "stage": "no_credentials",
                        "message": "登录态在,但没抽到 token/cookie",
                        "token": "", "cookie": "", "user_id": "",
                        "captcha_b64": captcha_b64, "sms_sent": True,
                        "error": "no_credentials"}

            return {
                "success": True,
                "stage": "done",
                "message": f"登录成功(token_len={len(token)}, cookies={len(bigmodel_cookies)})",
                "token": token, "cookie": cookie_str, "user_id": "",
                "captcha_b64": captcha_b64, "sms_sent": True, "error": "",
            }

    except ImportError as e:
        return {"success": False, "stage": "error",
                "message": f"playwright 未安装: {e}",
                "token": "", "cookie": "", "user_id": "",
                "captcha_b64": "", "sms_sent": False, "error": str(e)}
    except Exception as e:
        import traceback
        return {"success": False, "stage": "error",
                "message": f"流程异常: {e}",
                "token": "", "cookie": "", "user_id": "",
                "captcha_b64": captcha_b64, "sms_sent": False,
                "error": str(e), "traceback": traceback.format_exc()}
    finally:
        # 兜底关 browser,防止异常路径残留 Chromium 进程
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


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

            # 注入反检测(智谱可能拦截自动化)。
            # 注:Core.AntiDetest 真正导出的是 AntiDetectInjector.inject(),
            # 之前写的 inject_anti_detect() 不存在,所以一直 except 掉、反检测未生效。
            try:
                from Core.AntiDetect import AntiDetectInjector
                await AntiDetectInjector().inject(context)
            except Exception as e:
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