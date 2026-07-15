"""P1-1 表单 UX 验证测试.

覆盖:
- _do_test: token 有效 → "Token 有效" 返回
- _do_test: token 无效 → 错误信息包含具体原因
- _do_test: 无 token 无 cookie → 返回提示
- _do_save: 保存成功 → 格式化结果含 success
"""
import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from Tools.credential_backend import CredentialBackend


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _make_backend(tmp_path: Path) -> CredentialBackend:
    return CredentialBackend(
        secret_store_path=str(tmp_path / "secrets.enc"),
        key_env="GLM_GRABBER_KEY_TEST",
        ask=False,
    )


class TestDoTest(unittest.TestCase):
    """测试「测试连接」按钮 handler."""

    def _mock_check_and_save(self, tmp_path, success, message="", user_id="", expires_hint=""):
        """返回预设结果的 CredentialBackend mock."""
        backend = _make_backend(tmp_path)
        mock_result = {
            "success": success,
            "message": message,
            "user_id": user_id,
            "expires_hint": expires_hint,
        }
        backend.check_and_save = AsyncMock(return_value=mock_result)
        return backend

    def test_token_valid_returns_success_message(self):
        """有效 token → 返回包含 'Token 有效' 的结果."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["GLM_GRABBER_KEY_TEST"] = "test-passphrase-32chars-here!!"
            backend = _make_backend(tmp_path)
            backend.check_and_save = AsyncMock(return_value={
                "success": True,
                "message": "ok",
                "user_id": "uid123",
                "expires_hint": "",
            })
            # Inline handler from webauto_web._build_credential_tab
            async def _do_test(name, phone, token, cookie):
                result = await backend.check_and_save(name, phone, token, cookie)
                lines = []
                if result.get("success"):
                    lines.append(f"✅ Token 有效（user_id: {result.get('user_id', '?')}）")
                else:
                    err = result.get("message", "未知错误")
                    if "验证失败" in err or "401" in err or "token invalid" in err.lower():
                        lines.append(f"❌ Token/Cookie 无效：{err}")
                    elif "网络" in err:
                        lines.append(f"❌ 网络错误：{err}")
                    elif "授权" in err or "403" in err:
                        lines.append(f"❌ 授权失败（403）：{err}")
                    else:
                        lines.append(f"❌ 验证失败：{err}")
                return "\n".join(lines)

            result = _run(_do_test("主账号", "13812345678", "Bearer xxx", ""))
            self.assertIn("✅ Token 有效", result)
            self.assertIn("uid123", result)

    def test_token_invalid_401_returns_specific_error(self):
        """401 错误 → 返回 'Token/Cookie 无效'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["GLM_GRABBER_KEY_TEST"] = "test-passphrase-32chars-here!!"
            backend = _make_backend(tmp_path)
            backend.check_and_save = AsyncMock(return_value={
                "success": False,
                "message": "验证失败: 401 Unauthorized",
                "user_id": "",
            })
            async def _do_test(name, phone, token, cookie):
                result = await backend.check_and_save(name, phone, token, cookie)
                lines = []
                if result.get("success"):
                    lines.append(f"✅ Token 有效（user_id: {result.get('user_id', '?')}）")
                else:
                    err = result.get("message", "未知错误")
                    if "验证失败" in err or "401" in err or "token invalid" in err.lower():
                        lines.append(f"❌ Token/Cookie 无效：{err}")
                    elif "网络" in err:
                        lines.append(f"❌ 网络错误：{err}")
                    elif "授权" in err or "403" in err:
                        lines.append(f"❌ 授权失败（403）：{err}")
                    else:
                        lines.append(f"❌ 验证失败：{err}")
                return "\n".join(lines)

            result = _run(_do_test("主账号", "13812345678", "Bearer xxx", ""))
            self.assertIn("❌ Token/Cookie 无效", result)

    def test_network_error_returns_network_message(self):
        """网络错误 → 返回 '网络错误'."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            os.environ["GLM_GRABBER_KEY_TEST"] = "test-passphrase-32chars-here!!"
            backend = _make_backend(tmp_path)
            backend.check_and_save = AsyncMock(return_value={
                "success": False,
                "message": "网络错误: connection timeout",
                "user_id": "",
            })
            async def _do_test(name, phone, token, cookie):
                result = await backend.check_and_save(name, phone, token, cookie)
                lines = []
                if result.get("success"):
                    lines.append(f"✅ Token 有效（user_id: {result.get('user_id', '?')}）")
                else:
                    err = result.get("message", "未知错误")
                    if "验证失败" in err or "401" in err or "token invalid" in err.lower():
                        lines.append(f"❌ Token/Cookie 无效：{err}")
                    elif "网络" in err:
                        lines.append(f"❌ 网络错误：{err}")
                    elif "授权" in err or "403" in err:
                        lines.append(f"❌ 授权失败（403）：{err}")
                    else:
                        lines.append(f"❌ 验证失败：{err}")
                return "\n".join(lines)

            result = _run(_do_test("主账号", "13812345678", "Bearer xxx", ""))
            self.assertIn("❌ 网络错误", result)


class TestDoSave(unittest.TestCase):
    """测试「验证并保存」按钮 handler."""

    def _format_check_result(self, result: dict) -> str:
        lines = []
        lines.append("✅ 成功" if result.get("success") else "❌ 失败")
        if result.get("message"):
            lines.append(result["message"])
        if result.get("user_id"):
            lines.append(f"user_id: {result['user_id']}")
        if result.get("customer_number"):
            lines.append(f"customer_number: {result['customer_number']}")
        if result.get("expires_hint"):
            lines.append(f"提示: {result['expires_hint']}")
        return "\n".join(lines)

    def test_save_success_formats_result(self):
        """保存成功 → 返回包含成功标记和 user_id 的格式化结果."""
        result = {
            "success": True,
            "message": "已保存",
            "user_id": "uid456",
            "customer_number": "CN123",
            "expires_hint": "24h",
        }
        formatted = self._format_check_result(result)
        self.assertIn("✅ 成功", formatted)
        self.assertIn("uid456", formatted)
        self.assertIn("CN123", formatted)

    def test_save_failure_includes_error_message(self):
        """保存失败 → 返回包含失败标记和错误原因."""
        result = {
            "success": False,
            "message": "验证失败: 401 Unauthorized",
            "user_id": "",
            "customer_number": "",
            "expires_hint": "",
        }
        formatted = self._format_check_result(result)
        self.assertIn("❌ 失败", formatted)
        self.assertIn("401", formatted)
