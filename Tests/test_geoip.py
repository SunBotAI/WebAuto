"""
Tests/test_geoip.py — T-023 验收测试
IP 地理推断：ip2geoinfo / ip2timezone / suggest_fingerprint_from_ip
"""
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from Core.Profile.geoip import (
    GeoInfo,
    ip2geoinfo,
    ip2timezone,
    suggest_fingerprint_from_ip,
    _COUNTRY_LOCALE,
)


class TestGeoInfo:
    """GeoInfo 数据类"""

    @pytest.fixture(autouse=True)
    def _clear_geoip_cache(self):
        import Core.Profile.geoip as geoip_module
        if hasattr(geoip_module._open_db, "_reader"):
            try:
                delattr(geoip_module._open_db, "_reader")
            except AttributeError:
                pass
        if hasattr(ip2geoinfo, "_tf"):
            try:
                delattr(ip2geoinfo, "_tf")
            except AttributeError:
                pass
        yield

    def test_geoinfo_defaults(self):
        info = GeoInfo(ip="1.1.1.1")
        assert info.ip == "1.1.1.1"
        assert info.country is None
        assert info.city is None
        assert info.timezone is None
        assert info.locale is None
        assert info.raw is None

    def test_geoinfo_full(self):
        info = GeoInfo(
            ip="8.8.8.8",
            country="US",
            city="Mountain View",
            timezone="America/Los_Angeles",
            locale="en-US",
        )
        assert info.country == "US"
        assert info.city == "Mountain View"
        assert info.timezone == "America/Los_Angeles"
        assert info.locale == "en-US"

    def test_geoinfo_repr(self):
        info = GeoInfo(ip="8.8.8.8", country="US")
        r = repr(info)
        assert "8.8.8.8" in r
        assert "US" in r


class TestCountryLocaleMap:
    """国家代码 → locale 映射"""

    @pytest.fixture(autouse=True)
    def _clear_geoip_cache(self):
        import Core.Profile.geoip as geoip_module
        if hasattr(geoip_module._open_db, "_reader"):
            try:
                delattr(geoip_module._open_db, "_reader")
            except AttributeError:
                pass
        if hasattr(ip2geoinfo, "_tf"):
            try:
                delattr(ip2geoinfo, "_tf")
            except AttributeError:
                pass
        yield

    def test_known_countries(self):
        assert _COUNTRY_LOCALE["CN"] == "zh-CN"
        assert _COUNTRY_LOCALE["US"] == "en-US"
        assert _COUNTRY_LOCALE["JP"] == "ja-JP"
        assert _COUNTRY_LOCALE["DE"] == "de-DE"
        assert _COUNTRY_LOCALE["GB"] == "en-GB"
        assert _COUNTRY_LOCALE["FR"] == "fr-FR"
        assert _COUNTRY_LOCALE["KR"] == "ko-KR"
        assert _COUNTRY_LOCALE["TW"] == "zh-TW"

    def test_unknown_country_returns_none(self):
        # unknown → 不在 map 中 → locale 为 None（由 ip2geoinfo 处理）
        assert _COUNTRY_LOCALE.get("XX") is None


class TestIp2GeoinfoValidation:
    """ip2geoinfo 输入验证"""

    @pytest.fixture(autouse=True)
    def _clear_geoip_cache(self):
        """每个测试前清理全局缓存，确保隔离"""
        import Core.Profile.geoip as geoip_module
        # 清理 _open_db 的缓存 reader
        if hasattr(geoip_module._open_db, "_reader"):
            try:
                delattr(geoip_module._open_db, "_reader")
            except AttributeError:
                pass
        # 清理 ip2geoinfo 的 TimezoneFinder 缓存
        if hasattr(ip2geoinfo, "_tf"):
            try:
                delattr(ip2geoinfo, "_tf")
            except AttributeError:
                pass
        yield

    def test_invalid_ip_raises(self):
        with pytest.raises(ValueError, match="Invalid IP"):
            ip2geoinfo("")
        with pytest.raises(ValueError, match="Invalid IP"):
            ip2geoinfo("not-an-ip")
        with pytest.raises(ValueError, match="Invalid IP"):
            ip2geoinfo(None)

    def test_db_not_found_raises_file_not_found(self):
        # Patch _open_db to raise FileNotFoundError directly
        def raising_open_db(db_path):
            raise FileNotFoundError(
                f"MaxMind GeoIP2 database not found at /nonexistent/path/GeoLite2-City.mmdb. "
                "Download from https://dev.maxmind.com/geoip/geolite2/"
            )
        with patch('Core.Profile.geoip._open_db', raising_open_db):
            with pytest.raises(FileNotFoundError, match="MaxMind"):
                ip2geoinfo("8.8.8.8")


class TestIp2GeoinfoMocked:
    """ip2geoinfo 逻辑测试（mock MaxMind 数据库）"""

    def _mock_response(self, country_code="US", city_name="Mountain View",
                       lat=37.4056, lon=-122.0775):
        """构造 mock geoip2 响应对象"""
        mock_response = MagicMock()
        mock_response.country = MagicMock()
        mock_response.country.iso_code = country_code
        mock_response.country.name = None
        mock_response.registered_country = MagicMock()
        mock_response.registered_country.iso_code = None
        mock_response.continent = MagicMock()
        mock_response.continent.code = "NA"
        mock_response.city = MagicMock()
        mock_response.city.name = city_name
        mock_response.city.names = {"en": city_name}
        mock_response.location = MagicMock()
        mock_response.location.latitude = lat
        mock_response.location.longitude = lon
        return mock_response

    def _mock_timezone_result(self):
        """构造 mock TimezoneFinder"""
        mock_tf = MagicMock()
        mock_tf.timezone_at.return_value = "America/Los_Angeles"
        return mock_tf

    def test_ip2geoinfo_uses_country_code(self):
        """country code 正确映射"""
        mock_resp = self._mock_response(country_code="JP", city_name="Tokyo",
                                          lat=35.6762, lon=139.6503)
        mock_tf = self._mock_timezone_result()
        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            with patch.object(ip2geoinfo, "_tf", mock_tf, create=True):
                info = ip2geoinfo("8.8.8.8")

        assert info.country == "JP"
        assert info.city == "Tokyo"

    def test_ip2geoinfo_timezone_from_latlon(self):
        """timezone 从经纬度通过 TimezoneFinder 推断"""
        mock_resp = self._mock_response(lat=35.6762, lon=139.6503)
        mock_tf_instance = MagicMock()
        mock_tf_instance.timezone_at.return_value = "Asia/Tokyo"

        # timezonefinder may not be installed; patch the lazy import target at source
        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            # Patch the module-level TimezoneFinder lazy import
            with patch.dict("sys.modules", {"timezonefinder": MagicMock(TimezoneFinder=MagicMock(return_value=mock_tf_instance))}):
                # Clear stale _tf
                if hasattr(ip2geoinfo, "_tf"):
                    try:
                        delattr(ip2geoinfo, "_tf")
                    except AttributeError:
                        pass
                with patch.object(ip2geoinfo, "_tf", mock_tf_instance, create=True):
                    info = ip2geoinfo("203.0.113.1")

        assert info.timezone == "Asia/Tokyo"

    def test_ip2geoinfo_locale_from_country(self):
        """locale 从国家代码映射"""
        mock_resp = self._mock_response(country_code="DE")
        mock_tf = MagicMock()
        mock_tf.timezone_at.return_value = "Europe/Berlin"

        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            with patch.object(ip2geoinfo, "_tf", mock_tf, create=True):
                info = ip2geoinfo("8.8.8.8")

        assert info.locale == "de-DE"

    def test_ip2geoinfo_returns_raw_response(self):
        """raw 字段包含原始响应"""
        mock_resp = self._mock_response()
        mock_tf = MagicMock()
        mock_tf.timezone_at.return_value = "America/Los_Angeles"

        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            with patch.object(ip2geoinfo, "_tf", mock_tf, create=True):
                info = ip2geoinfo("8.8.8.8")

        assert info.raw is mock_resp

    def test_ip2geoinfo_fallback_on_exception(self):
        """geoip2 查询失败时返回空的 GeoInfo，不抛异常"""
        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_open.side_effect = Exception("network error")
            info = ip2geoinfo("8.8.8.8")

        assert info.ip == "8.8.8.8"
        assert info.country is None
        assert info.timezone is None

    def test_ip2geoinfo_no_location_means_no_timezone(self):
        """无经纬度 → timezone 为 None（不查 TimezoneFinder）"""
        mock_resp = MagicMock()
        mock_resp.country.iso_code = "US"
        mock_resp.registered_country.iso_code = None
        mock_resp.continent.code = "NA"
        mock_resp.city.name = None
        mock_resp.city.names = {}
        mock_resp.location.latitude = None
        mock_resp.location.longitude = None

        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader

            info = ip2geoinfo("127.0.0.1")

        assert info.timezone is None


class TestIp2Timezone:
    """ip2timezone 便捷函数"""

    @pytest.fixture(autouse=True)
    def _clear_geoip_cache(self):
        import Core.Profile.geoip as geoip_module
        if hasattr(geoip_module._open_db, "_reader"):
            try:
                delattr(geoip_module._open_db, "_reader")
            except AttributeError:
                pass
        if hasattr(ip2geoinfo, "_tf"):
            try:
                delattr(ip2geoinfo, "_tf")
            except AttributeError:
                pass
        yield

    def _mock_resp(self, lat=37.4, lon=-122.0):
        mock_resp = MagicMock()
        mock_resp.country.iso_code = "US"
        mock_resp.registered_country.iso_code = None
        mock_resp.continent.code = "NA"
        mock_resp.city.name = "Mountain View"
        mock_resp.city.names = {"en": "Mountain View"}
        mock_resp.location.latitude = lat
        mock_resp.location.longitude = lon
        return mock_resp

    def test_ip2timezone_returns_string(self):
        mock_tf_instance = MagicMock()
        mock_tf_instance.timezone_at.return_value = "America/Los_Angeles"
        mock_tf_class = MagicMock(return_value=mock_tf_instance)
        mock_resp = self._mock_resp()

        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            with patch.dict("sys.modules", {"timezonefinder": MagicMock(TimezoneFinder=mock_tf_class)}):
                if hasattr(ip2geoinfo, "_tf"):
                    try:
                        delattr(ip2geoinfo, "_tf")
                    except AttributeError:
                        pass
                with patch.object(ip2geoinfo, "_tf", mock_tf_instance, create=True):
                    tz = ip2timezone("8.8.8.8")

        assert tz == "America/Los_Angeles"

    def test_ip2timezone_raises_on_file_not_found(self):
        # FileNotFoundError now propagates (not swallowed)
        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_open.side_effect = FileNotFoundError("no db")
            with pytest.raises(FileNotFoundError):
                ip2timezone("8.8.8.8")


class TestSuggestFingerprint:
    """suggest_fingerprint_from_ip"""

    @pytest.fixture(autouse=True)
    def _clear_geoip_cache(self):
        import Core.Profile.geoip as geoip_module
        if hasattr(geoip_module._open_db, "_reader"):
            try:
                delattr(geoip_module._open_db, "_reader")
            except AttributeError:
                pass
        if hasattr(ip2geoinfo, "_tf"):
            try:
                delattr(ip2geoinfo, "_tf")
            except AttributeError:
                pass
        yield

    def test_returns_dict_with_keys(self):
        mock_resp = MagicMock()
        mock_resp.country.iso_code = "JP"
        mock_resp.registered_country.iso_code = None
        mock_resp.continent.code = "AS"
        mock_resp.city.name = "Tokyo"
        mock_resp.city.names = {"en": "Tokyo"}
        mock_resp.location.latitude = 35.6762
        mock_resp.location.longitude = 139.6503

        mock_tf_instance = MagicMock()
        mock_tf_instance.timezone_at.return_value = "Asia/Tokyo"
        mock_tf_class = MagicMock(return_value=mock_tf_instance)

        with patch("Core.Profile.geoip._open_db") as mock_open:
            mock_reader = MagicMock()
            mock_reader.city.return_value = mock_resp
            mock_open.return_value = mock_reader
            with patch.dict("sys.modules", {"timezonefinder": MagicMock(TimezoneFinder=mock_tf_class)}):
                if hasattr(ip2geoinfo, "_tf"):
                    try:
                        delattr(ip2geoinfo, "_tf")
                    except AttributeError:
                        pass
                with patch.object(ip2geoinfo, "_tf", mock_tf_instance, create=True):
                    result = suggest_fingerprint_from_ip("203.0.113.1")

        assert result["locale"] == "ja-JP"
        assert result["timezone"] == "Asia/Tokyo"
        assert result["country"] == "JP"
        assert result["city"] == "Tokyo"


class TestGeoipCli:
    """geoip.py CLI 入口"""

    def test_cli_main_missing_ip(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "-c",
             "from Core.Profile.geoip import ip2geoinfo; ip2geoinfo('')"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
        assert "Invalid IP" in result.stderr or "ValueError" in result.stderr
