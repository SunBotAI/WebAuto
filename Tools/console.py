"""智谱 GLM Coding 抢购控制台（独立启动入口）.

启动: python Tools/console.py
浏览器: http://localhost:7861

完整功能见 Tools/console_tab.py（Tab 内容提取）.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Tools.console_tab import build_console_tab


def main():
    import gradio as gr
    parser = argparse.ArgumentParser(description="WebAuto 智谱抢购控制台")
    parser.add_argument("--port", type=int, default=7861, help="监听端口(默认 7861)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--share", action="store_true", help="生成 Gradio 分享链接")
    args = parser.parse_args()

    with gr.Blocks(title="WebAuto 智谱抢购控制台") as demo:
        build_console_tab()

    print(f"🚀 智谱抢购控制台启动 → http://{args.host}:{args.port}")
    demo.launch(server_name=args.host, server_port=args.port, share=args.share)


if __name__ == "__main__":
    main()
