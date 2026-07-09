"""
Tests/test_profile_manager.py — FINGERPRINT-008 CLI 单元测试

通过 subprocess 调用真实 CLI 脚本，验证文件系统结果。
避免所有 mock/patch 的跨进程边界问题。
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
PROFILE_MANAGER = ROOT / "profile_manager.py"


# ─── CLI runner (subprocess) ───────────────────────────────────────────────

def run_cli(args, base_dir=None):
    """
    通过 subprocess 调用真实的 profile_manager.py。
    返回 (exit_code, stdout, stderr)。
    """
    cmd = [sys.executable, str(PROFILE_MANAGER)]
    if base_dir:
        cmd += ["--base-dir", base_dir]
    cmd += args

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=15,
        # Use explicit cwd to avoid CWD issues
        cwd=str(ROOT),
    )
    return result.returncode, result.stdout, result.stderr


# ─── Shared tmpdir helper ───────────────────────────────────────────────────

def with_tmpdir(fn):
    """在临时目录中执行 fn(tmpdir)，确保断言在目录删除前完成"""
    td = tempfile.mkdtemp(prefix="pm_test_")
    try:
        fn(td)
    finally:
        shutil.rmtree(td, ignore_errors=True)


# ─── list ─────────────────────────────────────────────────────────────────

class TestListCommand:
    def test_list_empty(self):
        """无 Profile 时 list 显示空"""
        with_tmpdir(lambda td: _assert(
            run_cli(["list"], base_dir=td),
            code=0,
            contains=["No profiles found"],  # exact case
        ))

    def test_list_one_profile(self):
        """有一个 Profile 时 list 显示完整行"""
        def run(td):
            run_cli(["create", "test-list-1", "--name", "Test One"], base_dir=td)
            _assert(run_cli(["list"], base_dir=td), code=0, contains=["test-list-1", "Test One"])
        with_tmpdir(run)

    def test_list_verbose(self):
        """list --verbose 显示 fingerprint 详情"""
        def run(td):
            run_cli(["create", "verbose-test", "--name", "Verbose Test", "--locale", "zh-CN"], base_dir=td)
            _assert(run_cli(["list", "--verbose"], base_dir=td), code=0, contains=["verbose-test", "CanvasSeed:", "zh-CN"])
        with_tmpdir(run)


# ─── create ────────────────────────────────────────────────────────────────

class TestCreateCommand:
    def test_create_success(self):
        """create 新 Profile 成功，文件写入正确"""
        with_tmpdir(lambda td: _create_and_verify(
            td,
            profile_id="new-profile",
            args=["--name", "New Profile", "--fingerprint-type", "stable"],
            assertions={
                "config_name": "New Profile",
                "canvas_seed": 0,  # stable type
            },
        ))

    def test_create_duplicate_error(self):
        """create 已存在的 Profile 报错"""
        def run(td):
            run_cli(["create", "dup-id"], base_dir=td)  # first create succeeds
            _assert(run_cli(["create", "dup-id"], base_dir=td), fails=True, contains_err=["already exists"])
        with_tmpdir(run)

    def test_create_with_locale_timezone_screen(self):
        """create 指定 locale / timezone / screen"""
        with_tmpdir(lambda td: _create_and_verify(
            td,
            profile_id="custom-fp",
            args=["--locale", "en-US", "--timezone", "America/New_York", "--screen", "2560x1440"],
            assertions={
                "locale": "en-US",
                "timezone": "America/New_York",
                "screen_resolution": [2560, 1440],
            },
        ))

    def test_create_invalid_screen_format(self):
        """create --screen 格式错误报错"""
        with_tmpdir(lambda td: _assert(
            run_cli(["create", "bad-screen", "--screen", "invalid"], base_dir=td),
            fails=True,
            contains_err=["Invalid screen format"],
        ))


# ─── delete ────────────────────────────────────────────────────────────────

class TestDeleteCommand:
    def test_delete_success(self):
        """delete 成功删除 Profile"""
        with_tmpdir(lambda td: _delete_and_verify(
            td,
            profile_id="to-delete",
            wipe=True,
        ))

    def test_delete_no_wipe(self):
        """delete --no-wipe 仅删除配置，保留 storage"""
        def run(td):
            # 创建 Profile 后在 storage 目录放文件
            run_cli(["create", "keep-storage"], base_dir=td)
            storage_dir = Path(td) / "keep-storage"
            storage_dir.mkdir(parents=True, exist_ok=True)
            marker = storage_dir / "somefile.txt"
            marker.write_text("keep me")

            code, out, err = run_cli(["delete", "keep-storage", "--no-wipe"], base_dir=td)
            assert code == 0, f"exit={code} err={err} out={out}"
            assert "storage kept" in out, f"Expected 'storage kept' in output: {out}"
            assert marker.exists(), f"Marker file should exist: {marker}"
        with_tmpdir(run)

    def test_delete_not_found(self):
        """delete 不存在的 Profile 报错"""
        with_tmpdir(lambda td: _assert(
            run_cli(["delete", "non-existent"], base_dir=td),
            fails=True,
            contains_err=["not found"],
        ))


# ─── export ───────────────────────────────────────────────────────────────

class TestExportCommand:
    def test_export_success(self):
        """export 导出 JSON 文件"""
        with_tmpdir(lambda td: _export_and_verify(td))

    def test_export_not_found(self):
        """export 不存在的 Profile 报错"""
        with_tmpdir(lambda td: _assert(
            run_cli(["export", "non-existent"], base_dir=td),
            fails=True,
            contains_err=["not found"],
        ))


# ─── import ───────────────────────────────────────────────────────────────

class TestImportCommand:
    def test_import_success(self):
        """import 从 JSON 导入新 Profile"""
        with_tmpdir(lambda td: _import_and_verify(td))

    def test_import_with_new_id(self):
        """import --id 强制使用新 ID"""
        def run(td):
            # 创建 Profile 并导出
            run_cli(["create", "source-profile"], base_dir=td)
            src_file = Path(td) / "source.json"
            run_cli(["export", "source-profile", "--output", str(src_file)], base_dir=td)

            # 用新 ID 导入
            code, out, err = run_cli([
                "import", str(src_file), "--id", "new-imported-id",
            ], base_dir=td)

            assert code == 0, f"exit={code} err={err} out={out}"
            assert (Path(td) / "source-profile").exists()
            assert (Path(td) / "new-imported-id").exists()

        with_tmpdir(run)

    def test_import_duplicate_error(self):
        """import 已存在的 Profile 报错"""
        def run(td):
            run_cli(["create", "exists-profile"], base_dir=td)
            export_file = Path(td) / "exists.json"
            run_cli(["export", "exists-profile", "--output", str(export_file)], base_dir=td)
            _assert(run_cli(["import", str(export_file)], base_dir=td), fails=True, contains_err=["already exists"])
        with_tmpdir(run)


# ─── warmup ──────────────────────────────────────────────────────────────

class TestWarmupCommand:
    def test_warmup_profile_not_found(self):
        """warmup 不存在的 Profile 报错"""
        with_tmpdir(lambda td: _assert(
            run_cli(["warmup", "non-existent"], base_dir=td),
            fails=True,
            contains_err=["not found"],
        ))


# ─── help ────────────────────────────────────────────────────────────────

class TestCliHelp:
    def test_help_output(self):
        """--help 显示所有命令"""
        with_tmpdir(lambda td: _assert(
            run_cli(["--help"], base_dir=td),
            code=0,
            contains=["list", "create", "delete", "warmup", "export", "import"],
        ))

    def test_subcommand_help(self):
        """子命令 --help 显示详细用法"""
        with_tmpdir(lambda td: _assert(
            run_cli(["create", "--help"], base_dir=td),
            code=0,
            contains=["--fingerprint-type", "--locale"],
        ))


# ─── Helper functions ───────────────────────────────────────────────────────

def _assert(result, code=None, fails=None, contains=None, contains_err=None, pre_cmds=None):
    """通用断言助手"""
    if pre_cmds:
        for cmd in pre_cmds:
            if isinstance(cmd, tuple):
                c, o, e = cmd
            else:
                c, o, e = cmd()
            # pre_cmds may fail (e.g. duplicate create), don't assert on them
    exit_code, stdout, stderr = result
    combined = stdout + "\n" + stderr

    if fails:
        assert exit_code != 0, f"Expected non-zero exit, got {exit_code}: out={stdout} err={stderr}"
        if contains_err:
            found = any(seg in combined for seg in contains_err)
            assert found, f"Expected one of {contains_err} in output: {combined}"
    else:
        if code is not None:
            assert exit_code == code, f"exit={exit_code} out={stdout} err={stderr}"
        if contains:
            found = all(seg in combined for seg in contains)
            assert found, f"Expected all of {contains} in output: {combined}"


def _export_profile(td, profile_id):
    """导出 Profile 到 td 目录"""
    out_file = Path(td) / f"{profile_id}.json"
    run_cli(["export", profile_id, "--output", str(out_file)], base_dir=td)
    return out_file


def _create_and_verify(td, profile_id, args, assertions):
    """创建 Profile 并验证文件系统"""
    code, out, err = run_cli(["create", profile_id] + args, base_dir=td)
    assert code == 0, f"exit={code} err={err} out={out}"
    assert "Created profile" in out

    profile_dir = Path(td) / profile_id
    assert profile_dir.exists(), f"Profile dir not created: {profile_dir}"

    if "config_name" in assertions:
        import yaml
        cfg = yaml.safe_load((profile_dir / "config.yaml").read_text())
        assert cfg["name"] == assertions["config_name"]

    fp = json.loads((profile_dir / "fingerprint.json").read_text())
    for key, expected in assertions.items():
        if key == "config_name":
            continue
        actual = fp.get(key)
        assert actual == expected, f"fingerprint.{key}: expected {expected}, got {actual}"


def _delete_and_verify(td, profile_id, wipe):
    """删除 Profile 并验证"""
    run_cli(["create", profile_id], base_dir=td)
    profile_dir = Path(td) / profile_id
    marker = profile_dir / "marker.txt"
    profile_dir.mkdir(parents=True, exist_ok=True)
    marker.write_text("marker")

    suffix = "" if wipe else " --no-wipe"
    code, out, err = run_cli([f"delete{suffix}", profile_id], base_dir=td)
    assert code == 0, f"exit={code} err={err} out={out}"

    if wipe:
        assert not profile_dir.exists(), f"Profile dir should be deleted: {profile_dir}"
    else:
        assert marker.exists(), f"Marker should exist with --no-wipe: {marker}"


def _export_and_verify(td):
    """导出并验证"""
    run_cli(["create", "export-test"], base_dir=td)
    out_file = Path(td) / "exported.json"
    code, out, err = run_cli([
        "export", "export-test", "--output", str(out_file),
    ], base_dir=td)
    assert code == 0, f"exit={code} err={err} out={out}"
    assert out_file.exists(), f"Export file not created: {out_file}"
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data["id"] == "export-test"


def _import_and_verify(td):
    """导入并验证"""
    # 创建 Profile 并导出
    run_cli(["create", "import-src", "--name", "Import Source"], base_dir=td)
    src_file = Path(td) / "import_src.json"
    run_cli(["export", "import-src", "--output", str(src_file)], base_dir=td)

    # 删除后重新导入
    run_cli(["delete", "import-src"], base_dir=td)
    code, out, err = run_cli(["import", str(src_file)], base_dir=td)
    assert code == 0, f"exit={code} err={err} out={out}"
    assert "Imported profile" in out
    assert (Path(td) / "import-src").exists()
