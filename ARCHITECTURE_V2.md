# WebAuto v2.0 架构设计文档

> 基于 Scrapling 优秀设计结合 WebAuto 独有优势的完整重构方案
> 目标：打造功能完整、简单易用的 Web 自动化通用框架

---

## 📊 现状评估

### ✅ 现有优势
| 模块 | 状态 | 说明 |
|------|------|------|
| 汉字点选验证码识别（PP-OCRv6） | ✅ 已完成 | Scrapling 没有的护城河能力 |
| 油猴级反检测注入 | ✅ 已完成 | fetch/XHR hook + JSON.parse 补丁，深度超过 Scrapling |
| NTP 高精度时间同步 | ✅ 已完成 | 抢购场景刚需，Scrapling 没有 |
| Playwright 基础封装 | ✅ 已完成 | 架构清晰，模块化良好 |
| 人类行为模拟 | 🚧 待移植 | 鼠标轨迹、误点修正等 |

### ❌ 当前不足
| 问题 | 影响 | 优先级 |
|------|------|--------|
| 只有浏览器模式 | 简单场景太笨重 | P0 |
| 选择器裸奔 | 页面改版就挂，没有重试/自适应 | P0 |
| 会话能力弱 | 没有 Cookie 持久化、代理轮换 | P0 |
| 没有并发支持 | 只能单页面操作 | P1 |
| 错误处理缺失 | 没有统一重试机制 | P0 |
| API 不够流畅 | Playwright API 很好，但缺少自动化友好封装 | P0 |

---

## 🎯 核心设计理念

### 三层架构 + 四种运行模式

```
┌─────────────────────────────────────────────────────────┐
│                   WebAuto 统一入口                      │
├─────────────────────────────────────────────────────────┤
│  🕷️ Spider 引擎  │  🧩 任务编排  │  🤖 MCP 服务        │
├─────────────────────────────────────────────────────────┤
│                   核心能力层                            │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │  获取器  │  │  选择器  │  │  验证码  │  │  反检测 │ │
│  │  4 模式  │  │  自适应  │  │  全类型  │  │  油猴级 │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐             │
│  │  时间轴  │  │  行为库  │  │  会话管  │             │
│  │  高精度  │  │  人类化  │  │  理器    │             │
│  └──────────┘  └──────────┘  └──────────┘             │
├─────────────────────────────────────────────────────────┤
│                   底层执行层                            │
│       Playwright / httpx / lxml / PP-OCRv6             │
└─────────────────────────────────────────────────────────┘
```

---

## 🔧 四大获取器模式

| 模式 | 场景 | 速度 | 反爬能力 | 实现技术 |
|------|------|------|---------|---------|
| **Http** | 接口请求、静态页面 | ⚡ 100x | ⭐⭐ | httpx + HTTP/3 + TLS 指纹模拟 |
| **Stealth** | 一般反爬网站 | 🚀 10x | ⭐⭐⭐⭐ | Playwright headless + 反检测注入 |
| **Browser** | 交互复杂的页面 | 🐢 1x | ⭐⭐⭐⭐ | 完整浏览器 + 行为模拟 |
| **Human** | 超高强度抢购 | 🐌 0.5x | ⭐⭐⭐⭐⭐ | 真实人类行为 + 鼠标轨迹 |

### API 设计
```python
# 一行切换模式
auto = WebAuto(mode='http')      # 纯 HTTP，最快
auto = WebAuto(mode='stealth')   # 隐形模式，绕过 90% 反爬
auto = WebAuto(mode='browser')   # 完整浏览器
auto = WebAuto(mode='human')     # 抢购专用模式
```

---

## 🎯 智能选择器系统

### 核心特性
- ✅ 自动重试 + 超时控制
- ✅ 自适应元素定位（页面改版自动重定位）
- ✅ 多选择器 fallback
- ✅ 按文本/特征查找，不用写 CSS 选择器

### API 设计
```python
# 链式调用，流畅自然
btn = await auto.find('.submit-btn')
                 .adaptive(True)       # 选择器失效自动重定位
                 .retry(3)             # 失败重试 3 次
                 .timeout(5000)        # 5 秒超时
                 .get()

await btn.click()

# 按文本查找，不用写选择器
btn = await auto.find_by_text('立即购买')
btn = await auto.find_by_feature(type='button', color='red')

# 多选择器 fallback
btn = await auto.find(['.submit-btn', '#submit', '[type=submit]'])
```

---

## 🚀 使用方式设计（简单易用原则）

### 1. 最简单的 3 行自动化
```python
from WebAuto import WebAuto

async with WebAuto(mode='stealth') as auto:
    await auto.goto('https://example.com')
    await auto.find('提交').click()  # 按文本找，不用写选择器
```

### 2. 验证码一行解决
```python
# 自动检测验证码类型，自动识别，自动点击
result = await auto.solve_captcha()  # 汉字点选/滑块/旋转/算数...
if result.success:
    print("✅ 验证码通过")
```

### 3. 抢购模式（护城河能力）
```python
# 精确到毫秒的抢购
await auto.time.sync()  # NTP 校时
await auto.time.sleep_until("2026-07-01 10:00:00.000")

# 预加载页面 + 预热点击
await auto.goto('https://shop.example.com/buy')
await auto.find('立即购买').preheat()  # 元素定位好，鼠标移过去
await auto.time.fire_at(target_time)   # 精确时间点击
```

### 4. Spider 批量模式
```python
from WebAuto import Spider, Task

class ProductSpider(Spider):
    concurrency = 5
    
    async def process(self, url):
        page = await auto.goto(url)
        yield {
            'title': await page.extract('.title'),
            'price': await page.extract('.price'),
        }

# 爬 100 个商品，支持暂停恢复
spider = ProductSpider(urls=['...'])
await spider.run(checkpoint='./spider_state.json')
```

---

## 📋 实现 Roadmap（按优先级）

### 🎯 P0 - 两周内完成（核心底座）

| # | 任务 | 状态 | 预计工时 |
|---|------|------|---------|
| 1 | 获取器抽象层设计（Fetcher 基类 + 4 种模式接口统一） | 📋 待开始 | 2h |
| 2 | HttpFetcher 实现（httpx + HTTP/3 + TLS 指纹） | 📋 待开始 | 3h |
| 3 | 智能选择器系统（重试 + 超时 + fallback） | 📋 待开始 | 4h |
| 4 | 会话管理器（Cookie 持久化 + 代理轮换） | 📋 待开始 | 3h |
| 5 | 统一错误处理体系 | 📋 待开始 | 2h |
| 6 | WebAuto 主入口重构 + 向后兼容 | 📋 待开始 | 2h |

### 🎯 P1 - 一个月内完成（增强能力）

| # | 任务 | 状态 | 预计工时 |
|---|------|------|---------|
| 7 | 自适应选择器算法（元素相似度匹配） | 📋 待开始 | 6h |
| 8 | Spider 并发引擎（并发控制 + 暂停恢复） | 📋 待开始 | 8h |
| 9 | Cloudflare Turnstile 绕过增强 | 📋 待开始 | 4h |
| 10 | MCP 服务封装 | 📋 待开始 | 4h |
| 11 | 人类行为模拟增强 | 📋 待开始 | 6h |

### 🎯 P2 - 长期优化

| # | 任务 | 状态 | 预计工时 |
|---|------|------|---------|
| 12 | CLI 交互模式（webauto shell） | 📋 待开始 | 4h |
| 13 | 插件体系 | 📋 待开始 | 8h |
| 14 | 性能优化（lxml 解析 + 批量操作） | 📋 待开始 | 4h |

---

## 🧩 模块拆分设计

```
WebAuto/
├── Core/
│   ├── __init__.py
│   ├── WebAuto.py              # 主入口（重构中）
│   ├── CaptchaSolver.py        # 验证码识别（已有）
│   ├── AntiDetect.py           # 反检测注入（已有）
│   ├── TimeSync.py             # 时间同步（已有）
│   ├── Fetchers/               # NEW: 获取器层
│   │   ├── __init__.py
│   │   ├── base.py            # Fetcher 抽象基类
│   │   ├── http.py            # HttpFetcher
│   │   ├── stealth.py         # StealthFetcher
│   │   ├── browser.py         # BrowserFetcher
│   │   └── human.py           # HumanFetcher
│   ├── Selector/               # NEW: 智能选择器
│   │   ├── __init__.py
│   │   ├── selector.py        # 选择器基类 + 链式调用
│   │   └── adaptive.py        # 自适应匹配算法
│   ├── Session/                # NEW: 会话管理
│   │   ├── __init__.py
│   │   ├── session.py         # 会话对象
│   │   └── proxy.py           # 代理轮换
│   └── Errors/                 # NEW: 统一异常
│       ├── __init__.py
│       └── exceptions.py
├── Spider/                     # NEW: 并发爬虫引擎
│   ├── __init__.py
│   ├── spider.py
│   └── task.py
├── Services/                   # 服务化封装
├── Examples/                   # 使用示例
├── Tests/                      # 测试用例
├── MCP/                        # NEW: MCP 服务
│   ├── __init__.py
│   └── server.py
├── ARCHITECTURE_V2.md         # 本文档
├── DESIGN.md
├── STATUS.md
└── requirements.txt
```

---

## 🔄 向后兼容策略

1. **现有 API 全部保留**：`WebAutoConfig`、`async with WebAuto()` 等不变
2. **渐进式重构**：新功能作为可选能力，不破坏原有代码
3. **默认行为不变**：默认还是 `mode='browser'`，与现有行为一致
4. ** deprecation warning**：旧 API 标记弃用但不删除，给迁移时间

---

## 🎯 验收标准

### P0 完成验收
- [ ] 四种获取器模式可以自由切换
- [ ] 智能选择器支持重试、超时、fallback
- [ ] 会话管理器支持 Cookie 持久化和代理轮换
- [ ] 所有现有功能（验证码、反检测、时间同步）正常工作
- [ ] 3 行代码完成简单自动化

### v2.0 完整验收
- [ ] 自适应选择器工作（页面改版能找到元素）
- [ ] Spider 并发引擎支持暂停恢复
- [ ] MCP 服务可被 Claude/Cursor 调用
- [ ] 文档完整 + 示例丰富

---

## 📝 实现笔记

### 参考 Scrapling 的优秀设计
1. 获取器抽象层设计（`scrapling.fetchers`）
2. 自适应选择器算法（元素相似度匹配）
3. Spider 并发架构
4. Cloudflare Turnstile 绕过技术

### WebAuto 独有的护城河
- 汉字点选验证码识别（PP-OCRv6）
- 油猴级 JS 注入（fetch/XHR hook + JSON.parse 补丁）
- NTP 高精度时间同步
- 抢购专用的人类行为模拟

---

*最后更新：2026-06-30*
