#!/usr/bin/env python3
"""
Profile Manager CLI — 交互式管理 Browser Profiles

用法：
    python profile_manager.py list
    python profile_manager.py create <profile_id> [--name NAME] [--fingerprint-type stable|random]
    python profile_manager.py delete <profile_id> [--no-wipe]
    python profile_manager.py warmup <profile_id> [--ntp/--no-ntp]
    python profile_manager.py export <profile_id> [--output FILE]
    python profile_manager.py import <file>
"""

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional, List

import click

from Core.Profile.store import ProfileStore
from Core.Profile.profile import Profile, ProfileStatus
from Core.Profile.orchestrator import BrowserOrchestrator


# ─── Click Group ────────────────────────────────────────────────────────────

@click.group(invoke_without_command=True)
@click.option("--base-dir", type=click.Path(file_okay=False, dir_okay=True), default=None,
              help="Profile 存储根目录（默认 ~/.cache/webauto/profiles）")
@click.pass_context
def cli(ctx, base_dir):
    """WebAuto Profile Manager — 增删改查 + warmup"""
    # 初始化 store 并通过 context 传递给所有子命令
    store = ProfileStore(base_dir=Path(base_dir) if base_dir else None)
    ctx.obj = {}
    ctx.obj["store"] = store

    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


# ─── Helpers ────────────────────────────────────────────────────────────────

def _print_profile_row(profiles: List[Profile]) -> None:
    """格式化打印 Profile 列表"""
    if not profiles:
        click.echo("  (no profiles found)")
        return

    header = f"  {'ID':<30} {'Name':<20} {'Status':<10} {'CanvasSeed':<12} {'Locale':<10}"
    click.echo(header)
    click.echo("  " + "-" * 85)

    for p in profiles:
        seed = str(p.fingerprint.canvas_seed) if p.fingerprint.canvas_seed else "—"
        click.echo(
            f"  {p.id:<30} {p.name[:18]:<20} {p.status.value:<10} "
            f"{seed:<12} {p.fingerprint.locale or '—':<10}"
        )


def _load_profile_or_exit(store: ProfileStore, profile_id: str) -> Profile:
    """加载 Profile，不存在则退出"""
    try:
        return store.get(profile_id)
    except FileNotFoundError:
        click.echo(f"Error: Profile '{profile_id}' not found.", err=True)
        sys.exit(1)


# ─── list ───────────────────────────────────────────────────────────────────

@cli.command("list")
@click.option("--verbose", "-v", is_flag=True, help="显示完整 fingerprint 信息")
@click.pass_context
def list_profiles(ctx, verbose):
    """列出所有 Profile（名称 + 状态 + canvas_seed）"""
    store: ProfileStore = ctx.obj["store"]
    profiles = store.list_all()

    if not profiles:
        click.echo("No profiles found.")
        return

    if verbose:
        for p in profiles:
            click.echo(f"\nProfile: {p.id}")
            click.echo(f"  Name:       {p.name}")
            click.echo(f"  Status:     {p.status.value}")
            click.echo(f"  CanvasSeed: {p.fingerprint.canvas_seed}")
            click.echo(f"  Locale:     {p.fingerprint.locale}")
            click.echo(f"  Timezone:   {p.fingerprint.timezone}")
            click.echo(f"  Screen:     {p.fingerprint.screen_resolution}")
            click.echo(f"  Tags:       {', '.join(p.tags) if p.tags else '—'}")
            click.echo(f"  LastUsed:   {p.last_used or 'never'}")
            click.echo(f"  Storage:    {p.storage_dir}")
    else:
        _print_profile_row(profiles)


# ─── create ─────────────────────────────────────────────────────────────────

@cli.command("create")
@click.argument("profile_id")
@click.option("--name", "-n", default=None, help="Profile 显示名称（默认同 profile_id）")
@click.option(
    "--fingerprint-type", "-f",
    type=click.Choice(["stable", "random"]),
    default="stable",
    help="fingerprint 类型：stable（固定 seed=0，便于排重）或 random（随机 seed）",
)
@click.option("--locale", "-l", default=None, help="浏览器 locale（如 zh-CN）")
@click.option("--timezone", "-z", default=None, help="时区（如 Asia/Shanghai）")
@click.option("--screen", "-s", default=None, help="分辨率（如 1920x1080）")
@click.pass_context
def create_profile(ctx, profile_id, name, fingerprint_type, locale, timezone, screen):
    """创建新 Profile"""
    store: ProfileStore = ctx.obj["store"]

    try:
        existing = store.get(profile_id)
    except FileNotFoundError:
        existing = None

    if existing is not None:
        click.echo(f"Error: Profile '{profile_id}' already exists.", err=True)
        sys.exit(1)

    # 构建 Profile
    profile = Profile(id=profile_id, name=name or profile_id)

    # fingerprint 类型
    if fingerprint_type == "stable":
        profile.fingerprint.canvas_seed = 0
    # random 保持默认值（Profile.__init__ 会自动生成）

    if locale:
        profile.fingerprint.locale = locale
    if timezone:
        profile.fingerprint.timezone = timezone
    if screen:
        try:
            w, h = map(int, screen.lower().split("x"))
            profile.fingerprint.screen_resolution = (w, h)
        except Exception:
            click.echo(f"Error: Invalid screen format '{screen}', use WxH (e.g. 1920x1080).", err=True)
            sys.exit(1)

    store.create(profile)
    click.echo(f"Created profile '{profile_id}' ({fingerprint_type} fingerprint).")


# ─── delete ──────────────────────────────────────────────────────────────────

@cli.command("delete")
@click.argument("profile_id")
@click.option("--no-wipe", is_flag=True, help="仅删除 Profile 配置，保留 storage 数据")
@click.pass_context
def delete_profile(ctx, profile_id, no_wipe):
    """删除 Profile（可选仅删除配置，保留 storage）"""
    store: ProfileStore = ctx.obj["store"]

    profile = store.get(profile_id)
    if profile is None:
        click.echo(f"Error: Profile '{profile_id}' not found.", err=True)
        sys.exit(1)

    wipe = not no_wipe
    store.delete(profile_id, wipe_storage=wipe)

    if wipe:
        click.echo(f"Deleted profile '{profile_id}' (including storage).")
    else:
        click.echo(f"Deleted profile '{profile_id}' config (storage kept).")


# ─── warmup ────────────────────────────────────────────────────────────────

@cli.command("warmup")
@click.argument("profile_id")
@click.option("--ntp/--no-ntp", default=True, help="是否启用 NTP 校时（默认启用）")
@click.option("--timeout", "-t", default=60, help="warmup 超时秒数")
@click.pass_context
def warmup_profile(ctx, profile_id, ntp, timeout):
    """预热指定 Profile（启动 BrowserContext）"""
    store: ProfileStore = ctx.obj["store"]
    profile = _load_profile_or_exit(store, profile_id)

    click.echo(f"Warming up profile '{profile_id}'...")

    async def _do_warmup():
        orch = BrowserOrchestrator(store=store, headless=True, max_concurrent=3)
        try:
            await asyncio.wait_for(orch.warmup([profile], ntp_sync=ntp), timeout=timeout)
            click.echo(f"Profile '{profile_id}' warmup complete.")
            return 0
        except asyncio.TimeoutError:
            click.echo(f"Warmup timed out after {timeout}s.", err=True)
            return 1
        except Exception as e:
            click.echo(f"Warmup failed: {e}", err=True)
            return 1
        finally:
            await orch.stop()

    exit_code = asyncio.run(_do_warmup())
    sys.exit(exit_code)


# ─── export ─────────────────────────────────────────────────────────────────

@cli.command("export")
@click.argument("profile_id")
@click.option("--output", "-o", type=click.Path(dir_okay=False), default=None, help="导出文件路径（默认 <profile_id>.json）")
@click.pass_context
def export_profile(ctx, profile_id, output):
    """导出一个 Profile 的完整配置（JSON）"""
    store: ProfileStore = ctx.obj["store"]
    profile = _load_profile_or_exit(store, profile_id)

    data = profile.to_dict()

    out_path = output or f"{profile_id}.json"
    Path(out_path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    click.echo(f"Exported '{profile_id}' to '{out_path}'.")


# ─── import ────────────────────────────────────────────────────────────────

@cli.command("import")
@click.argument("file", type=click.Path(exists=True, dir_okay=False))
@click.option("--id", "-i", default=None, help="强制使用新的 profile_id（默认用文件中的）")
@click.pass_context
def import_profile(ctx, file, id):
    """从 JSON 文件导入 Profile"""
    store: ProfileStore = ctx.obj["store"]

    try:
        data = json.loads(Path(file).read_text(encoding="utf-8"))
    except Exception as e:
        click.echo(f"Error reading JSON: {e}", err=True)
        sys.exit(1)

    new_id = id or data.get("id")
    if not new_id:
        click.echo("Error: No 'id' field in import file and --id not provided.", err=True)
        sys.exit(1)

    try:
        existing = store.get(new_id)
    except FileNotFoundError:
        existing = None

    if existing is not None:
        click.echo(f"Error: Profile '{new_id}' already exists.", err=True)
        sys.exit(1)

    # from_dict 内部已处理 fingerprint key，直接透传
    try:
        profile = Profile.from_dict(data)
    except Exception as e:
        click.echo(f"Error reconstructing profile: {e}", err=True)
        sys.exit(1)

    # 强制覆盖 id（支持 --id 重命名）
    profile.id = new_id

    store.create(profile)
    click.echo(f"Imported profile '{new_id}' from '{file}'.")


# ─── main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cli()  # Click auto-populates ctx.obj from @click.group options
