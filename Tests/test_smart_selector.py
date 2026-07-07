"""SmartSelector 单测。

覆盖:
- 基础 retry/retry_delay/fallback 链路
- 自定义 fallback 列表
- by_text 文本查找
- adaptive() 文本回退匹配
- exists() 不抛异常
- 异常链路:找不到时抛 ElementNotFoundError

使用 fake fetcher,不依赖真实网络/浏览器。
"""
import asyncio
import unittest
from typing import Any, List, Optional

from Core.Selector import SmartSelector, SelectorConfig, SelectorFactory
from Core.Errors import ElementNotFoundError


class FakeElement:
    def __init__(self, text="", attributes=None):
        self.text = text
        self.attributes = attributes or {}

    async def inner_text(self):
        return self.text

    def text_content(self):
        return self.text

    async def get_attribute(self, name):
        return self.attributes.get(name)

    def get(self, name):
        return self.attributes.get(name)

    async def click(self):
        pass

    async def type(self, text):
        pass


class FakeFetcher:
    """最小可用的 fetcher,供 SmartSelector 调用 find/find_all。"""

    def __init__(self, mapping: Optional[dict] = None):
        # selector -> element or list of elements
        self.mapping = mapping or {}
        self.find_calls: List[str] = []

    async def find(self, selector, **kwargs):
        self.find_calls.append(selector)
        return self.mapping.get(selector)

    async def find_all(self, selector, **kwargs):
        v = self.mapping.get(selector)
        if v is None:
            return []
        if isinstance(v, list):
            return v
        return [v]


def run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class BasicGetTest(unittest.TestCase):
    def test_returns_first_match(self):
        el = FakeElement(text="hi")
        f = FakeFetcher({".btn": el})
        s = SmartSelector(".btn", f)
        result = run(s.get())
        self.assertIs(result, el)

    def test_falls_back_to_alternative(self):
        target = FakeElement(text="fallback")
        f = FakeFetcher({".btn": None, ".submit": target})
        s = SmartSelector([".btn", ".submit"], f)
        result = run(s.get())
        self.assertIs(result, target)

    def test_uses_explicit_fallback_list(self):
        target = FakeElement(text="fb")
        f = FakeFetcher({".primary": None, ".btn": None, ".alt": target})
        s = SmartSelector(".primary", f)
        s.fallback([".btn", ".alt"])
        result = run(s.get())
        self.assertIs(result, target)

    def test_raises_when_nothing_found(self):
        f = FakeFetcher({})  # 空 mapping
        s = SmartSelector(".ghost", f)
        s.retry(2)  # 减少测试时间
        with self.assertRaises(ElementNotFoundError):
            run(s.get())


class ByTextTest(unittest.TestCase):
    def test_finds_by_inner_text(self):
        el = FakeElement(text="More information")
        f = FakeFetcher({"a": el})
        s = SmartSelector("a", f).by_text("More")
        result = run(s.get())
        self.assertIs(result, el)

    def test_by_text_returns_first_match(self):
        a = FakeElement(text="Apple")
        b = FakeElement(text="Banana")
        f = FakeFetcher({"li": [a, b]})
        s = SmartSelector("li", f).by_text("Banana")
        result = run(s.get())
        self.assertIs(result, b)


class ExistsTest(unittest.TestCase):
    def test_exists_returns_true_when_found(self):
        el = FakeElement()
        f = FakeFetcher({".btn": el})
        s = SmartSelector(".btn", f)
        self.assertTrue(run(s.exists()))

    def test_exists_returns_false_when_not_found(self):
        f = FakeFetcher({})
        s = SmartSelector(".ghost", f)
        s.retry(1)
        self.assertFalse(run(s.exists()))


class RetryTest(unittest.TestCase):
    def test_retry_then_succeed(self):
        # 模拟前两次失败,第三次成功
        state = {"calls": 0}

        async def maybe_find(selector, **kwargs):
            state["calls"] += 1
            if state["calls"] >= 3:
                return FakeElement()
            return None

        f = FakeFetcher()
        f.find = maybe_find  # type: ignore
        s = SmartSelector(".btn", f)
        s.retry(5).timeout(100)
        result = run(s.get())
        self.assertIsNotNone(result)
        self.assertGreaterEqual(state["calls"], 3)


class AdaptiveTest(unittest.TestCase):
    def test_adaptive_text_fallback_finds_via_tag(self):
        """原始选择器 .pay-btn 失败,但文本 'Pay' 在 button 上 - adaptive 应能找到。"""
        pay_btn = FakeElement(text="Pay Now")
        f = FakeFetcher({"button": [pay_btn, FakeElement(text="Cancel")]})
        s = SmartSelector(".pay-btn", f)  # 这个 selector 在 fake 里必然 None
        s.by_text("Pay")
        s.adaptive()
        s.retry(1)
        result = run(s.get())
        self.assertIs(result, pay_btn)


class SelectorFactoryTest(unittest.TestCase):
    def test_factory_call_returns_selector(self):
        f = FakeFetcher()
        factory = SelectorFactory(f)
        s = factory(".btn")
        self.assertIsInstance(s, SmartSelector)
        self.assertEqual(s._selector, ".btn")

    def test_factory_by_text(self):
        f = FakeFetcher()
        factory = SelectorFactory(f)
        s = factory.by_text("Click me", tag="button")
        self.assertEqual(s._by_text, "Click me")
        self.assertEqual(s._selector, "button")


class ChainShortcutsTest(unittest.TestCase):
    def test_chain_retry_timeout_return_self(self):
        f = FakeFetcher()
        s = SmartSelector(".x", f)
        self.assertIs(s.retry(3), s)
        self.assertIs(s.timeout(1000), s)
        self.assertIs(s.fallback([".y"]), s)
        self.assertIs(s.by_text("hi"), s)
        self.assertIs(s.adaptive(), s)


if __name__ == "__main__":
    unittest.main()