#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.client_cdp import cdp_port_for_index, is_tcp_port_available, mask_sensitive_text
from douluo_launcher.client_direct_login import (
    ClientDirectLoginConfig,
    execute_client_direct_login,
    is_complete_direct_login_url,
)
from douluo_launcher.config import load_accounts_from_bookmarks, load_settings


DEFAULT_SETTINGS = PROJECT_ROOT / "automation_settings.json"
DEFAULT_X5GAME_EXE = Path(r"E:\Program Files\DLH5\X5Game.exe")


def log(message: object) -> None:
    print(mask_sensitive_text(message), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Batch live verifier for X5Game.exe client direct login.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--auto-enter-game", dest="auto_enter_game", action="store_true", default=True)
    mode.add_argument("--no-enter-game", dest="auto_enter_game", action="store_false")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument("--bookmark-file", type=Path, default=None)
    parser.add_argument("--root-name", default="")
    parser.add_argument("--base-port", type=int, default=9222)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--x5game-path", type=Path, default=DEFAULT_X5GAME_EXE)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--keep-existing", action="store_true", help="Do not taskkill existing X5Game.exe first.")
    return parser.parse_args()


def stop_existing_x5game() -> None:
    result = subprocess.run(
        ["taskkill", "/IM", "X5Game.exe", "/F"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="gbk",
        errors="replace",
    )
    if result.returncode == 0:
        log(result.stdout.strip())
        time.sleep(2)
    else:
        log("No running X5Game.exe process found, continuing.")


def load_candidate_accounts(args: argparse.Namespace):
    settings = load_settings(args.settings)
    bookmark_file = args.bookmark_file or Path(settings.bookmark_file)
    root_name = args.root_name or settings.bookmark_root_name
    if not str(bookmark_file).strip():
        raise ValueError("No bookmark file configured. Pass --bookmark-file or configure automation_settings.json.")
    accounts = load_accounts_from_bookmarks(
        bookmark_file,
        root_name,
        level_names=settings.level_names,
        account_group_settings=settings.account_group_settings,
        log=lambda message: log("[bookmarks] " + str(message)),
    )
    return [account for account in accounts if is_complete_direct_login_url(account.url)][: max(0, int(args.limit))]


def main() -> int:
    args = parse_args()
    if not args.keep_existing:
        log("Closing existing X5Game.exe before batch...")
        stop_existing_x5game()

    accounts = load_candidate_accounts(args)
    if not accounts:
        log("No complete client direct-login URLs found in selected accounts.")
        return 2

    log(f"Batch selected {len(accounts)} account(s). Limit={args.limit}")
    results = []
    for index, account in enumerate(accounts):
        port = cdp_port_for_index(index, base_port=args.base_port)
        log(f"[{index + 1}/{len(accounts)}] account={account.key} window={account.game_window_no} port={port}")
        if not is_tcp_port_available(port):
            payload = {
                "account": account.key,
                "port": port,
                "pid": 0,
                "hwnd": 0,
                "success": False,
                "status": "客户端直登失败",
                "message": f"CDP port {port} is already in use",
            }
            results.append(payload)
            log(json.dumps(payload, ensure_ascii=False))
            continue
        result = execute_client_direct_login(
            ClientDirectLoginConfig(
                account_id=account.key,
                account_name=account.display_name,
                full_login_url=account.url,
                x5game_path=args.x5game_path,
                cdp_port=port,
                auto_enter_game=bool(args.auto_enter_game),
                timeout=float(args.timeout),
            ),
            log=lambda message, key=account.key: log(f"[{key}] {message}"),
        )
        binding = result.binding
        payload = {
            "account": account.key,
            "port": port,
            "pid": int(getattr(binding, "pid", 0) or 0),
            "hwnd": int(getattr(binding, "hwnd", 0) or 0),
            "success": result.success,
            "status": result.status,
            "message": result.message,
        }
        results.append(payload)
        log(json.dumps(payload, ensure_ascii=False))

    ok_count = sum(1 for item in results if item["success"])
    log(f"Batch done: {ok_count}/{len(results)} success.")
    return 0 if ok_count == len(results) else 3


if __name__ == "__main__":
    raise SystemExit(main())
