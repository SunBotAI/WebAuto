# ADR-002: 指纹浏览器集成架构规划与实现方案

**Status:** Accepted
**Accepted Date:** 2026-07-07
**Accepted by:** 大白（基于老大 23:37 拍板）
**Date:** 2026-07-07
**Author:** 小千

## Context

WebAuto 项目已有 StealthFetcher + AntiDetect 注入 + BrowserProfile，但仍受限于"单浏览器单指纹"模式——多账号场景下，每个账号需要独立的浏览器实例 + 独立的持久化指纹 + 独立的 Cookie 隔离 + 独立的代理通道。本次 ADR 提出"指纹浏览器（Fingerprint Browser）"完整架构，把 WebAuto 从"反检测工具"升级为"多账号隔离自动化平台"。

---

## 目录（章节级拆分 v1）

> **2026-07-08 拆分**：原文档 1003 行 / 44K 拆为 10 个章节文件 + 本主文件（ADR 摘要）。详细章节见子目录。

| # | 章节 | 文件 | 行 |
|---|------|------|-----|
| 1 | 背景与现状 | [01-背景与现状.md](./002-fingerprint-browser-integration/01-背景与现状.md) | 40 |
| 2 | 参考项目横向对比 | [02-参考项目横向对比.md](./002-fingerprint-browser-integration/02-参考项目横向对比.md) | 129 |
| 3 | 架构总览 | [03-架构总览.md](./002-fingerprint-browser-integration/03-架构总览.md) | 94 |
| 4 | 核心模块设计 | [04-核心模块设计.md](./002-fingerprint-browser-integration/04-核心模块设计.md) | 433 |
| 5 | 数据模型与持久化 | [05-数据模型与持久化.md](./002-fingerprint-browser-integration/05-数据模型与持久化.md) | 71 |
| 6 | 实现 Roadmap | [06-实现-Roadmap.md](./002-fingerprint-browser-integration/06-实现-Roadmap.md) | 59 |
| 7 | 风险与缓解 | [07-风险与缓解.md](./002-fingerprint-browser-integration/07-风险与缓解.md) | 28 |
| 8 | 验收标准 | [08-验收标准.md](./002-fingerprint-browser-integration/08-验收标准.md) | 47 |
| 9 | 附录:示例代码 | [09-附录-示例代码.md](./002-fingerprint-browser-integration/09-附录-示例代码.md) | 55 |
| 10 | 参考资料 | [10-参考资料.md](./002-fingerprint-browser-integration/10-参考资料.md) | 23 |

**子目录路径**：`./002-fingerprint-browser-integration/`

---

## 核心决策摘要（30 秒速读）

### 目标

把 WebAuto 升级为 **"指纹浏览器编排平台"**，对外提供与 AdsPower / Multilogin / GoLogin 同等级的多账号隔离能力，同时保持 WebAuto 现有优势（代码级可控 + 反检测深度 + NTP 抢购精度）。

### 关键参考模式（6 模式）

1. **Profile 即一切**（from GoLogin / AdsPower）：账号 = 指纹 + 代理 + Cookie + 脚本，Profile 级别捆绑
2. **Profile 持久化到本地**（from all）：`~/.cache/webauto/profiles/<id>/` 目录布局
3. **Profile 隔离的 BrowserContext**（from Playwright + GoLogin）：用 `user_data_dir` 而非软件隔离
4. **TLS 指纹**（from Scrapling + curl_cffi）：HTTP 模式用 `curl_cffi` 模拟真实 Chrome TLS handshake
5. **启动时批量预热**（from Scrapling + GoLogin）：抢购场景 T-30s 全部就绪
6. **Profile 池化 + 轮换**（from Scrapling Spider）：100 账号不直接开 100 Chromium

### 四层架构

```
Layer 4: 业务编排层（Spider / 抢购 / MCP / CLI）
Layer 3: Profile 编排层（ProfilePool / BrowserOrchestrator / ProfileStore）
Layer 2: 反检测注入层（AntiDetect / BrowserProfile / TLS 指纹 / Humanizer）
Layer 1: 底层执行层（Playwright / curl_cffi / PP-OCRv6 / ddddocr）
```

### 优先级

- **P0（2 周）**：Profile 数据类 + 存储 + 编排 + 池子 + AntiDetect 整合 + 隔离测试 + CLI
- **P1（4 周）**：HTTP/TLS 指纹 + 代理轮换 + Spider 并发 + MCP 集成
- **P2（3 月）**：行为学习 / 健康监控 / 云同步 / Web UI

### 关键风险（特别关注）

- **风险 6（高）**：AntiDetect 与 Profile 指纹不一致 → 强制 `Profile.apply_to_anti_detect` 同步 seed
- **风险 7（高）**：多账号风控关联 → 强制每 Profile 不同代理 + 不同 fingerprint_seed
- **风险 1-2（中）**：Chromium user-data 跨版本兼容 / 多 Profile 共享 Chromium 内存压力

---

## 变更日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-07-08 | v0.2 | **拆分**：原 1003 行单文件 → 10 章节文件 + 主文件（ADR 摘要） |
| 2026-07-07 | v0.1 | 初稿，基于 ADR-001 的模块拆分原则扩展到指纹浏览器 |
