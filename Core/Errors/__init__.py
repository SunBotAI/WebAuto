from .exceptions import (
    # 基异常
    WebAutoError,
    
    # 获取器异常
    FetcherError,
    FetcherInitError,
    FetcherNetworkError,
    FetcherTimeoutError,
    FetcherBlockedError,
    FetcherCloudflareError,
    
    # 选择器异常
    SelectorError,
    ElementNotFoundError,
    ElementNotVisibleError,
    SelectorTimeoutError,
    
    # 验证码异常
    CaptchaError,
    CaptchaSolveError,
    CaptchaNotFoundError,
    
    # 时间同步异常
    TimeSyncError,
    TimeSyncCalibrationError,
    
    # 会话异常
    SessionError,
    ProxyError,
    CookieError,
)

__all__ = [
    'WebAutoError',
    'FetcherError',
    'FetcherInitError',
    'FetcherNetworkError',
    'FetcherTimeoutError',
    'FetcherBlockedError',
    'FetcherCloudflareError',
    'SelectorError',
    'ElementNotFoundError',
    'ElementNotVisibleError',
    'SelectorTimeoutError',
    'CaptchaError',
    'CaptchaSolveError',
    'CaptchaNotFoundError',
    'TimeSyncError',
    'TimeSyncCalibrationError',
    'SessionError',
    'ProxyError',
    'CookieError',
]
