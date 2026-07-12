# ADR-004: Mock Target 补齐短信登录两阶段

**Status:** Accepted
**Date:** 2026-07-12
**Author:** 小千
**Context:** `Tools/console_tab.py` 上报 `📡 阶段: done / 📝 HTTP 404: GET /api/biz/code/smsCode/17640645696`，
导致 `Tools/credential_backend.py::login_by_sms` 第二阶段被面板标记为失败。

---

## Context

`login_by_sms` 是两阶段流程（见 `Tools/credential_backend.py:217`）：

1. **第一阶段**（`sms_code=""`）：调用 `GET /api/biz/code/smsCode/{phone}`，期望服务端返回 `200` 表示"已下发验证码"。
2. **第二阶段**（`sms_code` 非空）：调用 `GET /api/biz/code/checkSmsCode/{code}`，期望返回新 `token` + `Set-Cookie`。

本地调试时常把 `ApiClient.base_url` 切到 `Examples/mock_target/server.py`（端口 18080）以避开真实风控。
但旧版 mock 只实现了 `codeinterpreter/bizOrderLimit/*` 和 `user/sms/login`，**没有注册 `code/smsCode/{phone}` 与 `code/checkSmsCode/{code}`**，
命中 `do_GET` 末尾的兜底 `else: 404`，于是面板收到 `HTTP 404` 记为 `stage=done, success=False`。

线上 `https://bigmodel.cn` 实际是返回 200 的，所以这不是协议问题，纯粹是 mock 缺端点。

---

## Decision

在 `Examples/mock_target/server.py` 里新增两条 GET 路由，与真实协议同形：

- `GET /api/biz/code/smsCode/{phone}`
  - 任意 phone 都返回 `{"phone","sent":true,"expireIn":300}`（真实环境有 magipack 风控校验归属地，本地不模拟）。
- `GET /api/biz/code/checkSmsCode/{code}`
  - 4–8 位数字（`MOCK_SMS_CODE_MIN/MAX`）视为合法，生成 `mock-token-<hex>` 并通过 `Set-Cookie: bigmodel_token=…` 下发，
    供 `Core/Zhipu/http_client.py::_last_set_cookies` 抽取。
  - `0000`、`9999` 显式触发 `valid=false`，用于测试异常分支（与 `Tools/credential_backend.py` 的失败兜底对齐）。
  - 非数字 / 长度越界也返回 `valid=false`，避免误把非法输入当成功。

注册位置：在 `do_GET` 里 `/api/biz/codeinterpreter/priceAndCurrencyNew` 之后、`/test` 之前；不改动 `do_POST`，
因为真实接口也是 GET（与 `Core/Zhipu/constants.py:46-47` 的 `PATH_SMS_CODE` / `PATH_CHECK_SMS_CODE` 一致）。

---

## Consequences

**正面**
- 改 `base_url` 切到 mock 后，`login_by_sms` 能跑完两阶段；`stage=code_sent → stage=done`，面板日志正常收敛。
- `ApiClient` 的 `_last_set_cookies` 抽取链路在 mock 下也能完整覆盖，不用再依赖真实环境。
- `0000/9999` 失败用例可直接给上层做异常路径测试。

**风险**
- mock 与真实接口行为不一致：mock 任意码都通，真实环境是 6 位数字 + 风控校验。
  → 这是 mock 的本意（README 已声明"零风控"），不影响生产，仅需在测试时显式认知。
- `checkSmsCode` 在 mock 下用 GET；真实接口也是 GET，所以这里只是补齐，不是改协议。

---

## Verification

```bash
# 启动
python Examples/mock_target/server.py &

# 第一阶段
curl -sS -o /dev/null -w '%{http_code}\n' \
  http://127.0.0.1:18080/api/biz/code/smsCode/17640645696
# 期望 200

# 第二阶段(合法码,带 Set-Cookie)
curl -sSi http://127.0.0.1:18080/api/biz/code/checkSmsCode/123456 | head -20
# 期望 200 + Set-Cookie: bigmodel_token=... + JSON data.token

# 失败分支
curl -sS http://127.0.0.1:18080/api/biz/code/checkSmsCode/0000
# 期望 valid=false
```

---

## Related

- `Tools/credential_backend.py:217-290` — `login_by_sms` 两阶段定义
- `Core/Zhipu/session.py:111-160` — `relogin_by_sms` 同样路径，复用本修复
- `Core/Zhipu/constants.py:46-47` — `PATH_SMS_CODE` / `PATH_CHECK_SMS_CODE`
- `Core/Zhipu/http_client.py:80-110` — `_last_set_cookies` 抽取位置
- `Examples/mock_target/test_with_httpfetcher.py` — 用 mock 自检的脚本入口
