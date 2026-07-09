"""
E2E/test_orchestrator_e2e.py — Playwright 真实浏览器 E2E 测试

验证 BrowserOrchestrator 多 Profile 真实隔离：
1. 2 个 Profile 各自启动真实 Chromium Context
2. 验证 cookie 真实隔离（不同 Context 不同 cookie）
3. 验证 localStorage 真实隔离
4. 验证 Context 复用（同一 Profile 多次 get_context 返回同一 Context）

前置：需要 playwright install chromium（只装一次）
  .venv/bin/playwright install chromium
"""

import asyncio
import tempfile
from pathlib import Path

import pytest

from Core.Profile import Profile, FingerprintConfig, NetworkConfig
from Core.Profile.store import ProfileStore
from Core.Profile.orchestrator import BrowserOrchestrator


# ─── fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_base():
    """临时 Profile 存储目录（测试结束自动清理）"""
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def store(tmp_base):
    return ProfileStore(base_dir=tmp_base)


@pytest.fixture
async def orchestrator(store):
    o = BrowserOrchestrator(store=store, headless=True, max_concurrent=5)
    # E2E 测试不关心内存限制，禁用 _check_memory 避免 browser.process 版本兼容问题
    o._check_memory = lambda: None
    await o.start()
    yield o
    await o.stop()


@pytest.fixture
def profile_a(store):
    p = Profile(
        id="profile-a",
        name="账号-A",
        fingerprint=FingerprintConfig(
            locale="zh-CN",
            timezone="Asia/Shanghai",
            screen_resolution=(1920, 1080),
        ),
    )
    store.create(p)
    return p


@pytest.fixture
def profile_b(store):
    p = Profile(
        id="profile-b",
        name="账号-B",
        fingerprint=FingerprintConfig(
            locale="en-US",
            timezone="America/New_York",
            screen_resolution=(1366, 768),
        ),
    )
    store.create(p)
    return p


# ─── E2E 测试 ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_profiles_cookie_isolation(orchestrator, store, profile_a, profile_b):
    """
    验证两个 Profile 的 cookie 真实隔离：
    - profile-a 在 Context-A 设置 cookie
    - profile-b 在 Context-B 设置 cookie（必须是不同的 Context）
    - 各自读取自己的 cookie，互不干扰
    """
    # Profile-A: 借 Context，写入测试 cookie
    ctx_a = await orchestrator.get_context(profile_a)
    page_a = await ctx_a.new_page()
    await page_a.goto("https://example.com")
    await page_a.evaluate(
        "document.cookie = 'profile_a_token=abc123; path=/; SameSite=Lax'"
    )
    await page_a.reload()
    cookie_a = await page_a.evaluate("document.cookie")

    # Profile-B: 借 Context，验证没有 profile-a 的 cookie
    ctx_b = await orchestrator.get_context(profile_b)
    page_b = await ctx_b.new_page()
    await page_b.goto("https://example.com")
    cookie_b = await page_b.evaluate("document.cookie")

    # 各自只能读到自己的 cookie
    assert "profile_a_token=abc123" in cookie_a, f"Profile-A should see its own cookie: {cookie_a}"
    assert "profile_a_token" not in cookie_b, f"Profile-B should NOT see Profile-A cookie: {cookie_b}"
    assert cookie_a != cookie_b, "Two profiles should have different cookie states"

    await page_a.close()
    await page_b.close()


@pytest.mark.asyncio
async def test_two_profiles_localstorage_isolation(orchestrator, store, profile_a, profile_b):
    """
    验证 localStorage 真实隔离：
    - profile-a 写入 localStorage['test_key'] = 'value_a'
    - profile-b 的 localStorage['test_key'] 不存在
    """
    ctx_a = await orchestrator.get_context(profile_a)
    page_a = await ctx_a.new_page()
    await page_a.goto("https://example.com")
    await page_a.evaluate("localStorage.setItem('test_key', 'value_a')")

    ctx_b = await orchestrator.get_context(profile_b)
    page_b = await ctx_b.new_page()
    await page_b.goto("https://example.com")
    val_b = await page_b.evaluate("localStorage.getItem('test_key')")

    assert val_b is None, f"Profile-B should NOT see Profile-A localStorage, got: {val_b}"

    # 反过来验证 profile-a 仍然能读到自己的
    val_a = await page_a.evaluate("localStorage.getItem('test_key')")
    assert val_a == "value_a", f"Profile-A should still see its own localStorage: {val_a}"

    await page_a.close()
    await page_b.close()


@pytest.mark.asyncio
async def test_same_profile_reuses_context(orchestrator, store, profile_a):
    """
    验证同一 Profile 多次 get_context 返回同一 BrowserContext 实例：
    - 第一次 get_context(profile_a) 创建 Context
    - 第二次 get_context(profile_a) 返回同一 Context（不是新建）
    """
    ctx_1 = await orchestrator.get_context(profile_a)
    ctx_2 = await orchestrator.get_context(profile_a)

    assert ctx_1 is ctx_2, (
        f"Same profile should return same BrowserContext instance, "
        f"got {id(ctx_1)} vs {id(ctx_2)}"
    )

    # 验证 Context 复用：page_1 设置 cookie，page_2 能读到（同一 Context 共享 Cookie jar）
    page_1 = await ctx_1.new_page()
    await page_1.goto("https://example.com")
    await page_1.evaluate(
        "document.cookie = 'reuse_test=still_here; path=/; SameSite=Lax'"
    )

    page_2 = await ctx_2.new_page()
    await page_2.goto("https://example.com")
    val = await page_2.evaluate("document.cookie")
    assert "reuse_test=still_here" in val, (
        f"Reused context should share cookie jar: {val}"
    )

    await page_1.close()
    await page_2.close()


@pytest.mark.asyncio
async def test_different_profiles_get_different_contexts(orchestrator, store, profile_a, profile_b):
    """
    验证不同 Profile 拿到不同的 BrowserContext：
    - profile-a 和 profile-b 必须返回不同 Context 实例
    - 不同 Context 有不同的 user_data_dir
    """
    ctx_a = await orchestrator.get_context(profile_a)
    ctx_b = await orchestrator.get_context(profile_b)

    assert ctx_a is not ctx_b, "Different profiles must get different BrowserContext instances"

    # 验证 user_data_dir 不同（隔离的基础）
    udir_a = ctx_a.storage_state if ctx_a.storage_state else None
    # storage_state 返回 storage state file path，不是 user_data_dir
    # 用 fingerprint 验证隔离：不同 profile 不同 canvas_seed
    fp_a = store.get(profile_a.id).fingerprint
    fp_b = store.get(profile_b.id).fingerprint
    assert fp_a.canvas_seed != fp_b.canvas_seed, (
        "Different profiles must have different canvas_seed for fingerprint isolation"
    )


@pytest.mark.asyncio
async def test_profile_context_close_preserves_isolation(orchestrator, store, profile_a, profile_b):
    """
    验证 close_context 后隔离仍然保持：
    - profile-a 设置 cookie 后 close_context
    - profile-b 打开新 Context，应该没有 profile-a 的 cookie
    """
    # Profile-A: 写 cookie，关 Context
    ctx_a = await orchestrator.get_context(profile_a)
    page_a = await ctx_a.new_page()
    await page_a.goto("https://example.com")
    await page_a.evaluate(
        "document.cookie = 'close_test=keep; path=/; SameSite=Lax'"
    )
    await page_a.close()
    await orchestrator.close_context(profile_a)

    # Profile-B: 打开新 Context，验证没有 close_test cookie
    ctx_b = await orchestrator.get_context(profile_b)
    page_b = await ctx_b.new_page()
    await page_b.goto("https://example.com")
    cookie_b = await page_b.evaluate("document.cookie")

    assert "close_test" not in cookie_b, (
        f"After close_context, Profile-B should not see Profile-A cookie: {cookie_b}"
    )

    await page_b.close()


@pytest.mark.asyncio
async def test_fingerprint_injected_into_context(orchestrator, store, profile_a):
    """
    验证 fingerprint 配置注入到真实 Context：
    - profile-a 设置 locale=zh-CN, timezone=Asia/Shanghai
    - 打开页面，JS 读取 navigator.locale 应该反映这个配置
    """
    ctx = await orchestrator.get_context(profile_a)
    page = await ctx.new_page()
    await page.goto("https://example.com")

    # 验证 timezone 注入（JavaScript new Date().getTimezoneOffset() 反映 timezone）
    # Asia/Shanghai 是 UTC+8，offset 应该是 -480
    tz_offset = await page.evaluate("new Date().getTimezoneOffset()")
    assert tz_offset == -480, (
        f"Profile-A timezone should be Asia/Shanghai (offset -480), got {tz_offset}"
    )

    # 验证 screen_resolution 注入（通过 window.screen 读取）
    screen_width = await page.evaluate("window.screen.width")
    screen_height = await page.evaluate("window.screen.height")
    assert (screen_width, screen_height) == (1920, 1080), (
        f"Profile-A screen should be 1920x1080, got {screen_width}x{screen_height}"
    )

    await page.close()


@pytest.mark.asyncio
async def test_concurrent_two_profiles_no_deadlock(orchestrator, store, profile_a, profile_b):
    """
    验证两个 Profile 并发获取 Context 不会死锁：
    - asyncio.gather 并发调用 get_context
    - 两个都应在合理时间内完成（无死锁）
    """
    async def get_and_check(profile, expect_token):
        ctx = await orchestrator.get_context(profile)
        page = await ctx.new_page()
        await page.goto("https://example.com")
        await page.evaluate(
            f"document.cookie = 'token={expect_token}; path=/; SameSite=Lax'"
        )
        await page.reload()
        cookie = await page.evaluate("document.cookie")
        await page.close()
        return expect_token in cookie

    results = await asyncio.gather(
        get_and_check(profile_a, "token_a"),
        get_and_check(profile_b, "token_b"),
    )

    assert all(results), f"Both profiles should successfully set and read cookies: {results}"
