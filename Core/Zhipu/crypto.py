"""凭证加密存储模块.

使用 cryptography 的 Fernet (AES-128-CBC + HMAC-SHA256) 对账号 Cookie / Token
进行对称加密，落盘为 ``.secrets.enc``。主密钥支持两种模式：

1. **WEBAUTO_MASTER_KEY** 环境变量（优先）：直接是 urlsafe base64 Fernet key
2. **GLM_GRABBER_KEY** 环境变量（兼容）：用户口令 → PBKDF2 派生为 Fernet key

无任何 Key 时：
  - 非交互环境：抛 CryptoError
  - 交互环境：自动生成 32 字节随机 key，写入 ``~/.webauto_master.key``（0600）

设计目标：
- 配置文件（config.yaml）里不再出现明文凭证；
- 凭证文件即使泄露，没有 key 也无法解密；
- 支持多账号、可增量更新；
- 支持 Key 轮换（MultiFernet）。
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

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

# 环境变量名
WEBAUTO_KEY_ENV = "WEBAUTO_MASTER_KEY"  # 直接 Fernet key
LEGACY_KEY_ENV = "GLM_GRABBER_KEY"  # 用户口令（PBKDF2 派生）
# 自动生成 key 路径
_AUTO_KEY_PATH = Path.home() / ".webauto_master.key"
# PBKDF2 参数（仅用于 LEGACY_KEY_ENV 口令派生）
_PBKDF2_ITERATIONS = 400_000
_SALT = b"glm-coding-grabber-v1-salt"  # 固定盐（口令本身就是高熵源时可接受）


class CryptoError(RuntimeError):
    """凭证加解密相关错误。"""


# ---------------------------------------------------------------------------
# 密钥获取
# ---------------------------------------------------------------------------


def _derive_key(passphrase: str) -> bytes:
    """从用户口令派生 Fernet 兼容的 base64 urlsafe 密钥。"""
    raw = hashlib.pbkdf2_hmac(
        "sha256", passphrase.encode("utf-8"), _SALT, _PBKDF2_ITERATIONS, dklen=32
    )
    return base64.urlsafe_b64encode(raw)


def _load_auto_key() -> bytes | None:
    """尝试从 ~/.webauto_master.key 读取自动生成的 key。"""
    if not _AUTO_KEY_PATH.exists():
        return None
    try:
        key = _AUTO_KEY_PATH.read_bytes()
        if len(key) == 44 and b"=" in key:  # Fernet key 格式
            return key.strip()
    except Exception:
        pass
    return None


def _save_auto_key(key: bytes) -> None:
    """保存自动生成的 key 到 ~/.webauto_master.key（0600）。"""
    _AUTO_KEY_PATH.write_bytes(key)
    try:
        _AUTO_KEY_PATH.chmod(0o600)
    except OSError:
        pass


def _generate_key() -> bytes:
    """生成一个新的 Fernet key。"""
    return Fernet.generate_key()


def _get_fernet_key(*, ask: bool = True) -> bytes:
    """获取 Fernet 密钥。

    优先级:
      1. WEBAUTO_MASTER_KEY 环境变量（直接是 key）
      2. ~/.webauto_master.key 文件
      3. GLM_GRABBER_KEY 环境变量（PBKDF2 派生）
      4. 交互式询问，询问结果保存到 ~/.webauto_master.key
      5. 抛 CryptoError（禁止交互且无 key）
    """
    # 1. WEBAUTO_MASTER_KEY（直接 key）
    direct = os.environ.get(WEBAUTO_KEY_ENV)
    if direct:
        key = direct.encode("utf-8") if isinstance(direct, str) else direct
        try:
            Fernet(key)  # 验证格式
            return key
        except Exception:
            raise CryptoError(
                f"{WEBAUTO_KEY_ENV} 环境变量格式不对，需要是 urlsafe base64 Fernet key"
            )

    # 2. 自动生成的 key 文件
    auto_key = _load_auto_key()
    if auto_key:
        return auto_key

    # 3. GLM_GRABBER_KEY（口令派生）
    legacy = os.environ.get(LEGACY_KEY_ENV)
    if legacy:
        return _derive_key(legacy)

    # 4. 交互式生成
    if not ask:
        raise CryptoError(
            f"未找到 {WEBAUTO_KEY_ENV} 或 {LEGACY_KEY_ENV}，"
            f"且禁止交互。请设置 {WEBAUTO_KEY_ENV} 或 {LEGACY_KEY_ENV}。"
        )
    if not sys.stdin.isatty():
        raise CryptoError(
            f"未找到密钥，且当前非交互终端。"
            f"请设置 {WEBAUTO_KEY_ENV} 或 {LEGACY_KEY_ENV}。"
        )

    # 生成并保存
    key = _generate_key()
    print(f"[SecretStore] 未找到密钥，自动生成到 {_AUTO_KEY_PATH}（chmod 600）")
    print(f"[SecretStore] 请保存！丢失此文件将无法解密凭证。")
    print(f"[SecretStore] 建议: export {WEBAUTO_KEY_ENV}=$(cat {_AUTO_KEY_PATH})")
    _save_auto_key(key)
    return key


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
        key = _get_fernet_key(ask=ask)
        self._fernet = Fernet(key)

    def _try_decrypt(self, blob: bytes) -> dict[str, Any] | None:
        """尝试用当前 key 解密，失败返回 None（用于多 key 轮换）。"""
        try:
            plain = self._fernet.decrypt(blob)
            return json.loads(plain.decode("utf-8"))
        except InvalidToken:
            return None

    # -- 读 -----------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """读取并解密凭证库。文件不存在时返回空结构。"""
        if not self.path.exists():
            return {"accounts": []}
        blob = self.path.read_bytes()
        if not blob:
            return {"accounts": []}
        result = self._try_decrypt(blob)
        if result is not None:
            return result
        raise CryptoError(
            "凭证库解密失败：密钥错误或文件已损坏。"
            "如果刚升级过，请用 Tools/migrate_secrets.py 迁移。"
        )

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


# ---------------------------------------------------------------------------
# 迁移工具（给 migrate_secrets.py 用）
# ---------------------------------------------------------------------------


def load_legacy(secrets_path: str | Path) -> dict[str, Any] | None:
    """尝试用 GLM_GRABBER_KEY 解密，返回原始 JSON 或 None。"""
    path = Path(secrets_path)
    if not path.exists():
        return None
    blob = path.read_bytes()
    if not blob:
        return None
    try:
        legacy_key = os.environ.get(LEGACY_KEY_ENV)
        if not legacy_key:
            return None
        fernet = Fernet(_derive_key(legacy_key))
        plain = fernet.decrypt(blob)
        return json.loads(plain.decode("utf-8"))
    except Exception:
        return None


def migrate(secrets_path: str | Path, *, backup: bool = True) -> dict[str, Any]:
    """把老凭证迁移到 WEBAUTO_MASTER_KEY 加密。

    流程:
      1. 用 GLM_GRABBER_KEY 解密原始文件
      2. 备份原文件为 .bak
      3. 用新 key 重新加密保存

    Returns:
        解密后的原始数据（可用于验证）

    Raises:
        CryptoError: 无法解密（无 GLM_GRABBER_KEY 或文件损坏）
    """
    path = Path(secrets_path)
    data = load_legacy(path)
    if data is None:
        raise CryptoError(
            f"无法迁移：未设置 {LEGACY_KEY_ENV} 或文件 {path} 无法用该密钥解密"
        )

    if backup:
        bak = path.with_suffix(path.suffix + ".bak")
        import shutil
        shutil.copy2(path, bak)
        print(f"[migrate] 已备份到 {bak}")

    # 用新 key 保存
    store = SecretStore(path)
    store.save(data)
    print(f"[migrate] 已用 {WEBAUTO_KEY_ENV} 重新加密保存到 {path}")
    return data
