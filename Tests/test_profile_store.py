"""
Tests/test_profile_store.py — FINGERPRINT-003 验收测试
ProfileStore CRUD + import/export 单元测试
"""
import sys
import json
import tempfile
import zipfile
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.profile import Profile, ProfileStatus, FingerprintConfig, NetworkConfig
from Core.Profile.store import ProfileStore


class TestProfileStoreCRUD:
    """ProfileStore Create/Read/Update/Delete"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = ProfileStore(base_dir=Path(self.tmpdir))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_profile(self):
        """create: 创建 Profile 目录和文件"""
        p = Profile(id="profile-001", name="Test Profile")
        p.fingerprint.canvas_seed = 12345
        p.fingerprint.audio_seed = 67890
        p.tags = ["dev", "test"]
        p.network.proxy_url = "http://proxy.example.com:8080"

        path = self.store.create(p)

        assert path.exists()
        assert (path / "config.yaml").exists()
        assert (path / "fingerprint.json").exists()
        assert (path / "meta.json").exists()

    def test_get_existing_profile(self):
        """get: 读取已存在的 Profile"""
        p = Profile(id="profile-002", name="Get Test")
        p.fingerprint.canvas_seed = 111
        p.fingerprint.hardware_concurrency = 16
        self.store.create(p)

        loaded = self.store.get("profile-002")
        assert loaded.id == "profile-002"
        assert loaded.name == "Get Test"
        assert loaded.fingerprint.canvas_seed == 111
        assert loaded.fingerprint.hardware_concurrency == 16

    def test_get_nonexistent_raises(self):
        """get: 不存在的 Profile 抛出 FileNotFoundError"""
        with pytest.raises(FileNotFoundError):
            self.store.get("nonexistent")

    def test_save_updates_profile(self):
        """save: 更新 Profile 配置"""
        p = Profile(id="profile-003", name="Original")
        p.fingerprint.canvas_seed = 222
        self.store.create(p)

        # 修改后 save
        p.name = "Updated"
        p.fingerprint.canvas_seed = 333
        p.status = ProfileStatus.RUNNING
        self.store.save(p)

        loaded = self.store.get("profile-003")
        assert loaded.name == "Updated"
        assert loaded.fingerprint.canvas_seed == 333
        assert loaded.status == ProfileStatus.RUNNING

    def test_delete_removes_profile(self):
        """delete: 删除 Profile 目录"""
        p = Profile(id="profile-004", name="To Delete")
        self.store.create(p)
        assert self.store.get("profile-004").id == "profile-004"

        self.store.delete("profile-004")
        with pytest.raises(FileNotFoundError):
            self.store.get("profile-004")

    def test_delete_nonexistent_is_noop(self):
        """delete: 删除不存在的 Profile 不抛异常"""
        self.store.delete("nonexistent")  # 不应抛异常

    def test_list_all_returns_all_profiles(self):
        """list_all: 返回所有 Profile"""
        ids = ["list-001", "list-002", "list-003"]
        for pid in ids:
            p = Profile(id=pid, name=f"Profile {pid}")
            self.store.create(p)

        all_profiles = self.store.list_all()
        listed_ids = {pr.id for pr in all_profiles}
        assert listed_ids == set(ids)

    def test_list_all_empty_on_fresh_dir(self):
        """list_all: 空目录返回空列表"""
        assert self.store.list_all() == []

    def test_exists(self):
        """exists: 判断 Profile 是否存在"""
        p = Profile(id="exists-001", name="Exists Test")
        assert not self.store.exists("exists-001")
        self.store.create(p)
        assert self.store.exists("exists-001")

    def test_get_or_create_new(self):
        """get_or_create: 不存在则创建"""
        p = self.store.get_or_create("new-profile", name="New Profile")
        assert p.id == "new-profile"
        assert self.store.exists("new-profile")

    def test_get_or_create_existing(self):
        """get_or_create: 已存在则返回（不覆盖）"""
        p1 = self.store.get_or_create("existing", name="First")
        p1.fingerprint.canvas_seed = 999
        self.store.save(p1)

        p2 = self.store.get_or_create("existing", name="Second")
        assert p2.fingerprint.canvas_seed == 999
        assert p2.name == "First"  # 不被覆盖

    def test_storage_dir_assigned_on_create(self):
        """create: 自动分配 storage_dir"""
        p = Profile(id="storage-test")
        assert p.storage_dir is None
        self.store.create(p)
        assert p.storage_dir is not None
        assert p.storage_dir.name == "storage-test"


class TestProfileStoreFingerprintPersistence:
    """fingerprint.json 单独存储验证"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = ProfileStore(base_dir=Path(self.tmpdir))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fingerprint_json_written(self):
        """fingerprint.json 包含完整指纹数据"""
        p = Profile(id="fp-json-test")
        p.fingerprint.canvas_seed = 555
        p.fingerprint.audio_seed = 666
        p.fingerprint.webgl_vendor = "NVIDIA"
        self.store.create(p)

        fp_path = self.store._fingerprint_path("fp-json-test")
        with open(fp_path) as f:
            fp_data = json.load(f)

        assert fp_data["canvas_seed"] == 555
        assert fp_data["audio_seed"] == 666
        assert fp_data["webgl_vendor"] == "NVIDIA"

    def test_config_yaml_contains_full_profile(self):
        """config.yaml 包含完整 Profile（不含嵌套 fingerprint.json）"""
        p = Profile(id="yaml-full-test", name="Full Test")
        p.fingerprint.canvas_seed = 777
        p.fingerprint.screen_resolution = (2560, 1440)
        p.tags = ["tag1", "tag2"]
        self.store.create(p)

        config_path = self.store._config_path("yaml-full-test")
        with open(config_path) as f:
            data = yaml.safe_load(f)

        assert data["id"] == "yaml-full-test"
        assert data["fingerprint"]["canvas_seed"] == 777
        assert data["fingerprint"]["screen_resolution"] == [2560, 1440]
        assert data["tags"] == ["tag1", "tag2"]

    def test_meta_json_written(self):
        """meta.json 包含 id/name/tags/status/created_at"""
        p = Profile(id="meta-test", name="Meta Test", tags=["meta"])
        self.store.create(p)

        meta_path = self.store._meta_path("meta-test")
        with open(meta_path) as f:
            meta = json.load(f)

        assert meta["id"] == "meta-test"
        assert meta["name"] == "Meta Test"
        assert meta["tags"] == ["meta"]
        assert "created_at" in meta
        assert meta["status"] == "ready"


class TestProfileStoreImportExport:
    """ProfileStore import/export"""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = ProfileStore(base_dir=Path(self.tmpdir))

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_creates_zip(self):
        """export: 导出 Profile 为 .zip"""
        p = Profile(id="export-test", name="Export Test")
        p.fingerprint.canvas_seed = 888
        self.store.create(p)

        export_zip = Path(self.tmpdir) / "exported.zip"
        self.store.export("export-test", export_zip)

        assert export_zip.exists()
        assert export_zip.stat().st_size > 0

        # zip 内容检查
        with zipfile.ZipFile(export_zip) as zf:
            names = zf.namelist()
            assert any("config.yaml" in n for n in names)
            assert any("fingerprint.json" in n for n in names)
            assert any("meta.json" in n for n in names)

    def test_import_loads_profile(self):
        """import: 从 .zip 导入 Profile"""
        # 先创建并导出一个 Profile
        p = Profile(id="import-src", name="Import Source")
        p.fingerprint.canvas_seed = 999
        p.tags = ["imported"]
        self.store.create(p)

        export_zip = Path(self.tmpdir) / "exported.zip"
        self.store.export("import-src", export_zip)

        # 创建新 store 并 import
        store2 = ProfileStore(base_dir=Path(tempfile.mkdtemp()))
        imported = store2.import_(export_zip, new_id="import-dest")

        assert imported.id == "import-dest"
        assert imported.fingerprint.canvas_seed == 999
        assert imported.tags == ["imported"]

    def test_import_with_new_id(self):
        """import: new_id 参数重新分配 profile_id"""
        p = Profile(id="original-id", name="Original")
        p.fingerprint.canvas_seed = 123
        self.store.create(p)

        export_zip = Path(self.tmpdir) / "original.zip"
        self.store.export("original-id", export_zip)

        store2 = ProfileStore(base_dir=Path(tempfile.mkdtemp()))
        imported = store2.import_(export_zip, new_id="renamed-id")

        assert imported.id == "renamed-id"
        assert imported.name == "renamed-id"  # store.py 会同步 name
        assert store2.exists("renamed-id")
        assert not store2.exists("original-id")

    def test_import_nonexistent_zip_raises(self):
        """import: 不存在的 zip 抛出异常"""
        with pytest.raises(FileNotFoundError):
            self.store.import_(Path("/nonexistent.zip"))

    def test_save_does_not_wipe_user_data(self):
        """save: 只更新 config/meta/fingerprint，不碰 user-data"""
        p = Profile(id="userdata-test", name="UserData Test")
        self.store.create(p)

        # 手动创建 user-data 目录
        user_data_dir = self.store._user_data_dir("userdata-test")
        user_data_dir.mkdir(parents=True, exist_ok=True)
        (user_data_dir / "Local Storage" / "some.data").parent.mkdir(parents=True, exist_ok=True)
        (user_data_dir / "Local Storage" / "some.data").write_text("sensitive data")

        # save 不应删除 user-data
        p.name = "Updated"
        self.store.save(p)

        assert user_data_dir.exists()
        assert (user_data_dir / "Local Storage" / "some.data").exists()
