"""BrowserProfile: 持久化浏览器指纹,同 context 内一致。

为什么需要: 每次 AntiDetect 启动如果随机生成一个新的 canvas 噪声 seed +
新 WebGL 渲染器 + 新 hardwareConcurrency,这本身就是 bot 特征。同一个 user
打开同一个网站两次,fingerprint 必须 *稳定* (或者在一个小范围池子里轮转)。

模块职责:
    - profile.py:  Profile 数据类 + JSON 序列化/反序列化 + 字段约束
    - store.py:    持久化到本地 ~/.cache/webauto/profiles/
    - adapter.py:  Profile → AntiDetectConfig.fingerprint_seed 转换 + 浏览器启动参数构造

典型用法:
    from Core.BrowserProfile import BrowserProfile, ProfileStore

    # 加载或创建一个 profile
    store = ProfileStore()
    profile = store.get_or_create("workstation-01")

    # 注入到 AntiDetect
    from Core.AntiDetect import AntiDetectConfig
    cfg = AntiDetectConfig()
    profile.apply_to(cfg)
"""
from .profile import BrowserProfile, HardwareConsistent, ViewportConfig
from .store import ProfileStore

__all__ = [
    "BrowserProfile",
    "HardwareConsistent",
    "ViewportConfig",
    "ProfileStore",
]
