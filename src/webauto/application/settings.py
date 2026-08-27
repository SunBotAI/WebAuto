"""Persistent runtime configuration and encrypted local secret storage."""

from __future__ import annotations

import hmac
import json
import os
import secrets
import socket
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

DEFAULTS: dict[str, Any] = {
    "environment": "development",
    "runtime_dir": "var",
    "browser": {
        "mode": "managed",
        "executable": "",
        "cdp_endpoint": "http://127.0.0.1:9222",
        "headless": False,
    },
    "model": {"provider": "openai-compatible", "base_url": "", "model": ""},
    "browser_agent": {
        "backend": "local",
        "enabled": False,
        "allow_unrestricted_domains": False,
        "max_steps": 50,
        "max_duration_seconds": 1200,
    },
    "storage": {"profiles_dir": "data/profiles", "artifacts_dir": "var/artifacts"},
    "policy": {"purchase_approval_amount": 0, "publish_requires_approval": True},
    "sites": {"taobao": True, "jd": True, "xianyu": True},
}

SECRET_FIELDS = ("database_url", "redis_url", "model_api_key")


class SetupAuthorizer:
    """Separate bootstrap credential; never trusts browser-editable role headers."""

    def __init__(self, token_path: Path) -> None:
        self.token_path = token_path

    def token(self) -> str:
        configured = os.environ.get("WEBAUTO_SETUP_TOKEN")
        if configured:
            return configured
        if self.token_path.exists():
            return self.token_path.read_text(encoding="utf-8").strip()
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        value = secrets.token_urlsafe(32)
        self.token_path.write_text(value, encoding="utf-8")
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass
        return value

    def verify(self, supplied: str | None) -> bool:
        return bool(supplied) and hmac.compare_digest(supplied, self.token())


def _merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _merge(result[key], value)
        else:
            result[key] = value
    return result


class EncryptedSecretStore:
    """Fernet vault whose master key is environment-injected or file-protected locally."""

    def __init__(self, path: Path, key_path: Path, master_key: str | None = None) -> None:
        self.path = path
        self.key_path = key_path
        key = master_key or os.environ.get("WEBAUTO_MASTER_KEY") or self._local_key()
        self._fernet = Fernet(key.encode() if isinstance(key, str) else key)

    def _local_key(self) -> bytes:
        if self.key_path.exists():
            return self.key_path.read_bytes().strip()
        self.key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        self.key_path.write_bytes(key)
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        return key

    def load(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        try:
            raw = self._fernet.decrypt(self.path.read_bytes())
        except InvalidToken as exc:
            raise RuntimeError(
                "secret vault cannot be decrypted with the configured master key"
            ) from exc
        return json.loads(raw.decode("utf-8"))

    def save(self, values: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(values, ensure_ascii=False, sort_keys=True).encode("utf-8")
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_bytes(self._fernet.encrypt(payload))
        os.replace(temporary, self.path)


class RuntimeConfigStore:
    """Atomic public settings plus an encrypted secret sidecar."""

    def __init__(self, runtime_dir: Path) -> None:
        self.runtime_dir = runtime_dir
        self.config_dir = runtime_dir / "config"
        self.path = self.config_dir / "settings.json"
        self.authorizer = SetupAuthorizer(self.config_dir / "setup.token")
        self.mcp_authorizer = SetupAuthorizer(self.config_dir / "mcp.token")
        self.secrets = EncryptedSecretStore(
            self.config_dir / "secrets.enc", self.config_dir / "master.key"
        )

    def load(self) -> dict[str, Any]:
        stored = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        return _merge(DEFAULTS, stored)

    def public(self) -> dict[str, Any]:
        values = self.load()
        configured = self.secrets.load()
        values["secrets"] = {name: bool(configured.get(name)) for name in SECRET_FIELDS}
        values["setup_complete"] = self.path.exists()
        return values

    def update(
        self, settings: dict[str, Any], secret_updates: dict[str, str | None]
    ) -> dict[str, Any]:
        merged = _merge(self.load(), settings)
        self._validate(merged)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(temporary, self.path)
        secrets = self.secrets.load()
        for name, value in secret_updates.items():
            if name not in SECRET_FIELDS:
                continue
            if value is None:
                continue
            if value == "":
                secrets.pop(name, None)
            else:
                secrets[name] = value
        self.secrets.save(secrets)
        return self.public()

    def secret(self, name: str) -> str:
        return self.secrets.load().get(name, "")

    @staticmethod
    def _validate(values: dict[str, Any]) -> None:
        if values.get("environment") not in {"development", "production"}:
            raise ValueError("environment must be development or production")
        browser = values.get("browser", {})
        if browser.get("mode") not in {"managed", "cdp", "remote"}:
            raise ValueError("browser.mode must be managed, cdp or remote")
        amount = values.get("policy", {}).get("purchase_approval_amount", 0)
        if not isinstance(amount, (int, float)) or amount < 0:
            raise ValueError("purchase approval amount must be zero or greater")
        browser_agent = values.get("browser_agent", {})
        if browser_agent.get("backend") not in {"local", "browser_use"}:
            raise ValueError("browser_agent.backend must be local or browser_use")
        if not isinstance(browser_agent.get("enabled"), bool):
            raise TypeError("browser_agent.enabled must be a boolean")
        if not isinstance(browser_agent.get("allow_unrestricted_domains"), bool):
            raise TypeError("browser_agent.allow_unrestricted_domains must be a boolean")
        max_steps = browser_agent.get("max_steps")
        if not isinstance(max_steps, int) or not 1 <= max_steps <= 500:
            raise ValueError("browser_agent.max_steps must be between 1 and 500")
        duration = browser_agent.get("max_duration_seconds")
        if not isinstance(duration, (int, float)) or not 1 <= duration <= 14_400:
            raise ValueError("browser_agent.max_duration_seconds must be between 1 and 14400")

    def test_connections(self) -> dict[str, dict[str, Any]]:
        values, secrets = self.load(), self.secrets.load()
        agent = values.get("browser_agent", {})
        database_url = secrets.get("database_url", "")
        redis_url = secrets.get("redis_url", "")
        postgres = self._test_postgres(database_url)
        redis = self._test_socket_url(redis_url, 6379)
        if not database_url and values.get("environment") != "production":
            postgres = {
                "ok": True,
                "message": "本地个人模式使用内置 JSON 持久化；PostgreSQL 可选",
                "optional": True,
            }
        if not redis_url:
            redis = {
                "ok": True,
                "message": "本机 stdio MCP 不需要 Redis；远程 Worker 模式才需要",
                "optional": True,
            }
        model = self._test_model(
            values.get("model", {}),
            secrets.get("model_api_key", ""),
        )
        if not agent.get("enabled"):
            model = {
                "ok": True,
                "message": "MCP-first 外部智能体模式不需要内置模型",
                "optional": True,
            }
        return {
            "postgres": postgres,
            "redis": redis,
            "browser": self._test_browser(values.get("browser", {})),
            "browser_agent": self._test_browser_agent(agent),
            "model": model,
        }

    def prepare_local(self) -> dict[str, Any]:
        """Materialize safe local defaults and auto-detect a managed Chrome executable."""

        from webauto.runtime.browser import discover_browsers

        values = self.load()
        browser = dict(values.get("browser", {}))
        discovery = discover_browsers()
        configured = str(browser.get("executable") or "").strip()
        if browser.get("mode") == "managed" and not Path(configured).is_file():
            candidates = discovery.get("browsers", [])
            preferred = next(
                (
                    item
                    for item in candidates
                    if "edge" not in str(item.get("kind", "")).lower()
                    and "msedge" not in str(item.get("executable", "")).lower()
                ),
                candidates[0] if candidates else None,
            )
            if preferred:
                browser["executable"] = preferred["executable"]

        saved = self.update({"browser": browser}, {})
        for raw_path in (
            saved["storage"]["profiles_dir"],
            saved["storage"]["artifacts_dir"],
        ):
            path = Path(raw_path)
            if not path.is_absolute():
                path = self.runtime_dir.parent / path
            path.mkdir(parents=True, exist_ok=True)
        self.authorizer.token()
        self.mcp_authorizer.token()
        checks = self.test_connections()
        return {
            "ready": bool(checks["browser"]["ok"]),
            "mode": "mcp-first-local",
            "browser": checks["browser"],
            "persistence": checks["postgres"],
            "queue": checks["redis"],
            "setup_complete": True,
            "discovery": discovery,
            "next": "复制 MCP 配置到智能体；首次打开站点时在专属 Chrome 内登录",
        }
    async def initialize_database(self) -> dict[str, Any]:
        from webauto.storage.configuration import initialize_postgres

        return await initialize_postgres(self.secret("database_url"))

    @staticmethod
    def _test_postgres(dsn: str) -> dict[str, Any]:
        from webauto.storage.configuration import test_postgres

        return test_postgres(dsn)

    @staticmethod
    def _test_socket_url(value: str, default_port: int) -> dict[str, Any]:
        if not value:
            return {"ok": False, "message": "未配置 Redis"}
        try:
            parsed = urlparse(value)
            with socket.create_connection(
                (parsed.hostname or "127.0.0.1", parsed.port or default_port), 3
            ):
                pass
            return {"ok": True, "message": "Redis 端口可达"}
        except Exception as exc:  # noqa: BLE001 - configuration diagnostic boundary
            return {"ok": False, "message": f"Redis 连接失败：{type(exc).__name__}"}

    @staticmethod
    def _test_browser(browser: dict[str, Any]) -> dict[str, Any]:
        mode = browser.get("mode", "managed")
        if mode == "managed":
            configured = str(browser.get("executable") or "").strip()
            executable = Path(configured)
            if not configured:
                from webauto.runtime.browser import discover_browsers

                detected = discover_browsers().get("browsers", [])
                if detected:
                    return {
                        "ok": True,
                        "message": f"已自动检测浏览器：{detected[0]['executable']}",
                        "auto_detected": True,
                    }
            return {
                "ok": executable.is_file(),
                "message": "浏览器可执行文件存在" if executable.is_file() else "浏览器路径无效",
            }
        if mode == "cdp":
            try:
                endpoint = browser.get("cdp_endpoint", "").rstrip("/") + "/json/version"
                with urllib.request.urlopen(endpoint, timeout=3) as response:
                    ok = response.status == 200
                return {"ok": ok, "message": "CDP 连接成功" if ok else "CDP 响应异常"}
            except Exception as exc:  # noqa: BLE001 - CDP diagnostic boundary
                return {"ok": False, "message": f"CDP 连接失败：{type(exc).__name__}"}
        return {"ok": True, "message": "远程模式将在节点配对后验证"}

    @staticmethod
    def _test_browser_agent(agent: dict[str, Any]) -> dict[str, Any]:
        if not agent.get("enabled"):
            return {"ok": True, "message": "MCP-first 外部智能体模式；内置 Agent 未启用"}
        if agent.get("backend") == "local":
            return {"ok": True, "message": "本地确定性后端已启用"}
        try:
            from importlib.metadata import version

            from webauto.agent_backends import BrowserUseInteractiveToolsFactory

            installed = version("browser-use")
            actions = BrowserUseInteractiveToolsFactory().create().registry.registry.actions
        except (ImportError, RuntimeError) as exc:
            return {"ok": False, "message": f"Browser Use 不可用：{type(exc).__name__}: {exc}"}
        if installed != "0.13.7":
            return {"ok": False, "message": f"Browser Use 版本不匹配：{installed}"}
        return {
            "ok": True,
            "message": f"Browser Use {installed} 就绪；{len(actions)} 个受治理低风险交互动作",
        }

    @staticmethod
    def _test_model(model: dict[str, Any], api_key: str) -> dict[str, Any]:
        if not model.get("model"):
            return {"ok": False, "message": "未选择模型"}
        if not api_key:
            return {"ok": False, "message": "未配置模型密钥"}
        return {"ok": True, "message": "模型配置完整；首次调用时验证供应商响应"}
