r"""用 HttpFetcher 调通 mock target,验证 HttpFetcher 调智谱真实端点时的代码能跑通。

用法:
    # 1. 另起一个 shell:python Examples/mock_target/server.py
    # 2. 在这里跑:python Examples/mock_target/test_with_httpfetcher.py

这个脚本会跑完整个 preview → check → create 链路,并断言每一步响应结构合理。
完全本地,不接触真实风控。
"""
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from Core.Fetchers.http import HttpFetcher


MOCK_URL = "http://127.0.0.1:18080"


async def main():
    fetcher = HttpFetcher({
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36",
        "headers":    {"Origin": MOCK_URL, "Referer": MOCK_URL + "/"},
    })
    await fetcher.init()

    passed = 0
    failed = 0

    def check(label, ok, detail=""):
        nonlocal passed, failed
        if ok:
            print(f"  [OK]   {label}{('  ' + detail) if detail else ''}")
            passed += 1
        else:
            print(f"  [FAIL] {label}{('  ' + detail) if detail else ''}")
            failed += 1

    try:
        # ---- 1. health
        print("\n1. GET /health")
        r = await fetcher.get(f"{MOCK_URL}/health")
        data = json.loads(r.text)
        check("status 200", r.status == 200)
        check("data.ok == True", data.get("data", {}).get("ok") is True)
        check("data.mock == True", data.get("data", {}).get("mock") is True)

        # ---- 2. 登录态
        print("\n2. GET /api/biz/customer/getCustomerInfo")
        r = await fetcher.get(f"{MOCK_URL}/api/biz/customer/getCustomerInfo")
        data = json.loads(r.text)
        check("status 200", r.status == 200)
        check("userId present", "userId" in data.get("data", {}))

        # ---- 3. 价格表
        print("\n3. GET /api/biz/codeinterpreter/priceAndCurrencyNew")
        r = await fetcher.get(f"{MOCK_URL}/api/biz/codeinterpreter/priceAndCurrencyNew")
        data = json.loads(r.text)
        plans = data.get("data", {}).get("plans", [])
        check("3 plans (Lite/Pro/Max)", len(plans) == 3)
        check("Max.yearly present", any(p["tier"] == "Max" and "yearly" in p for p in plans))

        # ---- 4. preview
        print("\n4. POST /api/biz/codeinterpreter/bizOrderLimit/price/preview")
        r = await fetcher.post(
            f"{MOCK_URL}/api/biz/codeinterpreter/bizOrderLimit/price/preview",
            json={"productId": "mock-prod-max-yearly", "count": 1},
        )
        data = json.loads(r.text)
        check("status 200", r.status == 200)
        biz_id = data.get("data", {}).get("bizId")
        check("bizId present", bool(biz_id))
        check("actualAmount is float", isinstance(data.get("data", {}).get("actualAmount"), (int, float)))

        # ---- 5. check
        print("\n5. POST /api/biz/codeinterpreter/bizOrderLimit/check")
        r = await fetcher.post(
            f"{MOCK_URL}/api/biz/codeinterpreter/bizOrderLimit/check",
            json={"bizId": biz_id},
        )
        data = json.loads(r.text)
        check("status 200", r.status == 200)
        check("check.valid == True", data.get("data", {}).get("valid") is True)

        # ---- 6. create
        print("\n6. POST /api/biz/codeinterpreter/bizOrderLimit/create")
        r = await fetcher.post(
            f"{MOCK_URL}/api/biz/codeinterpreter/bizOrderLimit/create",
            json={"bizId": biz_id},
        )
        data = json.loads(r.text)
        check("status 200", r.status == 200)
        order = data.get("data", {})
        check("orderId present", bool(order.get("orderId")))
        check("payUrl present",   bool(order.get("payUrl")))
        check("status PENDING_PAY", order.get("status") == "PENDING_PAY")

        # ---- 7. /test 401 路径
        print("\n7. GET /test (verify error handling)")
        r = await fetcher.get(f"{MOCK_URL}/test")
        check("status 401", r.status == 401)
        check("error in body", "error" in json.loads(r.text))

        # ---- 8. 错误路径:bad bizId
        print("\n8. POST /api/biz/codeinterpreter/bizOrderLimit/check (bad bizId)")
        r = await fetcher.post(
            f"{MOCK_URL}/api/biz/codeinterpreter/bizOrderLimit/check",
            json={"bizId": "DOES-NOT-EXIST"},
        )
        data = json.loads(r.text)
        check("status 200 (server 200 with valid=false)", r.status == 200)
        check("data.valid is False", data.get("data", {}).get("valid") is False)
        check("code == EXPIRE", data.get("data", {}).get("code") == "EXPIRE")

    finally:
        await fetcher.close()

    print()
    print(f"=== 结果: {passed} 通过, {failed} 失败 ===")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
