"""凭证加密存储模块.

使用 cryptography 的 Fernet (AES-128-CBC + HMAC-SHA256) 对账号 Cookie / Token
进行对称加密，落盘为 ``.secrets.enc``。主密钥派生自用户口令（PBKDF2-HMAC-SHA256，
40 万次迭代），口令通过环境变量 ``GLM_GRABBER_KEY`` 传入；未设置时首次运行会
交互式生成并提示用户保存。

设计目标：
- 配置文件（config.yaml）里不再出现明文凭证；
- 凭证文件即使泄露，没有口令也无法解密；
- 支持多账号、可增量更新。
"""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

# 环境变量名：用户主密钥口令
KEY_ENV = "GLM_GRABBER_KEY"
# PBKDF2 参数
_PBKDF2_ITERATIONS = 400_000
_SALT = b"glm-coding-grabber-v1-salt"  # 固定盐（口令本身就是高熵源时可接受）


class CryptoError(RuntimeError):
    """凭证加解密相关错误。"""


# ---------------------------------------------------------------------------
# 密钥派生
# ---------------------------------------------------------------------------


def _derive_key(passphrase: str) -> bytes:
    """从用户口令派生 Fernet 兼容的 base64 urlsafe 密钥。"""
    raw = hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), _SALT, _PBKDF2_ITERATIONS, dklen=32
    )
    return base64.urlsafe_b64encode(raw)


def _get_passphrase(*, ask: bool = True) -> str:
    """从环境变量读取口令；不存在则交互式询问。"""
    pw = os.environ.get(KEY_ENV)
    if pw:
        return pw
    if not ask:
        raise CryptoError(
            f"未找到环境变量 {KEY_ENV}，且禁止交互式询问。请先设置口令。"
        )
    if not sys.stdin.isatty():
        raise CryptoError(
            f"未找到环境变量 {KEY_ENV}，且当前非交互终端，无法询问口令。"
        )
    pw = getpass.getpass("请输入凭证库主口令: ")
    if not pw:
        raise CryptoError("口令不能为空")
    return pw


# ---------------------------------------------------------------------------
# 读写
# ---------------------------------------------------------------------------


class SecretStore:
    """加密凭证库。

    数据结构（加密前 JSON）::

        {
            "accounts": [
                {"name": "主账号", "cookie": "...", "token": "...", "phone": "..."},
                ...
            ]
        }
    """

    def __init__(self, path: str | os.PathLike[str], *, ask: bool = True) -> None:
        self.path = Path(path)
        self._fernet = Fernet(_derive_key(_get_passphrase(ask=ask)))

    # -- 读 -----------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """读取并解密凭证库。文件不存在时返回空结构。"""
        if not self.path.exists():
            return {"accounts": []}
        blob = self.path.read_bytes()
        if not blob:
            return {"accounts": []}
        try:
            plain = self._fernet.decrypt(blob)
        except InvalidToken as e:
            raise CryptoError("凭证库解密失败：口令错误或文件已损坏") from e
        try:
            return json.loads(plain.decode("utf-8"))
        except json.JSONDecodeError as e:
            raise CryptoError("凭证库内容非合法 JSON") from e

    # -- 写 -----------------------------------------------------------------

    def save(self, data: dict[str, Any]) -> None:
        """加密并落盘。会以 0600 权限写入（尽力而为，Windows 上忽略）。"""
        plain = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        blob = self._fernet.encrypt(plain)
        self.path.write_bytes(blob)
        try:
            self.path.chmod(0o600)
        except OSError:  # Windows 上 chmod 语义不同，忽略
            pass

    # -- 便捷 API -----------------------------------------------------------

    def upsert_account(self, account: dict[str, Any]) -> None:
        """按 name 增量更新单个账号凭证。"""
        data = self.load()
        accounts: list[dict[str, Any]] = data.setdefault("accounts", [])
        name = account.get("name")
        if not name:
            raise CryptoError("account 必须包含 name 字段")
        for i, a in enumerate(accounts):
            if a.get("name") == name:
                a.update(account)
                accounts[i] = a
                break
        else:
            accounts.append(account)
        data["accounts"] = accounts
        self.save(data)

    def get_account(self, name: str) -> dict[str, Any] | None:
        for a in self.load().get("accounts", []):
            if a.get("name") == name:
                return a
        return None
