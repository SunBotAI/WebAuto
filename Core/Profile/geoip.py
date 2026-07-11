"""
Core/Profile/geoip.py — IP 地理推断

给定 IP，返回 (country_code, city, timezone, locale)。

依赖：
    pip install geoip2 timezonefinder

数据文件（MaxMind GeoIP2 City）：
    - 免费版：https://dev.maxmind.com/geoip/geolite2/
    - 下载 GeoLite2-City.mmdb 放到 ~/.cache/webauto/geoip/GeoLite2-City.mmdb
    - 或设置 MAXMIND_DB_PATH 环境变量

用法：
    from Core.Profile.geoip import ip2geoinfo, ip2timezone
    info = ip2geoinfo("8.8.8.8")
    # info.country  = "US"
    # info.city     = "Mountain View"
    # info.timezone = "America/Los_Angeles"
    # info.locale   = "en-US"
"""

from __future__ import annotations

import os
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ─── 数据类 ───────────────────────────────────────────────────────

# ISO 3166-1 alpha-2 → IETF BCP 47 locale 推断
# 覆盖常见国家，简单够用；复杂场景可扩展为 country → list[language]
_COUNTRY_LOCALE: dict[str, str] = {
    "CN": "zh-CN",
    "TW": "zh-TW",
    "HK": "zh-HK",
    "MO": "zh-MO",
    "SG": "zh-SG",
    "MY": "zh-MY",
    "US": "en-US",
    "GB": "en-GB",
    "AU": "en-AU",
    "CA": "en-CA",
    "NZ": "en-NZ",
    "IE": "en-IE",
    "DE": "de-DE",
    "AT": "de-AT",
    "CH": "de-CH",
    "FR": "fr-FR",
    "BE": "fr-BE",
    "CA": "fr-CA",
    "ES": "es-ES",
    "MX": "es-MX",
    "AR": "es-AR",
    "JP": "ja-JP",
    "KR": "ko-KR",
    "RU": "ru-RU",
    "BR": "pt-BR",
    "PT": "pt-PT",
    "IT": "it-IT",
    "NL": "nl-NL",
    "SE": "sv-SE",
    "NO": "no-NO",
    "DK": "da-DK",
    "FI": "fi-FI",
    "PL": "pl-PL",
    "CZ": "cs-CZ",
    "TR": "tr-TR",
    "IN": "en-IN",
    "TH": "th-TH",
    "VN": "vi-VN",
    "ID": "id-ID",
    "PH": "en-PH",
    "EG": "ar-EG",
    "SA": "ar-SA",
    "AE": "ar-AE",
    "IL": "he-IL",
    "GR": "el-GR",
    "HU": "hu-HU",
    "RO": "ro-RO",
    "UA": "uk-UA",
}


@dataclass
class GeoInfo:
    """
    IP → 地理信息推断结果。

    Attributes:
        ip:          查询的 IP
        country:     ISO 3166-1 alpha-2 国家代码，如 "US"
        city:        城市名，如 "Mountain View"（可能为空）
        timezone:    IANA 时区 ID，如 "America/Los_Angeles"
        locale:      BCP 47 locale，如 "en-US"
        raw:         原始 geoip2 记录（用于调试）
    """
    ip: str
    country: Optional[str] = None
    city: Optional[str] = None
    timezone: Optional[str] = None
    locale: Optional[str] = None
    raw: Optional[object] = None

    def __repr__(self) -> str:
        return (
            f"GeoInfo(ip={self.ip!r}, country={self.country!r}, "
            f"city={self.city!r}, tz={self.timezone!r}, locale={self.locale!r})"
        )


# ─── 核心函数 ─────────────────────────────────────────────────────

def _default_db_path() -> Path:
    """返回默认 MaxMind GeoIP2 数据库路径"""
    default = Path.home() / ".cache" / "webauto" / "geoip" / "GeoLite2-City.mmdb"
    return Path(os.environ.get("MAXMIND_DB_PATH", str(default)))


def _open_db(db_path: Optional[Path] = None):
    """
    打开 MaxMind 数据库，返回 reader。
    懒加载：全局缓存 reader 实例。
    """
    if not hasattr(_open_db, "_reader"):
        path = db_path or _default_db_path()
        if not path.exists():
            raise FileNotFoundError(
                f"MaxMind GeoIP2 database not found at {path}. "
                "Download from https://dev.maxmind.com/geoip/geolite2/ "
                "and set MAXMIND_DB_PATH or place at ~/.cache/webauto/geoip/GeoLite2-City.mmdb"
            )
        import geoip2.database
        _open_db._reader = geoip2.database.Reader(str(path))
    return _open_db._reader


def ip2geoinfo(ip: str, *, db_path: Optional[Path] = None) -> GeoInfo:
    """
    查询 IP 的地理信息。

    Args:
        ip:      IPv4 或 IPv6 地址（如 "8.8.8.8", "2001:4860:4860::8888"）
        db_path: 可选，覆盖 MaxMind 数据库路径

    Returns:
        GeoInfo 对象（country/city/timezone/locale 均可能为 None 表示查不到）

    Raises:
        FileNotFoundError: MaxMind 数据库未找到
        ValueError:        IP 格式无效
    """
    if not ip or not isinstance(ip, str):
        raise ValueError(f"Invalid IP address: {ip!r}")

    ip = ip.strip()

    # 格式校验（拒绝 "not-an-ip" 等明显非 IP 字符串）
    import ipaddress
    try:
        ipaddress.ip_address(ip)
    except ValueError:
        raise ValueError(f"Invalid IP address: {ip!r}")

    try:
        reader = _open_db(db_path)
        response = reader.city(ip)
    except FileNotFoundError:
        # 数据库文件缺失 → 不吞异常，让调用方知道要下载
        raise
    except Exception as exc:
        logger.debug("GeoIP lookup failed for %s: %s", ip, exc)
        return GeoInfo(ip=ip)

    # Country
    country = None
    if response.country and response.country.iso_code:
        country = response.country.iso_code
    elif response.registered_country and response.registered_country.iso_code:
        country = response.registered_country.iso_code
    elif response.continent and response.continent.code not in ("EU", "AP", "AF", "AO", "AN", "AS", "NA", "SA", "OC"):
        # 大洲代码不是国家，退回为空
        pass

    # City
    city = None
    if response.city and response.city.name:
        # 优先用本地化英文名，其次原始名称
        city = response.city.names.get("en") or response.city.name

    # Timezone — 使用 timezonefinder 从经纬度推断
    timezone_id = None
    if response.location and response.location.latitude and response.location.longitude:
        try:
            from timezonefinder import TimezoneFinder
            if not hasattr(ip2geoinfo, "_tf"):
                ip2geoinfo._tf = TimezoneFinder()
            tf: TimezoneFinder = ip2geoinfo._tf
            timezone_id = tf.timezone_at(
                lat=response.location.latitude,
                lng=response.location.longitude,
            )
        except ImportError:
            logger.warning("timezonefinder not installed, timezone will be None")
        except Exception as exc:
            logger.debug("Timezone lookup failed for %s: %s", ip, exc)

    # Locale — 从国家代码推断
    locale = _COUNTRY_LOCALE.get(country) if country else None

    return GeoInfo(
        ip=ip,
        country=country,
        city=city,
        timezone=timezone_id,
        locale=locale,
        raw=response,
    )


def ip2timezone(ip: str, *, db_path: Optional[Path] = None) -> Optional[str]:
    """
    便捷函数：直接返回 IP 对应的 IANA 时区 ID。

    >>> ip2timezone("8.8.8.8")
    'America/Los_Angeles'
    """
    return ip2geoinfo(ip, db_path=db_path).timezone


def suggest_fingerprint_from_ip(ip: str, *, db_path: Optional[Path] = None) -> dict:
    """
    根据 IP 地理信息，建议 FingerprintConfig 的 locale / timezone。

    用于 Profile 自动匹配：IP 地理 → timezone + locale，
    让 FingerprintConfig 与代理 IP 的物理位置一致（降低风控）。

    Returns:
        dict，含 keys: locale, timezone, country, city
        所有值可能为 None。

    用法：
        from Core.Profile import Profile
        from Core.Profile.geoip import suggest_fingerprint_from_ip

        info = suggest_fingerprint_from_ip("8.8.8.8")
        profile.fingerprint.locale  = info["locale"]  or profile.fingerprint.locale
        profile.fingerprint.timezone = info["timezone"] or profile.fingerprint.timezone
    """
    info = ip2geoinfo(ip, db_path=db_path)
    return {
        "locale":   info.locale,
        "timezone": info.timezone,
        "country":  info.country,
        "city":     info.city,
    }


# ─── CLI 调试入口 ─────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python geoip.py <IP>")
        sys.exit(1)

    ip = sys.argv[1]
    info = ip2geoinfo(ip)
    print(f"IP:         {info.ip}")
    print(f"Country:    {info.country}")
    print(f"City:       {info.city}")
    print(f"Timezone:   {info.timezone}")
    print(f"Locale:     {info.locale}")
