"""日志模块.

基于 loguru，提供：
- 控制台彩色输出（rich 集成）
- 文件滚动日志
- 敏感信息脱敏（避免泄露 Cookie/Token）
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from loguru import logger as _logger

# ---------------------------------------------------------------------------
# 脱敏正则
# ---------------------------------------------------------------------------

# 形如  token=eyJhbGciOi...  /  session_id=xxxx  /  Authorization: Bearer xxx
_SENSITIVE_PATTERNS = [
    # key=value 形式（cookie / url query）
    re.compile(
        r"(?i)((?:token|session[_-]?id|authorization|cookie|secret|password)"
        r"\s*[=:]\s*)([^\s,;'\"]+)"
    ),
    # Bearer xxx
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._\-]+)"),
]

_MASK = "***"


def mask_secrets(text: str) -> str:
    """把日志文本里疑似凭证的值替换成 ***。"""
    if not text:
        return text
    out = text
    for pat in _SENSITIVE_PATTERNS:
        out = pat.sub(lambda m: f"{m.group(1)}{_MASK}", out)
    return out


# ---------------------------------------------------------------------------
# 初始化
# ---------------------------------------------------------------------------


def setup_logger(
    *,
    level: str = "INFO",
    log_dir: str = "logs",
    rotation: str = "10 MB",
    retention: str = "14 days",
) -> None:
    """配置全局日志。

    Args:
        level: 控制台日志级别（DEBUG/INFO/WARNING/ERROR）。
        log_dir: 日文件存放目录。
        rotation: 单文件大小阈值。
        retention: 历史日志保留时长。
    """
    _logger.remove()

    # 控制台：彩色精简
    _logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        backtrace=False,
        diagnose=False,
        enqueue=True,
        format=(
            "<green>{time:HH:mm:ss.SSS}</green> "
            "<level>{level: <5}</level> "
            "<cyan>{name}</cyan> | <level>{message}</level>"
        ),
    )

    # 文件：完整 + 脱敏
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    _logger.add(
        str(log_path / "grabber_{time:YYYYMMDD}.log"),
        level="DEBUG",
        rotation=rotation,
        retention=retention,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        # loguru 的 filter 接收 record，这里在写入前对 message 脱敏
        filter=lambda record: _apply_mask(record),
    )


def _apply_mask(record: Any) -> bool:
    """在 record 上原地脱敏 message 与 args。返回 True 表示保留该条日志。"""
    msg = record.get("message", "")
    if msg:
        record["message"] = mask_secrets(msg)
    args = record.get("extra")
    if isinstance(args, dict):
        for k, v in list(args.items()):
            if isinstance(v, str):
                args[k] = mask_secrets(v)
    return True


def get_logger():
    """返回已配置的 loguru logger。"""
    return _logger
