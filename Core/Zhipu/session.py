"""会话与登录态管理.

负责：
- 从加密凭证库或 config 加载账号凭证
- 构造并持有 :class:`ApiClient`
- 检测登录态是否有效（通过一次 getCustomerInfo 探测）
- 登录态失效时直接排除账号(抢购链路);重登由用户在浏览器手动完成并回填凭证
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from Core.Zhipu.config import Account, AppConfig
from Core.Zhipu.constants import PATH_CUSTOMER_INFO
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
        # 把最终生效的 phone 挂到 client 上,便于日志/账单页等场景按账号区分
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

