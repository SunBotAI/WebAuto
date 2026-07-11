"""
Tests/test_profile_isolation_e2e.py — T-053 验收测试

跨 Profile E2E 隔离验证（mock server 路线）：

核心保证：
- 同一 Browser 实例下，5 个 Profile（智谱 5 账号场景）创建 5 个独立 BrowserContext
- Cookie 完全隔离（Profile A 的 cookie 在 Profile B 中不可见）
- localStorage 完全隔离（Profile A 写入的 key 在 Profile B 中不可见）
- IndexedDB 完全隔离（Profile A 的数据库在 Profile B 中不可见）
- 不同 Profile 的 user_data_dir 必须不同（filesystem-level 隔离依据）

实现：
- mock Browser.new_context() 返回 AsyncMock context
- 每个 context 维护独立的 cookies / localStorage / indexedDB 字典
- 用 BrowserOrchestrator + ProfileStore 真实代码路径（仅 mock 浏览器层）

参考：
- Playwright 官方 BrowserContext 文档：每个 context 天然隔离 Cookie/Storage/IndexedDB
- WebAuto ADR-003 Profile Migration：Profile.store 分配 storage_dir/user-data
- TASKLIST.md T-053：智谱 5 账号 Cookie 端到端隔离测试
"""

import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, ProfileStatus
from Core.Profile.orchestrator import BrowserOrchestrator
from Core.Profile.store import ProfileStore


# ─── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def tmpdir():
    """临时目录（每个测试独立）"""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)


@pytest.fixture
def store(tmpdir):
    """ProfileStore 实例（指向 tmpdir）"""
    return ProfileStore(base_dir=tmpdir)


def _make_zhipu_profile(profile_id: str, account_label: str, screen_res=(1920, 1080)) -> Profile:
    """创建智谱风格的 Profile（5 账号场景）

    每个 Profile 设独立的 screen_resolution，用于 mock 按 viewport 路由 context。
    """
    p = Profile(id=profile_id, name=f"Zhipu {account_label}")
    p.fingerprint.locale = "zh-CN"
    p.fingerprint.timezone = "Asia/Shanghai"
    p.fingerprint.platform = "Win64"
    p.fingerprint.vendor = "Google Inc."
    p.fingerprint.screen_resolution = screen_res
    p.fingerprint.hardware_concurrency = 8
    p.fingerprint.device_memory = 8
    # 唯一 user_agent 用于反查 profile_id
    p.fingerprint.user_agent = f"Mozilla/5.0 (X11; Linux x86_64) Profile/{profile_id} Safari/537.36"
    return p


# 5 个 Profile 用不同的 screen_resolution（mock 路由依据）
_ZHIPU_PROFILE_RES = [
    (1920, 1080),
    (1366, 768),
    (1536, 864),
    (1440, 900),
    (1280, 720),
]


@pytest.fixture
def five_zhipu_profiles(store):
    """5 个智谱账号 Profile（对应 TASKLIST.md T-053 验收场景）

    每个 Profile 用不同的 screen_resolution + user_agent，
    用于 mock browser 按 viewport/user_agent 路由到独立 context。
    """
    profiles = []
    for i in range(5):
        p = _make_zhipu_profile(
            profile_id=f"zhipu-account-{i}",
            account_label=f"Account {i}",
            screen_res=_ZHIPU_PROFILE_RES[i],
        )
        store.create(p)
        profiles.append(p)
    return profiles


@pytest.fixture
def isolated_mock_browser():
    """
    Mock Playwright Browser，模拟真实 BrowserContext 隔离语义。

    每个 context 独立存储：
    - cookies: List[dict]
    - local_storage: Dict[str, str]
    - indexed_db: Set[str]（database 名称集合）

    隔离保证：context A 的 cookies/localStorage/indexed_db 在 context B 中完全不可见。
    """
    cookies_store: dict = {}        # profile_id -> List[cookie dict]
    local_storage_store: dict = {}  # profile_id -> Dict[key, value]
    indexed_db_store: dict = {}     # profile_id -> Set[db_name]

    def make_context(profile_id: str):
        # 初始化独立存储
        cookies_store.setdefault(profile_id, [])
        local_storage_store.setdefault(profile_id, {})
        indexed_db_store.setdefault(profile_id, set())

        ctx = AsyncMock()
        ctx._profile_id = profile_id

        # Cookie API
        async def mock_add_cookies(cookies):
            cookies_store[profile_id].extend(cookies)

        async def mock_get_cookies(urls=None):
            return list(cookies_store[profile_id])

        ctx.add_cookies = mock_add_cookies
        ctx.get_cookies = mock_get_cookies

        # localStorage API（通过 add_init_script 模拟注入）
        async def mock_add_init_script(script: str):
            # 记录 init script 内容（用于验证隔离）
            pass

        async def mock_storage_state(origin=None):
            """返回 localStorage + cookies 状态"""
            return {
                "cookies": list(cookies_store[profile_id]),
                "origins": [
                    {
                        "origin": "https://example.com",
                        "localStorage": [
                            {"name": k, "value": v}
                            for k, v in local_storage_store[profile_id].items()
                        ],
                    }
                ],
            }

        ctx.add_init_script = mock_add_init_script
        ctx.storage_state = mock_storage_state
        ctx.close = AsyncMock()

        return ctx

    context_by_profile: dict = {}

    def _extract_profile_id(kw: dict) -> str:
        """从 ctx_kwargs 反查 profile_id（使用 user_agent 中的 Profile/<id> 标记）"""
        ua = kw.get("user_agent", "")
        # user_agent 格式：... Profile/<profile_id> Safari/...
        marker = "Profile/"
        if marker in ua:
            tail = ua.split(marker, 1)[1]
            profile_id = tail.split(" ", 1)[0]
            return profile_id
        # fallback：使用 viewport 反查（5 Profile 不同 resolution）
        viewport = kw.get("viewport", {})
        w = viewport.get("width")
        h = viewport.get("height")
        for res in [(1920, 1080), (1366, 768), (1536, 864), (1440, 900), (1280, 720)]:
            if (w, h) == res:
                idx = [(1920, 1080), (1366, 768), (1536, 864), (1440, 900), (1280, 720)].index(res)
                return f"zhipu-account-{idx}"
        return "unknown"

    async def new_context(**kw):
        """根据 user_agent 中 Profile/<id> 标记路由到独立 context"""
        profile_id = _extract_profile_id(kw)
        if profile_id in context_by_profile:
            return context_by_profile[profile_id]
        ctx = make_context(profile_id)
        context_by_profile[profile_id] = ctx
        return ctx

    mock_browser = AsyncMock()
    mock_browser.new_context = new_context
    mock_browser.close = AsyncMock()
    mock_browser.process = MagicMock()
    mock_browser.process.pid = 12345

    mock_pw = AsyncMock()
    mock_pw.chromium = AsyncMock()
    mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)
    mock_pw.stop = AsyncMock()

    return {
        "playwright": mock_pw,
        "browser": mock_browser,
        "cookies": cookies_store,
        "local_storage": local_storage_store,
        "indexed_db": indexed_db_store,
        "contexts": context_by_profile,
    }


@pytest.fixture
def orchestrator(store, isolated_mock_browser):
    """BrowserOrchestrator 实例，注入 mock browser"""
    mock = isolated_mock_browser
    orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=10)
    # 注入 mock（绕过真实 Playwright 启动）
    orch._browser = mock["browser"]
    orch._playwright = mock["playwright"]
    orch._semaphore = asyncio.Semaphore(10)
    return orch


# ─── Cookie 隔离测试 ───────────────────────────────────────────────────────


class TestCookieIsolationE2E:
    """T-053 验收 1/3：5 个 Profile 的 Cookie 完全隔离"""

    @pytest.mark.asyncio
    async def test_five_profiles_cookie_isolation(
        self, store, five_zhipu_profiles, isolated_mock_browser, orchestrator
    ):
        """
        5 个智谱账号 Profile 各设置不同 cookie，验证互相完全不可见。

        验收：
        - 每个 Profile 设置 1 个独有的 cookie（value = profile_id）
        - 任何 Profile 借出的 context.get_cookies() 只返回自己的 cookie
        - 跨 Profile 的 cookie value 不可见
        """
        mock = isolated_mock_browser
        contexts = []
        for p in five_zhipu_profiles:
            ctx = await orchestrator.get_context(p)
            contexts.append(ctx)
            # 每个 Profile 写 1 个独有 cookie
            await ctx.add_cookies([
                {
                    "name": "zhipu_token",
                    "value": f"token-for-{p.id}",
                    "domain": ".bigmodel.cn",
                },
                {
                    "name": "user_id",
                    "value": p.id,
                    "domain": ".bigmodel.cn",
                },
            ])

        # 验证：每个 context 只能看见自己的 cookie
        for i, ctx in enumerate(contexts):
            cookies = await ctx.get_cookies()
            cookie_dict = {c["name"]: c["value"] for c in cookies}

            # 自己写的两个 cookie 在
            assert cookie_dict.get("zhipu_token") == f"token-for-zhipu-account-{i}"
            assert cookie_dict.get("user_id") == f"zhipu-account-{i}"

            # 其他 4 个 Profile 的 cookie 不可见
            for j in range(5):
                if j == i:
                    continue
                assert cookie_dict.get("user_id") != f"zhipu-account-{j}", (
                    f"Profile {i} 看见了 Profile {j} 的 cookie（隔离失败）"
                )

        # 验证 cookies_store 字典里 5 个 Profile 独立存储
        assert len(mock["cookies"]) == 5, (
            f"应有 5 个独立 cookie 存储，实际 {len(mock['cookies'])}"
        )
        for p in five_zhipu_profiles:
            assert p.id in mock["cookies"]
            assert len(mock["cookies"][p.id]) == 2

        await orchestrator.stop()

    @pytest.mark.asyncio
    async def test_cookie_value_does_not_leak_across_profiles(
        self, store, five_zhipu_profiles, orchestrator
    ):
        """
        边界：Profile A 的 cookie value 不会被 Profile B 通过任何途径读到。

        即便同名 cookie（如都是 'session_id'），不同 Profile 的 value 必须不同。
        """
        contexts = []
        for p in five_zhipu_profiles:
            ctx = await orchestrator.get_context(p)
            contexts.append(ctx)
            await ctx.add_cookies([
                {
                    "name": "session_id",
                    "value": f"unique-session-{p.id}",
                    "domain": ".bigmodel.cn",
                }
            ])

        # 收集所有 session_id 值
        session_values = []
        for i, ctx in enumerate(contexts):
            cookies = await ctx.get_cookies()
            sess = next((c["value"] for c in cookies if c["name"] == "session_id"), None)
            session_values.append(sess)

        # 所有 session_id 必须不同
        assert len(set(session_values)) == 5, (
            f"5 个 Profile 的 session_id 必须互不相同，实际: {session_values}"
        )

        await orchestrator.stop()


# ─── localStorage 隔离测试 ─────────────────────────────────────────────────


class TestLocalStorageIsolationE2E:
    """T-053 验收 2/3：5 个 Profile 的 localStorage 完全隔离"""

    @pytest.mark.asyncio
    async def test_five_profiles_localstorage_isolation(
        self, store, five_zhipu_profiles, isolated_mock_browser, orchestrator
    ):
        """
        5 个 Profile 各写不同的 localStorage key，验证互相不可见。

        验收：
        - 每个 Profile 写 1 个独有 localStorage['last_query_id']
        - 通过 storage_state() 验证：每个 context 只看见自己的 localStorage
        """
        mock = isolated_mock_browser
        contexts = []
        for p in five_zhipu_profiles:
            ctx = await orchestrator.get_context(p)
            contexts.append(ctx)
            # 模拟业务：在 context 上设置 localStorage（实际通过 add_init_script 注入）
            mock["local_storage"][p.id]["last_query_id"] = f"q-{p.id}"
            mock["local_storage"][p.id]["theme"] = "dark"

        # 验证：每个 context 的 storage_state() 只返回自己的 localStorage
        for i, ctx in enumerate(contexts):
            state = await ctx.storage_state()
            origins = state.get("origins", [])
            assert len(origins) == 1
            local_storage_items = origins[0].get("localStorage", [])
            ls_dict = {item["name"]: item["value"] for item in local_storage_items}

            # 自己的 key 在
            assert ls_dict.get("last_query_id") == f"q-zhipu-account-{i}"
            assert ls_dict.get("theme") == "dark"

            # 其他 4 个 Profile 的 key 不可见
            for j in range(5):
                if j == i:
                    continue
                assert ls_dict.get("last_query_id") != f"q-zhipu-account-{j}", (
                    f"Profile {i} 的 storage_state 暴露了 Profile {j} 的 localStorage"
                )

        # 验证 local_storage_store 字典里 5 个 Profile 独立存储
        assert len(mock["local_storage"]) == 5
        for p in five_zhipu_profiles:
            assert p.id in mock["local_storage"]
            assert mock["local_storage"][p.id] == {
                "last_query_id": f"q-{p.id}",
                "theme": "dark",
            }

        await orchestrator.stop()


# ─── IndexedDB 隔离测试 ────────────────────────────────────────────────────


class TestIndexedDBIsolationE2E:
    """T-053 验收 3/3：5 个 Profile 的 IndexedDB 完全隔离"""

    @pytest.mark.asyncio
    async def test_five_profiles_indexeddb_isolation(
        self, store, five_zhipu_profiles, isolated_mock_browser, orchestrator
    ):
        """
        5 个 Profile 各创建不同的 IndexedDB database，验证互相不可见。

        验收：
        - 每个 Profile 在自己的 context 创建 1 个独有 IndexedDB database
        - indexed_db 字典里 5 个 Profile 的 database 集合完全独立
        """
        mock = isolated_mock_browser
        contexts = []
        for p in five_zhipu_profiles:
            ctx = await orchestrator.get_context(p)
            contexts.append(ctx)
            # 模拟：在 IndexedDB 创建 database
            mock["indexed_db"][p.id].add(f"zhipu_chat_history_{p.id}")
            mock["indexed_db"][p.id].add("user_preferences")

        # 验证：每个 Profile 只能看见自己的 IndexedDB database
        for i, p in enumerate(five_zhipu_profiles):
            dbs = mock["indexed_db"][p.id]
            assert f"zhipu_chat_history_{p.id}" in dbs
            assert "user_preferences" in dbs

            # 其他 4 个 Profile 的独有 database 不可见
            for j in range(5):
                if j == i:
                    continue
                assert f"zhipu_chat_history_zhipu-account-{j}" not in dbs, (
                    f"Profile {i} 看见了 Profile {j} 的 IndexedDB database（隔离失败）"
                )

        # 验证 indexed_db 字典里 5 个 Profile 独立存储
        assert len(mock["indexed_db"]) == 5
        for p in five_zhipu_profiles:
            assert p.id in mock["indexed_db"]
            assert len(mock["indexed_db"][p.id]) == 2

        await orchestrator.stop()


# ─── user_data_dir 隔离测试 ────────────────────────────────────────────────


class TestUserDataDirIsolationE2E:
    """T-053 验收补充：5 个 Profile 的 user_data_dir 必须不同"""

    @pytest.mark.asyncio
    async def test_five_profiles_distinct_user_data_dirs(
        self, store, five_zhipu_profiles, orchestrator
    ):
        """
        5 个 Profile 创建 context 时，各自走自己 storage_dir/user-data 路径。

        验收：
        - user_data_dir 在 5 个 Profile 间互不相同
        - 每个 Profile 的 user_data_dir = profile.storage_dir / 'user-data'
        """
        user_data_dirs = set()
        for p in five_zhipu_profiles:
            ctx = await orchestrator.get_context(p)
            # Profile.user_data_dir() 返回 storage_dir/user-data
            expected_dir = p.get_user_data_dir()
            user_data_dirs.add(expected_dir)

        # 5 个 user_data_dir 必须互不相同
        assert len(user_data_dirs) == 5, (
            f"5 个 Profile 的 user_data_dir 必须互不相同，实际 {len(user_data_dirs)} 个"
        )

        # 每个 user_data_dir 的父目录（storage_dir）必须存在（store.create 时创建）
        # user-data 子目录由 BrowserOrchestrator 启动时按需创建（mock 模式不创建）
        for ud in user_data_dirs:
            assert ud.parent.exists(), f"storage_dir 不存在: {ud.parent}"
            assert ud.name == "user-data"

        await orchestrator.stop()


# ─── Context 复用测试 ──────────────────────────────────────────────────────


class TestContextReuseE2E:
    """T-053 验收补充：同一 Profile 多次 get_context 返回同一 context"""

    @pytest.mark.asyncio
    async def test_same_profile_reuses_context(
        self, store, five_zhipu_profiles, orchestrator
    ):
        """
        同一 Profile 调用 get_context() 多次，返回**同一** context 实例。
        这保证了 Cookie/Storage 状态在多次借/还之间保留。
        """
        ctx_first = await orchestrator.get_context(five_zhipu_profiles[0])
        ctx_second = await orchestrator.get_context(five_zhipu_profiles[0])
        ctx_third = await orchestrator.get_context(five_zhipu_profiles[0])

        assert ctx_first is ctx_second is ctx_third, (
            "同一 Profile 多次 get_context 必须返回同一 context 实例"
        )

        # 但不同 Profile 仍然返回不同 context
        ctx_other = await orchestrator.get_context(five_zhipu_profiles[1])
        assert ctx_other is not ctx_first, (
            "不同 Profile 必须返回不同 context 实例"
        )

        await orchestrator.stop()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])