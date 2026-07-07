"""CredentialBackend 业务逻辑单测.

覆盖:
- check_and_save:成功路径 / token 空 / cookie 空 / AuthError 失败
- login_by_sms:第一阶段(发码) / 第二阶段(校验+保存)
- list_accounts:脱敏 / 不存在
- delete_account:成功 / 不存在
- check_passphrase:有/无 GLM_GRABBER_KEY
"""
import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Tools.credential_backend import CredentialBackend, _mask_phone


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_backend(tmp_path: Path) -> CredentialBackend:
    return CredentialBackend(
        secret_store_path=str(tmp_path / "secrets.enc"),
        key_env="GLM_GRABBER_KEY_TEST",
        ask=False,
    )


def _set_passphrase(value: str):
    os.environ["GLM_GRABBER_KEY_TEST"] = value
    return value


def _del_passphrase():
    os.environ.pop("GLM_GRABBER_KEY_TEST", None)


class MaskPhoneTest(unittest.TestCase):
    def test_full_phone(self):
        self.assertEqual(_mask_phone("13812345678"), "138****5678")

    def test_short_phone_passthrough(self):
        # 太短则不脱敏(避免误伤)
        self.assertEqual(_mask_phone("123"), "123")
        self.assertEqual(_mask_phone(""), "")
        self.assertEqual(_mask_phone(None), "")


class CheckAndSaveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        _set_passphrase("test-passphrase")

    def tearDown(self):
        _del_passphrase()

    def test_empty_account_name(self):
        b = _make_backend(self.tmp_path)
        result = run(b.check_and_save("", "138xxxxxxxx", token="xxx"))
        self.assertFalse(result["success"])
        self.assertIn("账号名", result["message"])

    def test_no_token_no_cookie(self):
        b = _make_backend(self.tmp_path)
        result = run(b.check_and_save("主账号", "138xxxxxxxx"))
        self.assertFalse(result["success"])
        self.assertIn("token", result["message"])

    def test_verify_token_returns_401(self):
        """token 验证失败 → 整体失败,不保存。"""
        b = _make_backend(self.tmp_path)

        # mock _verify_token 直接返回失败
        async def fake_verify(token="", cookie=""):
            return {"valid": False, "user_id": "", "authenticated": False, "error": "401"}
        b._verify_token = fake_verify

        result = run(b.check_and_save("主账号", "138xxxxxxxx", token="bad-token"))
        self.assertFalse(result["success"])
        self.assertIn("验证失败", result["message"])
        # 确认没有写文件
        self.assertFalse((self.tmp_path / "secrets.enc").exists())

    def test_verify_token_success_saves(self):
        """token 有效 → 加密保存到 .secrets.enc。"""
        b = _make_backend(self.tmp_path)

        async def fake_verify(token="", cookie=""):
            return {
                "valid": True,
                "user_id": "user-abc-123",
                "customer_number": "C001",
                "authenticated": True,
                "error": "",
            }
        b._verify_token = fake_verify

        result = run(b.check_and_save("主账号", "13812345678", token="good-token"))
        self.assertTrue(result["success"], result["message"])
        self.assertEqual(result["user_id"], "user-abc-123")

        # 验证文件确实被写入
        self.assertTrue((self.tmp_path / "secrets.enc").exists())


class LoginBySmsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        _set_passphrase("test-passphrase")

    def tearDown(self):
        _del_passphrase()

    def test_empty_account(self):
        b = _make_backend(self.tmp_path)
        result = run(b.login_by_sms("", "138xxxxxxxx"))
        self.assertEqual(result["stage"], "error")

    def test_first_stage_sends_code(self):
        """sms_code 为空 → 第一阶段,只发验证码,返回 code_sent。"""
        b = _make_backend(self.tmp_path)
        # mock ApiClient.request
        with patch("Tools.credential_backend.ApiClient") as MockClient:
            mock_client = MagicMock()
            mock_client.request = AsyncMock(return_value={"code": 200})
            mock_client.aclose = AsyncMock()
            mock_client._last_set_cookies = []
            MockClient.return_value = mock_client

            result = run(b.login_by_sms("主账号", "13812345678"))
            self.assertEqual(result["stage"], "code_sent")
            self.assertTrue(result["success"])
            # 检查请求的 path 包含 smsCode
            call_args = mock_client.request.call_args
            self.assertIn("/api/biz/code/smsCode/", call_args.args[1])

    def test_second_stage_invalid_code(self):
        """sms_code 错误 → 校验失败。"""
        b = _make_backend(self.tmp_path)
        with patch("Tools.credential_backend.ApiClient") as MockClient:
            mock_client = MagicMock()
            # 第一次发码成功(测试中跳过),直接走第二阶段
            # 模拟 checkSmsCode 返回 401
            from Core.Zhipu.exceptions import AuthError
            mock_client.request = AsyncMock(side_effect=AuthError("短信码错误"))
            mock_client.aclose = AsyncMock()
            mock_client._last_set_cookies = []
            MockClient.return_value = mock_client

            result = run(b.login_by_sms("主账号", "13812345678", sms_code="000000"))
            self.assertEqual(result["stage"], "done")
            self.assertFalse(result["success"])
            self.assertIn("短信码", result["message"])

    def test_second_stage_success(self):
        """sms_code 正确 → 拿到 token/cookie,验证后保存。"""
        b = _make_backend(self.tmp_path)
        with patch("Tools.credential_backend.ApiClient") as MockClient:
            mock_client = MagicMock()
            # checkSmsCode 返回带 token 的 body
            mock_client.request = AsyncMock(return_value={
                "code": 200,
                "data": {"token": "new-bearer-token-abc"},
            })
            mock_client.aclose = AsyncMock()
            mock_client._last_set_cookies = ["sid=xyz; Path=/", "tok=def; Path=/"]
            MockClient.return_value = mock_client

            # mock _verify_token 返回成功
            async def fake_verify(token="", cookie=""):
                return {
                    "valid": True,
                    "user_id": "user-xyz-789",
                    "customer_number": "C-XYZ",
                    "authenticated": True,
                    "error": "",
                }
            b._verify_token = fake_verify

            result = run(b.login_by_sms("主账号", "13812345678", sms_code="123456"))
            self.assertEqual(result["stage"], "done")
            self.assertTrue(result["success"], result["message"])
            self.assertEqual(result["user_id"], "user-xyz-789")
            self.assertTrue((self.tmp_path / "secrets.enc").exists())


class ListAccountsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)

    def test_no_passphrase_returns_empty(self):
        _del_passphrase()
        b = _make_backend(self.tmp_path)
        result = run(b.list_accounts())
        self.assertEqual(result, [])

    def test_passphrase_set_empty_db(self):
        _set_passphrase("test")
        b = _make_backend(self.tmp_path)
        result = run(b.list_accounts())
        self.assertEqual(result, [])

    def test_passphrase_set_with_data(self):
        _set_passphrase("test")
        b = _make_backend(self.tmp_path)
        # 写入测试数据
        store = b._get_store(write=True)
        store.upsert_account({
            "name": "主账号",
            "phone": "13812345678",
            "token": "tok-1",
            "cookie": "",
            "user_id": "u-1",
            "saved_at": "2026-07-03T00:00:00",
            "last_check": "2026-07-03T00:00:00",
        })
        result = run(b.list_accounts())
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "主账号")
        self.assertEqual(result[0]["phone"], "138****5678")  # 脱敏
        self.assertTrue(result[0]["has_token"])


class DeleteAccountTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)
        _set_passphrase("test")

    def test_delete_existing(self):
        b = _make_backend(self.tmp_path)
        store = b._get_store(write=True)
        store.upsert_account({"name": "a", "phone": "1", "token": "t"})
        store.upsert_account({"name": "b", "phone": "2", "token": "t"})

        result = run(b.delete_account("a"))
        self.assertTrue(result["success"])
        remaining = run(b.list_accounts())
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["name"], "b")

    def test_delete_nonexistent(self):
        b = _make_backend(self.tmp_path)
        result = run(b.delete_account("nope"))
        self.assertFalse(result["success"])


class CheckPassphraseTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.tmp_path = Path(self.tmp)

    def test_configured(self):
        _set_passphrase("test")
        b = _make_backend(self.tmp_path)
        result = b.check_passphrase()
        self.assertTrue(result["configured"])
        self.assertIn("GLM_GRABBER_KEY_TEST", result["message"])

    def test_not_configured(self):
        _del_passphrase()
        b = _make_backend(self.tmp_path)
        result = b.check_passphrase()
        self.assertFalse(result["configured"])
        self.assertIn("建议", result["message"])


if __name__ == "__main__":
    unittest.main()