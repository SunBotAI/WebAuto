"""
Core/Profile/store.py — Profile 本地持久化

~/.cache/webauto/profiles/<profile_id>/
├── config.yaml   # Profile 配置（YAML）
├── fingerprint.json  # 指纹数据（机器可读）
├── local-storage.json # localStorage / sessionStorage
├── user-data/    # Chromium User Data Directory
└── meta.json     # 标签/创建时间/最后使用/状态
"""

from __future__ import annotations

import json
import yaml
import shutil
from pathlib import Path
from typing import List, Optional, Dict, Any
from datetime import datetime

from .profile import Profile, ProfileStatus


class ProfileStore:
    """Profile 本地持久化（CRUD + import/export）"""

    DEFAULT_DIR = Path.home() / ".cache" / "webauto" / "profiles"

    def __init__(self, base_dir: Optional[Path] = None):
        self.base_dir = base_dir or self.DEFAULT_DIR
        self.base_dir.mkdir(parents=True, exist_ok=True)

    # ─── 路径 helpers ──────────────────────────────────────────

    def _profile_dir(self, profile_id: str) -> Path:
        return self.base_dir / profile_id

    def _config_path(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "config.yaml"

    def _fingerprint_path(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "fingerprint.json"

    def _meta_path(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "meta.json"

    def _user_data_dir(self, profile_id: str) -> Path:
        return self._profile_dir(profile_id) / "user-data"

    # ─── CRUD ─────────────────────────────────────────────────

    def create(self, profile: Profile) -> Path:
        """
        创建 Profile：分配 storage_dir，写 config.yaml + fingerprint.json + meta.json。
        不创建 user-data 目录（BrowserOrchestrator 启动时按需创建）。
        """
        if not profile.storage_dir:
            profile.storage_dir = self._profile_dir(profile.id)

        pdir = self._profile_dir(profile.id)
        pdir.mkdir(parents=True, exist_ok=True)

        # config.yaml
        config_data = profile.to_dict()
        with open(self._config_path(profile.id), "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)

        # fingerprint.json（单独存储，便于快速读取）
        with open(self._fingerprint_path(profile.id), "w", encoding="utf-8") as f:
            json.dump(profile.fingerprint.to_dict(), f, indent=2, ensure_ascii=False)

        # meta.json
        meta = {
            "id": profile.id,
            "name": profile.name,
            "tags": profile.tags,
            "created_at": datetime.now().isoformat(),
            "last_used": None,
            "status": profile.status.value,
        }
        with open(self._meta_path(profile.id), "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        return pdir

    def get(self, profile_id: str) -> Profile:
        """读取 Profile 配置（不加载 user-data）"""
        config_path = self._config_path(profile_id)
        if not config_path.exists():
            raise FileNotFoundError(f"Profile not found: {profile_id}")

        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        return Profile.from_dict(data)

    def list_all(self) -> List[Profile]:
        """列出所有 Profile"""
        profiles = []
        if not self.base_dir.exists():
            return profiles

        for subdir in self.base_dir.iterdir():
            if subdir.is_dir() and (subdir / "config.yaml").exists():
                try:
                    profiles.append(self.get(subdir.name))
                except Exception:
                    continue
        return profiles

    def save(self, profile: Profile) -> None:
        """
        更新 Profile 配置（不重启浏览器）。
        仅更新 config.yaml + meta.json，不碰 user-data。
        """
        # 更新 meta
        meta_path = self._meta_path(profile.id)
        if meta_path.exists():
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
        else:
            meta = {"id": profile.id, "created_at": datetime.now().isoformat()}

        meta["last_used"] = profile.last_used
        meta["status"] = profile.status.value
        meta["tags"] = profile.tags
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        # 更新 config.yaml
        config_path = self._config_path(profile.id)
        config_data = profile.to_dict()
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.dump(config_data, f, allow_unicode=True, default_flow_style=False)

        # 更新 fingerprint.json
        with open(self._fingerprint_path(profile.id), "w", encoding="utf-8") as f:
            json.dump(profile.fingerprint.to_dict(), f, indent=2, ensure_ascii=False)

    def delete(self, profile_id: str, *, wipe_storage: bool = True) -> None:
        """
        删除 Profile。
        wipe_storage=True: 连带删除 user-data（不可恢复）
        wipe_storage=False: 保留 user-data（用于备份/迁移）
        """
        pdir = self._profile_dir(profile_id)
        if not pdir.exists():
            return

        if wipe_storage:
            shutil.rmtree(pdir)
        else:
            # 只删 config，不碰 user-data
            for f in [self._config_path(profile_id),
                      self._fingerprint_path(profile_id),
                      self._meta_path(profile_id)]:
                f.unlink(missing_ok=True)

    def get_or_create(self, profile_id: str, **defaults) -> Profile:
        """便捷方法：存在则读，不存在则创建"""
        try:
            return self.get(profile_id)
        except FileNotFoundError:
            profile = Profile(id=profile_id, name=profile_id, **defaults)
            self.create(profile)
            return profile

    # ─── Import / Export ──────────────────────────────────────

    def export(self, profile_id: str, target_zip: Path) -> None:
        """
        导出 Profile 包（含 config + fingerprint + user-data）为 .zip。
        用于跨机器迁移。
        """
        import zipfile

        pdir = self._profile_dir(profile_id)
        if not pdir.exists():
            raise FileNotFoundError(f"Profile not found: {profile_id}")

        with zipfile.ZipFile(target_zip, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in pdir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(pdir.parent)
                    zf.write(file_path, arcname)

    def import_(self, source_zip: Path, new_id: Optional[str] = None) -> Profile:
        """
        从 .zip 导入 Profile 包。
        new_id=None: 保持原 profile_id；new_id: 分配新 profile_id
        """
        import zipfile

        with zipfile.ZipFile(source_zip, "r") as zf:
            # 读 config 确定原 id
            config_raw = zf.read("profiles/*/config.yaml").decode("utf-8")
            import re
            match = re.search(r"profiles/([^/]+)/", list(zf.namelist())[0])
            if not match:
                raise ValueError("Invalid profile zip format")
            old_id = match.group(1)
            target_id = new_id or old_id

            # 解压到新目录
            target_dir = self._profile_dir(target_id)
            target_dir.mkdir(parents=True, exist_ok=True)

            for name in zf.namelist():
                if name.endswith("/"):
                    continue
                # 重命名路径中的旧 id → 新 id
                new_name = name.replace(f"profiles/{old_id}/", f"profiles/{target_id}/", 1)
                target_path = self.base_dir.parent / new_name
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(name) as src, open(target_path, "wb") as dst:
                    dst.write(src.read())

        profile = self.get(target_id)
        if new_id and target_id != old_id:
            profile.id = target_id
            profile.name = target_id
            self.save(profile)
        return profile
