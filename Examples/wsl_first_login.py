r"""wsl_first_login.py - bigmodel.cn 手动登录入口(跨平台)。

用法:
    # WSL/Linux/macOS/Windows 一致:
    python Examples/wsl_first_login.py

行为:
    1) 启 headed chromium (playwright 内部管理路径,跨平台一致)
    2) 打开 https://bigmodel.cn
    3) 给你 10 分钟手动登录
    4) 检测到登录成功 (看到套餐页 / user-center) 自动结束
    5) userdata 自动保存到 ~/.cache/webauto/chromium (跨平台)

登录成功判据:
    - URL 包含 '/user-center' / '/glm-coding' / '/subscribe'
    - 或者 document.title 包含 '套餐' / '个人中心'
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def main():
    """Delegate 到 Tools/cdp_launch.py first-run。"""
    # 检查 cdp_launch 子命令存在
    print("[wsl_first_login] 重定向到 Tools/cdp_launch.py first-run")
    print("[wsl_first_login] 10 分钟 headed,登录 bigmodel.cn")
    print()

    # 自动 reuse cdp_launch 的 first-run (full-cycle 路径)
    sys.argv = [
        "cdp_launch.py",
        "first-run",
        "--url", "https://bigmodel.cn",
        "--hold-minutes", "10",
        "--fingerprint-seed", "42",
    ]

    # 调用 Tools/cdp_launch.main
    from Tools.cdp_launch import main as cdp_main
    return cdp_main()


if __name__ == "__main__":
    sys.exit(main() or 0)
