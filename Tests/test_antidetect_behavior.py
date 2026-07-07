"""行为级反检测 (2026-07-06 加强, 解决 bigmodel.cn 中文点选 captcha 405)."""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector


def test_behavior_anti_detect_default_on():
    cfg = AntiDetectConfig()
    assert cfg.enable_behavior_anti_detect is True


def test_inject_script_contains_behavior():
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    # 关键 8 项
    required = [
        ("PluginArray.prototype", "PluginArray.prototype"),
        ("chrome.runtime Proxy", "new Proxy"),
        ("PointerEvent 补全", "pointerId"),
        ("visibilityState 修复", "visibilityState"),
        ("__cdp_sessions 清理", "__cdp_sessions"),
        ("navigator.connection 补全", "navigator.connection"),
        ("performance.now 降级", "performance.now = function"),
        ("Notification.permission default", "Notification.permission"),
    ]
    missing = [name for name, kw in required if kw not in script]
    assert not missing, f"inject script 缺: {missing}"


def test_inject_script_no_auto_panel():
    """回归: 浮动 UI 仍不应该自动创建."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    assert "setTimeout(() => window.__shopauto_createShadowPanel" not in script


if __name__ == "__main__":
    test_behavior_anti_detect_default_on()
    test_inject_script_contains_behavior()
    test_inject_script_no_auto_panel()
    print("OK: 3 passed")
