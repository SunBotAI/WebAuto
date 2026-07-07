"""HttpFetcher 单元测试。

覆盖:
- 基础 GET (需要联网,可用本地 HTML 字符串替代)
- find / find_all / extract 在已加载 DOM 上的行为
- lxml 6.x truthy 兼容
- set_proxy 时机约束
- click/type/evaluate 在 HTTP 模式下正确抛 NotImplementedError
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from Core.Fetchers import HttpFetcher
from Core.Errors import (
    ElementNotFoundError,
    FetcherInitError,
    FetcherNetworkError,
    FetcherTimeoutError,
)


class FakeResponse:
    """模拟 httpx.Response,供 HttpFetcher 内部使用。"""

    def __init__(self, status=200, text="", content=None, headers=None, url="https://x.test/"):
        self.status_code = status
        self.text = text
        self.content = (content or text.encode("utf-8"))
        self.headers = headers or {}
        self.url = url


SAMPLE_HTML = """
<!doctype html>
<html><head><title>Example Domain</title></head>
<body><h1>Example Domain</h1>
<p>Some text <a href="/more">More information</a></p>
<a href="/other">Other</a>
</body></html>
"""


def run(coro):
    """Helper: run coroutine to completion."""
    return asyncio.get_event_loop().run_until_complete(coro)


class HttpFetcherInitTest(unittest.TestCase):
    def test_init_creates_client(self):
        async def go():
            f = HttpFetcher()
            await f.init()
            try:
                self.assertTrue(f._initialized)
                self.assertIsNotNone(f._client)
            finally:
                await f.close()
        run(go())

    def test_init_raises_on_missing_dependency(self):
        """故意传错配置,应该包成 FetcherInitError。"""
        async def go():
            f = HttpFetcher({'http2': True})  # 没装 h2 时会报错
            # 这次 h2 已装,得通过 mock httpx 失败路径
            with patch('Core.Fetchers.http.httpx.AsyncClient', side_effect=ImportError("mocked")):
                with self.assertRaises(FetcherInitError):
                    await f.init()
        run(go())

    def test_close_resets_state(self):
        async def go():
            f = HttpFetcher()
            await f.init()
            await f.close()
            self.assertFalse(f._initialized)
            self.assertIsNone(f._client)
        run(go())


class HttpFetcherGetTest(unittest.TestCase):
    def test_get_returns_response_with_dom(self):
        async def go():
            f = HttpFetcher()
            await f.init()
            try:
                # mock 内部 _client.get
                fake = FakeResponse(text=SAMPLE_HTML)
                f._client.get = AsyncMock(return_value=fake)
                resp = await f.get("https://example.com")
                self.assertEqual(resp.status, 200)
                self.assertIn("Example Domain", resp.text)
                self.assertIsNotNone(f._last_dom)
                self.assertGreater(len(f._last_dom), 0)
            finally:
                await f.close()
        run(go())

    def test_get_propagates_timeout_error(self):
        import httpx as _httpx
        async def go():
            f = HttpFetcher()
            await f.init()
            try:
                f._client.get = AsyncMock(side_effect=_httpx.TimeoutException("mocked"))
                with self.assertRaises(FetcherTimeoutError):
                    await f.get("https://x.test/")
            finally:
                await f.close()
        run(go())

    def test_get_propagates_network_error(self):
        import httpx as _httpx
        async def go():
            f = HttpFetcher()
            await f.init()
            try:
                f._client.get = AsyncMock(side_effect=_httpx.NetworkError("mocked"))
                with self.assertRaises(FetcherNetworkError):
                    await f.get("https://x.test/")
            finally:
                await f.close()
        run(go())


class HttpFetcherDomQueryTest(unittest.TestCase):
    def setUp(self):
        self.fetcher = HttpFetcher()

    def tearDown(self):
        run(self.fetcher.close())

    def _load(self):
        async def go():
            await self.fetcher.init()
            fake = FakeResponse(text=SAMPLE_HTML)
            self.fetcher._client.get = AsyncMock(return_value=fake)
            await self.fetcher.get("https://example.com")
        run(go())

    def test_find_returns_first_match(self):
        self._load()
        h1 = run(self.fetcher.find("h1"))
        self.assertIsNotNone(h1)
        self.assertEqual(h1.text_content().strip(), "Example Domain")

    def test_find_raises_when_no_dom(self):
        # 没加载任何东西就 find
        async def go():
            with self.assertRaises(ElementNotFoundError):
                await self.fetcher.find("h1")
        run(go())

    def test_find_returns_none_when_no_match(self):
        self._load()
        result = run(self.fetcher.find(".nope-not-here"))
        self.assertIsNone(result)

    def test_find_all(self):
        self._load()
        links = run(self.fetcher.find_all("a"))
        self.assertEqual(len(links), 2)

    def test_extract_text(self):
        self._load()
        text = run(self.fetcher.extract("h1"))
        self.assertEqual(text, "Example Domain")

    def test_extract_attribute(self):
        self._load()
        href = run(self.fetcher.extract("a", "href"))
        # lxml 会保留原始 href
        self.assertEqual(href, "/more")


class HttpFetcherUnsupportedOpsTest(unittest.TestCase):
    """HTTP 模式下 click/type/screenshot/evaluate 必须抛 NotImplementedError。"""

    def setUp(self):
        self.fetcher = HttpFetcher()
        run(self.fetcher.init())

    def tearDown(self):
        run(self.fetcher.close())

    def test_click_not_supported(self):
        with self.assertRaises(NotImplementedError):
            run(self.fetcher.click(".btn"))

    def test_type_not_supported(self):
        with self.assertRaises(NotImplementedError):
            run(self.fetcher.type("input", "hello"))

    def test_screenshot_not_supported(self):
        with self.assertRaises(NotImplementedError):
            run(self.fetcher.screenshot())

    def test_evaluate_not_supported(self):
        with self.assertRaises(NotImplementedError):
            run(self.fetcher.evaluate("() => 1"))


class HttpFetcherProxyTest(unittest.TestCase):
    def test_set_proxy_before_init(self):
        f = HttpFetcher()
        f.set_proxy("http://127.0.0.1:7890")
        self.assertEqual(f._proxy, "http://127.0.0.1:7890")

    def test_set_proxy_after_init_raises(self):
        async def go():
            f = HttpFetcher()
            await f.init()
            try:
                with self.assertRaises(RuntimeError):
                    f.set_proxy("http://127.0.0.1:7890")
            finally:
                await f.close()
        run(go())


class HttpFetcherCookiesTest(unittest.TestCase):
    def test_set_and_get_cookies(self):
        f = HttpFetcher()
        f.set_cookies({"a": "1", "b": "2"})
        self.assertEqual(f.get_cookies(), {"a": "1", "b": "2"})


if __name__ == "__main__":
    unittest.main()