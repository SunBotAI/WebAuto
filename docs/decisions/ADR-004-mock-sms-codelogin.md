# ADR-004: 移除智谱短信登录 API 调用(改用浏览器手动补凭证)

**Status:** Accepted(原"补 mock 路由"作废,本次重写)
**Date:** 2026-07-12
**Author:** 小千
**Context:** 抢购链路(`/api/biz/code/smsCode/17640645696`)在 2026-07 持续返回 HTTP 404,
触发 `❌ 登录失败 / HTTP 404`,抢购主流程直接挂掉。

---

## Context(根因重述)

智谱**没有给第三方开放短信登录的 API**。`/api/biz/code/smsCode/{phone}` 与
`/api/biz/code/checkSmsCode/{code}` 是从浏览器登录页抓包看到的 XHR 端点:

- 必须带登录页上下文里的 cookie + magipack 风控字段(浏览器指纹/captchaId);
- 纯 `httpx` 裸调用会在服务端被识别为"非浏览器环境",直接 404 或风控拒绝;
- 即便服务端 200,真实场景下我们仍然拿不到"用户收到的 6 位短信码",需要有人在浏览器页面上点按钮收码。

限量套餐抢购的本质是"和真人拼手速",**没有 API,只有浏览器**。
原 ADR-004(补 mock 让 `login_by_sms` 在本地跑通)在协议层成立,但解决不了真实抢购场景:
本地脚本通了,线上依然 404,抢购依然失败。**方向错了**。

---

## Decision

### 代码层:全部移除短信登录的 API 调用

- `Core/Zhipu/constants.py` — `PATH_SMS_CODE` / `PATH_CHECK_SMS_CODE` 注释为"已下线,不要再用"
- `Core/Zhipu/session.py` — 删 `SessionManager.relogin_by_sms` 方法 + `_prompt_sms_code` 辅助
- `Core/Zhipu/orchestrator.py` — `_prepare_sessions` 不再自动重登,失效账号直接 `log.error` 排除
- `Core/Zhipu/exceptions.py` — `AuthError` docstring 改为"抢购主流程跳过,用户在浏览器回填"
- `Tools/credential_backend.py` — 删 `login_by_sms`
- `Tools/console_tab.py` — 顶部折叠面板替换为"如何从浏览器抓 token"的 Markdown 引导
- `Tools/webauto_web.py` — Tab "短信登录" 替换为 "凭证导入" 引导 Tab

### 真实使用流程(抢购前必须就绪)

1. Chrome/Firefox 打开 `https://bigmodel.cn/glm-coding`,用账密/扫码正常登录
2. DevTools → Network → 任一请求 → 复制 `Authorization: Bearer ...` 的 token
   + `Cookie` 请求头的整段 cookie
3. 在面板 **Tab 1: 验证 Token** 粘贴 → 点 **验证并保存**(落到 `.secrets.enc`)
4. 抢购启动时,如某账号 token 失效,日志会写:
   `[账号名] 登录态失效,跳过本账号。请在浏览器登录 https://bigmodel.cn 后回填 token/cookie`
   此时回步骤 2 重抓,继续下一轮抢购

### Mock 层:`Examples/mock_target/server.py` 路由保留,标 DEPRECATED

- 两条 `/api/biz/code/{smsCode,checkSmsCode}/*` 路由仅供**离线脚本**验证客户端代码
  形态/契约,不代表真实接口可用。
- 顶部 docstring + 路由实现都加了 `[DEPRECATED]` 标记。

---

## Consequences

**正面**
- 抢购链路不再因 404 而整体失败;失效账号直接跳过,其他账号继续抢。
- 不再误导用户去"输短信码"(产品层面就不该有这个 UI,智谱本来就没这 API)。
- 真实场景下"补凭证"完全在浏览器里完成,绕开 magipack 风控。

**风险/取舍**
- token 失效的账号无法自动续命:用户必须**在抢购窗口期内**手动补凭证。
  这是无法绕过的限制——任何"自动续命"都要浏览器自动化,而限量套餐抢购窗口
  通常 < 100ms,浏览器启动 + 登录 + 抓 cookie 远大于窗口期,毫无意义。
- 历史"补 mock 路由"的部分(ADR-004 v1)作废,改成本次"完全移除 API 调用"。

---

## Verification

```bash
# 1. 静态扫描:确认全代码库不再调用这两条端点
rg -n "PATH_SMS_CODE|PATH_CHECK_SMS_CODE|relogin_by_sms|login_by_sms" Core/ Tools/
# 期望:零命中(文案里的"已下线/不支持"等说明性文本除外)

# 2. 编译:所有改动文件可被 py_compile
python3 -m py_compile \
  Core/Zhipu/constants.py \
  Core/Zhipu/session.py \
  Core/Zhipu/orchestrator.py \
  Core/Zhipu/exceptions.py \
  Tools/credential_backend.py \
  Tools/console_tab.py \
  Tools/webauto_web.py \
  Examples/mock_target/server.py

# 3. 抢购链路冒烟:启动 Orchestrator,验证失效账号被明确跳过且不抛异常
python3 -c "
import asyncio
from Core.Zhipu.config import load_config, AppConfig
from Core.Zhipu.orchestrator import Orchestrator
cfg = load_config('config.yaml')
orch = Orchestrator(cfg)
asyncio.run(orch.run())  # 不再做 404 短信重登
"
```

---

## Related

- v1 ADR-004(作废):在 mock 里补两条路由——证明方向错了,仅供离线脚本
- `Tools/credential_backend.py::check_and_save` — 抓 token 后真正写入凭证库的入口(保留)
- `Core/Zhipu/session.py::check_alive` — 抢购启动时的登录态探测(保留)
- `Core/Zhipu/orchestrator.py::_prepare_sessions` — 失效账号跳过逻辑(本次修改)
