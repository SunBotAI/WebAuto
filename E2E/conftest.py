"""
E2E/conftest.py — pytest 配置（E2E 测试目录）
"""
import sys
from pathlib import Path

# 把项目根目录加入 Python 路径（Tests 目录的待遇）
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

# 启用 pytest-asyncio 的 auto 模式
pytest_plugins = ['pytest_asyncio']
