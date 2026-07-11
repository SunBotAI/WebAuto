# 快速开始

> 5 分钟上手 WebAuto。

---

## 安装

```bash
# 克隆项目
git clone <repo_url>
cd WebAuto

# 安装依赖
pip install -r requirements.txt

# 安装 Playwright 浏览器（仅 browser/stealth/human 模式需要）
playwright install chromium
```

---

## 第一个自动化脚本

```python
import asyncio
from Core.WebAuto import WebAuto, WebAutoConfig

async def main():
    config = WebAutoConfig(
        headless=False,
        anti_detect=True,
        enable_captcha_solver=True,
        enable_time_sync=True
    )

    async with WebAuto(config) as auto:
        # 打开页面
        await auto.goto("https://example.com")

        # 验证码自动处理（如果有）
        result = await auto.captcha.solve_from_page(auto.page)
        if result.success:
            await auto.captcha.click_points(auto.page, result)

        # 时间同步（抢购场景）
        target_time = "2026-01-01 10:00:00"
        await auto.time.sleep_until_server_time(target_time)

        print("完成！")

asyncio.run(main())
```

---

## 常见场景

### 场景 1：基础浏览器自动化

```python
from Core.WebAuto import WebAuto, WebAutoConfig

async with WebAuto(WebAutoConfig()) as auto:
    await auto.goto("https://example.com")
    await auto.page.fill("#search", "关键词")
    await auto.page.click(".submit")
```

### 场景 2：反检测自动化（绕过爬虫检测）

```python
from Core.WebAuto import WebAuto, WebAutoConfig
from Core.AntiDetect import inject_anti_detect

async with WebAuto(WebAutoConfig(anti_detect=True)) as auto:
    await auto.goto("https://example.com")
    await inject_anti_detect(auto.page)
    # 页面上的检测脚本会失效
```

### 场景 3：验证码识别

```python
# 自动检测并解决页面上的验证码
result = await solver.solve_from_page(page)
if result.success:
    await solver.click_points(page, result)
```

### 场景 4：Profile 池并发

```python
from Core.Profile.store import ProfileStore
from Core.Profile.pool import ProfilePool, AcquireStrategy

store = ProfileStore()
pool = ProfilePool(store, strategy=AcquireStrategy.LEAST_USED)

async with pool.context(tag="grab-task") as profile:
    # profile 已经准备好，可以直接用
    print(f"Using profile {profile.id}")
```

### 场景 5：智谱 GLM Coding 抢购

```bash
# 1. 准备配置
cp config.example.yaml config.yaml
# 编辑 config.yaml，填入 Authorization token

# 2. NTP 校时
python -m Core.Zhipu sync

# 3. 执行抢购
python -m Core.Zhipu grab -c config.yaml
```

---

## 运行测试

```bash
# 跑单元测试（不需要浏览器）
python -m unittest discover Tests -v

# 跑基础 demo（不需要浏览器，HTTP 模式）
python Examples/example_basic.py

# 跑抢购 demo（需要浏览器）
python Examples/example_glm_rush.py
```

---

## 目录结构

```
WebAuto/
├── Core/                    # 核心模块（WebAuto、AntiDetect、CaptchaSolver、TimeSync...）
├── Examples/                # 示例脚本
├── Tests/                  # 测试用例
├── References/             # 开源参考项目源码
├── docs/                   # 文档
│   ├── README.md          # 文档索引
│   ├── ARCHITECTURE.md   # 架构文档
│   ├── MODULES.md        # 模块 API 参考
│   ├── QUICKSTART.md     # 本文档
│   └── MCP/              # MCP 集成文档
└── requirements.txt        # 依赖
```

---

## 下一步

- 了解架构设计 → [ARCHITECTURE.md](ARCHITECTURE.md)
- 查模块 API → [MODULES.md](MODULES.md)
- 接 AI 工具 → [MCP/](MCP/) 目录
- 完整文档 → [README.md](../README.md)

---

*最后更新：2026-07-14*
