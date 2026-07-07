@echo off
REM ============================================================
REM DEPRECATED! Use Tools/cdp_launch.py instead.
REM
REM This .bat was a workaround for the original "WSL attach
REM Windows Chrome" path, which we abandoned in 2026-07.
REM Cross-platform equivalent:
REM
REM     python Tools/cdp_launch.py first-run
REM     python Tools/cdp_launch.py visit
REM     python Tools/cdp_launch.py stealth-test
REM     python Tools/cdp_launch.py hold
REM
REM The .py version auto-detects your OS, manages playwright
REM bundled Chromium, persistent userdata, AntiDetect injection,
REM and works on Linux / macOS / Windows / WSL uniformly.
REM
REM Kept here only as a fallback for users who can't run Python.
REM Remove at your discretion.
REM ============================================================
echo This .bat is DEPRECATED. Run instead:
echo     python Tools\cdp_launch.py
exit /b 1
