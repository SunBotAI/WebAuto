#!/usr/bin/env python3
"""智谱凭证保存脚本（CLI fallback，等价于 WebAuto 面板 Tab 1）

为什么需要这个脚本：
- 面板 gradio 4.44.1 + starlette 1.3.1 不兼容（500 错误），临时绕开
- 等价于面板 Tab 1 的"粘 Authorization 头 → 验证 → 保存"流程
- 走 CredentialBackend.check_and_save() → 调 BigModelApi.get_customer_info() 验证 → SecretStore.upsert_account() 加密存到 .secrets.enc

使用流程：
1. 浏览器登录 bigmodel.cn
2. F12 → Network → 找任一 getCustomerInfo 请求
3. 复制 Authorization 头（完整值,含 "Bearer " 前缀）
4. 跑本脚本:
   GLM_GRABBER_KEY="any-st…oose" .venv-fix/bin/python Tools/save_token.py --name "主账号"
5. 粘贴 Authorization 头 → 验证 → 保存
6. 跑抢购:
   .venv-fix/bin/python -m Core.Zhipu grab
"""
import argparse
import asyncio
import getpass
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Tools.credential_backend import CredentialBackend


def _run(coro):
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def main() -> int:
    p = argparse.ArgumentParser(description="智谱凭证验证+保存 (等价于面板 Tab 1)")
    p.add_argument("--name", required=True, help="账号别名 (如 '主账号')")
    p.add_argument("--phone", default="", help="手机号 (可选,留空会问)")
    p.add_argument("--token", default="", help="Authorization 头值 (可选,留空会问)")
    p.add_argument("--cookie", default="", help="Cookie 值 (可选,留空会问)")
    args = p.parse_args()

    # 缺哪个问哪个 (按老大操作流:优先 token)
    token = args.token or getpass.getpass("Authorization (含 'Bearer ' 前缀): ").strip()
    cookie = args.cookie or getpass.getpass("Cookie (可回车跳过): ").strip()
    phone = args.phone or input("手机号 (可回车跳过): ").strip()

    if not token and not cookie:
        print("❌ token 和 cookie 至少需要一个")
        return 2

    backend = CredentialBackend(ask=False)
    result = _run(backend.check_and_save(
        account_name=args.name,
        phone=phone,
        token=token,
        cookie=cookie,
    ))
    if result.get("success"):
        print(f"✅ 凭证已加密保存到 {result.get('store_path', '.secrets.enc')}")
        return 0
    else:
        print(f"❌ 验证失败: {result.get('message', result)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
