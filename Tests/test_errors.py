"""异常体系单测。

覆盖:
- WebAutoError 是所有异常的根
- 异常继承链符合 docs
- 异常可以 raise / catch / isinstance
"""
import unittest

from Core.Errors import (
    WebAutoError,
    # 获取器
    FetcherError,
    FetcherInitError,
    FetcherNetworkError,
    FetcherTimeoutError,
    FetcherBlockedError,
    FetcherCloudflareError,
    # 选择器
    SelectorError,
    ElementNotFoundError,
    ElementNotVisibleError,
    SelectorTimeoutError,
    # 验证码
    CaptchaError,
    CaptchaSolveError,
    CaptchaNotFoundError,
    # 时间同步
    TimeSyncError,
    TimeSyncCalibrationError,
    # 会话
    SessionError,
    ProxyError,
    CookieError,
)


class InheritanceTest(unittest.TestCase):
    def test_all_inherit_webautoerror(self):
        """所有自定义异常都必须继承 WebAutoError,这样用户一个 except 就能捕。"""
        exceptions = [
            FetcherError, FetcherInitError, FetcherNetworkError, FetcherTimeoutError,
            FetcherBlockedError, FetcherCloudflareError,
            SelectorError, ElementNotFoundError, ElementNotVisibleError, SelectorTimeoutError,
            CaptchaError, CaptchaSolveError, CaptchaNotFoundError,
            TimeSyncError, TimeSyncCalibrationError,
            SessionError, ProxyError, CookieError,
        ]
        for exc in exceptions:
            with self.subTest(exc=exc.__name__):
                self.assertTrue(
                    issubclass(exc, WebAutoError),
                    f"{exc.__name__} must inherit WebAutoError",
                )

    def test_subtree_inheritance(self):
        self.assertTrue(issubclass(FetcherInitError, FetcherError))
        self.assertTrue(issubclass(FetcherTimeoutError, FetcherError))
        self.assertTrue(issubclass(FetcherNetworkError, FetcherError))
        self.assertTrue(issubclass(FetcherCloudflareError, FetcherBlockedError))
        self.assertTrue(issubclass(FetcherCloudflareError, FetcherError))

        self.assertTrue(issubclass(ElementNotFoundError, SelectorError))
        self.assertTrue(issubclass(ElementNotVisibleError, SelectorError))
        self.assertTrue(issubclass(SelectorTimeoutError, SelectorError))

        self.assertTrue(issubclass(CaptchaSolveError, CaptchaError))
        self.assertTrue(issubclass(CaptchaNotFoundError, CaptchaError))

        self.assertTrue(issubclass(TimeSyncCalibrationError, TimeSyncError))

        self.assertTrue(issubclass(ProxyError, SessionError))
        self.assertTrue(issubclass(CookieError, SessionError))


class RaiseTest(unittest.TestCase):
    def test_raise_and_catch(self):
        try:
            raise ElementNotFoundError("test")
        except WebAutoError as e:
            self.assertIsInstance(e, ElementNotFoundError)
            self.assertIsInstance(e, SelectorError)
            self.assertEqual(str(e), "test")

    def test_catch_via_base_class(self):
        with self.assertRaises(WebAutoError):
            raise FetcherTimeoutError("timeout")

    def test_catch_via_middle_class(self):
        with self.assertRaises(FetcherError):
            raise FetcherNetworkError("network down")


if __name__ == "__main__":
    unittest.main()