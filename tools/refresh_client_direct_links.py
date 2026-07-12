#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
import threading
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.automation import AccountRunner
from douluo_launcher.client_cdp import mask_sensitive_text
from douluo_launcher.config import AccountConfig, load_settings
from douluo_launcher.direct_link_refresh import (
    DEFAULT_CHANNEL_NAME,
    LOGIN_ENDPOINT,
    AccountsStore,
    BookmarkUrlUpdater,
    BookmarkWriteContext,
    CaptureFailed,
    ChannelConfig,
    DirectLinkRefreshService,
    DirectLoginFields,
    LoginFailed,
    RefreshAccount,
    RefreshResult,
    default_refresh_data_dir,
    ensure_refresh_data_dir,
    import_accounts_from_file,
    load_channels,
    merge_accounts_by_name,
    redact_sensitive_text,
)
from douluo_launcher.direct_link_login import (
    DirectLinkLoginOptions,
    capture_account_fields_http,
    create_login_capturer,
    load_http_har_for_mode,
)


DEFAULT_SETTINGS = PROJECT_ROOT / "automation_settings.json"
DEFAULT_HTTP_HAR = PROJECT_ROOT / "docs" / "111.cn.har"


def _mask_piece(value: object, *, keep: int = 3) -> str:
    text = str(value if value is not None else "")
    if not text:
        return "<empty>"
    if len(text) <= keep * 2:
        return "*" * len(text)
    return f"{text[:keep]}***{text[-keep:]}"


def _safe_log(message: object, *, username: str = "", password: str = "") -> None:
    text = redact_sensitive_text(mask_sensitive_text(message))
    if username:
        text = text.replace(username, _mask_piece(username, keep=2))
    if password:
        text = text.replace(password, "***PASSWORD***")
    print(text, flush=True)


def _parse_json_or_jsonp(text: str) -> dict[str, object]:
    clean = str(text or "").strip()
    match = re.match(r"^[\w$.]+\((.*)\)\s*;?$", clean, re.S)
    if match:
        clean = match.group(1)
    try:
        payload = json.loads(clean)
    except json.JSONDecodeError as exc:
        raise CaptureFailed(f"h5sdk/login 响应不是有效 JSON/JSONP: {exc}") from exc
    if not isinstance(payload, dict):
        raise CaptureFailed("h5sdk/login 响应不是对象")
    return payload


def _extract_login_fields(payload: dict[str, object]) -> DirectLoginFields:
    state = payload.get("state")
    if str(state) not in {"1", "True", "true"}:
        message = str(payload.get("msg") or "登录接口返回失败")
        raise LoginFailed(message)
    data = payload.get("data")
    if not isinstance(data, dict):
        raise CaptureFailed("h5sdk/login 响应缺少 data 对象")
    fields = DirectLoginFields(
        token=str(data.get("token") or ""),
        time=str(data.get("time") or ""),
        sign=str(data.get("sign") or ""),
        uid=str(data.get("uid") or ""),
        uname=str(data.get("uname") or ""),
    )
    try:
        fields.validate()
    except ValueError as exc:
        raise CaptureFailed(str(exc)) from exc
    return fields


def _field_summary(fields: DirectLoginFields) -> str:
    return (
        f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
        f"token_len={len(fields.token)} time_len={len(fields.time)} sign_len={len(fields.sign)}"
    )


def _capture_account_fields(args: argparse.Namespace, account: RefreshAccount, channel: ChannelConfig) -> DirectLoginFields:
    settings = load_settings(args.settings)
    runner = AccountRunner(
        AccountConfig(
            level="刷新地址",
            bookmark_no=0,
            game_window_no=0,
            url=channel.web_login_url,
            bookmark_title=account.name,
        ),
        settings,
        threading.Event(),
        log=lambda message: _safe_log(message, username=account.username, password=account.password),
        update_status=lambda _account, status: _safe_log(f"[{account.name}] status={status}"),
    )
    runner._prepare_playwright_runtime()

    from playwright.sync_api import sync_playwright

    playwright = None
    browser = None
    try:
        playwright = sync_playwright().start()
        launcher = getattr(playwright, settings.browser)
        browser = launcher.launch(
            headless=bool(args.headless),
            args=[
                f"--window-size={settings.window_width},{settings.window_height}",
                "--window-position=100,100",
            ],
        )
        page = browser.new_page(viewport={"width": settings.window_width, "height": settings.window_height})
        _safe_log(f"[{account.name}] 打开登录页 host={urlparse(channel.web_login_url).netloc}")
        page.goto(channel.web_login_url, wait_until="domcontentloaded", timeout=settings.page_load_timeout_ms)
        if not runner._detect_login_form(page):
            raise LoginFailed("未检测到账号密码登录界面")

        with page.expect_response(
            lambda response: LOGIN_ENDPOINT in response.url,
            timeout=float(args.capture_timeout) * 1000,
        ) as response_info:
            runner._fill_and_submit_login(page, account.username, account.password)

        response = response_info.value
        query_keys = [key for key, _value in parse_qsl(urlparse(response.url).query, keep_blank_values=True)]
        payload = _parse_json_or_jsonp(response.text())
        fields = _extract_login_fields(payload)
        _safe_log(f"[{account.name}] 捕获 h5sdk/login query_keys={','.join(query_keys)}")
        _safe_log(f"[{account.name}] 字段: {_field_summary(fields)}")
        return fields
    finally:
        if browser is not None:
            try:
                browser.close()
            except Exception:
                pass
        if playwright is not None:
            try:
                playwright.stop()
            except Exception:
                pass


def _capture_account_fields_http(
    args: argparse.Namespace,
    account: RefreshAccount,
    channel: ChannelConfig,
    har_payload: dict[str, object],
    stop_event: threading.Event | None = None,
) -> DirectLoginFields:
    return capture_account_fields_http(
        _login_options_from_args(args),
        account,
        channel,
        har_payload,
        stop_event=stop_event,
        log=lambda message: _safe_log(message, username=account.username, password=account.password),
    )


def _login_options_from_args(args: argparse.Namespace) -> DirectLinkLoginOptions:
    return DirectLinkLoginOptions(
        mode=str(args.login_mode or "auto"),
        http_har=Path(args.http_har),
        http_timeout=float(args.http_timeout),
        http_connect_timeout=float(getattr(args, "http_connect_timeout", 5.0)),
        http_read_timeout=float(getattr(args, "http_read_timeout", 2.0)),
    )


def _build_login_capturer(
    args: argparse.Namespace,
    har_payload: dict[str, object] | None,
):
    return create_login_capturer(
        _login_options_from_args(args),
        har_payload,
        playwright_capturer=lambda account, channel, _stop: _capture_account_fields(args, account, channel),
        http_capturer=lambda account, channel, payload, stop_event: _capture_account_fields_http(
            args, account, channel, payload, stop_event
        ),
        log=lambda message: _safe_log(message),
        fallback_confirm=lambda account_name: input(
            f"[{account_name}] HTTP 登录失败，是否明确回退 Playwright？ [y/N]: "
        ).strip().lower() in {"y", "yes"},
    )


def _load_http_har_for_mode(args: argparse.Namespace) -> dict[str, object] | None:
    return load_http_har_for_mode(_login_options_from_args(args), log=lambda message: _safe_log(message))


def _print_import_failures(failures) -> None:
    for failure in failures:
        _safe_log(f"[import] row={failure.row_number} status={failure.status} message={failure.message}")


def _print_progress(result: RefreshResult) -> None:
    status = result.status
    detail = result.message
    _safe_log(f"[{result.name}] {status}: {detail}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="刷新客户端直登地址，并写入本地账号库/直登链接库。")
    parser.add_argument("--import-file", type=Path, default=None, help="导入 csv/txt/xlsx 账号文件后刷新。")
    parser.add_argument("--channel", default=DEFAULT_CHANNEL_NAME, help=f"登录渠道名。默认：{DEFAULT_CHANNEL_NAME}")
    parser.add_argument("--name", default="", help="只刷新指定 name。")
    parser.add_argument("--limit", type=int, default=0, help="只刷新前 N 个账号。0 表示不限制。")
    parser.add_argument("--expire-days", type=int, default=22, help="过期提示天数。默认 22。")
    parser.add_argument("--data-dir", type=Path, default=default_refresh_data_dir(), help=f"数据目录。默认：{default_refresh_data_dir()}")
    bookmark_mode = parser.add_mutually_exclusive_group()
    bookmark_mode.add_argument("--dry-run", action="store_true", help="只预览收藏夹写回；本地账号库、链接库和 .url 仍会更新。")
    bookmark_mode.add_argument("--write-bookmarks", action="store_true", help="按显式提供的收藏夹上下文执行安全写回。")
    parser.add_argument("--bookmark-file", type=Path, default=None, help="Chromium Bookmarks 文件；真实写回时必填。")
    parser.add_argument("--bookmark-browser", choices=("Edge", "Chrome"), default="", help="浏览器类型；真实写回时必填。")
    parser.add_argument("--bookmark-profile", default="", help="浏览器 profile 名；真实写回时必填。")
    parser.add_argument("--bookmark-root-path", default="", help="已确认的收藏夹根节点结构路径；真实写回时必填。")
    parser.add_argument("--bookmark-root-name", default="", help="CSV bookmark_path 可省略的收藏夹根目录名。")
    parser.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS, help=f"自动化设置路径。默认：{DEFAULT_SETTINGS}")
    parser.add_argument(
        "--login-mode",
        choices=("auto", "http", "playwright"),
        default="auto",
        help="登录模式：auto=HTTP 优先失败回退 Playwright，http=仅 HTTP，playwright=仅浏览器。默认 auto。",
    )
    parser.add_argument("--http-har", type=Path, default=DEFAULT_HTTP_HAR, help=f"HTTP 登录研究 HAR。默认：{DEFAULT_HTTP_HAR}")
    parser.add_argument("--http-timeout", type=float, default=30.0, help="纯 HTTP 单次请求超时秒数。默认 30。")
    parser.add_argument("--http-connect-timeout", type=float, default=5.0, help="纯 HTTP 连接超时秒数。默认 5。")
    parser.add_argument("--http-read-timeout", type=float, default=2.0, help="纯 HTTP 读取无响应超时秒数。默认 2。")
    parser.add_argument("--capture-timeout", type=float, default=30.0, help="Playwright 捕获 h5sdk/login 超时秒数。默认 30。")
    parser.add_argument("--headless", action="store_true", help="使用无头浏览器捕获登录接口。")
    parser.add_argument("--retries", type=int, default=1, help="单账号失败重试次数。默认 1。")
    return parser.parse_args()


def _bookmark_updater_from_args(args: argparse.Namespace, paths) -> BookmarkUrlUpdater:
    write_bookmarks = bool(getattr(args, "write_bookmarks", False))
    if not write_bookmarks:
        return BookmarkUrlUpdater(dry_run=True, log=lambda message: _safe_log(message))

    bookmark_file = getattr(args, "bookmark_file", None)
    browser = str(getattr(args, "bookmark_browser", "") or "").strip()
    profile = str(getattr(args, "bookmark_profile", "") or "").strip()
    root_path = str(getattr(args, "bookmark_root_path", "") or "").strip()
    missing = [
        name
        for name, value in (
            ("--bookmark-file", bookmark_file),
            ("--bookmark-browser", browser),
            ("--bookmark-profile", profile),
            ("--bookmark-root-path", root_path),
        )
        if not value
    ]
    if missing:
        raise ValueError("真实收藏夹写回缺少显式参数: " + ", ".join(missing))

    context = BookmarkWriteContext(
        bookmark_file=Path(bookmark_file),
        browser=browser,
        profile=profile,
        root_path=root_path,
        root_name=str(getattr(args, "bookmark_root_name", "") or "").strip(),
    )
    return BookmarkUrlUpdater(
        context=context,
        backups_dir=paths.backups_dir,
        dry_run=False,
        log=lambda message: _safe_log(message),
    )


def main() -> int:
    args = parse_args()
    paths = ensure_refresh_data_dir(args.data_dir)
    channels = load_channels(args.data_dir)
    if args.channel not in channels:
        _safe_log(f"[ERROR] 未找到渠道：{args.channel}。可用渠道：{', '.join(channels)}")
        return 1

    account_store = AccountsStore(paths.accounts_path)
    accounts = account_store.load()
    refresh_candidates = accounts

    _safe_log(f"[refresh] data_dir={paths.data_dir}")
    _safe_log(f"[refresh] accounts={paths.accounts_path}")
    _safe_log(f"[refresh] direct_links={paths.direct_links_path}")
    _safe_log(f"[refresh] url_dir={paths.url_dir}")
    _safe_log(f"[refresh] summary={paths.summary_path}")

    if args.import_file is not None:
        if not args.import_file.exists():
            _safe_log(f"[ERROR] 账号文件不存在：{args.import_file}")
            return 1
        imported = import_accounts_from_file(args.import_file, channel=args.channel)
        refresh_candidates = imported.accounts
        accounts = merge_accounts_by_name([*accounts, *imported.accounts])
        account_store.save(accounts)
        _safe_log(f"[import] imported={len(imported.accounts)} failures={len(imported.failures)}")
        _print_import_failures(imported.failures)

    selected_names = {args.name.strip()} if args.name.strip() else None
    selected_count = len(
        [account for account in refresh_candidates if not selected_names or account.name in selected_names]
    )
    if args.limit and args.limit > 0:
        selected_count = min(selected_count, int(args.limit))
    if selected_count <= 0:
        _safe_log("[refresh] 没有可刷新账号。请先使用 --import-file 导入，或维护 accounts.enc.json。")
        return 0

    try:
        http_har_payload = _load_http_har_for_mode(args)
    except Exception as exc:
        _safe_log(f"[ERROR] HTTP 登录初始化失败: {redact_sensitive_text(exc)}")
        return 1
    _safe_log(
        f"[refresh] login_mode={args.login_mode} "
        f"http_ready={http_har_payload is not None}"
    )

    try:
        bookmark_updater = _bookmark_updater_from_args(args, paths)
    except ValueError as exc:
        _safe_log(f"[ERROR] {exc}")
        return 1

    service = DirectLinkRefreshService(
        data_dir=args.data_dir,
        login_capturer=_build_login_capturer(args, http_har_payload),
        bookmark_updater=bookmark_updater,
        expire_days=args.expire_days,
        log=lambda message: _safe_log(message),
    )
    summary = service.refresh_accounts(
        refresh_candidates,
        channel_name=args.channel,
        names=selected_names,
        limit=args.limit,
        retries=args.retries,
        progress=_print_progress,
    )
    _safe_log(
        "[refresh] done "
        f"total={summary.total} success={summary.success} failure={summary.failure} "
        f"local_links={summary.local_links} bookmark_success={summary.bookmark_success} "
        f"bookmark_skipped={getattr(summary, 'bookmark_skipped', 0)} "
        f"bookmark_failure={summary.bookmark_failure}"
    )
    return 0 if summary.failure == 0 else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        _safe_log(f"[ERROR] {exc}")
        raise SystemExit(1)
