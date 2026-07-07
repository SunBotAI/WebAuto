"""会话与登录态管理.

负责：
- 从加密凭证库或 config 加载账号凭证
- 构造并持有 :class:`ApiClient`
- 检测登录态是否有效（通过一次 getCustomerInfo 探测）
- 登录态失效时支持短信验证码重登（需人工介入取验证码）
- 重登后把新凭证回写到加密凭证库
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from Core.Zhipu.config import Account, AppConfig
from Core.Zhipu.constants import PATH_CHECK_SMS_CODE, PATH_CUSTOMER_INFO, PATH_SMS_CODE
from Core.Zhipu.crypto import SecretStore
from Core.Zhipu.exceptions import AuthError
from Core.Zhipu.http_client import ApiClient
from Core.Zhipu.logger import get_logger

log = get_logger()


@dataclass(slots=True)
class Session:
    """一个账号的活动会话。"""

    account: Account
    client: ApiClient
    user_id: str = ""

    async def aclose(self) -> None:
        await self.client.aclose()


class SessionManager:
    """会话生命周期管理。"""

    def __init__(self, config: AppConfig, secret_store: Optional[SecretStore]) -> None:
        self.config = config
        self.secret_store = secret_store

    # ----------------------------------------------------------- 构造会话

    def build_client(self, account: Account) -> ApiClient:
        """根据账号配置构造 ApiClient。

        凭证优先级：加密库 > config.account.cookie/token。
        """
        cookie = account.cookie
        token = account.token
        phone = account.phone

        # 优先从加密库读取
        if self.secret_store is not None:
            stored = self.secret_store.get_account(account.name)
            if stored:
                cookie = stored.get("cookie") or cookie
                token = stored.get("token") or token
                phone = stored.get("phone") or phone

        if not cookie and not token:
            log.warning(
                f"[{account.name}] 未找到任何凭证（cookie/token 均为空），"
                "将尝试匿名请求，大概率失败"
            )

        client = ApiClient(
            self.config,
            token=token,
            cookie=cookie,
            account_name=account.name,
        )
        # 把最终生效的 phone 挂到 client 上，便于后续短信登录复用
        client._phone = phone  # type: ignore[attr-defined]
        return client

    # ----------------------------------------------------------- 登录态检测

    async def check_alive(self, session: Session) -> bool:
        """探测登录态是否有效。成功则把 user_id 写入 session。"""
        try:
            data = await session.client.request("GET", PATH_CUSTOMER_INFO)
        except AuthError:
            return False
        except Exception as e:  # noqa: BLE001
            log.warning(f"[{session.account.name}] 登录态探测异常: {e}")
            return False
        d = data.get("data") if isinstance(data, dict) else None
        uid = ""
        if isinstance(d, dict):
            uid = str(d.get("userId") or d.get("id") or "")
        session.user_id = uid
        alive = bool(uid)
        log.info(
            f"[{session.account.name}] 登录态{'有效' if alive else '失效'}"
            + (f"，userId={uid}" if alive else "")
        )
        return alive

    # ----------------------------------------------------------- 短信重登

    async def relogin_by_sms(self, session: Session) -> bool:
        """通过短信验证码重新登录。

        流程（需求 4.1）：
          1. 发送验证码到账号手机
          2. 等待用户在终端输入收到的验证码
          3. 校验验证码，拿到新的 token/cookie
          4. 热更新 client 凭证并回写加密库

        Returns:
            是否重登成功。
        """
        phone = getattr(session.client, "_phone", None) or session.account.phone
        if not phone:
            log.error(
                f"[{session.account.name}] 无法短信重登：缺少手机号"
            )
            return False

        log.info(f"[{session.account.name}] 开始短信验证码登录，手机号: {phone}")
        # 1. 发送验证码
        try:
            await session.client.request(
                "GET", PATH_SMS_CODE.format(phone=phone)
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"[{session.account.name}] 发送验证码失败: {e}")
            return False

        # 2. 用户输入
        code = await asyncio.to_thread(_prompt_sms_code, session.account.name)
        if not code:
            log.error(f"[{session.account.name}] 未获取到验证码，重登中止")
            return False

        # 3. 校验
        try:
            resp = await session.client.request(
                "GET", PATH_CHECK_SMS_CODE.format(code=code)
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"[{session.account.name}] 验证码校验失败: {e}")
            return False

        d = resp.get("data") if isinstance(resp, dict) else None
        new_token = ""
        if isinstance(d, dict):
            new_token = str(d.get("token") or "")

        # 从响应头 set-cookie 拿新 cookie(ApiClient 已拦截到 _last_set_cookies)
        from .http_client import set_cookies_to_cookie_string
        new_cookie = set_cookies_to_cookie_string(
            session.client._last_set_cookies
        )
        if new_cookie:
            log.info(
                f"[{session.account.name}] 从响应头拿到 {len(session.client._last_set_cookies)} 个 set-cookie"
            )

        if not new_token and not new_cookie:
            log.error(
                f"[{session.account.name}] 验证码校验通过但未拿到新凭证，"
                "请检查接口返回结构(data.token / Set-Cookie)"
            )
            return False

        # 4. 热更新 + 回写
        session.client.update_credentials(
            token=new_token or None, cookie=new_cookie or None
        )
        if self.secret_store is not None:
            self.secret_store.upsert_account(
                {
                    "name": session.account.name,
                    "token": new_token,
                    "cookie": new_cookie,
                    "phone": phone,
                }
            )
        log.success(f"[{session.account.name}] 短信重登成功，凭证已更新")
        return True


def _prompt_sms_code(account_name: str) -> str:
    """在终端阻塞读取用户输入的验证码。"""
    try:
        return input(
            f"[{account_name}] 请输入收到的短信验证码（回车跳过）: "
        ).strip()
    except (EOFError, KeyboardInterrupt):
        return ""
