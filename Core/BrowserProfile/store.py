"""ProfileStore: 把 BrowserProfile 持久化到本地目录。

默认目录: ~/.cache/webauto/profiles/<profile_id>.json
可由 WEBAUTO_PROFILE_DIR 环境变量覆盖。

读写都用原子文件操作(write-temp-then-rename)避免半写文件被另一个进程读到。
"""
import json
import os
import random
import tempfile
import time
import warnings
from pathlib import Path
from typing import Optional

from .profile import BrowserProfile, HardwareConsistent, ViewportConfig


_DEFAULT_DIRNAME = ".cache/webauto/profiles"


def _store_dir() -> Path:
    env = os.environ.get("WEBAUTO_PROFILE_DIR")
    if env:
        return Path(env)
    home = Path.home()
    return home / _DEFAULT_DIRNAME


class ProfileStore:
    """文件系统版的 BrowserProfile 持久化。"""
    def __init__(self, root: Optional[Path] = None):
        self.root = Path(root) if root else _store_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, profile_id: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in profile_id)
        return self.root / f"{safe}.json"

    def exists(self, profile_id: str) -> bool:
        return self._path(profile_id).exists()

    def load(self, profile_id: str) -> Optional[BrowserProfile]:
        path = self._path(profile_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BrowserProfile.from_dict(data)
        except Exception as e:
            warnings.warn(f"ProfileStore.load({profile_id}) 失败: {e}", stacklevel=1)
            return None

    def save(self, profile: BrowserProfile) -> None:
        path = self._path(profile.profile_id)
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        if profile.created_at is None:
            profile.created_at = now
        profile.updated_at = now
        # 原子写
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=str(path.parent),
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as tmp:
            tmp_name = tmp.name
            json.dump(profile.to_dict(), tmp, ensure_ascii=False, indent=2)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)

    def list_ids(self) -> list[str]:
        ids = []
        for p in self.root.glob("*.json"):
            if not p.name.startswith("."):
                ids.append(p.stem)
        return sorted(ids)

    def get_or_create(
        self,
        profile_id: str,
        seed: Optional[int] = None,
        label: str = "",
    ) -> BrowserProfile:
        """读 profile_id.json;不存在就 new 一个,种子随机。
        
        seed 参数可选:测试时指定固定 seed 让结果可重现。
        """
        existing = self.load(profile_id)
        if existing:
            return existing
        if seed is None:
            seed = random.randint(0, 2**31 - 1)
        prof = BrowserProfile(
            profile_id=profile_id,
            label=label or profile_id,
            fingerprint_seed=seed,
        )
        self.save(prof)
        return prof

    def delete(self, profile_id: str) -> bool:
        path = self._path(profile_id)
        if path.exists():
            path.unlink()
            return True
        return False
