"""launchd 스케줄 — 매일 18:00 KST `indepth kcif daily` (단발 잡).

tgagent install.py 패턴 미러 (실행 시점 경로 resolve → drift 없음). 단발
StartCalendarInterval 잡이므로 KeepAlive 없음. 시크릿은 절대 넣지 않는다.
"""

from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

from indepth_analysis.kcif.paths import LOG_DIR, PROJECT_ROOT

LABEL = "com.lanoir42.kcif-daily"
PLIST_PATH = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
HOUR, MINUTE = 18, 0


def _build_plist() -> dict:
    uv = shutil.which("uv") or "/opt/homebrew/bin/uv"
    path_env = ":".join(p for p in [
        str(Path.home() / ".local/bin"), "/opt/homebrew/bin",
        "/usr/local/bin", "/usr/bin", "/bin",
    ])
    return {
        "Label": LABEL,
        "ProgramArguments": [uv, "run", "--project", str(PROJECT_ROOT),
                             "indepth", "kcif", "daily"],
        "WorkingDirectory": str(PROJECT_ROOT),
        "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
        "RunAtLoad": False,
        "StandardOutPath": str(LOG_DIR / "kcif-daily.log"),
        "StandardErrorPath": str(LOG_DIR / "kcif-daily.err.log"),
        "EnvironmentVariables": {
            "PATH": path_env,
            "HOME": str(Path.home()),
        },
    }


def install() -> str:
    PLIST_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(PLIST_PATH, "wb") as f:
        plistlib.dump(_build_plist(), f)
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"],
                   capture_output=True)  # 실패 무시 (미설치 상태)
    r = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(PLIST_PATH)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"launchctl bootstrap failed: {r.stderr.strip()}")
    return str(PLIST_PATH)


def uninstall() -> bool:
    uid = os.getuid()
    subprocess.run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"], capture_output=True)
    if PLIST_PATH.exists():
        PLIST_PATH.unlink()
        return True
    return False


def status() -> str:
    uid = os.getuid()
    r = subprocess.run(["launchctl", "print", f"gui/{uid}/{LABEL}"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        return "미설치 (launchctl print 실패)"
    lines = [ln.strip() for ln in r.stdout.splitlines()
             if any(k in ln for k in ("state", "last exit", "program"))]
    return "\n".join(lines) or r.stdout[:500]
