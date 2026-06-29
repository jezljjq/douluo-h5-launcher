from __future__ import annotations

import argparse
import ctypes
import json
import sys
import threading
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from douluo_launcher.background_login import BackgroundSingleAccountRunner
from douluo_launcher.config import AccountConfig, app_root, load_accounts_from_bookmark_root, load_settings
from douluo_launcher.window_manager import DEFAULT_TITLE_TEMPLATE, GameWindow, launch_game_process, list_game_windows, user32
from douluo_launcher.window_operator import BackgroundOperator


LIVE_LEVEL = "存钻"
LIVE_BACKGROUND_SERIAL_LIMIT = 2
DEFAULT_GAME_PATH = r"E:\Program Files\DLH5\X5Game.exe"


@dataclass
class LiveAccountResult:
    level: str
    bookmark_no: int
    game_window_no: int
    hwnd: int | None
    status: str
    result: bool
    passport: str = ""
    elapsed_seconds: float = 0.0


class GlobalInputGuard:
    def __init__(self) -> None:
        self.set_foreground_call_count = 0
        self.set_cursor_pos_count = 0
        self.mouse_event_count = 0
        self.keybd_event_count = 0
        self._patches: list[tuple[object, str, object]] = []

    def __enter__(self) -> "GlobalInputGuard":
        self._patch_ctypes_user32()
        self._patch_win32gui()
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:
        for owner, name, original in reversed(self._patches):
            try:
                setattr(owner, name, original)
            except Exception:
                pass

    def _replace(self, owner: object, name: str, replacement) -> None:
        try:
            original = getattr(owner, name)
            setattr(owner, name, replacement)
            self._patches.append((owner, name, original))
        except Exception:
            pass

    def _patch_ctypes_user32(self) -> None:
        user32_dll = ctypes.windll.user32

        def set_foreground(_hwnd):
            self.set_foreground_call_count += 1
            return 0

        def set_cursor_pos(_x, _y):
            self.set_cursor_pos_count += 1
            return 0

        def mouse_event(*_args):
            self.mouse_event_count += 1
            return None

        def keybd_event(*_args):
            self.keybd_event_count += 1
            return None

        self._replace(user32_dll, "SetForegroundWindow", set_foreground)
        self._replace(user32_dll, "SetCursorPos", set_cursor_pos)
        self._replace(user32_dll, "mouse_event", mouse_event)
        self._replace(user32_dll, "keybd_event", keybd_event)

    def _patch_win32gui(self) -> None:
        try:
            import win32gui
        except Exception:
            return

        def set_foreground_window(_hwnd):
            self.set_foreground_call_count += 1
            return 0

        self._replace(win32gui, "SetForegroundWindow", set_foreground_window)

    @property
    def mouse_stolen(self) -> bool:
        return self.set_cursor_pos_count > 0 or self.mouse_event_count > 0

    @property
    def keyboard_stolen(self) -> bool:
        return self.keybd_event_count > 0


def select_live_accounts(
    accounts: Iterable[AccountConfig],
    *,
    level: str = LIVE_LEVEL,
    limit: int = LIVE_BACKGROUND_SERIAL_LIMIT,
) -> list[AccountConfig]:
    selected = [account for account in accounts if account.level == level]
    selected.sort(key=lambda account: account.bookmark_no)
    return selected[: max(0, int(limit))]


def scan_h5_windows(game_path: str) -> list[GameWindow]:
    return list_game_windows(
        title_template=DEFAULT_TITLE_TEMPLATE,
        game_exe_path=game_path,
        allow_unnumbered=True,
    )


def wait_for_new_window(
    *,
    before_hwnds: set[int],
    game_path: str,
    timeout_seconds: float,
) -> GameWindow | None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() <= deadline:
        windows = scan_h5_windows(game_path)
        new_windows = [window for window in windows if int(window.hwnd) not in before_hwnds]
        if new_windows:
            return sorted(new_windows, key=lambda window: int(window.hwnd))[0]
        time.sleep(0.5)
    return None


def rename_test_window(hwnd: int, index: int, title_template: str = DEFAULT_TITLE_TEMPLATE) -> str:
    title = title_template.format(index=index, number=index, hwnd=hwnd, old_title="")
    ok = bool(user32.SetWindowTextW(wintypes.HWND(int(hwnd)), title))
    if not ok:
        error_code = ctypes.get_last_error()
        raise RuntimeError(f"测试窗口临时编号失败 hwnd={hwnd} error={error_code}")
    return title


def launch_two_test_windows(game_path: str, *, timeout_seconds: float) -> tuple[list[int], list[dict[str, object]]]:
    before_windows = scan_h5_windows(game_path)
    before_hwnds = {int(window.hwnd) for window in before_windows}
    if before_hwnds:
        raise RuntimeError(f"启动前已存在 H5 窗口，拒绝 live 验证：{sorted(before_hwnds)}")

    launched: list[dict[str, object]] = []
    known_hwnds = set(before_hwnds)
    for index in range(1, LIVE_BACKGROUND_SERIAL_LIMIT + 1):
        launch_result = launch_game_process(game_path)
        if not launch_result.success:
            raise RuntimeError(f"启动第 {index} 个测试窗口失败：{launch_result.error}")
        window = wait_for_new_window(
            before_hwnds=known_hwnds,
            game_path=game_path,
            timeout_seconds=timeout_seconds,
        )
        if window is None:
            raise RuntimeError(f"启动第 {index} 个测试窗口后未检测到新增 hwnd")
        known_hwnds.add(int(window.hwnd))
        new_title = rename_test_window(int(window.hwnd), index)
        launched.append(
            {
                "index": index,
                "hwnd": int(window.hwnd),
                "old_title": window.title,
                "new_title": new_title,
            }
        )
        time.sleep(0.8)
    return sorted(known_hwnds - before_hwnds), launched


def reuse_existing_test_windows(game_path: str, *, limit: int = LIVE_BACKGROUND_SERIAL_LIMIT) -> tuple[list[int], list[dict[str, object]]]:
    windows = scan_h5_windows(game_path)
    by_number = {int(window.number): window for window in windows if window.number is not None}
    missing = [index for index in range(1, limit + 1) if index not in by_number]
    if missing:
        raise RuntimeError(f"复用测试窗口失败，缺少编号窗口：{missing}")
    selected = [by_number[index] for index in range(1, limit + 1)]
    return (
        [int(window.hwnd) for window in selected],
        [
            {
                "index": index,
                "hwnd": int(window.hwnd),
                "old_title": window.title,
                "new_title": window.title,
                "reused": True,
            }
            for index, window in enumerate(selected, start=1)
        ],
    )


def load_live_accounts(settings_path: Path, *, level: str, limit: int) -> tuple[object, list[AccountConfig]]:
    settings = load_settings(settings_path)
    accounts = load_accounts_from_bookmark_root(
        settings.bookmark_file,
        settings.bookmark_root_path,
        level_names=settings.level_names,
        account_group_settings=settings.account_group_settings,
    )
    selected = select_live_accounts(accounts, level=level, limit=limit)
    if len(selected) != limit:
        raise RuntimeError(f"live 验证需要 {limit} 个 {level} 账号，当前只有 {len(selected)} 个")
    window_numbers = [account.game_window_no for account in selected]
    expected = list(range(1, limit + 1))
    if window_numbers != expected:
        raise RuntimeError(f"{level} 前 {limit} 个账号窗口号必须是 {expected}，当前是 {window_numbers}")
    return settings, selected


def run_background_serial_limit2(
    *,
    settings_path: Path,
    game_path: str,
    output_dir: Path,
    level: str = LIVE_LEVEL,
    limit: int = LIVE_BACKGROUND_SERIAL_LIMIT,
    launch_timeout_seconds: float = 45.0,
    reuse_existing_windows: bool = False,
) -> dict[str, object]:
    if limit != LIVE_BACKGROUND_SERIAL_LIMIT:
        raise RuntimeError("此 live 脚本固定只允许 limit=2")
    game_exe = Path(game_path)
    if not game_exe.exists():
        raise FileNotFoundError(f"游戏程序不存在：{game_exe}")

    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"live_background_serial_limit2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    summary_path = output_dir / "latest_live_background_serial_limit2.json"
    settings, accounts = load_live_accounts(settings_path, level=level, limit=limit)

    detailed_logs: list[str] = []

    def write_log(message: str) -> None:
        text = str(message)
        detailed_logs.append(text)
        with log_path.open("a", encoding="utf-8") as file:
            file.write(text + "\n")

    before_windows = scan_h5_windows(str(game_exe))
    before_hwnds = [int(window.hwnd) for window in before_windows]
    write_log(f"启动前 H5 hwnd={before_hwnds}")
    if reuse_existing_windows:
        new_hwnds, launched = reuse_existing_test_windows(str(game_exe), limit=limit)
        write_log(f"复用现有测试窗口 hwnd={new_hwnds}")
    else:
        new_hwnds, launched = launch_two_test_windows(str(game_exe), timeout_seconds=launch_timeout_seconds)
        write_log(f"新增测试窗口 hwnd={new_hwnds}")
    for item in launched:
        write_log(f"测试窗口{item['index']}: hwnd={item['hwnd']} {item['old_title']} -> {item['new_title']}")

    statuses: dict[str, str] = {}
    passports: dict[str, str] = {}
    results: list[LiveAccountResult] = []
    stop_event = threading.Event()
    operator = BackgroundOperator()

    def update_status(account: AccountConfig, status: str) -> None:
        statuses[account.key] = status
        write_log(f"[状态][窗口{account.game_window_no}] {status}")

    def passport_found(account: AccountConfig, passport: str) -> None:
        passports[account.key] = passport
        write_log(f"[通行证][窗口{account.game_window_no}] {passport}")

    with GlobalInputGuard() as guard:
        for index, account in enumerate(accounts, start=1):
            print(f"[后台串行][{index}/{limit}] 窗口{account.game_window_no}：开始", flush=True)
            started = time.perf_counter()
            runner = BackgroundSingleAccountRunner(
                account,
                settings,
                stop_event,
                log=write_log,
                update_status=update_status,
                passport_found=passport_found,
                operator=operator,
            )
            result = bool(runner.run())
            elapsed = time.perf_counter() - started
            status = statuses.get(account.key, "成功" if result else "失败")
            if result and status == "已进入游戏，跳过":
                print(f"[后台串行][{index}/{limit}] 窗口{account.game_window_no}：已进入游戏，跳过", flush=True)
            elif result:
                passport = passports.get(account.key, "")
                if passport:
                    print(f"[后台串行][{index}/{limit}] 窗口{account.game_window_no}：识别通行证 {passport}", flush=True)
                print(f"[后台串行][{index}/{limit}] 窗口{account.game_window_no}：成功", flush=True)
            else:
                print(f"[后台串行][{index}/{limit}] 窗口{account.game_window_no}：失败", flush=True)
            results.append(
                LiveAccountResult(
                    level=account.level,
                    bookmark_no=account.bookmark_no,
                    game_window_no=account.game_window_no,
                    hwnd=new_hwnds[index - 1] if index - 1 < len(new_hwnds) else None,
                    status=status,
                    result=result,
                    passport=passports.get(account.key, ""),
                    elapsed_seconds=round(elapsed, 3),
                )
            )

        summary = {
            "started_at": datetime.now().isoformat(timespec="seconds"),
            "game_path": str(game_exe),
            "level": level,
            "limit": limit,
            "before_hwnds": before_hwnds,
            "launched_test_windows": not reuse_existing_windows,
            "reused_existing_test_windows": bool(reuse_existing_windows),
            "launched": launched,
            "new_hwnds": new_hwnds,
            "accounts": [
                {
                    "level": account.level,
                    "bookmark_no": account.bookmark_no,
                    "game_window_no": account.game_window_no,
                    "url": account.url,
                }
                for account in accounts
            ],
            "results": [asdict(result) for result in results],
            "continued_after_first_failure": bool(results and not results[0].result and len(results) > 1),
            "mouse_stolen": guard.mouse_stolen,
            "keyboard_stolen": guard.keyboard_stolen,
            "set_foreground_call_count": guard.set_foreground_call_count,
            "set_cursor_pos_count": guard.set_cursor_pos_count,
            "mouse_event_count": guard.mouse_event_count,
            "keybd_event_count": guard.keybd_event_count,
            "background_operator": {
                "uses_global_mouse": bool(operator.uses_global_mouse),
                "uses_global_keyboard": bool(operator.uses_global_keyboard),
                "calls_set_foreground_window": bool(operator.calls_set_foreground_window),
            },
            "success_windows_preserved": bool(getattr(settings, "background_keep_success_browser", False)),
            "log_path": str(log_path),
        }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="后台当前层串行 live 验证：固定存钻前 2 个账号。")
    parser.add_argument("--game-path", default=DEFAULT_GAME_PATH)
    parser.add_argument("--settings-path", default=str(app_root() / "automation_settings.json"))
    parser.add_argument("--output-dir", default=str(app_root() / "debug_background"))
    parser.add_argument("--launch-timeout", type=float, default=45.0)
    parser.add_argument("--reuse-existing-test-windows", action="store_true")
    args = parser.parse_args()

    try:
        run_background_serial_limit2(
            settings_path=Path(args.settings_path),
            game_path=str(args.game_path),
            output_dir=Path(args.output_dir),
            launch_timeout_seconds=float(args.launch_timeout),
            reuse_existing_windows=bool(args.reuse_existing_test_windows),
        )
        return 0
    except Exception as exc:
        print(f"live_background_serial_limit2 failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
