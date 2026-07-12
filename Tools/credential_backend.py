"""智谱凭证管理业务后端.

独立于 Gradio UI,可以单独用 Python 脚本调用。所有公开方法都是 async,
因为内部要调 BigModelApi.get_customer_info() 验证 token。

Usage (脚本)::

    backend = CredentialBackend()
    result = await backend.check_and_save(
        account_name="主账号",
        phone="138xxxxxxxx",
        token="eyJhbGc...",
    )
    if result["success"]:
        print("✅ 已加密保存到 .secrets.enc")
"""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from Core.Zhipu.api import BigModelApi
from Core.Zhipu.config import Account, AppConfig
from Core.Zhipu.crypto import CryptoError, SecretStore
from Core.Zhipu.exceptions import (
    AuthError,
    NetworkError,
    ZhipuError,
    CheckExpireError,
)
from Core.Zhipu.http_client import ApiClient
from Core.Zhipu.logger import get_logger

log = get_logger()


def _mask_phone(phone: str) -> str:
    """138****1234 形式脱敏手机号,给 UI 列表展示用。"""
    if not phone or len(phone) < 7:
        return phone or ""
    return phone[:3] + "****" + phone[-4:]


class CredentialBackend:
    """凭证管理业务后端。

    Args:
        secret_store_path: Fernet 加密库文件路径(.secrets.enc)。
        key_env: 加密口令的环境变量名(默认 GLM_GRABBER_KEY)。
        ask: SecretStore 初始化时若找不到口令,是否交互询问。
             web UI 模式下应设为 False,因为 UI 自己处理口令缺失。
    """

    def __init__(
        self,
        secret_store_path: str = ".secrets.enc",
        key_env: str = "GLM_GRABBER_KEY",
        *,
        ask: bool = False,
    ) -> None:
        self.secret_store_path = secret_store_path
        self.key_env = key_env
        self._ask = ask
        self._cached_store: Optional[SecretStore] = None

    # ----------------------------------------------------------- 内部工具

    def _get_passphrase(self) -> Optional[str]:
        """从环境变量拿加密口令。"""
        return os.environ.get(self.key_env)

    def _get_store(self, *, write: bool = False) -> SecretStore:
        """懒加载 SecretStore。

        读路径:口令不存在 → 抛 CryptoError(UI 可捕获显示)。
        写路径:口令不存在 → 用一个临时口令加密(后续导入正式口令可读)。
        """
        if self._cached_store is not None:
            return self._cached_store
        passphrase = self._get_passphrase()
        # SecretStore 内部固定读 os.environ["GLM_GRABBER_KEY"],如果用户用其他
        # 环境变量名,我们同步设置到默认 key(避免 SecretStore 的耦合)。
        if passphrase is None and not write:
            raise CryptoError(
                f"未设置环境变量 {self.key_env},无法读取凭证库。"
                f"请先设置:export {self.key_env}=<passphrase>"
            )
        if passphrase is None:
            # 临时口令模式
            passphrase = "webauto-temp-key-please-set-env-var"
        if os.environ.get("GLM_GRABBER_KEY") != passphrase:
            # 把 user 提供的口令同步到 SecretStore 默认 key
            os.environ["GLM_GRABBER_KEY"] = passphrase
        self._cached_store = SecretStore(self.secret_store_path, ask=False)
        return self._cached_store

    async def _verify_token(
        self, token: str = "", cookie: str = ""
    ) -> dict[str, Any]:
        """用 ApiClient 发 get_customer_info,验证 token/cookie 有效性。

        Returns:
            {valid: bool, user_id: str, authenticated: bool, error: str}
        """
        cfg = AppConfig(
            accounts=[Account(name="_verify_only", phone="")],
            target_plan="Max",
            billing_cycle="yearly",
            pay_channel="alipay",
        )
        client = ApiClient(cfg, token=token, cookie=cookie, account_name="_verify")
        try:
            api = BigModelApi(client, cfg)
            info = await api.get_customer_info()
            return {
                "valid": bool(info.user_id),
                "user_id": info.user_id,
                "customer_number": info.customer_number,
                "authenticated": info.authenticated,
                "error": "",
            }
        except AuthError as e:
            return {"valid": False, "user_id": "", "authenticated": False, "error": str(e)}
        except NetworkError as e:
            return {"valid": False, "user_id": "", "authenticated": False, "error": f"网络错误: {e}"}
        except ZhipuError as e:
            return {"valid": False, "user_id": "", "authenticated": False, "error": str(e)}
        finally:
            await client.aclose()

    # ----------------------------------------------------------- 公开 API

    async def check_and_save(
        self,
        account_name: str,
        phone: str,
        token: str = "",
        cookie: str = "",
    ) -> dict[str, Any]:
        """校验 + 保存凭证。

        流程:
          1. 至少有 token 或 cookie(否则报错)
          2. 调 _verify_token 验证有效性
          3. 通过 → 调 SecretStore.upsert_account 保存
          4. 返回结果 dict

        Args:
            account_name: 账号名(本地标识,如"主账号")。
            phone: 手机号(账号标识用)。
            token: Bearer token(从浏览器 Authorization 头取)。
            cookie: 完整 Cookie(从浏览器 Cookie 取)。

        Returns:
            {success, message, user_id, customer_number, expires_hint}
        """
        if not account_name.strip():
            return {"success": False, "message": "账号名不能为空", "user_id": "", "customer_number": "", "expires_hint": ""}
        if not token and not cookie:
            return {"success": False, "message": "token 和 cookie 至少填一个", "user_id": "", "customer_number": "", "expires_hint": ""}

        # 1. 验证
        verify = await self._verify_token(token=token, cookie=cookie)
        if not verify["valid"]:
            return {
                "success": False,
                "message": f"验证失败: {verify['error']}",
                "user_id": "",
                "customer_number": "",
                "expires_hint": "",
            }

        # 2. 保存
        try:
            store = self._get_store(write=True)
            store.upsert_account({
                "name": account_name.strip(),
                "phone": phone.strip(),
                "token": token,
                "cookie": cookie,
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "last_check": datetime.now(timezone.utc).isoformat(),
                "user_id": verify["user_id"],
            })
            return {
                "success": True,
                "message": f"✅ 已保存账号 [{account_name}] 到 {self.secret_store_path}",
                "user_id": verify["user_id"],
                "customer_number": verify["customer_number"],
                "expires_hint": "token 有效期通常 24h,过期请重新 check",
            }
        except CryptoError as e:
            return {
                "success": False,
                "message": f"加密保存失败: {e}",
                "user_id": "",
                "customer_number": "",
                "expires_hint": "",
            }
        except Exception as e:  # noqa: BLE001
            log.exception("保存凭证失败")
            return {
                "success": False,
                "message": f"保存失败: {e}",
                "user_id": "",
                "customer_number": "",
                "expires_hint": "",
            }


    async def list_accounts(self) -> list[dict[str, Any]]:
        """列出已保存的账号(脱敏后给 UI 显示)。

        Returns:
            [{name, phone_masked, user_id, saved_at, last_check, has_token, has_cookie}, ...]
        """
        try:
            store = self._get_store(write=False)
        except CryptoError:
            return []

        try:
            data = store.load()
            accounts = data.get("accounts", [])
            rows = []
            for a in accounts:
                rows.append({
                    "name": a.get("name", ""),
                    "phone": _mask_phone(a.get("phone", "")),
                    "user_id": a.get("user_id", ""),
                    "saved_at": a.get("saved_at", ""),
                    "last_check": a.get("last_check", ""),
                    "has_token": bool(a.get("token")),
                    "has_cookie": bool(a.get("cookie")),
                })
            return rows
        except CryptoError as e:
            log.warning(f"读取凭证库失败: {e}")
            return []

    async def delete_account(self, account_name: str) -> dict[str, Any]:
        """删除账号。Fernet 加密库没有 delete,做法是 load → 过滤 → 重写。"""
        try:
            store = self._get_store(write=False)
            data = store.load()
            accounts = data.get("accounts", [])
            before = len(accounts)
            accounts = [a for a in accounts if a.get("name") != account_name]
            if len(accounts) == before:
                return {"success": False, "message": f"未找到账号 [{account_name}]"}
            data["accounts"] = accounts
            store.save(data)
            return {"success": True, "message": f"已删除账号 [{account_name}]"}
        except CryptoError as e:
            return {"success": False, "message": str(e)}

    def check_passphrase(self) -> dict[str, Any]:
        """检查 GLM_GRABBER_KEY 环境变量是否设置。给 UI 在启动时提示。"""
        passphrase = self._get_passphrase()
        if passphrase:
            return {"configured": True, "message": f"✅ 已从 {self.key_env} 读取加密口令"}
        else:
            return {
                "configured": False,
                "message": (
                    f"⚠️ 未设置 {self.key_env} 环境变量。\n"
                    f"粘贴 token 仍可用,但保存的凭证将用临时口令加密,\n"
                    f"重启后无法读取。\n\n"
                    f"建议:export {self.key_env}=<your-passphrase>"
                ),
            }

    # ----------------------------------------------------------- 扫码登录

    async def auto_login_capture(
        self,
        account_name: str,
        phone: str = "",
        *,
        timeout_sec: int = 120,
        headless: bool = False,
        progress_callback=None,
    ) -> dict[str, Any]:
        """Playwright 扫码登录智谱,返回 {success, message, token, cookie,
        user_id, qrcode_b64, error, stage}。

        stage 取值:init / qrcode_ready / waiting_scan / login_detected /
        verifying / done / error。
        """
        from Tools.auto_login import auto_login_capture as _auto_login
        return await _auto_login(
            account_name=account_name,
            phone=phone,
            timeout_sec=timeout_sec,
            headless=headless,
            progress_callback=progress_callback,
        )

    # ----------------------------------------------------------- 手机号+短信码登录

    async def start_phone_login(
        self,
        account_name: str,
        phone: str,
        *,
        timeout_sec: int = 180,
        progress_callback=None,
    ) -> dict[str, Any]:
        """启动手机号登录流程,返回 sms_provider hook 和 captcha_b64。

        设计:gradio 调这个 → 拿到 sms_code_provider(closure)→ 在面板把
        "输入 6 位短信码"框的 value 变化 hook 进 provider; Playwright 流程在
        后台跑,sms_code_provider 第一次被 await 时挂起,等用户填码后被
        推进 → 流程继续。

        Returns:
            {
              "sms_provider": async () -> str,  把这个传给 auto_login.phone_login_capture
              "task": asyncio.Task,  任务句柄
            }
        """
        import asyncio
        from Tools.auto_login import phone_login_capture as _phone_login

        loop = asyncio.get_event_loop()
        sms_future: asyncio.Future = loop.create_future()

        async def sms_provider() -> str:
            return await sms_future

        async def _runner():
            return await _phone_login(
                account_name=account_name,
                phone=phone,
                sms_code_provider=sms_provider,
                captcha_done_event=asyncio.Event(),  # 占位,phone_login_capture 内部用 _wait_captcha_passed 轮询
                timeout_sec=timeout_sec,
                headless=False,
                progress_callback=progress_callback,
            )

        task = loop.create_task(_runner())
        return {"task": task, "sms_future": sms_future, "sms_provider": sms_provider}

    async def submit_sms_code(self, sms_future, code: str) -> None:
        """面板"输入短信码"触发:把 6 位码推给 phone_login_capture。"""
        if sms_future is not None and not sms_future.done():
            sms_future.set_result(code)

    async def cancel_phone_login(self, sms_future) -> None:
        if sms_future is not None and not sms_future.done():
            sms_future.set_result("")

    async def phone_login_and_save(
        self,
        account_name: str,
        phone: str,
        sms_code_provider,
        *,
        timeout_sec: int = 180,
        progress_callback=None,
    ) -> dict[str, Any]:
        """手机号+短信码 完整登录 + 验证 + 加密落盘。

        sms_code_provider: async () -> str 由面板提供(用户输入 6 位码时 set_result)。
        """
        if not account_name.strip():
            return {"stage": "error", "success": False, "message": "account name required",
                    "captcha_b64": "", "user_id": ""}
        if not phone or len(phone) < 11:
            return {"stage": "error", "success": False, "message": "phone invalid",
                    "captcha_b64": "", "user_id": ""}

        from Tools.auto_login import phone_login_capture as _phone_login
        import asyncio

        capture = await _phone_login(
            account_name=account_name,
            phone=phone,
            sms_code_provider=sms_code_provider,
            captcha_done_event=asyncio.Event(),
            timeout_sec=timeout_sec,
            headless=False,
            progress_callback=progress_callback,
        )
        if not capture.get("success"):
            return {
                "stage": capture.get("stage", "error"),
                "success": False,
                "message": capture.get("message", "phone login failed"),
                "captcha_b64": capture.get("captcha_b64", ""),
                "user_id": "",
            }
        # 阶段 2: 验证
        verify = await self._verify_token(
            token=capture["token"], cookie=capture["cookie"]
        )
        if not verify["valid"]:
            return {"stage": "error", "success": False,
                    "message": f"phone login ok but token invalid: {verify['error']}",
                    "captcha_b64": capture.get("captcha_b64", ""), "user_id": ""}
        # 阶段 3: 落盘
        store = self._get_store(write=True)
        store.upsert_account({
            "name": account_name.strip(),
            "phone": phone.strip(),
            "token": capture["token"],
            "cookie": capture["cookie"],
            "saved_at": datetime.now(timezone.utc).isoformat(),
            "last_check": datetime.now(timezone.utc).isoformat(),
            "user_id": verify["user_id"],
        })
        return {
            "stage": "done", "success": True,
            "message": f"phone login ok, [{account_name}] saved to {store.path if hasattr(store, 'path') else '.secrets.enc'}",
            "captcha_b64": capture.get("captcha_b64", ""),
            "user_id": verify["user_id"],
        }

    async def auto_login_and_save(
        self,
        account_name: str,
        phone: str = "",
        *,
        timeout_sec: int = 120,
        progress_callback=None,
    ) -> dict[str, Any]:
        """扫码登录 + 验证 + 落盘的完整流程。

        流程:
          1. Playwright 扫码登录,拿 token+cookie
          2. 调 _verify_token 验证有效性
          3. SecretStore 加密保存
          4. 返回结果 dict

        这个方法就是 gradio 面板 Tab 4 "扫码登录(自动)" 调用的入口。
        """
        if not account_name.strip():
            return {"stage": "error", "success": False, "message": "账号名不能为空",
                    "qrcode_b64": "", "user_id": ""}

        # 阶段 1:扫码登录
        capture = await self.auto_login_capture(
            account_name=account_name,
            phone=phone,
            timeout_sec=timeout_sec,
            progress_callback=progress_callback,
        )
        if not capture["success"]:
            return {
                "stage": "error",
                "success": False,
                "message": capture.get("message", "扫码登录失败"),
                "qrcode_b64": capture.get("qrcode_b64", ""),
                "user_id": "",
            }

        # 阶段 2:验证 token
        # 这里直接调 _verify_token 而不是再调一次 get_customer_info
        verify = await self._verify_token(
            token=capture["token"], cookie=capture["cookie"]
        )
        if not verify["valid"]:
            return {
                "stage": "error",
                "success": False,
                "message": f"扫码登录拿到凭证但验证失败: {verify['error']}",
                "qrcode_b64": capture.get("qrcode_b64", ""),
                "user_id": "",
            }

        # 阶段 3:加密保存
        try:
            store = self._get_store(write=True)
            store.upsert_account({
                "name": account_name.strip(),
                "phone": phone.strip(),
                "token": capture["token"],
                "cookie": capture["cookie"],
                "saved_at": datetime.now(timezone.utc).isoformat(),
                "last_check": datetime.now(timezone.utc).isoformat(),
                "user_id": verify["user_id"],
            })
            return {
                "stage": "done",
                "success": True,
                "message": f"✅ 扫码登录成功,账号 [{account_name}] 已加密保存",
                "qrcode_b64": capture.get("qrcode_b64", ""),
                "user_id": verify["user_id"],
            }
        except CryptoError as e:
            return {
                "stage": "error",
                "success": False,
                "message": f"扫码成功但加密保存失败: {e}",
                "qrcode_b64": capture.get("qrcode_b64", ""),
                "user_id": verify.get("user_id", ""),
            }