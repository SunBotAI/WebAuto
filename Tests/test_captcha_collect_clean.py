"""Tests/test_captcha_collect_clean.py - captcha 标注启发式测试。"""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Examples.captcha_collect_clean import parse_label_from_prompt


class TestParseLabel:
    def test_basic_4_names_with_punct(self):
        assert parse_label_from_prompt(
            "请按顺序点击: 张三 李四 王五 赵六"
        ) == "张三李四王五赵六"

    def test_basic_4_names_brackets(self):
        assert parse_label_from_prompt(
            "按顺序依次点击【张三】【李四】【王五】【赵六】"
        ) == "张三李四王五赵六"

    def test_basic_4_names_spaces(self):
        assert parse_label_from_prompt(
            "依次点击 张三 李四 王五 赵六"
        ) == "张三李四王五赵六"

    def test_empty(self):
        assert parse_label_from_prompt("") == ""
        assert parse_label_from_prompt(None) == ""

    def test_realistic_glm_style(self):
        # 智谱真站常见形态: 名字以英文逗号 / 顿号隔开,前后有提示语
        got = parse_label_from_prompt("请按顺序依次点击下面的汉字: 张三、李四、王五、赵六")
        assert "张三" in got and "李四" in got
        assert "王五" in got and "赵六" in got
        assert len(got) == 8
