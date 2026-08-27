"""Discover local Chrome-family executables and authorized CDP endpoints."""

from __future__ import annotations

import os
import shutil
import urllib.request
from pathlib import Path
from typing import Any


def discover_browsers() -> dict[str, Any]:
    candidates: list[tuple[str, str]] = []
    configured = os.environ.get("WEBAUTO_CHROME_EXECUTABLE")
    if configured:
        candidates.append(("configured", configured))
    if os.name == "nt":
        candidates.extend(
            [
                ("chrome", r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
                ("chrome", r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
                ("edge", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
                ("edge", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
            ]
        )
    for command in (
        "google-chrome",
        "google-chrome-stable",
        "chromium",
        "chromium-browser",
        "msedge",
    ):
        resolved = shutil.which(command)
        if resolved:
            candidates.append((command, resolved))
    seen: set[str] = set()
    browsers = []
    for kind, raw_path in candidates:
        path = str(Path(raw_path).resolve())
        key = os.path.normcase(path)
        if key in seen or not Path(path).is_file():
            continue
        seen.add(key)
        browsers.append({"kind": kind, "executable": path})
    cdp = []
    for port in (9222, 9223, 9333):
        endpoint = f"http://127.0.0.1:{port}"
        try:
            with urllib.request.urlopen(endpoint + "/json/version", timeout=0.25) as response:
                if response.status == 200:
                    cdp.append({"endpoint": endpoint, "available": True})
        except (OSError, ValueError):
            cdp.append({"endpoint": endpoint, "available": False})
    return {"browsers": browsers, "cdp_endpoints": cdp}
