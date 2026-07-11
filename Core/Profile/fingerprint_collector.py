"""
Core/Profile/fingerprint_collector.py — 从真实浏览器采集指纹数据

流程：
1. 用 Playwright 打开指定 URL（用户手动过验证码）
2. 注入手防检测 JS 脚本（获取纯净指纹）
3. 采集：Canvas/WebGL/TLS/UA/Cookie/LocalStorage/SessionStorage
4. 返回 FingerprintConfig + BrowserState，可存入 Profile 池

用法：
    collector = FingerprintCollector(headless=False)
    result = await collector.collect(url="https://example.com")
    # result.fingerprint → FingerprintConfig
    # result.cookies    → list[Cookie]
    # result.local_storage, session_storage → dict
"""
from __future__ import annotations

import asyncio
import json
from typing import Optional
from dataclasses import dataclass, field

from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from .profile import FingerprintConfig
from .fingerprint_gen import FingerprintGenerator


# ─── 采集结果 ───────────────────────────────────────────────────

@dataclass
class FingerprintResult:
    """采集到的完整指纹数据"""
    fingerprint: FingerprintConfig
    user_agent: str
    cookies: list[dict]
    local_storage: dict
    session_storage: dict
    navigator_props: dict = field(default_factory=dict)
    webgl_info: dict = field(default_factory=dict)
    canvas_hash: str = ""


# ─── JavaScript 注入脚本（获取纯净指纹）────────────────────────────

_FP_SCRIPT = r"""
() => {
    const result = {};

    // ── Navigator ──────────────────────────────────────────────
    result.navigator = {
        userAgent: navigator.userAgent,
        platform: navigator.platform,
        language: navigator.language,
        languages: Array.from(navigator.languages),
        hardwareConcurrency: navigator.hardwareConcurrency || 0,
        deviceMemory: navigator.deviceMemory || 0,
        webdriver: navigator.webdriver || false,
    };

    // ── Screen ─────────────────────────────────────────────────
    result.screen = {
        width: screen.width,
        height: screen.height,
        colorDepth: screen.colorDepth,
        pixelDepth: screen.pixelDepth,
    };

    // ── Canvas Fingerprint ──────────────────────────────────────
    try {
        const canvas = document.createElement('canvas');
        canvas.width = 200;
        canvas.height = 50;
        const ctx = canvas.getContext('2d');
        ctx.textBaseline = 'top';
        ctx.font = "14px 'Arial'";
        ctx.fillStyle = '#f60';
        ctx.fillRect(125, 1, 62, 20);
        ctx.fillStyle = '#069';
        ctx.fillText('Playwright 👀', 2, 15);
        ctx.fillStyle = 'rgba(102, 204, 0, 0.7)';
        ctx.fillText('Playwright 👀', 4, 17);
        result.canvasHash = canvas.toDataURL().substring(0, 64);
    } catch(e) {
        result.canvasHash = 'ERROR: ' + e.message;
    }

    // ── WebGL Fingerprint ──────────────────────────────────────
    try {
        const canvas = document.createElement('canvas');
        canvas.width = 256;
        canvas.height = 128;
        const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl');
        if (gl && gl instanceof WebGLRenderingContext) {
            const debugInfo = gl.getExtension('WEBGL_debug_renderer_info');
            result.webgl = {
                vendor: debugInfo
                    ? gl.getParameter(debugInfo.UNMASKED_VENDOR_WEBGL)
                    : gl.getParameter(gl.VENDOR),
                renderer: debugInfo
                    ? gl.getParameter(debugInfo.UNMASKED_RENDERER_WEBGL)
                    : gl.getParameter(gl.RENDERER),
                version: gl.getParameter(gl.VERSION),
                shadingLanguage: gl.getParameter(gl.SHADING_LANGUAGE_VERSION),
            };
            // 采样几个 GL 参数
            result.webgl.parameters = {
                'ALIASED_LINE_WIDTH_RANGE': Array.from(gl.getParameter(gl.ALIASED_LINE_WIDTH_RANGE)),
                'ALIASED_POINT_SIZE_RANGE': Array.from(gl.getParameter(gl.ALIASED_POINT_SIZE_RANGE)),
                'MAX_TEXTURE_SIZE': gl.getParameter(gl.MAX_TEXTURE_SIZE),
                'MAX_RENDERBUFFER_SIZE': gl.getParameter(gl.MAX_RENDERBUFFER_SIZE),
                'MAX_VERTEX_ATTRIBS': gl.getParameter(gl.MAX_VERTEX_ATTRIBS),
            };
        } else {
            result.webgl = { error: 'WebGL not available' };
        }
    } catch(e) {
        result.webgl = { error: e.message };
    }

    // ── AudioContext Fingerprint ────────────────────────────────
    try {
        const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioCtx.createOscillator();
        const analyser = audioCtx.createAnalyser();
        const gain = audioCtx.createGain();
        const processor = audioCtx.createScriptProcessor(4096, 1, 1);
        oscillator.type = 'triangle';
        gain.gain.value = 0;
        oscillator.connect(analyser);
        analyser.connect(processor);
        processor.connect(gain);
        gain.connect(audioCtx.destination);
        oscillator.start(0);
        const fingerprint = processor.listeners('audioprocess');
        result.audioContextAvailable = true;
        result.audioContextState = audioCtx.state;
        oscillator.stop();
        audioCtx.close();
    } catch(e) {
        result.audioContextAvailable = false;
        result.audioContextError = e.message;
    }

    // ── Timezone / Date ────────────────────────────────────────
    result.timezone = {
        offset: new Date().getTimezoneOffset(),
        iana: Intl.DateTimeFormat().resolvedOptions().timeZone,
    };

    // ── Document ──────────────────────────────────────────────
    result.document = {
        charset: document.characterSet,
        referrer: document.referrer,
    };

    // ── Connection ─────────────────────────────────────────────
    if (navigator.connection) {
        result.connection = {
            effectiveType: navigator.connection.effectiveType,
            downlink: navigator.connection.downlink,
            rtt: navigator.connection.rtt,
            saveData: navigator.connection.saveData,
        };
    }

    return result;
}
"""


@dataclass
class CollectorConfig:
    """采集器配置"""
    headless: bool = False
    timeout_ms: int = 30000
    wait_for_manual_captcha_s: int = 120  # 用户手动过验证码的超时


class FingerprintCollector:
    """
    从真实浏览器采集指纹数据。

    使用说明：
    1. 创建 collector = FingerprintCollector(headless=False)
    2. await collector.open_browser()
    3. await collector.navigate(url) → 浏览器窗口弹出，用户手动操作
    4. await collector.collect() → 返回 FingerprintResult
    5. await collector.close()
    """

    def __init__(self, config: Optional[CollectorConfig] = None):
        self.config = config or CollectorConfig()
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    async def open_browser(self):
        """打开无头或有头浏览器"""
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(
            headless=self.config.headless,
        )
        self._context = await self._browser.new_context(
            # 不指定 UA，让浏览器用默认的
            accept_downloads=True,
        )
        self._page = await self._context.new_page()

    async def navigate(self, url: str) -> Page:
        """导航到 URL，返回 Page（用户可在弹出的浏览器窗口手动操作）"""
        if self._page is None:
            raise RuntimeError("Browser not opened. Call open_browser() first.")
        await self._page.goto(url, wait_until="domcontentloaded", timeout=0)
        return self._page

    async def collect(self, page: Optional[Page] = None) -> FingerprintResult:
        """
        采集当前页面（已导航完成后）的指纹数据。

        调用时机：用户手动过完验证码、页面加载稳定后。
        """
        target = page or self._page
        if target is None:
            raise RuntimeError("No page available")

        # 在目标页面执行采集脚本
        raw = await target.evaluate(_FP_SCRIPT)

        # ── 解析 UA ──────────────────────────────────────────
        ua = raw.get("navigator", {}).get("userAgent", "")
        platform = raw.get("navigator", {}).get("platform", "Linux x86_64")
        locale = raw.get("navigator", {}).get("language", "en-US")

        # ── Canvas Seed ─────────────────────────────────────
        canvas_hash = raw.get("canvasHash", "")

        # ── WebGL ───────────────────────────────────────────
        webgl_info = raw.get("webgl", {})
        webgl_vendor = webgl_info.get("vendor", "Intel Inc.")
        webgl_renderer = webgl_info.get("renderer", "llvmpipe")

        # ── Screen ─────────────────────────────────────────
        screen_info = raw.get("screen", {})
        screen_width = screen_info.get("width", 1920)
        screen_height = screen_info.get("height", 1080)

        # ── Hardware ────────────────────────────────────────
        hw_concurrency = raw.get("navigator", {}).get("hardwareConcurrency", 8)
        device_memory = raw.get("navigator", {}).get("deviceMemory", 8)

        # ── Timezone ────────────────────────────────────────
        tz_info = raw.get("timezone", {})
        tz_offset = tz_info.get("offset", 0)
        tz_iana = tz_info.get("iana", "America/New_York")

        # ── 构造 FingerprintConfig ───────────────────────────
        gen = FingerprintGenerator()
        fp = gen.generate(template=None)  # 从随机 seed 开始
        fp.user_agent = ua
        fp.platform = platform
        fp.locale = locale
        fp.timezone = tz_iana
        fp.screen_resolution = (screen_width, screen_height)
        fp.hardware_concurrency = hw_concurrency
        fp.device_memory = device_memory
        fp.webgl_vendor = webgl_vendor
        fp.webgl_renderer = webgl_renderer
        fp.canvas_seed = self._str_to_seed(canvas_hash)
        fp.audio_seed = self._str_to_seed(ua + platform)

        # ── Cookies / Storage ───────────────────────────────
        cookies = []
        try:
            if self._context:
                cookies = [
                    {"name": c["name"], "value": c["value"],
                     "domain": c.get("domain", ""), "path": c.get("path", "/"),
                     "secure": c.get("secure", False)}
                    for c in await self._context.cookies()
                ]
        except Exception:
            pass

        local_storage = {}
        session_storage = {}
        try:
            ls = await target.evaluate(
                "() => JSON.stringify(localStorage)"
            )
            local_storage = json.loads(ls) if ls else {}
        except Exception:
            pass
        try:
            ss = await target.evaluate(
                "() => JSON.stringify(sessionStorage)"
            )
            session_storage = json.loads(ss) if ss else {}
        except Exception:
            pass

        return FingerprintResult(
            fingerprint=fp,
            user_agent=ua,
            cookies=cookies,
            local_storage=local_storage,
            session_storage=session_storage,
            navigator_props=raw.get("navigator", {}),
            webgl_info=webgl_info,
            canvas_hash=canvas_hash,
        )

    async def close(self):
        """关闭浏览器"""
        if self._page:
            await self._page.close()
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    @staticmethod
    def _str_to_seed(s: str) -> int:
        """将字符串哈希为 0..2^31-1 的整数 seed"""
        import hashlib
        h = hashlib.sha256(s.encode()).digest()
        return int.from_bytes(h[:4], "big") & 0x7FFFFFFF
