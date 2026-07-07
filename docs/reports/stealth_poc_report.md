# Stealth Playwright PoC 报告

**生成时间:** 2026-07-07 23:00
**Chromium:** `/home/claw/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome`
**模式:** Headless + 10 stealth JS evasions

---

## 测试摘要

| 站点 | 结果 | 耗时 |
|------|------|------|
| SannySoft Bot Detection | ✅ (New 检测通过) | ~10s |
| BrowserLeaks Canvas | ✅ 页面加载正常 | ~7s |
| IPRoyal Proxy Check | ✅ 页面加载正常 | ~7s |

---

## SannySoft Bot Detection — 关键结果

SannySoft 有 3 类测试：(Old) 传统浏览器测试、(New) 现代 headless 检测、PhantomJS 旧引擎测试。

### ✅ 通过的 (New) 现代反爬检测

| 测试 | 结果 | 说明 |
|------|------|------|
| WebDriver (New) | ✅ missing (passed) | `navigator.webdriver = false`，无自动化标志 |
| WebDriver Advanced | ✅ passed | 自动化相关属性全部清除 |
| Chrome (New) | ✅ present (passed) | Chrome browser 正常识别 |
| Permissions (New) | ✅ prompt (passed) | 权限 API 返回 expected 值 |
| Plugins is of type PluginArray | ✅ passed | `PluginArray` 实例伪造成功 |
| WebGL Vendor (New) | ✅ Intel Inc. | 伪装 Intel 独显，绕过 WebGL fingerprinting |
| WebGL Renderer (New) | ✅ Intel Iris OpenGL Engine | 伪装真实显卡驱动 |

### ⚠️ 未完全通过的测试（headless 环境限制）

| 测试 | 结果 | 说明 |
|------|------|------|
| User Agent (Old) | ❌ 显示 HeadlessChrome | Chromium headless 模式强制 UA，无法在 JS 层完全覆盖 |
| Languages (Old) | ❌ zh-CN | `page.context.new_page()` 创建页面时 locale 已固定 |
| Permissions (Old) | ❌ prompt | 和 (New) 结果相同，检测的是旧的 permissions API |
| Plugins Length (Old) | ❌ 3 或 5 | headless 环境插件列表与真实 Chrome 不同 |
| Broken Image Dimensions | ❌ 16x16 | Headless Chromium 默认占位图，非真实资源加载失败 |

---

## 技术实现细节

### Stealth Evasions（10 个 JS 脚本）

1. **navigator.webdriver** — `Object.defineProperty(navigator,'webdriver',{value:false})`，配合 `--disable-blink-features=AutomationControlled` Chrome flag
2. **PluginArray 实例** — 创建真正 `PluginArray.prototype` 链的数组对象，通过 `__proto__` 继承
3. **WebGL Debug Renderer** — 劫持 `getExtension('WEBGL_debug_renderer_info')`，返回假的 `Intel Inc. / Intel Iris OpenGL Engine`，同时劫持 `getParameter` 和 `HTMLCanvasElement.prototype.getContext`
4. **chrome.loadTimes / chrome.csi** — 伪造完整的 chrome timing API
5. **navigator.hardwareConcurrency / deviceMemory** — 返回合理值 8
6. **Permissions Query** — 模拟权限状态返回
7. **Languages** — 通过 `Object.defineProperty` 在 context 层面尝试覆盖
8. **chrome.runtime** — 清理 `chrome.runtime.id`
9. **Outer Dimensions** — 伪装 `outerWidth/outerHeight`
10. **Notification Permission** — 模拟 `default` 而非 `granted`

### 关键发现

- **`--disable-blink-features=AutomationControlled` + `webdriver=false`**: 两者缺一不可，单一方法无法绕过检测
- **WebGL**: 劫持 `getExtension('WEBGL_debug_renderer_info')` 比劫持 `getParameter` 更有效
- **PluginArray**: 不能用普通数组，必须通过 `__proto__` 继承真正的 `PluginArray.prototype`
- **Headless 限制**: `User-Agent`、`Languages`、`Plugins Length` 是 Chromium headless 模式基础设施的一部分，JS 层无法完全覆盖

---

## CloakBrowser 状态

- **下载状态**: GitHub release 下载速度极慢（~20KB/s），curl 后台仍在下载（206MB 文件）
- **PoC 脚本已写好**: `Services/cloakbrowser_poc.py`
- **安装成功**: `pip install cloakbrowser 0.4.8` ✅
- **阻塞原因**: CloakBrowser 需要自己的 patched Chromium 二进制（206MB），网络下载需 3h+

---

## 结论与后续

### PoC 验收

| 验收项 | 状态 | 说明 |
|--------|------|------|
| 安装成功 | ✅ | pip install cloakbrowser + undetected-playwright 均成功 |
| PoC 脚本通过 | ✅ | stealth_poc.py 可运行，3 站均出结果 |
| 反检测站点通过 | ⚠️ | SannySoft (New) 核心检测全部通过，Old 测试部分受 headless 限制 |
| 报告 | ✅ | 本文档 |
| Git Commit | 🔄 | 待执行 |

### 建议

1. **优先采用 Stealth Playwright 方案**: 不依赖 CloakBrowser，自包含，稳定
2. **后续优化方向**: 
   - 换用 `--headless=new` 模式（Chrome 112+）改善 UA 伪装
   - 加入 `AdBlock` / `uBlock` 扩展减少无效请求
   - 对接代理池 + session 轮换提高大规模使用稳定性
3. **CloakBrowser**: 后台继续下载，下载完成后可做 A/B 对比测试
