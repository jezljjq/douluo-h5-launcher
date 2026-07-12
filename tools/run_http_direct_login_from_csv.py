#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.direct_link_refresh import (
    RefreshAccount,
    build_client_direct_url,
    default_channel_config,
    import_accounts_from_file,
)
from tools.probe_http_direct_login import (
    DEFAULT_HAR,
    DEFAULT_WEB_LOGIN_URL,
    http_login_from_har,
    load_har,
    sanitize_probe_text,
)


def select_accounts_from_csv(
    csv_path: Path,
    *,
    name: str = "",
    limit: int = 1,
) -> list[RefreshAccount]:
    if limit < 1:
        raise ValueError("--limit 必须大于等于 1")
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV 不存在: {csv_path}")

    imported = import_accounts_from_file(csv_path)
    accounts = [
        account
        for account in imported.accounts
        if account.enabled
        and str(account.username or "").strip()
        and str(account.password or "")
    ]
    clean_name = str(name or "").strip()
    if clean_name:
        accounts = [account for account in accounts if account.name == clean_name]
    if not accounts:
        detail = f"；导入失败行数={len(imported.failures)}" if imported.failures else ""
        raise ValueError(f"CSV 中没有可用账号{detail}")
    return accounts[:limit]


def sanitize_account_error(exc: Exception, account: RefreshAccount) -> str:
    text = sanitize_probe_text(exc)
    for secret in (account.username, account.password):
        if secret:
            text = text.replace(str(secret), "***")
    return text


def run_accounts(
    *,
    csv_path: Path,
    har_path: Path,
    name: str,
    limit: int,
    timeout: float,
    web_login_url: str,
) -> int:
    if not har_path.exists():
        raise FileNotFoundError(f"HAR 不存在: {har_path}")
    payload = load_har(har_path)
    accounts = select_accounts_from_csv(csv_path, name=name, limit=limit)
    failures = 0

    for index, account in enumerate(accounts, start=1):
        try:
            fields = http_login_from_har(
                har_payload=payload,
                username=account.username,
                password=account.password,
                web_login_url=web_login_url,
                timeout=timeout,
            )
            direct_url = build_client_direct_url(fields, channel=default_channel_config())
            parsed = urlparse(direct_url)
            query_keys = sorted(key for key, _value in parse_qsl(parsed.query, keep_blank_values=True))
            print(
                "[ACCOUNT] "
                f"index={index}/{len(accounts)} status=success "
                f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
                f"token_len={len(fields.token)} time_len={len(fields.time)} "
                f"sign_len={len(fields.sign)}",
                flush=True,
            )
            print(
                "[DIRECT] "
                f"ready=True host={parsed.netloc} path={parsed.path} "
                f"query_keys={','.join(query_keys)}",
                flush=True,
            )
        except Exception as exc:
            failures += 1
            print(
                "[ACCOUNT] "
                f"index={index}/{len(accounts)} status=failed "
                f"error={sanitize_account_error(exc, account)}",
                file=sys.stderr,
                flush=True,
            )
    return 1 if failures else 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="从本地 CSV 选择账号，执行纯 HTTP 客户端直登凭证验证；不修改原 CSV。"
    )
    parser.add_argument("--csv", type=Path, required=True, help="账号 CSV/TXT/XLSX 文件。")
    parser.add_argument("--name", default="", help="可选：按账号名称精确选择。")
    parser.add_argument("--limit", type=int, default=1, help="最多验证多少条账号。默认 1。")
    parser.add_argument("--har", type=Path, default=DEFAULT_HAR, help=f"登录研究 HAR。默认：{DEFAULT_HAR}")
    parser.add_argument("--web-login-url", default=DEFAULT_WEB_LOGIN_URL, help="37 网页登录入口。")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次 HTTP 超时秒数。默认 30。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return run_accounts(
        csv_path=args.csv,
        har_path=args.har,
        name=args.name,
        limit=args.limit,
        timeout=args.timeout,
        web_login_url=args.web_login_url,
    )


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {sanitize_probe_text(exc)}", file=sys.stderr)
        raise SystemExit(1)
