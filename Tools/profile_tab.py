"""Profile Tab — Gradio Tab 实现，供 profile_panel.py 和 webauto_web.py 共用。

不要直接 launch 此文件，用 profile_panel.py 或 webauto_web.py 启动。
"""
from __future__ import annotations

import asyncio
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from Core.Profile.profile import Profile, ProfileStatus
    from Core.Profile.store import ProfileStore
    from Core.Profile.pool import ProfilePool

import gradio as gr

from Core.Profile.profile import NetworkConfig, Profile, ProfileStatus
from Core.Profile.store import ProfileStore
from Core.Profile.pool import AcquireStrategy, ProfilePool
from Core.Profile.fingerprint_gen import (
    FingerprintGenerator,
    PLATFORM_MAP,
    UA_TEMPLATES,
)


# ─── 全局后端实例（与 profile_panel.py 共享）──────────────────────

_store: ProfileStore | None = None
_pool: ProfilePool | None = None


def _get_store() -> ProfileStore:
    global _store
    if _store is None:
        _store = ProfileStore()
    return _store


def _get_pool() -> ProfilePool:
    global _pool
    if _pool is None:
        _pool = ProfilePool(_get_store(), strategy=AcquireStrategy.LEAST_USED, max_concurrent=5)
    return _pool


# ─── 数据格式化 helpers ───────────────────────────────────────────

def _profile_status_emoji(status: ProfileStatus) -> str:
    return {
        ProfileStatus.READY: "🟢 READY",
        ProfileStatus.RUNNING: "🔵 RUNNING",
        ProfileStatus.COOLDOWN: "🟡 COOLDOWN",
        ProfileStatus.BANNED: "🔴 BANNED",
        ProfileStatus.ARCHIVED: "⚪ ARCHIVED",
    }.get(status, str(status))


def _profile_to_row(p: Profile) -> list[Any]:
    cooldown_str = ""
    if p.status == ProfileStatus.COOLDOWN and p.cooldown_until:
        remaining = max(0, p.cooldown_until - time.time())
        cooldown_str = f"{remaining:.0f}s"
    return [
        p.id,
        p.name,
        ",".join(p.tags) if p.tags else "",
        _profile_status_emoji(p.status),
        cooldown_str,
        p.network.proxy_url or "",
        p.fingerprint.user_agent[:40] + "..."
        if len(p.fingerprint.user_agent) > 40
        else p.fingerprint.user_agent,
    ]


def _profiles_to_rows(profiles: list[Profile]) -> list[list[Any]]:
    return [_profile_to_row(p) for p in profiles]


def _build_fingerprint_preview(p: Profile) -> str:
    fp = p.fingerprint
    return (
        f"**UA:**\n```\n{fp.user_agent}\n```\n"
        f"**Platform:** {fp.platform}\n"
        f"**Locale:** {fp.locale}\n"
        f"**Timezone:** {fp.timezone}\n"
        f"**Screen:** {fp.screen_resolution}\n"
        f"**Color Depth:** {fp.color_depth}\n"
        f"**Hardware Concurrency:** {fp.hardware_concurrency}\n"
        f"**Device Memory:** {fp.device_memory} GB\n"
        f"**WebGL Vendor:** {fp.webgl_vendor}\n"
        f"**WebGL Renderer:** {fp.webgl_renderer}\n"
        f"**Canvas Seed:** {fp.canvas_seed}\n"
        f"**Audio Seed:** {fp.audio_seed}\n"
        f"**Proxy:** {p.network.proxy_url or '(无)'}\n"
    )


# ─── Tab builder ─────────────────────────────────────────────────

def _run(coro):
    try:
        loop = asyncio.new_event_loop()
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def build_profile_tab() -> None:
    """
    在当前 Gradio Blocks 上下文中追加 Profile 管理 Tab。

    调用方式（在 Gradio with Block 内）:
        with gr.Tab("🔑 Profile"):
            build_profile_tab()
    """
    store = _get_store()
    pool = _get_pool()

    # ── Tab1: Profile 列表 + CRUD + 指纹预览 ─────────────────────

    gr.Markdown("### Profile 管理")

    with gr.Row():
        with gr.Column(scale=2):
            t1_refresh = gr.Button("🔄 刷新列表", variant="secondary")
            t1_table = gr.Dataframe(
                headers=[
                    "ID", "名称", "标签", "状态", "CD剩余",
                    "代理", "UA(截断)",
                ],
                datatype=["str"] * 7,
                value=_profiles_to_rows(store.list_all()),
                interactive=False,
                max_height=280,
            )

        with gr.Column(scale=1):
            t1_detail_md = gr.Markdown("**👆 点预览按钮，填入下方 ID 查看指纹详情**")
            t1_id_input = gr.Textbox(
                label="Profile ID（手动输入或从表格复制）",
                placeholder="e.g. a1b2c3d4",
            )
            t1_preview_btn = gr.Button("🔍 预览指纹", variant="secondary")

    # ── 创建 ─────────────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### ➕ 创建新 Profile")

    with gr.Row():
        with gr.Column():
            c_name = gr.Textbox(label="名称", placeholder="e.g. 主账号-US")
            c_tags = gr.Textbox(
                label="标签（逗号分隔）",
                placeholder="e.g. US, residential",
                value="default",
            )
            c_ua_type = gr.Dropdown(
                label="UA 类型",
                choices=list(UA_TEMPLATES.keys()),
                value="linux_chrome_120",
            )
            c_proxy = gr.Textbox(
                label="代理 URL（可选）",
                placeholder="http://user:***@host:port",
            )
            c_locale = gr.Textbox(label="Locale", value="en-US")
            c_timezone = gr.Textbox(label="Timezone", value="America/New_York")
            c_country = gr.Textbox(
                label="GeoIP Country（ISO）",
                placeholder="US",
            )
            c_btn = gr.Button("✅ 创建 Profile", variant="primary")

        with gr.Column():
            c_result = gr.Textbox(
                label="操作结果",
                interactive=False,
                lines=6,
            )

    # ── 编辑/删除 ─────────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### ✏️ 编辑 / 🗑️ 删除")

    with gr.Row():
        with gr.Column():
            e_id = gr.Textbox(label="Profile ID（要编辑/删除的）")
            e_name = gr.Textbox(label="新名称（不改留空）")
            e_tags = gr.Textbox(label="新标签（不改留空）")
            e_proxy = gr.Textbox(label="新代理 URL（不改留空）")
            with gr.Row():
                e_save = gr.Button("💾 保存修改", variant="primary")
                e_del = gr.Button("🗑️ 删除 Profile", variant="stop")
            e_result = gr.Textbox(
                label="操作结果",
                interactive=False,
                lines=4,
            )

    # ── 借/还池子 ─────────────────────────────────────────────

    gr.Markdown("---")
    gr.Markdown("### 📤 Profile 池（acquire / release）")
    gr.Markdown(
        "> 手动借出 Profile，用完后归还。支持超时自动归还。"
    )

    with gr.Row():
        with gr.Column():
            t2_refresh = gr.Button("🔄 刷新池状态", variant="secondary")
            t2_status = gr.JSON(
                value=pool.get_status(),
                label="池状态",
            )

        with gr.Column():
            t2_acq_profile = gr.Textbox(
                label="要借的 Profile ID（留空自动选）",
                placeholder="留空则按策略自动分配",
            )
            t2_acq_tag = gr.Textbox(
                label="Tag（sticky 策略用）",
                placeholder="e.g. grab-task",
            )
            t2_acq_timeout = gr.Number(
                label="超时（秒）",
                value=30.0,
                minimum=1,
                maximum=300,
            )
            t2_acq_btn = gr.Button("📤 Acquire（借出）", variant="primary")
            t2_acq_result = gr.Textbox(
                label="借出结果",
                interactive=False,
                lines=4,
            )

        with gr.Column():
            t2_rel_id = gr.Textbox(
                label="要归还的 Profile ID",
                placeholder="从上方借出结果的 ID",
            )
            t2_rel_cooldown = gr.Number(
                label="归还后 cooldown（秒，0=直接 READY）",
                value=0.0,
                minimum=0,
                maximum=3600,
            )
            t2_rel_btn = gr.Button("📥 Release（归还）", variant="primary")
            t2_rel_result = gr.Textbox(
                label="归还结果",
                interactive=False,
                lines=4,
            )

    gr.Markdown("---")
    gr.Markdown("### 📥 导入 / 📤 导出 JSON")

    with gr.Row():
        with gr.Column():
            t3_exp_id = gr.Textbox(
                label="要导出的 Profile ID（全部导出不填）",
                placeholder="留空导出所有",
            )
            t3_exp_btn = gr.Button("📤 导出 Profile", variant="primary")
            t3_exp_result = gr.File(label="导出的文件", file_count="single")

        with gr.Column():
            t3_imp_file = gr.File(
                label="导入 JSON 文件",
                file_count="single",
                file_types=[".json"],
            )
            t3_imp_new_id = gr.Textbox(
                label="新 Profile ID（不改留空，保持原 ID）",
                placeholder="e.g. new-profile-001",
            )
            t3_imp_btn = gr.Button("📥 导入 Profile", variant="primary")
            t3_imp_result = gr.Textbox(
                label="导入结果",
                interactive=False,
                lines=5,
            )

    t3_exp_all_btn = gr.Button(
        "📦 导出全部 Profile 为 JSON",
        variant="secondary",
    )
    t3_exp_all_result = gr.File(
        label="全部 Profile JSON",
        file_count="single",
    )

    # ═══════════════════════════════════════════════════════════════
    # 事件绑定
    # ═══════════════════════════════════════════════════════════════

    def _refresh_list():
        return _profiles_to_rows(store.list_all())

    def _preview_fingerprint(pid: str) -> str:
        if not pid.strip():
            return "**👆 填入上方 ID 后点预览按钮**"
        try:
            p = store.get(pid.strip())
            return _build_fingerprint_preview(p)
        except FileNotFoundError:
            return f"❌ Profile {pid} 不存在"

    def _do_create(
        name: str, tags_str: str, ua_type: str,
        proxy: str, locale: str, timezone: str, country: str,
    ) -> tuple[str, list]:
        if not name.strip():
            return "⚠️ 名称不能为空", _profiles_to_rows(store.list_all())
        tags = [t.strip() for t in tags_str.split(",") if t.strip()]
        ua_choices = UA_TEMPLATES.get(
            ua_type, UA_TEMPLATES["linux_chrome_120"],
        )
        gen = FingerprintGenerator()
        fp = gen.generate(template=ua_type)
        fp.user_agent = ua_choices[0]
        fp.platform = PLATFORM_MAP.get(ua_type, "Linux x86_64")
        fp.locale = locale
        fp.timezone = timezone
        net = NetworkConfig()
        if proxy.strip():
            net.proxy_url = proxy.strip()
        if country.strip():
            net.geoip_country = country.strip().upper()
        profile = Profile(
            name=name.strip(),
            tags=tags,
            fingerprint=fp,
            network=net,
        )
        try:
            store.create(profile)
            return f"✅ 创建成功: {profile.id}", _profiles_to_rows(store.list_all())
        except Exception as e:
            return f"❌ 创建失败: {e}", _profiles_to_rows(store.list_all())

    def _do_save(
        pid: str, new_name: str, new_tags: str, new_proxy: str,
    ) -> str:
        if not pid.strip():
            return "⚠️ Profile ID 不能为空"
        try:
            p = store.get(pid.strip())
        except FileNotFoundError:
            return f"❌ Profile {pid} 不存在"
        if new_name.strip():
            p.name = new_name.strip()
        if new_tags.strip():
            p.tags = [t.strip() for t in new_tags.split(",") if t.strip()]
        if new_proxy.strip():
            p.network.proxy_url = new_proxy.strip()
        try:
            store.save(p)
            return f"✅ 已保存: {p.id} ({p.name})"
        except Exception as e:
            return f"❌ 保存失败: {e}"

    def _do_delete(pid: str) -> str:
        if not pid.strip():
            return "⚠️ Profile ID 不能为空"
        try:
            store.delete(pid.strip())
            return f"✅ 已删除: {pid}"
        except FileNotFoundError:
            return f"❌ Profile {pid} 不存在"
        except Exception as e:
            return f"❌ 删除失败: {e}"

    async def _do_acquire_async(
        profile_id: str, tag: str, timeout: float,
    ):
        if profile_id.strip():
            try:
                p = store.get(profile_id.strip())
                p.status = ProfileStatus.RUNNING
                p.last_used = time.time()
                store.save(p)
                async with pool._lock:
                    pool._in_use[p.id] = time.time()
                return f"✅ 借出: {p.id} ({p.name})\n状态: {_profile_status_emoji(p.status)}"
            except FileNotFoundError:
                return f"❌ Profile {profile_id} 不存在"
            except Exception as e:
                return f"❌ 借出失败: {e}"
        kwargs: dict = {"timeout": timeout}
        if tag.strip():
            kwargs["tag"] = tag.strip()
        try:
            p = await pool.acquire(**kwargs)
            return (
                f"✅ 借出: {p.id} ({p.name})\n"
                f"状态: {_profile_status_emoji(p.status)}\n"
                f"代理: {p.network.proxy_url or '(无)'}"
            )
        except asyncio.TimeoutError:
            return f"⏰ 等待 {timeout}s 超时，无可用 Profile"
        except Exception as e:
            return f"❌ 借出失败: {e}"

    def _do_acquire(
        profile_id: str, tag: str, timeout: float,
    ) -> str:
        return _run(_do_acquire_async(profile_id, tag, timeout))

    async def _do_release_async(profile_id: str, cooldown: float):
        if not profile_id.strip():
            return "⚠️ Profile ID 不能为空"
        try:
            p = store.get(profile_id.strip())
        except FileNotFoundError:
            return f"❌ Profile {profile_id} 不存在"
        try:
            await pool.release(p, cooldown=cooldown)
            return f"✅ 已归还: {p.id}，cooldown={cooldown}s"
        except Exception as e:
            return f"❌ 归还失败: {e}"

    def _do_release(profile_id: str, cooldown: float) -> str:
        return _run(_do_release_async(profile_id, cooldown))

    def _do_export_single(export_id: str) -> str:
        if not export_id.strip():
            return "⚠️ 请填写 Profile ID"
        try:
            p = store.get(export_id.strip())
            import json as _json
            data = p.to_dict()
            data["_status_str"] = p.status.value
            tmp = Path(tempfile.gettempdir()) / f"profile_{p.id}.json"
            tmp.write_text(
                _json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            return str(tmp)
        except FileNotFoundError:
            return f"❌ Profile {export_id} 不存在"
        except Exception as e:
            return f"❌ 导出失败: {e}"

    def _do_export_all() -> str:
        import json as _json
        profiles = store.list_all()
        data = []
        for p in profiles:
            pd = p.to_dict()
            pd["_status_str"] = p.status.value
            data.append(pd)
        tmp = Path(tempfile.gettempdir()) / "all_profiles.json"
        tmp.write_text(
            _json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return str(tmp)

    def _do_import(file_path: str, new_id: str) -> str:
        import json as _json
        if not file_path:
            return "⚠️ 请先上传 JSON 文件"
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = _json.load(f)
            items = [content] if isinstance(content, dict) else content
            imported = []
            for item in items:
                if "_status_str" in item:
                    item["status"] = item["_status_str"]
                profile = Profile.from_dict(item)
                if new_id.strip():
                    profile.id = new_id.strip()
                store.create(profile)
                imported.append(profile.id)
            return f"✅ 导入成功: {', '.join(imported)}"
        except Exception as e:
            return f"❌ 导入失败: {e}"

    # bind events
    t1_refresh.click(fn=_refresh_list, outputs=t1_table)

    t1_preview_btn.click(
        fn=_preview_fingerprint,
        inputs=[t1_id_input],
        outputs=[t1_detail_md],
    )

    c_btn.click(
        fn=_do_create,
        inputs=[c_name, c_tags, c_ua_type, c_proxy,
                c_locale, c_timezone, c_country],
        outputs=[c_result, t1_table],
    )

    e_save.click(
        fn=_do_save,
        inputs=[e_id, e_name, e_tags, e_proxy],
        outputs=[e_result],
    )
    e_del.click(
        fn=_do_delete,
        inputs=[e_id],
        outputs=[e_result],
    )

    t2_refresh.click(fn=lambda: pool.get_status(), outputs=t2_status)

    t2_acq_btn.click(
        fn=_do_acquire,
        inputs=[t2_acq_profile, t2_acq_tag, t2_acq_timeout],
        outputs=[t2_acq_result],
    )
    t2_rel_btn.click(
        fn=_do_release,
        inputs=[t2_rel_id, t2_rel_cooldown],
        outputs=[t2_rel_result],
    )

    t3_exp_btn.click(
        fn=_do_export_single,
        inputs=[t3_exp_id],
        outputs=[t3_exp_result],
    )
    t3_exp_all_btn.click(fn=_do_export_all, outputs=[t3_exp_all_result])
    t3_imp_btn.click(
        fn=_do_import,
        inputs=[t3_imp_file, t3_imp_new_id],
        outputs=[t3_imp_result],
    )
