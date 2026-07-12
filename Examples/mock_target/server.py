r"""智谱 GLM Coding 本地 mock target (零依赖 + 零风控)。

用法:
    python Examples/mock_target/server.py                # 启动 mock server 监听 18080
    python Examples/mock_target/server.py --port 19090   # 自定义端口

然后验证:
    curl http://127.0.0.1:18080/
    curl http://127.0.0.1:18080/health
    curl http://127.0.0.1:18080/api/biz/customer/getCustomerInfo
    curl -X POST http://127.0.0.1:18080/api/biz/codeinterpreter/bizOrderLimit/price/preview \\
         -H 'Content-Type: application/json' -d '{\"productId\":\"mock-prod-max-yearly\"}'
    curl -X POST http://127.0.0.1:18080/api/biz/codeinterpreter/bizOrderLimit/check \\
         -H 'Content-Type: application/json' -d '{\"bizId\":\"mock-biz-1234-5678-9abc-def0\"}'

覆盖 GLM Coding 实际请求链路的几个关键端点:
    GET  /health                                                    健康检查
    GET  /api/biz/customer/getCustomerInfo                          查登录态
    GET  /api/biz/codeinterpreter/priceAndCurrencyNew               价格表
    POST /api/biz/codeinterpreter/bizOrderLimit/price/preview       preview 拿 bizId
    POST /api/biz/codeinterpreter/bizOrderLimit/check               check 校验 bizId
    POST /api/biz/codeinterpreter/bizOrderLimit/create              创建订单(不真下单)
    POST /api/biz/user/sms/login                                    验证码登录(任何 code 都通)
    GET  /api/biz/code/smsCode/{phone}                               第一阶段:发短信验证码(任意 phone 都通)
    GET  /api/biz/code/checkSmsCode/{code}                           第二阶段:校验短信码(任意 4-8 位数字都通;0000/9999 失败)
    GET  /test                                                      永远 401,用于测试错误处理

为什么 stdlib:
    零依赖,在任何 venv(甚至 .venv-fix/.venv)都能直接跑。
    想要更花哨可以加 flask,但这里刻意保持简单。
"""
import json
import sys
import time
import uuid
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse


MOCK_USER = {
    "userId":   "mock-user-1234",
    "nickname": "mock_user",
    "avatar":   "",
    "vip":      True,
    "phone":    "138****1234",
}

MOCK_BIZID = "mock-biz-1234-5678-9abc-def0"
# 短信登录两阶段使用的"任意码放行"白名单:
#   - 第一阶段 GET  /api/biz/code/smsCode/{phone}      → 任意 phone 都返回 sent=True
#   - 第二阶段 GET  /api/biz/code/checkSmsCode/{code}  → 任意 4~8 位数字 code 都返回 token
# 与真实智谱接口不同(magipack 风控会校验手机号归属地),此处只用于本地闭环。
MOCK_SMS_CODE_MIN = 4
MOCK_SMS_CODE_MAX = 8
MOCK_SMS_FAIL_CODES = {"0000", "9999"}  # 显式触发"校验失败",便于测试异常分支

MOCK_PRICING = {
    "plans": [
        {"tier": "Lite",     "monthly": 19, "quarterly": 57, "yearly": 199},
        {"tier": "Pro",      "monthly": 49, "quarterly": 147, "yearly": 499},
        {"tier": "Max",      "monthly": 99, "quarterly": 297, "yearly": 999},
    ],
}

MOCK_PRODUCTS = {
    ("Lite",    "monthly"):   "mock-prod-lite-monthly",
    ("Lite",    "quarterly"): "mock-prod-lite-quarterly",
    ("Lite",    "yearly"):    "mock-prod-lite-yearly",
    ("Pro",     "monthly"):   "mock-prod-pro-monthly",
    ("Pro",     "quarterly"): "mock-prod-pro-quarterly",
    ("Pro",     "yearly"):    "mock-prod-pro-yearly",
    ("Max",     "monthly"):   "mock-prod-max-yearly",
    ("Max",     "quarterly"): "mock-prod-max-quarterly",
    ("Max",     "yearly"):    "mock-prod-max-yearly",
}


class MockHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write(
            f"[{time.strftime('%H:%M:%S')}] {self.command} {self.path}  "
            f"(from {self.client_address[0]})\n"
        )

    def _json(self, code: int, data, status: int = 200):
        if code == 200:
            body = json.dumps({"code": 200, "msg": "success", "data": data},
                              ensure_ascii=False).encode()
        else:
            body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length > 0 else b""
            return json.loads(raw.decode()) if raw else {}
        except Exception:
            return {}

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self._json(200, {"ok": True, "mock": True, "ts": time.time()})
        elif path == "/api/biz/customer/getCustomerInfo":
            self._json(200, MOCK_USER)
        elif path == "/api/biz/codeinterpreter/priceAndCurrencyNew":
            self._json(200, MOCK_PRICING)
        elif path.startswith("/api/biz/code/smsCode/"):
            # 第一阶段:发送验证码。任意 phone 都返回 sent=True,
            # 真实环境 magipack 会校验手机号归属地,这里不模拟。
            phone = path.rsplit("/", 1)[-1]
            self._json(200, {
                "phone":    phone,
                "sent":     True,
                "expireIn": 300,
            })
        elif path.startswith("/api/biz/code/checkSmsCode/"):
            # 第二阶段:校验验证码。
            code = path.rsplit("/", 1)[-1]
            if code in MOCK_SMS_FAIL_CODES:
                self._json(200, {
                    "code":    code,
                    "valid":   False,
                    "message": "验证码错误(mock)",
                })
                return
            if not (code.isdigit() and MOCK_SMS_CODE_MIN <= len(code) <= MOCK_SMS_CODE_MAX):
                self._json(200, {
                    "code":    code,
                    "valid":   False,
                    "message": f"验证码长度需在 {MOCK_SMS_CODE_MIN}~{MOCK_SMS_CODE_MAX} 位数字(mock)",
                })
                return
            # 校验通过:下发 token + set-cookie,供 ApiClient._last_set_cookies 抽取
            token = f"mock-token-{uuid.uuid4().hex[:16]}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Set-Cookie",
                             f"bigmodel_token={token}; Path=/; HttpOnly")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Expose-Headers", "Set-Cookie")
            body = json.dumps({
                "code": 200,
                "msg":  "success",
                "data": {
                    "token":    token,
                    "loggedIn": True,
                    "userId":   MOCK_USER["userId"],
                },
            }, ensure_ascii=False).encode()
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        elif path == "/test":
            self._json(401, {"error": "unauthorized"}, status=401)
        elif path == "/":
            self._json(200, {
                "mock": True,
                "endpoints": [
                    "GET  /health",
                    "GET  /api/biz/customer/getCustomerInfo",
                    "GET  /api/biz/codeinterpreter/priceAndCurrencyNew",
                    "POST /api/biz/codeinterpreter/bizOrderLimit/price/preview",
                    "POST /api/biz/codeinterpreter/bizOrderLimit/check",
                    "POST /api/biz/codeinterpreter/bizOrderLimit/create",
                    "POST /api/biz/user/sms/login",
                    "GET  /test   (always 401, for testing error handling)",
                ],
            })
        else:
            self._json(404, {"error": f"mock: no such endpoint {path}"}, status=404)

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_body()

        if path == "/api/biz/codeinterpreter/bizOrderLimit/price/preview":
            product_id = body.get("productId")
            if not product_id:
                self._json(400, {"error": "missing productId"}, status=400)
                return
            self._json(200, {
                "bizId":       MOCK_BIZID,
                "actualAmount": 99.0,
                "couponInfo":   {"id": None, "discount": 0},
                "expireAt":     int(time.time()) + 600,
            })
        elif path == "/api/biz/codeinterpreter/bizOrderLimit/check":
            biz_id = body.get("bizId")
            if biz_id == MOCK_BIZID:
                self._json(200, {
                    "bizId":    biz_id,
                    "valid":    True,
                    "expireIn": 600,
                    "amount":   99.0,
                })
            else:
                self._json(200, {
                    "bizId":    biz_id,
                    "valid":    False,
                    "code":     "EXPIRE",
                    "expireIn": 0,
                })
        elif path == "/api/biz/codeinterpreter/bizOrderLimit/create":
            biz_id = body.get("bizId")
            if biz_id != MOCK_BIZID:
                self._json(400, {"error": "invalid bizId"}, status=400)
                return
            order_id = "mock-order-" + uuid.uuid4().hex[:12]
            self._json(200, {
                "orderId":  order_id,
                "bizId":    biz_id,
                "payUrl":   f"http://127.0.0.1:18080/mock-pay?order={order_id}",
                "status":   "PENDING_PAY",
                "amount":   99.0,
                "expireAt": int(time.time()) + 900,
            })
        elif path == "/api/biz/user/sms/login":
            phone = body.get("phone", "")
            self._json(200, {
                "phone":     phone,
                "loggedIn":  True,
                "userId":    MOCK_USER["userId"],
                "mockToken": f"mock-token-{uuid.uuid4().hex[:16]}",
            })
        else:
            self._json(404, {"error": f"mock: no such endpoint {path}"}, status=404)


def main():
    parser = argparse.ArgumentParser(description="智谱 GLM Coding 本地 mock")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18080)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MockHandler)
    print(f"🚀 Mock target 已启动: http://{args.host}:{args.port}")
    print(f"   验证: curl http://{args.host}:{args.port}/")
    print(f"   Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[STOP] mock stopped")
        server.server_close()


if __name__ == "__main__":
    main()
