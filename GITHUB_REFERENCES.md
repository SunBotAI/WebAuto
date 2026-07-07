# GitHub 智谱抢购脚本参考汇总

> 收集自 GitHub 的开源智谱 GLM Coding Plan 抢购脚本，供研究参考

## 高星热门项目

### 1. Spanky96/glm-coding-grabber ⭐ 413
- **类型**: 油猴(Tampermonkey) + Python
- **特点**: ddddocr 验证码自动识别
- **地址**: https://github.com/Spanky96/glm-coding-grabber

### 2. OLmatter/glm-coding-helper ⭐ 398
- **类型**: 油猴脚本
- **特点**: 本地 CPU/GPU OCR 识别中文点选验证码，多窗口并发，支付页保护
- **地址**: https://github.com/OLmatter/glm-coding-helper

### 3. qtaxm/glm-rush ⭐ 373
- **类型**: Python / 油猴
- **特点**: v4.0 并发重试 + 反检测 + 高精度定时
- **地址**: https://github.com/qtaxm/glm-rush

### 4. hd233yui/glm-coding-sniper ⭐ 87
- **类型**: 油猴 + Console
- **特点**: 自动抢购脚本
- **地址**: https://github.com/hd233yui/glm-coding-sniper

## 其他可用项目

| 项目 | Star | 类型 | 特点 |
|------|------|------|------|
| duicym/glm-rush-plus | 15⭐ | - | 自动捕获真实API参数 + 极速并发引擎 |
| funisgoou/glm-coding-grabber | 1⭐ | Python异步 | NTP同步/凭证加密/多账号并发/多渠道通知/Playwright备用 |
| xxjrq/glmhelp | 4⭐ | Chrome扩展 | 套餐补货监控、自动点击、通知提醒 |
| thejtf/GLMhelper | 5⭐ | Chrome扩展 | 自动抢购Chrome扩展 |
| sakurawwwxh/GLM-CodingPlan-Assistant | 9⭐ | - | 智谱 GLM Coding 抢购助手 |
| langbyyi/GLM_bypass | 5⭐ | - | Tampermonkey + ddddocr 验证码识别 |
| Jasmyn-X/glm-coding-grabber | 5⭐ | 油猴 | 服务器时间对齐 + DOM 监听 + 自动点击 |
| KingYeon-Zoo/GLM-Auto-Sniper | 3⭐ | 油猴 | 高强度自动化抢购 |
| LingC001/zhipu-sniper | 2⭐ | - | 智谱code plan自动化抢购 |
| bert995/glm-sniper | 3⭐ | Chrome扩展 | GLM5.1 Coding包月套餐抢购助手 |

## 技术方案对比

### 通用实现思路
1. **前端注入** - 油猴(Tampermonkey)：自动点击 + DOM监听（最主流）
2. **验证码识别** - ddddocr / 本地OCR 识别中文点选验证码
3. **时间同步** - NTP服务器时间对齐，高精度定时触发
4. **并发请求** - 多窗口/多账号并发抢购
5. **通知提醒** - 补货监控 + 成功/失败推送

### 各方案技术栈对比

| 方案 | 前端 | OCR | 并发 | 反检测 |
|------|------|-----|------|--------|
| OLmatter/glm-coding-helper | 油猴 | 本地OCR | 多窗口 | 基础 |
| Spanky96/glm-coding-grabber | 油猴 | ddddocr | 单窗口 | 基础 |
| qtaxm/glm-rush | Python | - | 多线程 | ✅ 完整 |
| funisgoou/glm-coding-grabber | Playwright | - | 多账号 | ✅ 完整 |

## 下一步研究计划

1. [ ] Clone 2-3 个代表性项目到 reference/ 目录
2. [ ] 分析各项目的实现差异
3. [ ] 提取通用技术要点
4. [ ] 整合到现有 webauto 技术方案中

---
*更新时间: 2026-06-29*
