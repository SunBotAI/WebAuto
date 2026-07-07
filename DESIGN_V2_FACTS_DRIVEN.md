# WebAuto v2 — 真实抓包驱动的自动化设计

> 与 `ARCHITECTURE_V2.md` 互补：那份文档描述的是"目标态"，
> 本文档补的是"**怎么用真实数据去驱动目标态**"。

---

## 一、现状的真实卡点

读完代码和文档后，**纸上很丰满，代码里其实还有几块真空地带**，
是 ARCHITECTURE_V2 没真正解决的：

| 卡点 | 现状 | 影响 |
|------|------|------|
| **没有"真实抓包 → 真实代码"闭环** | `Core/Zhipu/api.py` 里的接口路径、签名算法、参数名都是凭经验猜的，**没有真实智普网站抓包校对** | 抢购能不能跑通完全靠运气 |
| **`Core/Zhipu` 是 v1 平行宇宙** | `Core/WebAuto_v2.py` 在用 4 层 fetcher，但 Zhipu 子包**完全没用 fetcher 层**，自己撸了一坨 `http_client.py` | 重复造轮子，反检测能力没继承下来 |
| **没有 HTTP/3 / TLS 指纹** | ARCHITECTURE_V2 写着"HttpFetcher + HTTP/3 + TLS 指纹"，实际 `Fetchers/http.py` 只支持 HTTP/2 | 智普这种强反爬场景过不了 |
| **没有"页面改版自动适配"** | SmartSelector 写了 `adaptive` 文本回退，但**没有基于元素特征相似度的算法** | 智普改版就挂 |
| **浏览器模式是 Playwright 完整启动** | 没有"复用你日常 Chrome 登录态"的 CDP 附加入口 | 抢购需要登录态，等于要重新跑一遍登录 |
| **没有真实可视化抢的 replay/录像** | demo 没有，出了事没法回放 | 抢购出问题只能靠脑补 |

> "用 cmd 调 Chrome 抓真实信息"的直觉是对的——就是要补这一块。

---

## 二、新设计：三轴架构

```
        ┌─────────────────────── 真实抓包层 (真实浏览器/真实智普) ───────────────────────┐
        │                                                                            │
        │   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────┐│
        │   │ CDP 附加入口 │    │ HAR 抓包分析 │    │ 真实页面解析 │    │ 接口探测 ││
        │   │ cdp_attach.py│    │ Network.*    │    │ dom_probe.py │    │ api_probe││
        │   │ 复用登录态   │    │ 落盘+离线分析│    │ 真实选择器   │    │ 真实参数 ││
        │   └──────┬───────┘    └──────┬───────┘    └──────┬───────┘    └────┬─────┘│
        │          │                   │                   │                 │      │
        └──────────┼───────────────────┼───────────────────┼─────────────────┼──────┘
                   ▼                   ▼                   ▼                 ▼
        ┌─────────────────────── 知识沉淀层 (yaml/md) ─────────────────────────────┐
        │  zhipu_selectors.yaml  zhipu_apis.yaml  zhipu_signing.md  zhipu_replay/  │
        └───────────────────────────────┬──────────────────────────────────────────┘
                                        │ 喂给 ↓
        ┌─────────────────────── 执行层 (Core/Zhipu + Fetchers) ─────────────────────┐
        │                                                                            │
        │   scheduler 用真实选择器 → StealthFetcher/HumanFetcher 真实执行            │
        │   → Orchestrator 统一编排 → 通知 + 日志                                    │
        │                                                                            │
        └────────────────────────────────────────────────────────────────────────────┘
```

**三轴各管一件事**：
- **真实抓包轴**：用真 Chrome 真智普把"事实"挖出来 → 落到 yaml/md
- **知识沉淀轴**：把"事实"变成可消费的契约，**和代码解耦**
- **执行轴**：Core/Zhipu 读契约执行，**不再硬编码假设**

---

## 三、按优先级排的具体动作

### 🎯 P0（这一轮必做）— **真实抓包校准 + CDP 入口**

| # | 任务 | 产出 | 估时 |
|---|------|------|------|
| 1 | **CDP 附加统一入口** `Tools/cdp_attach.py` 升级：支持 `--user-data-dir`（你日常 Chrome）、自动探测 9222 端口、health-check | 一个 `from cdp_attach import attach_to_chrome` 库函数 | 2h |
| 2 | **HAR 抓包工具** `Tools/zhipu_har.py`：CDP `Network.*` 事件流式落盘到 `diagnostic_output/har/` | 一个命令行：`python -m Tools.zhipu_har capture --url ...` | 2h |
| 3 | **真实选择器探测** `Tools/dom_probe.py`：在已登录页面跑 JS 列出套餐相关选择器、按钮、倒计时 DOM，导出 `zhipu_selectors.yaml` | yaml + md 报告 | 1.5h |
| 4 | **真实接口探测** `Tools/api_probe.py`：从 HAR 提取智普 API 端点、入参/出参结构、签名头，导出 `zhipu_apis.yaml` | yaml + md | 2h |
| 5 | **`Core/Zhipu/api.py` 读 yaml 契约**（不再硬编码路径/参数名）| 改 1 文件 | 1h |

> 这一轮做完，"用 cmd 调 Chrome 抓真实信息"的需求就落地了。
> 后续所有工作都基于真实事实。

### 🎯 P1（下一轮）— **执行层吸收抓包成果**

| # | 任务 | 估时 |
|---|------|------|
| 6 | `Core/Zhipu/http_client.py` 删掉，改用 `Fetchers/http.py` + TLS 指纹（curlforge/ja3 之类） | 3h |
| 7 | `Core/Zhipu/browser.py` 改为 `StealthFetcher` + `CDP attach` 模式（复用登录态） | 2h |
| 8 | SmartSelector `adaptive` 真正实现元素特征相似度（DOM path + 文本 + 临近元素） | 4h |
| 9 | 抢购 Replay：失败时落 `replay/{timestamp}.json`（HAR + DOM 快照 + 鼠标轨迹），出问题可回放 | 3h |
| 10 | `Fetchers/http.py` 加 HTTP/3（httpx[http3] 或 aioquic） | 3h |

### 🎯 P2（一月内）— **Spider + MCP + 真实监控**

| # | 任务 | 估时 |
|---|------|------|
| 11 | Spider 引擎（并发爬套餐/价格变动） | 8h |
| 12 | MCP server（让 Claude/Cursor 直接调你工具） | 4h |
| 13 | 真实监控：智普改版检测（每天跑一次 dom_probe，diff 上报） | 4h |
| 14 | 抢购 A/B 矩阵：plan_groups × accounts × channels 自动找最优 | 6h |

---

## 四、这一轮的最小可执行方案（5 个文件）

```
Tools/
├── zhipu_har.py        # 真实抓包 (HAR 落盘)              [新]
├── dom_probe.py        # 真实选择器探测                    [新]
└── cdp_attach.py       # 升级：Chrome 登录态附加           [改]

Core/Zhipu/
└── api.py              # 改为读 zhipu_apis.yaml 契约        [改]

diagnostic_output/      # 抓包/HAR/选择器快照 落盘处         [新]
```

**这一轮做完能拿到什么**：
- 你运行 `python -m Tools.zhipu_har capture --url https://www.zhipuai.cn/...`，得到一个 HAR
- 跑 `dom_probe` 得到一个 `zhipu_selectors.yaml`（里面是真实选择器，不是猜的）
- `Core/Zhipu/api.py` 读这份 yaml，抢购用的是**真实接口契约**
- 哪天智普改版，你重跑一次工具链，几分钟内拿到新契约，不用改代码

---

## 五、和 ARCHITECTURE_V2 的关系

**不是推翻，是补缺**：
- ARCHITECTURE_V2 的"四层 fetcher / 智能选择器 / Spider / MCP"是**正确的目标态**
- 它缺的是"**怎么用真实数据去驱动这个目标态**"——也就是上面的"真实抓包轴 + 知识沉淀轴"
- 这一轮先把"事实来源"打通，后续每一层 fetcher、每一个选择器、每一个 API 调用，都不再凭假设

---

## 六、待确认

要开干前需要知道三件事：

1. **Chrome 装在哪儿**？（默认路径我先写 `Tools/cdp_attach.py` 的探测逻辑）
2. **日常 Chrome 是不是已经登录了智普**？（决定用 CDP 附加还是无头启新进程）
3. **智普入口 URL**（套餐页 / 登录页 / 抢购页任一）—— 这一轮不用真去访问你的账号，但**协议层、选择器形态**得用真实网站去校。

---

*最后更新：2026-07-06*
