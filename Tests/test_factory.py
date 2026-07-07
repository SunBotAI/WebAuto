"""create_fetcher 工厂单测。

覆盖:
- 四种 mode 都返回正确的 Fetcher 子类
- 不支持 mode 抛 ValueError
- mode 字段正确标记
"""
import unittest

from Core.Fetchers import (
    create_fetcher,
    FetcherMode,
    HttpFetcher,
    StealthFetcher,
    BrowserFetcher,
    HumanFetcher,
    BaseFetcher,
)


class CreateFetcherTest(unittest.TestCase):
    def test_http_mode(self):
        f = create_fetcher("http")
        self.assertIsInstance(f, HttpFetcher)
        self.assertEqual(f.mode, FetcherMode.HTTP)

    def test_stealth_mode(self):
        f = create_fetcher("stealth")
        self.assertIsInstance(f, StealthFetcher)
        self.assertEqual(f.mode, FetcherMode.STEALTH)

    def test_browser_mode(self):
        f = create_fetcher("browser")
        self.assertIsInstance(f, BrowserFetcher)
        self.assertEqual(f.mode, FetcherMode.BROWSER)

    def test_human_mode(self):
        f = create_fetcher("human")
        self.assertIsInstance(f, HumanFetcher)
        self.assertEqual(f.mode, FetcherMode.HUMAN)

    def test_default_mode(self):
        # 默认 mode 应该是 browser
        f = create_fetcher()
        self.assertIsInstance(f, BaseFetcher)

    def test_invalid_mode_raises(self):
        with self.assertRaises(ValueError):
            create_fetcher("not-a-real-mode")

    def test_inheritance_chain(self):
        # HumanFetcher 继承 BrowserFetcher, BrowserFetcher 继承 StealthFetcher
        self.assertTrue(issubclass(BrowserFetcher, StealthFetcher))
        self.assertTrue(issubclass(HumanFetcher, BrowserFetcher))

    def test_browser_defaults_headless_false(self):
        f = create_fetcher("browser")
        # BrowserFetcher 默认 headless=False(显示窗口)
        self.assertFalse(f.config.get("headless", True))

    def test_human_defaults_headless_false(self):
        f = create_fetcher("human")
        self.assertFalse(f.config.get("headless", True))

    def test_human_has_behavior_params(self):
        f = create_fetcher("human")
        self.assertTrue(hasattr(f, "mouse_speed"))
        self.assertTrue(hasattr(f, "click_delay_min"))
        self.assertTrue(hasattr(f, "type_delay_max"))


if __name__ == "__main__":
    unittest.main()