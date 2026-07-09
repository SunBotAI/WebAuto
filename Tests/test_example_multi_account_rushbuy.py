"""
Tests/test_example_multi_account_rushbuy.py — T-009 多账号抢购示例 smoke test

验证：
1. example_multi_account_rushbuy.py 可正常导入（无语法/依赖错误）
2. create_profiles() 返回 3 个 Profile
3. Profile 属性正确（id / fingerprint / network）
4. main() 函数存在且可调用（不实际启动浏览器，只验证结构）
"""

import asyncio
import tempfile
import importlib.util
import sys
from pathlib import Path

import pytest

# ─── helpers ────────────────────────────────────────────────────────────────

def load_example_module():
    """动态加载 example_multi_account_rushbuy.py，不污染已导入的模块"""
    example_path = Path(__file__).parent.parent / "Examples" / "example_multi_account_rushbuy.py"
    spec = importlib.util.spec_from_file_location("example_multi_account_rushbuy", example_path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["example_multi_account_rushbuy"] = mod
    spec.loader.exec_module(mod)
    return mod


def reload_example_module():
    """重新加载（每次测试用干净模块）"""
    if "example_multi_account_rushbuy" in sys.modules:
        del sys.modules["example_multi_account_rushbuy"]
    return load_example_module()


# ─── Test: 导入无错误 ───────────────────────────────────────────────────────

def test_module_imports_without_error():
    """导入 example_multi_account_rushbuy.py 无语法/依赖错误"""
    mod = reload_example_module()
    assert mod is not None


# ─── Test: create_profiles() 返回 3 个 Profile ─────────────────────────────

def test_create_profiles_returns_three():
    """create_profiles() 返回恰好 3 个 Profile"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))
    assert len(profiles) == 3, f"期望 3 个 Profile，实际 {len(profiles)}"


def test_create_profiles_ids():
    """3 个 Profile id 分别为 account-001 / -002 / -003"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))
    ids = {p.id for p in profiles}
    assert ids == {"account-001", "account-002", "account-003"}


def test_create_profiles_names():
    """3 个 Profile name 分别为 账号-A / -B / -C"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))
    names = {p.name for p in profiles}
    assert names == {"账号-A", "账号-B", "账号-C"}


def test_create_profiles_fingerprint():
    """每个 Profile 有独立 fingerprint（locale / timezone / screen）"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))

    for p in profiles:
        assert p.fingerprint.locale == "zh-CN"
        assert p.fingerprint.timezone == "Asia/Shanghai"
        assert p.fingerprint.screen_resolution == (1920, 1080)


def test_create_profiles_network():
    """每个 Profile 有 network.proxy_url"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))

    for p in profiles:
        assert p.network.proxy_url == "http://localhost:7890"
        assert p.network.geoip_country == "CN"


def test_create_profiles_tags():
    """每个 Profile 有 rushbuy tag"""
    mod = reload_example_module()
    with tempfile.TemporaryDirectory() as tmp:
        profiles = mod.create_profiles(Path(tmp))

    for p in profiles:
        assert "rushbuy" in p.tags
        assert "flash-sale" in p.tags


# ─── Test: main() 函数存在 ──────────────────────────────────────────────────

def test_main_function_exists():
    """main() 异步函数存在"""
    mod = reload_example_module()
    assert hasattr(mod, "main")
    assert asyncio.iscoroutinefunction(mod.main)


# ─── Test: account_worker 函数存在 ─────────────────────────────────────────

def test_account_worker_exists():
    """account_worker 异步函数存在，签名正确"""
    mod = reload_example_module()
    assert hasattr(mod, "account_worker")
    assert asyncio.iscoroutinefunction(mod.account_worker)


# ─── Test: 配置常量存在 ─────────────────────────────────────────────────────

def test_config_constants():
    """RUSH_TIME / ADVANCE_MS / TARGET_URL 等配置常量存在"""
    mod = reload_example_module()
    assert hasattr(mod, "RUSH_TIME")
    assert hasattr(mod, "ADVANCE_MS")
    assert hasattr(mod, "TARGET_URL")
    assert hasattr(mod, "TABS_PER_ACCOUNT")
    assert mod.ADVANCE_MS == 200
    assert isinstance(mod.TARGET_URL, str)


# ─── Test: 扩展指南注释存在 ─────────────────────────────────────────────────

def test_expansion_guide_comment():
    """文件底部有扩展指南注释"""
    mod = reload_example_module()
    src = Path(mod.__file__).read_text()
    assert "扩展到更多账号只需" in src
    assert "max_concurrent" in src
    assert "STICKY_BY_TAG" in src
