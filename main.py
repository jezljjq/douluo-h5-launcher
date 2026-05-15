from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path


ADMIN_RESTART_RESULT_ENV = "DOULUO_ADMIN_RESTART_RESULT"


def _is_running_as_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _request_admin_restart() -> int:
    if getattr(sys, "frozen", False):
        target = sys.executable
        params = subprocess.list2cmdline(sys.argv[1:])
        working_dir = str(Path(sys.executable).resolve().parent)
    else:
        script_path = str(Path(__file__).resolve())
        target = sys.executable
        params = subprocess.list2cmdline([script_path, *sys.argv[1:]])
        working_dir = str(Path(script_path).parent)

    return int(
        ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            target,
            params or None,
            working_dir,
            1,
        )
    )


def _ensure_admin_on_startup() -> bool:
    if os.name != "nt" or _is_running_as_admin():
        return True

    result = _request_admin_restart()
    if result > 32:
        return False

    os.environ[ADMIN_RESTART_RESULT_ENV] = str(result)
    return True


def main() -> None:
    if not _ensure_admin_on_startup():
        return

    from douluo_launcher.gui import LauncherApp

    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
