from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path
import shutil
import threading


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


def _collect_runtime_diagnostics() -> dict[str, object]:
    from douluo_launcher.config import app_root, project_root

    app_dir = app_root()
    project_dir = project_root()
    debug_dir = app_dir / "debug_ocr"
    logs_dir = app_dir / "logs"
    playwright_browsers = Path(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        or str(Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright")
    )

    def item(path: Path) -> dict[str, object]:
        return {"path": str(path), "exists": path.exists()}

    try:
        py32 = subprocess.run(
            ["py", "-3.14-32", "-c", "import sys; print(sys.executable)"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        py32_path = py32.stdout.strip()
        py32_ok = py32.returncode == 0
    except Exception as exc:
        py32_path = str(exc)
        py32_ok = False

    chromium_dirs: list[str] = []
    if playwright_browsers.exists():
        chromium_dirs = [str(path) for path in playwright_browsers.glob("chromium*")]

    return {
        "sys_frozen": bool(getattr(sys, "frozen", False)),
        "sys_executable": sys.executable,
        "cwd": os.getcwd(),
        "__file__": __file__,
        "app_root": str(app_dir),
        "project_root": str(project_dir),
        "automation_settings": item(app_dir / "automation_settings.json"),
        "dm_click_helper": item(app_dir / "dm_click_helper.py"),
        "template_passport_btn": item(debug_dir / "template_passport_btn.png"),
        "browser_pos": item(debug_dir / "browser_pos.json"),
        "passport_dialog_pos_cache": item(debug_dir / "passport_dialog_pos_cache.json"),
        "window_manager_settings": item(app_dir / "window_manager_settings.json"),
        "logs_dir": item(logs_dir),
        "debug_ocr_dir": item(debug_dir),
        "playwright_browsers_path": str(playwright_browsers),
        "playwright_browsers_path_exists": playwright_browsers.exists(),
        "playwright_chromium_candidates": chromium_dirs,
        "playwright_internal_local_browsers": item(app_dir / "_internal" / "playwright" / "driver" / "package" / ".local-browsers"),
        "tesseract_path": shutil.which("tesseract"),
        "python_32bit_ok": py32_ok,
        "python_32bit_path": py32_path,
        "is_admin": _is_running_as_admin(),
    }


def _diagnose_runtime() -> None:
    diagnostics = _collect_runtime_diagnostics()
    app_dir = Path(str(diagnostics["app_root"]))
    logs_dir = app_dir / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    output_path = logs_dir / "runtime_diagnostics.json"
    output_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(diagnostics, ensure_ascii=False, indent=2))


def _run_account_action_child(config_path: Path) -> None:
    from douluo_launcher.automation import AccountRunner
    from douluo_launcher.config import AccountConfig, app_root, load_settings

    cfg = json.loads(config_path.read_text(encoding="utf-8"))
    event_path = Path(cfg["event_path"])
    result_path = Path(cfg["result_path"])
    event_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    os.environ.setdefault(
        "PLAYWRIGHT_BROWSERS_PATH",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright"),
    )

    def emit(kind: str, value: object) -> None:
        payload = {"type": kind, "value": value}
        with event_path.open("a", encoding="utf-8") as file:
            file.write(json.dumps(payload, ensure_ascii=False) + "\n")
            file.flush()

    try:
        settings = load_settings(Path(cfg["settings_path"]))
        account = AccountConfig(
            level=cfg["level"],
            bookmark_no=int(cfg["bookmark_no"]),
            game_window_no=int(cfg["game_window_no"]),
            url=cfg["url"],
        )
        stop = threading.Event()
        runner = AccountRunner(
            account,
            settings,
            stop,
            log=lambda msg: emit("log", str(msg)),
            update_status=lambda _account, status: emit("status", str(status)),
            passport_found=lambda _account, passport: emit("passport", str(passport)),
        )
        action = cfg.get("action", "full")
        verify_state = ""
        if action == "fast_submit":
            flow_result = runner.run_game_flow_fast_submit()
        elif action == "verify":
            verify_state = runner.verify_login_result()
            flow_result = verify_state == "logged_in"
        else:
            flow_result = runner.run_game_flow()

        result = {
            "result": bool(flow_result),
            "verify_state": verify_state,
            "submit_result": runner.last_fast_submit_result,
            "timing": runner.last_timings.get("总计", 0),
        }
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
    except Exception as exc:
        emit("log", f"[子进程异常] {exc}")
        result_path.write_text(
            json.dumps(
                {
                    "result": False,
                    "verify_state": "",
                    "submit_result": "failed",
                    "timing": 0,
                    "error": str(exc),
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )


def main() -> None:
    if "--diagnose-runtime" in sys.argv:
        _diagnose_runtime()
        return

    if "--run-account-action" in sys.argv:
        index = sys.argv.index("--run-account-action")
        _run_account_action_child(Path(sys.argv[index + 1]))
        return

    if not _ensure_admin_on_startup():
        return

    from douluo_launcher.gui import LauncherApp

    app = LauncherApp()
    app.mainloop()


if __name__ == "__main__":
    main()
