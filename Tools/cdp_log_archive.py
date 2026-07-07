r"""CDP log archive: 调试会话归档工具。

动机:
    一次调试,你能抓到:
      - cdp_smoke 输出 (CDP fingerprint 基线)
      - cdp_stealth_apply 跑 9 项的 score
      - cdp_token_extract 抽到的 cookie JSON
      - cdp_inspect 持续 N 秒抓到的所有 API 请求 + body
      - 你的代码当时跑到的截图、console log

    这些放在不同目录不同文件名里,调试过 2-3 次就不知道哪一次是真的。
    本工具把一次调试会话打成一个包:
      调试目录/.sessions/<时间戳>/
        meta.json                - 调试元数据
        smoke.txt                - cdp_smoke 的输出
        stealth.json             - cdp_stealth_apply 的输出
        session.json             - 抽到的 cookie(注意: 含 token, 不要 commit)
        network/                 - cdp_inspect 抓的每个请求
        notes.md                 - 你自己写两句(手动)

用法:
    # 初始化一个会话(打基础信息)
    .venv/bin/python Tools/cdp_log_archive.py init --label "调试 v2.5-preview"

    # 打包当前会话到 zip(方便分享/归档)
    .venv/bin/python Tools/cdp_log_archive.py pack --label "调试 v2.5-preview"

    # 列已有会话
    .venv/bin/python Tools/cdp_log_archive.py list

    # 比对两次会话(stealth score diff、network 数量 diff)
    .venv/bin/python Tools/cdp_log_archive.py diff <label1> <label2>
"""
import argparse
import json
import shutil
import subprocess
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent.parent
DEFAULT_ROOT = ROOT / "logs" / "cdp_sessions"


def _ts() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _session_dir(label: str, root: Path = DEFAULT_ROOT) -> Path:
    safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    return root / f"{_ts()}_{safe_label}"


def cmd_init(args):
    target = _session_dir(args.label)
    target.mkdir(parents=True, exist_ok=True)
    meta = {
        "label":     args.label,
        "startTs":   _ts(),
        "gitInfo":   _git_info(),
        "antiDetectConfig": _anti_detect_info(),
    }
    (target / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (target / "notes.md").write_text(
        f"# 调试会话 {args.label}\n\n创建于 {meta['startTs']}\n\n"
        "## 调试目标\n\n(写一下你这次想验证什么)\n\n"
        "## 结果\n\n- [ ] 通过 ...\n- [ ] 通过 ...\n",
        encoding="utf-8",
    )
    print(f"[OK] 会话目录: {target}")
    print(f"     meta.json  +  notes.md 已写")
    print()
    print(f"     接下来跑 cdp_smoke / cdp_stealth_apply / cdp_token_extract 时, ")
    print(f"     把 --output / --save-dir 指向:")
    print(f"        {target}/")
    print()
    print(f"     或者用 --session-label 跑现有的几个 cdp_xxx 工具")
    print(f"     它们会自动归到这里。")
    return 0


def cmd_pack(args):
    base = _find_session(args.label)
    if not base:
        return 1
    zip_path = base.with_suffix(".zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in base.rglob("*"):
            if p.is_file():
                zf.write(p, p.relative_to(base.parent))
    print(f"[OK] 打包: {zip_path}  ({zip_path.stat().st_size // 1024} KB)")
    print(f"     这个 zip 含 token/cookie,等同于明文密码:")
    print(f"     不要发到 IM、不要 commit。")
    return 0


def cmd_list(args):
    root = DEFAULT_ROOT
    if not root.exists():
        print(f"[INFO] 还没会话目录: {root}")
        return 0
    sessions = sorted(root.iterdir(), key=lambda p: p.name, reverse=True)
    if not sessions:
        print(f"[INFO] {root} 下没有会话")
        return 0
    print(f"=== 会话列表 ({len(sessions)} 个) ===")
    for s in sessions[:30]:  # 最多列 30 个
        if s.is_dir():
            meta_file = s / "meta.json"
            note = ""
            if meta_file.exists():
                m = json.loads(meta_file.read_text(encoding="utf-8"))
                note = f" [{m.get('gitInfo',{}).get('sha7','?')}]"
            files = [p.name for p in s.iterdir() if p.is_file()]
            print(f"  {s.name}{note}  含 {len(files)} 文件")
    return 0


def cmd_diff(args):
    a = _find_session(args.label_a)
    b = _find_session(args.label_b)
    if not (a and b):
        return 1
    print(f"=== diff: {a.name}  vs  {b.name} ===")
    # stealth score 对比
    score_a = _read_score(a / "stealth.json")
    score_b = _read_score(b / "stealth.json")
    if score_a and score_b:
        print(f"  stealth score : {score_a['score']}/{score_a['total']}"
              f"  →  {score_b['score']}/{score_b['total']}")
    # network 请求数对比
    nw_a = list((a / "network").glob("*.json")) if (a / "network").exists() else []
    nw_b = list((b / "network").glob("*.json")) if (b / "network").exists() else []
    print(f"  network 请求 : {len(nw_a)}  →  {len(nw_b)}")
    # 用了哪些 tools
    ta = set(p.name for p in a.iterdir() if p.is_file())
    tb = set(p.name for p in b.iterdir() if p.is_file())
    only_a = ta - tb
    only_b = tb - ta
    if only_a: print(f"  A 独有: {only_a}")
    if only_b: print(f"  B 独有: {only_b}")
    return 0


def _find_session(label: str, root: Path = DEFAULT_ROOT) -> Path | None:
    if not root.exists():
        print(f"[ERR] {root} 不存在"); return None
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)
    matches = sorted(root.glob(f"*_{safe}"), reverse=True)
    if not matches:
        print(f"[ERR] 找不到 label='{label}' 的会话(glob: *_{safe})")
        return None
    return matches[0]


def _git_info() -> dict:
    """轻量读 git HEAD sha(此项目可能因环境拿不到,容错)。"""
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ROOT), stderr=subprocess.DEVNULL, timeout=2,
        ).decode().strip()
        return {"sha7": out}
    except Exception:
        return {}


def _anti_detect_info() -> dict:
    try:
        from Core.AntiDetect import AntiDetectConfig
        return {
            "defaultConfig": {f: getattr(AntiDetectConfig(), f)
                              for f in AntiDetectConfig.__dataclass_fields__
                              if not f.startswith("_")},
        }
    except Exception as e:
        return {"error": str(e)}


def _read_score(path: Path) -> dict | None:
    if not path.exists(): return None
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
        return d.get("score") if isinstance(d, dict) else None
    except Exception:
        return None


def main():
    parser = argparse.ArgumentParser(description="CDP log archive")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="开新会话(打 meta)")
    p_init.add_argument("--label", required=True, help="会话标签")
    p_init.set_defaults(func=cmd_init)

    p_pack = sub.add_parser("pack", help="打包会话到 zip")
    p_pack.add_argument("--label", required=True)
    p_pack.set_defaults(func=cmd_pack)

    p_list = sub.add_parser("list", help="列已有会话")
    p_list.set_defaults(func=cmd_list)

    p_diff = sub.add_parser("diff", help="比对两个会话")
    p_diff.add_argument("label_a")
    p_diff.add_argument("label_b")
    p_diff.set_defaults(func=cmd_diff)

    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
