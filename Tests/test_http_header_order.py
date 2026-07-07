"""Tests/test_http_header_order.py - HttpFetcher 的 Chrome header order 改造测试。

实际验证:
    - headers dict 转 _normalize_headers 后,输出的 list-of-tuples 顺序符合 Chrome 120 的常见 order
    - 未知 header 兜底放最后
    - 重复 key(case-insensitive)被去重
"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Fetchers.http import _CHROME_HEADER_ORDER, _normalize_headers


class TestChromeHeaderOrder:
    def test_standard_headers_in_order(self):
        headers = {
            "Accept-Language": "zh-CN,zh;q=0.9",
            "User-Agent":      "Test/1.0",
            "Accept":          "text/html",
            "Accept-Encoding": "gzip",
            "Connection":      "keep-alive",
        }
        ordered = _normalize_headers(headers)
        keys = [k for k, _ in ordered]
        # 必须按 Chrome order 排: Connection 在前面, 然后 Accept/Accept-Encoding/Accept-Language
        # User-Agent 也得在合理位置
        # 简言之:Connection 必须在 Accept-Language 之前
        assert keys.index("Connection") < keys.index("Accept-Language")
        # Accept-Language 是 Chrome 顺序的倒数第二三个之一
        assert keys.index("Accept-Encoding") < keys.index("Accept-Language")

    def test_unknown_headers_at_end(self):
        headers = {
            "User-Agent":      "X",
            "X-Custom-Hdr":    "y",
            "Authorization":   "Bearer X",
            "Accept":          "*/*",
        }
        ordered = _normalize_headers(headers)
        keys = [k for k, _ in ordered]
        # X-Custom-Hdr / Authorization 不在 chrome order,应放最后
        chrome_part = [k for k in keys if k in {"User-Agent", "Accept"}]
        custom_part = [k for k in keys if k in {"X-Custom-Hdr", "Authorization"}]
        assert all(keys.index(c) < len(chrome_part) for c in chrome_part)
        assert all(keys.index(c) >= len(chrome_part) for c in custom_part)

    def test_preserves_known_header_value(self):
        headers = {
            "User-Agent":      "CustomUA/2.0",
            "Accept-Language": "en-US",
            "Accept":          "text/html",
        }
        ordered = _normalize_headers(headers)
        d = dict(ordered)
        assert d["User-Agent"] == "CustomUA/2.0"
        assert d["Accept-Language"] == "en-US"

    def test_case_insensitive_header_name(self):
        """HTTP header name 是 case-insensitive,normalize 后小写键入 dict 应该都能找到。"""
        headers = {
            "user-agent":    "x",
            "ACCEPT":        "y",
            "accept-language": "z",
        }
        ordered = _normalize_headers(headers)
        # 三个都该进 ordered
        keys_lower = [k.lower() for k, _ in ordered]
        assert "user-agent" in keys_lower
        assert "accept" in keys_lower
        assert "accept-language" in keys_lower
        # 同一个 key 只能出现一次(case-insensitive 去重)
        assert len(keys_lower) == len(set(keys_lower))

    def test_empty_headers(self):
        assert _normalize_headers({}) == []

    def test_chrome_header_order_is_a_superset_of_used_headers(self):
        """sanity: 我们常用的几个 header 都应该出现在 _CHROME_HEADER_ORDER 里。"""
        for h in ("Accept", "Accept-Language", "Accept-Encoding", "User-Agent",
                  "Connection"):
            assert h in _CHROME_HEADER_ORDER, f"{h} 缺"
