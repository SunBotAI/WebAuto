"""
WebAuto 统一异常定义
所有异常继承自 WebAutoError,方便统一捕获和处理
"""


class WebAutoError(Exception):
    """WebAuto 基异常"""
    pass


# ===== 获取器异常 =====
class FetcherError(WebAutoError):
    """获取器基异常"""
    pass


class FetcherInitError(FetcherError):
    """获取器初始化失败"""
    pass


class FetcherNetworkError(FetcherError):
    """网络错误"""
    pass


class FetcherTimeoutError(FetcherError):
    """请求超时"""
    pass


class FetcherBlockedError(FetcherError):
    """被反爬拦截"""
    pass


class FetcherCloudflareError(FetcherBlockedError):
    """Cloudflare 拦截"""
    pass


# ===== 选择器异常 =====
class SelectorError(WebAutoError):
    """选择器基异常"""
    pass


class ElementNotFoundError(SelectorError):
    """元素找不到"""
    pass


class ElementNotVisibleError(SelectorError):
    """元素不可见"""
    pass


class SelectorTimeoutError(SelectorError):
    """选择器超时"""
    pass


# ===== 验证码异常 =====
class CaptchaError(WebAutoError):
    """验证码基异常"""
    pass


class CaptchaSolveError(CaptchaError):
    """验证码识别失败"""
    pass


class CaptchaNotFoundError(CaptchaError):
    """找不到验证码"""
    pass


# ===== 时间同步异常 =====
class TimeSyncError(WebAutoError):
    """时间同步基异常"""
    pass


class TimeSyncCalibrationError(TimeSyncError):
    """校时失败"""
    pass


# ===== 会话异常 =====
class SessionError(WebAutoError):
    """会话基异常"""
    pass


class ProxyError(SessionError):
    """代理错误"""
    pass


class CookieError(SessionError):
    """Cookie 错误"""
    pass
