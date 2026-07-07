r"""captcha_collect_clean.py -- 采到的 captcha 样张清洗 + 标注。

任务:
    1. 扫 Examples/.captcha_samples/ 下所有 captcha_<timestamp>/ 目录
    2. 读 meta.json 里的 promptText ("请按顺序点击: 张三 李四 王五 赵六")
    3. 整理成 manifest.csv (适合训练):
        image_path, label, prompt_text, captured_at
       其中 label 从 prompt 解析出 (按顺序的 4 个汉字)

    4. 输出 examples/.captcha_samples/manifest.csv
    5. 数据完整性检查: 列出没有 meta.json / 没有 screenshot.png 的坏样张

用法:
    # 默认扫 .captcha_samples
    python Examples/captcha_collect_clean.py

    # 自定义源目录
    python Examples/captcha_collect_clean.py --source /path/to/samples
"""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path


def parse_label_from_prompt(prompt: str) -> str:
    """从 prompt 提取 4 个名字片段,作为 label。

    样例:
        "请按顺序点击: 张三 李四 王五 赵六" -> "张三李四王五赵六"
        "按顺序依次点击【张三】【李四】【王五】【赵六】" -> "张三李四王五赵六"
        "依次点击 张三 李四 王五 赵六" -> "张三李四王五赵六"

    启发式:
        - 找 prompt 里所有连续 2-3 字中文片段(名字常见长度)
        - 选出现频率合理(这里粗略选"出现 1 次"的,过滤掉像"点击""顺序"
          这种**多次**出现的功能词)
        - 按 prompt 出现顺序取前 4 个拼接
    """
    if not prompt:
        return ""
    # 启发式: 中文名字通常 2 字(张三/李四)
    # 抠所有 2 字片段,按 prompt 出现顺序取前 4 个。
    candidates = re.findall(r"[一-鿿]{2,3}", prompt)
    seen = set()
    out = []
    for w in candidates:
        if len(w) == 2 and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) == 4:
            break
    if len(out) == 4:
        return "".join(out)
    # 退化: 2 字不够 4 个时混入 3 字
    for w in candidates:
        if len(w) == 3 and w not in seen:
            seen.add(w)
            out.append(w)
        if len(out) == 4:
            break
    return "".join(out)


def main():
    p = argparse.ArgumentParser(description="captcha 样张清洗 + 标注")
    p.add_argument("--source", default=str(Path(__file__).parent / ".captcha_samples"))
    p.add_argument("--output", default=None,
                   help="manifest 输出路径 (默认与 source 同目录 manifest.csv)")
    args = p.parse_args()

    src = Path(args.source)
    output = Path(args.output) if args.output else src / "manifest.csv"

    if not src.exists():
        print(f"[FAIL] {src} 不存在;先跑 captcha_collect.py 采一批样张")
        return 1

    items = []
    bad = []
    for sample_dir in sorted(src.iterdir()):
        if not sample_dir.is_dir() or not sample_dir.name.startswith("captcha_"):
            continue
        meta_file = sample_dir / "meta.json"
        png_file  = sample_dir / "screenshot.png"
        if not meta_file.exists():
            bad.append({"dir": sample_dir.name, "reason": "no meta.json"})
            continue
        if not png_file.exists():
            bad.append({"dir": sample_dir.name, "reason": "no screenshot.png"})
            continue

        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        label = parse_label_from_prompt(meta.get("promptText", ""))
        if not label:
            bad.append({"dir": sample_dir.name, "reason": "no label in prompt"})

        items.append({
            "image_path":   str(png_file.resolve()),
            "label":        label,
            "prompt_text":  (meta.get("promptText") or "")[:200],
            "captured_at":  meta.get("capturedAt", ""),
            "url":          meta.get("url", ""),
            "selector":     meta.get("selector", ""),
        })

    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "image_path", "label", "prompt_text", "captured_at", "url", "selector",
        ])
        writer.writeheader()
        for item in items:
            writer.writerow(item)

    print(f"[OK] 共 {len(items)} 条样张写到 {output}")
    if bad:
        print(f"[WARN] {len(bad)} 个坏样张:")
        for b in bad:
            print(f"       {b['dir']}: {b['reason']}")

    labels = Counter(item["label"] for item in items)
    print()
    print("[label 分布(前 10)]")
    for label, count in labels.most_common(10):
        print(f"  {count:3d}  {label}")

    print()
    print(f"[manifest] {output}")
    print(f"[下一步]")
    print(f"  把这个 csv 给 captcha_solver_train.py -- 训练 PaddleOCR / ddddocr 模型")
    print(f"  训练数据结构: image_path + label (4 个汉字的拼接)")


if __name__ == "__main__":
    main()
