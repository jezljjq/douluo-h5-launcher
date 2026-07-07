#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.client_cdp import mask_sensitive_text
from douluo_launcher.client_direct_login import (
    ClientDirectLoginConfig,
    execute_client_direct_login,
    is_complete_direct_login_url,
)


DEFAULT_X5GAME_EXE = Path(r"E:\Program Files\DLH5\X5Game.exe")
DEFAULT_URL_FILE = PROJECT_ROOT / "debug_login_chain" / "client_login_url.txt"


def log(message: object) -> None:
    print(mask_sensitive_text(message), flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="One-shot live verifier for X5Game.exe client direct login."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--auto-enter-game",
        dest="auto_enter_game",
        action="store_true",
        default=True,
        help="Navigate, call enterGame, and wait for game runtime markers. Default.",
    )
    mode.add_argument(
        "--no-enter-game",
        dest="auto_enter_game",
        action="store_false",
        help="Stop after importServer + notice readiness; do not call enterGame.",
    )
    parser.add_argument("--port", type=int, default=9222, help="CDP port. Default: 9222.")
    parser.add_argument(
        "--url-file",
        type=Path,
        default=DEFAULT_URL_FILE,
        help=f"File containing complete direct-login URL. Default: {DEFAULT_URL_FILE}",
    )
    parser.add_argument(
        "--x5game-path",
        type=Path,
        default=DEFAULT_X5GAME_EXE,
        help=f"X5Game.exe path. Default: {DEFAULT_X5GAME_EXE}",
    )
    parser.add_argument("--timeout", type=float, default=60.0, help="Login timeout seconds. Default: 60.")
    return parser.parse_args()


def stop_existing_x5game() -> None:
    log("[1/8] Closing existing X5Game.exe if present...")
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


def read_login_url(path: Path) -> str:
    log(f"[2/8] Reading client login URL from: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Login URL file does not exist: {path}")
    url = path.read_text(encoding="utf-8-sig").strip()
    if not url:
        raise ValueError(f"Login URL file is empty: {path}")
    if not is_complete_direct_login_url(url):
        raise ValueError("URL is not a complete client direct-login URL")
    parsed = urlparse(url)
    log(f"Loaded login URL entry: {parsed.hostname}{parsed.path} with direct-login params")
    return url


def main() -> int:
    args = parse_args()
    try:
        stop_existing_x5game()
        login_url = read_login_url(args.url_file)
        log(f"[3/8] Starting client direct login on CDP port {args.port}...")
        result = execute_client_direct_login(
            ClientDirectLoginConfig(
                account_id="live-once",
                account_name="live-once",
                full_login_url=login_url,
                x5game_path=args.x5game_path,
                cdp_port=args.port,
                auto_enter_game=bool(args.auto_enter_game),
                timeout=float(args.timeout),
            ),
            log=lambda message: log("[client] " + message),
        )
        log("[7/8] Final markers:")
        if result.check:
            log(json.dumps(result.check.markers.__dict__, ensure_ascii=False, indent=2))
            log(json.dumps(result.check.runtime.__dict__ if result.check.runtime else {}, ensure_ascii=False, indent=2))
        log("[8/8] Result:")
        if result.success:
            if args.auto_enter_game:
                log("client direct login success")
            else:
                log("客户端已就绪，未自动进入游戏。")
            return 0
        log(f"FAILED: {result.message}")
        return 3
    except Exception as exc:
        log(f"[ERROR] {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
