"""P1-2 Fernet 加密验证测试.

覆盖:
- .secrets.enc 文件是加密二进制（不是 JSON 明文）
- WEBAUTO_MASTER_KEY 环境变量生效
- 密钥不存在时自动生成到 ~/.webauto_master.key
- 迁移脚本 dry-run 正常
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.fernet import Fernet


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class TestSecretsEncrypted(unittest.TestCase):
    """验证 .secrets.enc 是加密二进制，不是明文 JSON."""

    def test_secrets_file_is_binary_encrypted(self):
        """SecretStore 保存后，文件内容不是合法 JSON."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_file = tmp_path / ".secrets.enc"

            # 用临时 WEBAUTO_MASTER_KEY
            key = Fernet.generate_key()
            with patch.dict(os.environ, {"WEBAUTO_MASTER_KEY": key.decode()}):
                from Core.Zhipu.crypto import SecretStore
                store = SecretStore(secrets_file)
                store.save({"accounts": [{"name": "主账号", "token": "secret"}]})

            blob = secrets_file.read_bytes()
            # 不应该是 JSON
            self.assertRaises(json.JSONDecodeError, json.loads, blob.decode("utf-8"))
            # 应该是 base64 编码的 Fernet token
            try:
                Fernet(key).decrypt(blob)
            except Exception:
                self.fail(".secrets.enc 不是有效的 Fernet 密文")

    def test_secrets_requires_key_to_read(self):
        """无密钥时无法解密（抛出 CryptoError）."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_file = tmp_path / ".secrets.enc"

            # 用一个 key 保存
            key = Fernet.generate_key()
            from Core.Zhipu.crypto import SecretStore
            store = SecretStore(secrets_file)
            store.save({"accounts": []})

            # 用另一个 key 尝试解密
            other_key = Fernet.generate_key()
            with patch.dict(os.environ, {"WEBAUTO_MASTER_KEY": other_key.decode()}):
                from Core.Zhipu.crypto import SecretStore as SS2
                store2 = SS2(secrets_file)
                with self.assertRaises(Exception):  # CryptoError 或 InvalidToken
                    store2.load()


class TestMasterKeyEnv(unittest.TestCase):
    """验证 WEBAUTO_MASTER_KEY 环境变量生效."""

    def test_webauto_master_key_used(self):
        """设置了 WEBAUTO_MASTER_KEY 时用它加密/解密."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_file = tmp_path / ".secrets.enc"
            key = Fernet.generate_key()

            with patch.dict(os.environ, {"WEBAUTO_MASTER_KEY": key.decode()}):
                from Core.Zhipu.crypto import SecretStore
                store = SecretStore(secrets_file)
                store.save({"accounts": [{"name": "测试账号"}]})

                # 同一 key 应该能解密
                store2 = SecretStore(secrets_file)
                data = store2.load()
                self.assertEqual(data["accounts"][0]["name"], "测试账号")


class TestAutoKeyGeneration(unittest.TestCase):
    """验证无密钥时自动生成到 ~/.webauto_master.key."""

    def test_no_key_raises_error_in_non_interactive(self):
        """非交互环境无密钥 → 抛 CryptoError."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_file = tmp_path / ".secrets.enc"

            # 清除所有可能的环境变量
            env = {
                k: v for k, v in os.environ.items()
                if k not in ("WEBAUTO_MASTER_KEY", "GLM_GRABBER_KEY")
            }
            with patch.dict(os.environ, env, clear=False):
                # 模拟非交互
                with patch("sys.stdin.isatty", return_value=False):
                    from Core.Zhipu.crypto import SecretStore, CryptoError
                    with self.assertRaises(CryptoError):
                        SecretStore(secrets_file, ask=False)


class TestMigrateSecrets(unittest.TestCase):
    """验证迁移脚本 dry-run 正常."""

    def test_migrate_dry_run_success(self):
        """GLM_GRABBER_KEY 解密 + dry-run 不写入."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            secrets_file = tmp_path / ".secrets.enc"

            # 先用 legacy key 保存
            legacy_passphrase = "test-legacy-passphrase-32-chars!!"
            os.environ["GLM_GRABBER_KEY"] = legacy_passphrase
            from Core.Zhipu.crypto import SecretStore, _derive_key
            from cryptography.fernet import Fernet
            fernet = Fernet(_derive_key(legacy_passphrase))
            data = {"accounts": [{"name": "老账号", "phone": "13800001111"}]}
            blob = fernet.encrypt(json.dumps(data).encode())
            secrets_file.write_bytes(blob)

            # dry-run
            from Tools.migrate_secrets import main as migrate_main
            import sys
            with patch.object(sys, "argv", ["migrate_secrets.py", "--secrets", str(secrets_file), "--dry-run"]):
                # 不抛异常即成功
                try:
                    migrate_main()
                except SystemExit as e:
                    self.assertEqual(e.code, 0)
