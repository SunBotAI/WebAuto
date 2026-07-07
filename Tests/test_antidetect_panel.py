"""AntiDetect: shadow panel 默认不应该 auto-create (避免真实站挡按钮).

2026-07-06: 旧版本 _shadow_dom_script 在每次页面 load 后自动调用
__shopauto_createShadowPanel() 创建 '🛡️ WebAuto' 浮动 div, 在
bigmodel.cn 等真实站点上挡住登录按钮 / 验证码. 现已改:
- 默认 enable_shadow_panel=False
- 即便 True, 也不再 auto-create
- 工具函数 __shopauto_createShadowPanel / __shopauto_removeShadowPanel 仍暴露
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from Core.AntiDetect import AntiDetectConfig, AntiDetectInjector


def test_default_shadow_panel_disabled():
    cfg = AntiDetectConfig()
    assert cfg.enable_shadow_panel is False, (
        f"enable_shadow_panel 默认应为 False (避免挡登录按钮), 实际 {cfg.enable_shadow_panel}"
    )


def test_inject_script_no_auto_create():
    """注入脚本里不应出现自动 createShadowPanel 的 setTimeout 调用."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    assert "setTimeout(() => window.__shopauto_createShadowPanel" not in script, (
        "init script 里仍在自动调用 createShadowPanel(), 会再挡按钮"
    )
    # 也不能出现 addEventListener('load', ...) 自动调
    assert "addEventListener('load'" not in script or "__shopauto_createShadowPanel" not in script, (
        "load 事件里仍在自动调 createShadowPanel()"
    )


def test_remove_api_present():
    """工具函数 __shopauto_removeShadowPanel 必须注入, 供 clean-ui 子命令调用."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    assert "__shopauto_removeShadowPanel" in script, (
        "init script 缺少 __shopauto_removeShadowPanel 工具, 无法清理已注入的浮动 div"
    )


def test_create_api_present():
    """工具函数 __shopauto_createShadowPanel 也要暴露, 谁需要谁手动调."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    assert "__shopauto_createShadowPanel" in script, (
        "init script 缺少 __shopauto_createShadowPanel 工具"
    )


def test_inject_script_no_visible_panel_html():
    """注入脚本里不能含可见的 '已注入' 标识 HTML (那是浮动 UI 的内容)."""
    inj = AntiDetectInjector(AntiDetectConfig())
    script = inj.get_inject_script()
    # createShadowPanel 的 htmlContent 参数默认值含 "🛡️ WebAuto" + "已注入",
    # 但这是 lazy 参数, 不会自动渲染. 关键是 script 里不能有自动 append 的痕迹.
    # 我们检查没有 document.body.appendChild(newHost) 出现 (除了在 createShadowPanel 函数体内作为 lazy 模板)
    appends = script.count("appendChild(newHost)")
    assert appends <= 1, f"appendChild(newHost) 出现 {appends} 次, 应只在 createShadowPanel 函数内一次"


if __name__ == "__main__":
    test_default_shadow_panel_disabled()
    test_inject_script_no_auto_create()
    test_remove_api_present()
    test_create_api_present()
    test_inject_script_no_visible_panel_html()
    print("OK: 5 passed")
