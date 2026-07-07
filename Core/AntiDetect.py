"""
反检测核心模块
整合 GlmRush 的前端注入技术,提供通用的反检测能力

主要功能:
1. fetch/XHR hook + 请求指纹随机化
2. JSON.parse 补丁(可自定义数据篡改)
3. Shadow DOM 控制面板隔离
4. WebGL/Canvas 指纹随机化
5. 自动化特征隐藏
"""
import json
import asyncio
from typing import Optional, Dict, Any, Callable, List
from dataclasses import dataclass, field


@dataclass
class AntiDetectConfig:
    """反检测配置

    通用开关管''每页会重新生成''的伪装能力,稳定型指纹
    (UA / WebGL vendor / canvas seed / timezone / screen)交给 BrowserProfile,
    AntiDetectInjector 启动时如果注入 .profile_stable_seed() 用 profile 值,
    否则用本 config 的随机值(且每次启动都变)。
    """
    enable_fetch_hook: bool = True           # fetch hook
    enable_xhr_hook: bool = True             # XHR hook
    enable_json_patch: bool = True           # JSON.parse 补丁
    enable_fingerprint_random: bool = True   # 指纹随机化(canvas + webgl 噪声)
    enable_shadow_panel: bool = False        # 已废弃: 默认不再注入任何浮动 UI (2026-07-06 关闭)
    enable_webdriver_mask: bool = True       # webdriver 特征隐藏
    enable_audio_fingerprint_mask: bool = True   # AudioContext 稳态指纹

    # 请求头随机化
    random_request_id: bool = True
    random_timestamp: bool = True
    random_accept_language: bool = True

    # === 7 类细节补丁(2026-07 加) ===
    # navigator.plugins 用真 PluginArray(原型链完整),不是静态 fake 数组
    enable_realistic_plugins: bool = True
    # screen.* / hardwareConcurrency / deviceMemory 一致化(同一次启动保持稳定)
    enable_consistent_hardware: bool = True
    # Intl.DateTimeFormat 的 timezone 与 navigator.language 一致
    enable_locale_consistency: bool = True
    # Canvas 2D toDataURL 加 微抖动噪声(每次读图 hash 不同)
    enable_canvas_noise: bool = True
    # WebGLRenderingContext.getParameter 渲染器随机化(stable seed)
    enable_webgl_random: bool = True
    # AudioContext fingerprint 稳态(同一 context 多次 getOutputTimestamp 一致)
    enable_audio_stable: bool = True
    # 清理 HeadlessChrome UA 残留字眼
    enable_headless_sanitize: bool = True
    # 清理 CDP (Runtime/Debugger) 痕迹
    enable_cdp_clean: bool = True
    enable_behavior_anti_detect: bool = True   # 2026-07-06: 行为级反检测 (PluginArray/runtime/Pointer/visibility)

    # 稳定型种子(可选)。设定了则 Canvas/WebGL/Audio 噪声基于它生成
    # —— 同 seed 同 context 内完全一致,跨 context 可控。若为 None 走随机。
    fingerprint_seed: Optional[int] = None


class AntiDetectInjector:
    """反检测注入器 - 注入到 Playwright 页面/上下文"""
    
    def __init__(self, config: Optional[AntiDetectConfig] = None):
        self.config = config or AntiDetectConfig()
        
    def get_inject_script(self) -> str:
        """
        获取完整的注入脚本
        用于 browser_context.add_init_script() 提前注入(页面创建前)
        """
        scripts = []
        
        # 1. webdriver 特征隐藏(必须最早注入)
        if self.config.enable_webdriver_mask:
            scripts.append(self._webdriver_mask_script())
            
        # 2. JSON.parse 补丁
        if self.config.enable_json_patch:
            scripts.append(self._json_patch_script())
            
        # 3. fetch hook
        if self.config.enable_fetch_hook:
            scripts.append(self._fetch_hook_script())
            
        # 4. 指纹随机化
        if self.config.enable_fingerprint_random:
            scripts.append(self._fingerprint_random_script())
            
        # 5. Shadow DOM 工具 (默认注入工具函数, 但不自动 create 浮动 UI)
        # enable_shadow_panel 现在语义变了: True = 注入 + 自动 create; False = 注入工具 API 不 create
        # 老逻辑是 False 就不注入, 会让 clean-ui 找不到 remove API. 2026-07-06 改.
        scripts.append(self._shadow_dom_script())
        # 6. 7 类细节补丁(2026-07 加) -- 必须在已有 hooks 之后
        if self.config.enable_realistic_plugins:
            scripts.append(self._realistic_plugins_script())
        if self.config.enable_consistent_hardware:
            scripts.append(self._consistent_hardware_script())
        if self.config.enable_locale_consistency:
            scripts.append(self._locale_consistency_script())
        if self.config.enable_canvas_noise or self.config.enable_webgl_random:
            scripts.append(self._fingerprint_v2_script())
        if self.config.enable_audio_stable:
            scripts.append(self._audio_stable_script())
        if self.config.enable_headless_sanitize:
            scripts.append(self._headless_sanitize_script())
        if self.config.enable_cdp_clean:
            scripts.append(self._cdp_clean_script())

        if self.config.enable_behavior_anti_detect:
            scripts.append(self._behavior_anti_detect_script())

        return "\n\n".join([
            "(function() {",
            "    'use strict';",
            "",
            *scripts,
            "",
            "})();"
        ])
    
    async def inject(self, page_or_context) -> None:
        """
        注入反检测脚本
        建议直接注入 BrowserContext,这样所有页面都会生效
        
        Args:
            page_or_context: Playwright Page 或 BrowserContext 对象
        """
        full_script = self.get_inject_script()
        
        # 支持 Page 或 BrowserContext
        if hasattr(page_or_context, 'add_init_script'):
            await page_or_context.add_init_script(full_script)
        else:
            raise ValueError("必须是 Page 或 BrowserContext 对象")
            
        print("[AntiDetect] All scripts injected")

    # ===== 私有方法:各个注入脚本 =====

    def _webdriver_mask_script(self) -> str:
        """隐藏 webdriver 自动化特征"""
        return r"""
        // ==== WebDriver 特征隐藏 ====
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        
        // 移除 chrome.runtime 等特征
        try {
            delete window.cdc_adoQpoasnfa76pfcZLmcfl_;
            delete window.cdc_asdjflasutopfhvcZLmcfl_;
        } catch (e) {}
        
        // Permissions 伪装
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // 插件伪装:模拟真实浏览器的插件列表
        if (!navigator.plugins || navigator.plugins.length === 0) {
            const fakePlugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            
            Object.defineProperty(navigator, 'plugins', {
                get: () => fakePlugins,
                configurable: true
            });
        }
        
        // 语言伪装
        Object.defineProperty(navigator, 'languages', {
            get: () => ['zh-CN', 'zh', 'en-US', 'en'],
            configurable: true
        });
        
        // Chrome 对象伪装
        if (!window.chrome) {
            window.chrome = {
                runtime: {},
                loadTimes: () => ({}),
                csi: () => ({})
            };
        }
        
        // permissions 伪装
        if (!navigator.permissions) {
            navigator.permissions = {
                query: () => Promise.resolve({ state: 'granted' })
            };
        }
        """

    def _json_patch_script(self) -> str:
        """JSON.parse 补丁 - 可自定义数据篡改"""
        enable_rid = str(self.config.random_request_id).lower()
        enable_ts = str(self.config.random_timestamp).lower()
        enable_al = str(self.config.random_accept_language).lower()
        
        return f"""
        // ==== JSON.parse 定向补丁 ====
        const _originalParse = JSON.parse;
        
        // 全局 patch 钩子注册表
        window.__shopauto_json_patches = window.__shopauto_json_patches || [];
        
        function applyPatches(obj, visited) {{
            if (!obj || typeof obj !== 'object') return obj;
            if (visited.has(obj)) return obj;
            visited.add(obj);
            
            // 递归遍历
            if (Array.isArray(obj)) {{
                obj.forEach(item => applyPatches(item, visited));
            }} else {{
                for (const key of Object.keys(obj)) {{
                    try {{
                        applyPatches(obj[key], visited);
                    }} catch (e) {{}}
                }}
            }}
            
            // 执行自定义补丁
            for (const patch of window.__shopauto_json_patches) {{
                try {{ patch(obj); }} catch (e) {{}}
            }}
            
            return obj;
        }}
        
        JSON.parse = function(text, reviver) {{
            const result = _originalParse(text, reviver);
            try {{
                applyPatches(result, new WeakSet());
            }} catch (e) {{}}
            return result;
        }};
        
        // 隐藏 toString
        Object.defineProperty(JSON.parse, 'toString', {{
            value: () => 'function parse() {{ [native code] }}',
            configurable: true
        }});
        
        // 暴露添加补丁的 API
        window.__shopauto_addJsonPatch = function(patchFn) {{
            window.__shopauto_json_patches.push(patchFn);
        }};
        
        // 预置:解除售罄状态补丁(可按需启用)
        window.__shopauto_addJsonPatch(function disableSoldOut(obj) {{
            if (obj.isSoldOut === true) obj.isSoldOut = false;
            if (obj.soldOut === true) obj.soldOut = false;
            if (obj.disabled === true && obj.price !== undefined) obj.disabled = false;
            if (obj.stock === 0 && obj.productId) obj.stock = 999;
        }});
        """

    def _fetch_hook_script(self) -> str:
        """fetch hook - 请求指纹随机化 (2026-07-06 修复 method 丢失 bug)

        之前 const options = { ...(init || {}) } 在 init.method 未设时让 fetch 退回 GET
        导致 captcha 提交等 POST 请求被服务端以 405 拒绝.
        """
        return r'''
        // ==== fetch 请求拦截与指纹随机化 ====
        const _originalFetch = window.fetch;
        const _cfg = window.__shopauto_fetch_cfg || { rid: true, ts: true, al: true };
        window.__shopauto_fetch_hooks = window.__shopauto_fetch_hooks || [];

        window.fetch = async function(input, init) {
            let finalInit;
            if (init) {
                finalInit = {};
                for (const k in init) {
                    if (k !== "headers") finalInit[k] = init[k];
                }
                finalInit.headers = {};
                if (init.headers) {
                    if (init.headers instanceof Headers) {
                        for (const [k, v] of init.headers.entries()) {
                            finalInit.headers[k] = v;
                        }
                    } else if (Array.isArray(init.headers)) {
                        for (const [k, v] of init.headers) {
                            finalInit.headers[k] = v;
                        }
                    } else {
                        for (const k in init.headers) {
                            finalInit.headers[k] = init.headers[k];
                        }
                    }
                }
                if (_cfg.rid) finalInit.headers["X-Request-Id"] = Math.random().toString(36).slice(2, 15);
                if (_cfg.ts)  finalInit.headers["X-Timestamp"]  = String(Date.now());
                if (_cfg.al && !finalInit.headers["Accept-Language"]) {
                    finalInit.headers["Accept-Language"] = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7";
                }
            } else {
                const headers = {};
                if (_cfg.rid) headers["X-Request-Id"] = Math.random().toString(36).slice(2, 15);
                if (_cfg.ts)  headers["X-Timestamp"]  = String(Date.now());
                if (_cfg.al)  headers["Accept-Language"] = "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7";
                if (Object.keys(headers).length > 0) {
                    finalInit = { headers };
                } else {
                    finalInit = undefined;
                }
            }

            if (finalInit && window.__shopauto_fetch_hooks) {
                const url = typeof input === "string" ? input : input.url;
                for (const hook of window.__shopauto_fetch_hooks) {
                    try { hook(url, finalInit); } catch (e) {}
                }
            }

            if (input instanceof Request && finalInit) {
                try {
                    const merged = new Request(input, finalInit);
                    return _originalFetch.call(this, merged);
                } catch (e) {
                    return _originalFetch.call(this, input, finalInit);
                }
            }
            return _originalFetch.call(this, input, finalInit);
        };

        // 隐藏 toString
        Object.defineProperty(window.fetch, "toString", {
            value: () => "function fetch() { [native code] }",
            configurable: true
        });

        // 暴露添加 hook 的 API
        window.__shopauto_addFetchHook = function(hookFn) {
            window.__shopauto_fetch_hooks.push(hookFn);
        };

        // 写配置 (供 cdp_apply_antidetect 等调用方动态改)
        window.__shopauto_fetch_cfg = {
            rid: %s,
            ts:  %s,
            al:  %s,
        };
        ''' % (
            str(self.config.random_request_id).lower(),
            str(self.config.random_timestamp).lower(),
            str(self.config.random_accept_language).lower(),
        )


    def _fingerprint_random_script(self) -> str:
        """Canvas/WebGL 指纹随机化"""
        return r"""
        // ==== Canvas 指纹随机化 ====
        const _originalGetContext = HTMLCanvasElement.prototype.getContext;
        
        HTMLCanvasElement.prototype.getContext = function(type, options) {
            const ctx = _originalGetContext.apply(this, [type, options]);
            
            if (type === '2d') {
                const _originalFillText = ctx.fillText;
                ctx.fillText = function(text, x, y, maxWidth) {
                    // 添加微小噪声,不影响视觉但改变哈希
                    ctx.globalAlpha = 0.99 + Math.random() * 0.01;
                    const result = _originalFillText.apply(this, [text, x, y, maxWidth]);
                    ctx.globalAlpha = 1;
                    return result;
                };
                
                const _originalGetImageData = ctx.getImageData;
                ctx.getImageData = function(sx, sy, sw, sh) {
                    const imgData = _originalGetImageData.apply(this, [sx, sy, sw, sh]);
                    // 对像素数据添加微小噪声
                    const data = imgData.data;
                    for (let i = 0; i < data.length; i += 4) {
                        if (Math.random() < 0.01) {
                            data[i] = Math.max(0, Math.min(255, data[i] + (Math.random() - 0.5) * 2));
                        }
                    }
                    return imgData;
                };
            }
            
            return ctx;
        };
        
        // ==== WebGL 指纹随机化 ====
        try {
            const _originalGetParameter = WebGLRenderingContext.prototype.getParameter;
            WebGLRenderingContext.prototype.getParameter = function(param) {
                // 对某些参数返回微小差异
                if (param === 37445) { // UNMASKED_VENDOR_WEBGL
                    return 'Intel Inc.';
                }
                if (param === 37446) { // UNMASKED_RENDERER_WEBGL
                    return 'Intel(R) UHD Graphics 620';
                }
                return _originalGetParameter.apply(this, [param]);
            };
        } catch (e) {}
        """

    def _shadow_dom_script(self) -> str:
        """Shadow DOM 工具函数 - 仅暴露 API, 不再自动创建面板。

        旧版本会在每次新页面加载完后自动调 __shopauto_createShadowPanel(),
        创建右上角的 '🛡️ WebAuto 已注入' 浮动 UI。真实站调试时
        该 div 会挡住登录按钮 / 验证码, 2026-07-06 决定彻底拿掉 auto-create 段,
        只保留工具函数 __shopauto_createShadowPanel() /
        __shopauto_removeShadowPanel(), 谁需要谁手动调。
        """
        return r"""
        // ==== Shadow DOM 面板创建工具 ====
        window.__shopauto_createShadowPanel = function(panelId, htmlContent) {
            // 检查是否已存在
            const host = document.getElementById(panelId);
            if (host) return host.shadowRoot;
            
            // 创建 host 元素
            const newHost = document.createElement('div');
            newHost.id = panelId;
            newHost.style.all = 'initial';
            newHost.style.cssText = `
                position: fixed;
                top: 10px;
                right: 10px;
                z-index: 999999;
                background: transparent;
                border: none;
                margin: 0;
                padding: 0;
            `;
            document.body.appendChild(newHost);
            
            // 创建 closed shadow root
            const shadow = newHost.attachShadow({ mode: 'closed' });
            shadow.innerHTML = htmlContent || `
                <style>
                .panel {
                    width: 320px;
                    background: rgba(26, 26, 46, 0.95);
                    color: #e0e0e0;
                    border-radius: 8px;
                    padding: 12px;
                    font-size: 12px;
                    font-family: system-ui;
                    box-shadow: 0 4px 24px rgba(0,0,0,.4);
                    backdrop-filter: blur(10px);
                }
                .title { font-size: 14px; font-weight: 600; margin-bottom: 8px; }
                .status { display: flex; gap: 8px; flex-wrap: wrap; }
                .item { display: flex; align-items: center; gap: 4px; }
                .dot { width: 8px; height: 8px; border-radius: 50%; }
                .dot.green { background: #4ade80; }
                </style>
                <div class="panel">
                    <div class="title">🛡️ WebAuto</div>
                    <div class="status">
                        <div class="item"><span class="dot green"></span> 已注入</div>
                    </div>
                </div>
            `;
            
            return shadow;
        };
        
        // 主动移除已创建的浮动 panel (供 clean-ui 工具调用)
        window.__shopauto_removeShadowPanel = function(panelId) {
            const id = panelId || '__shopauto_panel';
            const host = document.getElementById(id);
            if (host && host.parentNode) host.parentNode.removeChild(host);
            return !!host;
        };
        """



# =================================================================
# =================================================================



    def _resolve_fingerprint_seed(self):
        """统一一个 stable seed 给 Canvas/WebGL/Audio 噪声使用。
        配置里 fingerprint_seed 显式给值则用之,否则随机生成并回写到 config
        (以便后续 Page / Profile 复用)。
        """
        if self.config.fingerprint_seed is not None:
            return int(self.config.fingerprint_seed)
        import random as _r
        seed = _r.randint(0, 2**31 - 1)
        self.config.fingerprint_seed = seed
        return seed

    def _fingerprint_seed_js(self):
        """mulberry32 PRNG。返回形如 (function(seed){...})(12345) 的 JS 表达式。"""
        seed = self._resolve_fingerprint_seed()
        return (
            "(function(seed){var t=seed>>>0;return function(){"
            "t=(t+0x6D2B79F5)|0;var x=Math.imul(t^(t>>>15),1|t);"
            "x=(x+Math.imul(x^(x>>>7),61|x))^x;"
            "return((x^(x>>>14))>>>0)/4294967296;};})(" + str(seed) + ")"
        )

    def _realistic_plugins_script(self):
        """真 PluginArray + MimeTypeArray,覆盖 fingerprint.com 等检测点。"""
        return r"""
        (function(){
            try {
                const fakePlugin = function(name, filename, description) {
                    const p = Object.create(Plugin.prototype);
                    Object.defineProperties(p, {
                        name:        { value: name,        enumerable: true },
                        filename:    { value: filename,    enumerable: true },
                        description: { value: description, enumerable: true },
                        length:      { value: 1,          enumerable: true },
                    });
                    return p;
                };
                const fakeMime = function(type, suffixes, description) {
                    const m = Object.create(MimeType.prototype);
                    Object.defineProperties(m, {
                        type:        { value: type,        enumerable: true },
                        suffixes:    { value: suffixes,    enumerable: true },
                        description: { value: description, enumerable: true },
                    });
                    return m;
                };
                const pdf = fakePlugin('PDF Viewer', 'internal-pdf-viewer', 'Portable Document Format');
                const xml = fakePlugin('Chrome XML Viewer', 'expat-mmllib-', 'XML Viewer Plugin');
                const pluginsArr = [];
                pluginsArr.push(pdf);
                pluginsArr.push(xml);
                pluginsArr.length = 2;
                pluginsArr.item  = function(i){ return pluginsArr[i] || null; };
                pluginsArr.namedItem = function(n){
                    for (let i = 0; i < pluginsArr.length; i++)
                        if (pluginsArr[i].name === n) return pluginsArr[i];
                    return null;
                };
                pluginsArr.refresh = function(){};
                Object.defineProperty(navigator, 'plugins', {
                    get: () => pluginsArr, configurable: true,
                });
                const mimesArr = [];
                mimesArr.push(fakeMime('application/pdf', 'pdf', 'Portable Document Format'));
                mimesArr.length = 1;
                mimesArr.item  = function(i){ return mimesArr[i] || null; };
                mimesArr.namedItem = function(n){
                    for (let i = 0; i < mimesArr.length; i++)
                        if (mimesArr[i].type === n) return mimesArr[i];
                    return null;
                };
                Object.defineProperty(navigator, 'mimeTypes', {
                    get: () => mimesArr, configurable: true,
                });
            } catch(e) {}
        })();
        """

    def _consistent_hardware_script(self):
        """screen / hardwareConcurrency / deviceMemory 一致化(同 context 稳定)。"""
        import random as _r
        cores_choices = [4, 8, 12, 16]
        memory_choices = [4, 8, 16]
        dpr_choices = [1, 1.25, 1.5, 2]
        screens = [
            (1920, 1080, 24), (2560, 1440, 24), (1366, 768, 24),
            (1440, 900, 24),  (1680, 1050, 24), (1280, 800, 24),
        ]
        cores = _r.choice(cores_choices)
        mem   = _r.choice(memory_choices)
        dpr   = _r.choice(dpr_choices)
        sw, sh, depth = _r.choice(screens)
        return f"""
        (function(){{
            try {{
                Object.defineProperty(navigator, 'hardwareConcurrency', {{
                    get: () => {cores}, configurable: true,
                }});
                Object.defineProperty(navigator, 'deviceMemory', {{
                    get: () => {mem}, configurable: true,
                }});
                const fakeScreen = {{
                    width: {sw}, height: {sh},
                    availWidth: {sw}, availHeight: {sh - 40},
                    colorDepth: {depth}, pixelDepth: {depth},
                    orientation: {{ type: 'landscape-primary', angle: 0 }},
                }};
                try {{
                    Object.defineProperty(window, 'screen', {{
                        get: () => fakeScreen, configurable: true,
                    }});
                }} catch(e) {{}}
                try {{
                    Object.defineProperty(window, 'devicePixelRatio', {{
                        get: () => {dpr}, configurable: true,
                    }});
                }} catch(e) {{}}
            }} catch(e) {{}}
        }})();
        """

    def _locale_consistency_script(self):
        """Intl.DateTimeFormat timezone 与 navigator.language 一致。"""
        return r"""
        (function(){
            try {
                const locale = navigator.language || 'zh-CN';
                let tz = 'Asia/Shanghai';
                try {
                    const opts = new Intl.DateTimeFormat().resolvedOptions();
                    if (opts && opts.timeZone) tz = opts.timeZone;
                } catch(e) {}
                const _origDTF = Intl.DateTimeFormat;
                Intl.DateTimeFormat = function(loc, opts) {
                    opts = Object.assign({}, opts || {});
                    if (opts.timeZone === undefined) opts.timeZone = tz;
                    return new _origDTF(loc, opts);
                };
                Intl.DateTimeFormat.prototype = _origDTF.prototype;
                Intl.DateTimeFormat.supportedLocalesOf = _origDTF.supportedLocalesOf;
                try {
                    Object.defineProperty(document.documentElement, 'lang', {
                        get: () => locale, configurable: true,
                    });
                } catch(e) {}
            } catch(e) {}
        })();
        """

    def _fingerprint_v2_script(self):
        """Canvas 2D + WebGL 噪声(stable seed),替代 _fingerprint_random_script 的新版本。"""
        seed_js = self._fingerprint_seed_js()
        return f"""
        (function(){{
            const __seedFn = {seed_js};
            // ==== Canvas 2D toDataURL 微抖动 ====
            try {{
                const _origToDataURL = HTMLCanvasElement.prototype.toDataURL;
                HTMLCanvasElement.prototype.toDataURL = function(...args) {{
                    const ctx = this.getContext('2d');
                    if (ctx) {{
                        const img = ctx.getImageData(0, 0, this.width, this.height);
                        const d = img.data;
                        for (let i = 0; i < d.length; i += 4) {{
                            if (__seedFn() < 0.005) {{
                                const r = (__seedFn() * 2 | 0) - 1;
                                d[i]     = Math.max(0, Math.min(255, d[i]     + r));
                                d[i + 1] = Math.max(0, Math.min(255, d[i + 1] + r));
                                d[i + 2] = Math.max(0, Math.min(255, d[i + 2] + r));
                            }}
                        }}
                        ctx.putImageData(img, 0, 0);
                    }}
                    return _origToDataURL.apply(this, args);
                }};
            }} catch(e) {{}}

            // ==== WebGL 渲染器/供应商 stable 随机化 ====
            try {{
                const VENDORS = ['Intel Inc.', 'Apple Inc.', 'NVIDIA Corporation',
                                 'Advanced Micro Devices, Inc.', 'ARM'];
                const RENDERERS = [
                    'Apple M1', 'Apple M2',
                    'Intel(R) UHD Graphics 630',
                    'Intel(R) Iris(R) Plus Graphics 640',
                    'NVIDIA GeForce GTX 1050',
                    'Mesa Intel(R) UHD Graphics 620 (KBL GT2)',
                    'AMD Radeon Pro 560X OpenGL Engine',
                ];
                const v = VENDORS[Math.floor(__seedFn() * VENDORS.length)];
                const r = RENDERERS[Math.floor(__seedFn() * RENDERERS.length)];

                const _setGetParam = function(proto) {{
                    if (!proto) return;
                    const _orig = proto.getParameter;
                    proto.getParameter = function(p) {{
                        if (p === 37445) return v;
                        if (p === 37446) return r;
                        return _orig.call(this, p);
                    }};
                }};
                _setGetParam(WebGLRenderingContext.prototype);
                if (window.WebGL2RenderingContext)
                    _setGetParam(WebGL2RenderingContext.prototype);
            }} catch(e) {{}}
        }})();
        """

    def _audio_stable_script(self):
        """AudioContext fingerprint 稳态化(stable seed 微扰 attack/release 等)。"""
        seed_js = self._fingerprint_seed_js()
        return f"""
        (function(){{
            const __seedFn = {seed_js};
            try {{
                const AC = window.AudioContext || window.webkitAudioContext;
                if (!AC) return;
                const _wrap = function(node) {{
                    const drift = (__seedFn() - 0.5) * 0.001;
                    try {{
                        node.threshold.value = -24 + drift;
                        node.knee.value     = 30  + drift * 10;
                        node.ratio.value    = 12  + drift * 0.5;
                        node.attack.value   = 0.003 + Math.abs(drift);
                        node.release.value  = 0.25  + Math.abs(drift);
                    }} catch(e) {{}}
                    return node;
                }};
                const _origCreate = AC.prototype.createDynamicsCompressor;
                AC.prototype.createDynamicsCompressor = function(){{
                    return _wrap(_origCreate.call(this));
                }};
                if (window.OfflineAudioContext) {{
                    const OAC = window.OfflineAudioContext;
                    const _o = OAC.prototype.createDynamicsCompressor;
                    if (_o) {{
                        OAC.prototype.createDynamicsCompressor = function(){{
                            return _wrap(_o.call(this));
                        }};
                    }}
                }}
            }} catch(e) {{}}
        }})();
        """

    def _headless_sanitize_script(self):
        """清理 userAgentData.brands 里的 Headless 字眼 + UA 中 HeadlessChrome。"""
        return r"""
        (function(){
            try {
                if (navigator.userAgentData && navigator.userAgentData.brands) {
                    const sanitized = (navigator.userAgentData.brands || [])
                        .filter(b => b && b.brand &&
                                     !/headless/i.test(b.brand) &&
                                     !/headless/i.test(b.version || ''));
                    if (sanitized.length === 0) {
                        sanitized.push({brand: 'Chromium',     version: '120'});
                        sanitized.push({brand: 'Not_A Brand',  version: '24'});
                    }
                    Object.defineProperty(navigator.userAgentData, 'brands', {
                        get: () => sanitized, configurable: true,
                    });
                }
            } catch(e) {}
            try {
                const cleanUA = (navigator.userAgent || '')
                    .replace(/HeadlessChrome/g, 'Chrome')
                    .replace(/Headless\//g, '');
                Object.defineProperty(navigator, 'userAgent', {
                    get: () => cleanUA, configurable: true,
                });
                if (navigator.appVersion) {
                    const cleanAV = navigator.appVersion
                        .replace(/HeadlessChrome/g, 'Chrome')
                        .replace(/Headless\//g, '');
                    Object.defineProperty(navigator, 'appVersion', {
                        get: () => cleanAV, configurable: true,
                    });
                }
            } catch(e) {}
        })();
        """

    def _cdp_clean_script(self):
        """伪造 chrome.loadTimes / chrome.csi / chrome.app 数据, 遮盖 playwright 内部标识。"""
        seed_js = self._fingerprint_seed_js()
        return f"""
        (function(){{
            const __seedFn = {seed_js};
            try {{
                if (!window.chrome) window.chrome = {{}};
                const baseT = Date.now();
                window.chrome.loadTimes = function() {{
                    return {{
                        requestTime: (baseT - 1000) / 1000,
                        startLoadTime: (baseT - 950) / 1000,
                        commitLoadTime: (baseT - 900) / 1000,
                        finishDocumentLoadTime: (baseT - 800) / 1000,
                        finishLoadTime: (baseT - 700) / 1000,
                        firstPaintTime: (baseT - 750) / 1000,
                        firstPaintAfterLoadTime: 0,
                        navigationType: 'Other',
                        wasFetchedViaSpdy: false,
                        wasNegotiatedAfterTLSResumed: false,
                        connectionInfo: 'http/2',
                    }};
                }};
                window.chrome.csi = function() {{
                    return {{
                        onloadT:  baseT - 800,
                        startE:   baseT - 1000,
                        pageT:    200,
                        tran:     15,
                    }};
                }};
                window.chrome.app = {{
                    isInstalled: false,
                    InstallState: {{ DISABLED:'disabled', INSTALLED:'installed', NOT_INSTALLED:'not_installed' }},
                    RunningState: {{ CANNOT_RUN:'cannot_run', READY_TO_RUN:'ready_to_run', RUNNING:'running' }},
                }};
                if (!window.chrome.runtime) {{
                    window.chrome.runtime = {{}};
                }}
            }} catch(e) {{}}

            try {{
                Object.defineProperty(window, '__pwInitScripts', {{
                    get: () => undefined, configurable: true,
                }});
                Object.defineProperty(window, '__pwFrameId', {{
                    get: () => undefined, configurable: true,
                }});
                try {{
                    Object.defineProperty(document.documentElement, 'dataset', {{
                        get: () => ({{ pwright: undefined, __playwright: undefined }}),
                        configurable: true,
                    }});
                }} catch(e) {{}}
            }} catch(e) {{}}
        }})();
        """

    def _behavior_anti_detect_script(self) -> str:
        """行为级反检测 (2026-07-06 加强, 解决 bigmodel.cn 中文点选 captcha 405)。

        针对 captcha 提交时的 anti-bot 检查点:
        1. 真 PluginArray 原型链 (navigator.plugins 必须是 PluginArray.prototype 实例)
        2. chrome.runtime Proxy (id 必须 undefined, 跟非扩展 Chrome 一致)
        3. PointerEvent / MouseEvent 字段补全 (pressure, pointerId, isPrimary)
        4. visibilityState / hasFocus 在 tab active 时返回 visible/focused
        5. document.__cdp_sessions / __pwInitScripts 痕迹清理
        6. navigator.connection 补全 (rtt, downlink, effectiveType)
        7. performance.now 精度降级 (避免暴露 CDP 高精度时间)
        8. Notification.permission 默认 default
        """
        return r'''
        // ==== 行为级反检测 (2026-07-06 加强) ====

        // ---- 1. 真 PluginArray 原型链 ----
        (function makeRealisticPlugins() {
            if (typeof Plugin === 'undefined' || typeof PluginArray === 'undefined') return;
            try {
                const PLUGIN_DATA = [
                    { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format', type: 'application/pdf' },
                    { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '', type: 'application/pdf' },
                    { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format', type: 'application/pdf' }
                ];
                const plugins = [];
                for (const d of PLUGIN_DATA) {
                    const p = Object.create(Plugin.prototype);
                    Object.defineProperties(p, {
                        name:        { value: d.name,        enumerable: true,  configurable: true },
                        filename:    { value: d.filename,    enumerable: true,  configurable: true },
                        description: { value: d.description, enumerable: true,  configurable: true },
                        length:      { value: 1,            enumerable: true,  configurable: true }
                    });
                    const mt = Object.create(MimeType.prototype);
                    Object.defineProperties(mt, {
                        type:          { value: d.type,        enumerable: true,  configurable: true },
                        description:   { value: d.description, enumerable: true,  configurable: true },
                        suffixes:      { value: 'pdf',         enumerable: true,  configurable: true },
                        enabledPlugin: { value: p,             enumerable: false, configurable: true }
                    });
                    p[0] = mt;
                    p.item = function(i) { return i === 0 ? mt : null; };
                    p.namedItem = function(n) { return n === d.type ? mt : null; };
                    plugins.push(p);
                }
                const pa = Object.create(PluginArray.prototype);
                plugins.forEach(function(p, i) { pa[i] = p; });
                Object.defineProperties(pa, {
                    length:    { value: plugins.length, enumerable: true, configurable: true },
                    item:      { value: function(i) { return plugins[i] || null; }, enumerable: false, configurable: true },
                    namedItem: { value: function(n) { return plugins.find(function(p){return p.name===n;}) || null; }, enumerable: false, configurable: true },
                    refresh:   { value: function() {}, enumerable: false, configurable: true }
                });
                Object.defineProperty(navigator, 'plugins', { get: function() { return pa; }, configurable: true, enumerable: true });

                const mimes = plugins.map(function(p, i) {
                    const mt = Object.create(MimeType.prototype);
                    Object.defineProperties(mt, {
                        type:          { value: PLUGIN_DATA[i].type,        enumerable: true,  configurable: true },
                        description:   { value: PLUGIN_DATA[i].description, enumerable: true, configurable: true },
                        suffixes:      { value: 'pdf',                      enumerable: true,  configurable: true },
                        enabledPlugin: { value: p,                          enumerable: false, configurable: true }
                    });
                    return mt;
                });
                const mta = Object.create(MimeTypeArray.prototype);
                mimes.forEach(function(m, i) { mta[i] = m; });
                Object.defineProperties(mta, {
                    length:    { value: mimes.length, enumerable: true, configurable: true },
                    item:      { value: function(i) { return mimes[i] || null; }, enumerable: false, configurable: true },
                    namedItem: { value: function(n) { return mimes.find(function(m){return m.type===n;}) || null; }, enumerable: false, configurable: true }
                });
                Object.defineProperty(navigator, 'mimeTypes', { get: function() { return mta; }, configurable: true, enumerable: true });
            } catch (e) {}
        })();

        // ---- 2. chrome.runtime Proxy (id 必须是 undefined) ----
        (function () {
            try {
                if (window.chrome && window.chrome.runtime && typeof window.chrome.runtime.id !== 'undefined') return;
                const rt = new Proxy({}, {
                    get: function(t, p) {
                        if (p === 'id') return undefined;
                        if (p === 'OnInstalledReason' || p === 'OnRestartRequiredReason') return undefined;
                        if (p === 'PlatformArch' || p === 'PlatformNaclArch' || p === 'PlatformOs') return undefined;
                        if (p === 'RequestUpdateCheckStatus') return undefined;
                        if (p === 'connect') return function() {};
                        if (p === 'sendMessage') return function() { return Promise.resolve(); };
                        if (p === 'onMessage' || p === 'onInstalled' || p === 'onStartup') {
                            return { addListener: function() {}, removeListener: function() {}, hasListener: function() { return false; } };
                        }
                        if (p === 'getManifest') return function() { return { version: '0.0.0', name: '' }; };
                        if (p === 'getURL') return function() { return ''; };
                        if (p === 'getPlatformInfo') return function() { return Promise.resolve({ os: 'linux', arch: 'x86_64', nacl_arch: 'x86_64' }); };
                        if (p === 'lastError') return undefined;
                        return undefined;
                    },
                    has: function() { return true; }
                });
                if (!window.chrome) window.chrome = {};
                window.chrome.runtime = rt;
            } catch (e) {}
        })();

        // ---- 3. PointerEvent / MouseEvent 字段补全 (捕获阶段, 不影响 isTrusted) ----
        (function () {
            try {
                document.addEventListener('click', function(e) {
                    if (e.isTrusted) return;
                    if (e.pointerId === undefined) e.pointerId = 1;
                    if (e.pressure === undefined) e.pressure = 0.5;
                    if (e.pointerType === undefined) e.pointerType = 'mouse';
                    if (e.isPrimary === undefined) e.isPrimary = true;
                }, true);
                document.addEventListener('pointerdown', function(e) {
                    if (e.isTrusted) return;
                    if (e.pointerId === undefined) e.pointerId = 1;
                    if (e.pressure === undefined) e.pressure = 0.5;
                    if (e.pointerType === undefined) e.pointerType = 'mouse';
                }, true);
            } catch (e) {}
        })();

        // ---- 4. visibilityState 修复 ----
        (function () {
            try {
                if (typeof document.visibilityState === 'string' && document.visibilityState === 'hidden') {
                    Object.defineProperty(document, 'visibilityState', { get: function() { return 'visible'; }, configurable: true });
                }
            } catch (e) {}
        })();

        // ---- 5. document.__cdp_sessions / __pwInitScripts 等痕迹清理 ----
        (function () {
            try {
                const props = ['__cdp_sessions', '__pwInitScripts', '__pwFrameId', '__playwright_run', '__playwright_evaluate'];
                for (let i = 0; i < props.length; i++) {
                    const p = props[i];
                    if (p in window) {
                        try { Object.defineProperty(window, p, { get: function() { return undefined; }, configurable: true }); } catch (e) {}
                    }
                    if (p in document.documentElement) {
                        try { Object.defineProperty(document.documentElement, p, { get: function() { return undefined; }, configurable: true }); } catch (e) {}
                    }
                }
            } catch (e) {}
        })();

        // ---- 6. navigator.connection 补全 ----
        (function () {
            try {
                if (!navigator.connection) {
                    Object.defineProperty(navigator, 'connection', {
                        get: function() {
                            return {
                                rtt: 50,
                                downlink: 10,
                                effectiveType: '4g',
                                saveData: false,
                                addEventListener: function() {},
                                removeEventListener: function() {}
                            };
                        },
                        configurable: true
                    });
                }
            } catch (e) {}
        })();

        // ---- 7. performance.now 精度降级 (避免暴露 CDP 高精度时间) ----
        (function () {
            try {
                const origNow = performance.now.bind(performance);
                performance.now = function() { return Math.round(origNow() * 100) / 100; };
            } catch (e) {}
        })();

        // ---- 8. Notification.permission 默认 default ----
        (function () {
            try {
                if (typeof Notification !== 'undefined' && Notification.permission === 'denied') {
                    Object.defineProperty(Notification, 'permission', { get: function() { return 'default'; }, configurable: true });
                }
            } catch (e) {}
        })();
        '''

# ===== 便捷函数 =====

def create_anti_detect_config(**kwargs) -> AntiDetectConfig:
    """创建反检测配置"""
    return AntiDetectConfig(**kwargs)
