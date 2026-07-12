from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from threading import Event
from typing import Callable

from tools.probe_http_direct_login import http_login_from_har, load_har, sanitize_probe_text

from .config import app_root, source_project_root
from .direct_link_refresh import ChannelConfig, DirectLoginFields, LoginFailed, RefreshAccount


DEFAULT_HTTP_HAR = (source_project_root() or app_root()) / "docs" / "111.cn.har"
LOGIN_MODES = {"auto", "http", "playwright"}


@dataclass(frozen=True)
class DirectLinkLoginOptions:
    mode: str = "auto"
    http_har: Path = DEFAULT_HTTP_HAR
    http_timeout: float = 30.0
    http_connect_timeout: float = 5.0
    http_read_timeout: float = 2.0

    @property
    def normalized_mode(self) -> str:
        mode = str(self.mode or "auto").strip().lower()
        if mode not in LOGIN_MODES:
            raise ValueError(f"未知刷新登录模式: {mode}")
        return mode


LoginCapturer = Callable[[RefreshAccount, ChannelConfig, Event | None], DirectLoginFields]
HttpCapturer = Callable[[RefreshAccount, ChannelConfig, dict[str, object], Event | None], DirectLoginFields]
LogCallback = Callable[[str], None]
FallbackConfirm = Callable[[str], bool]


def load_http_har_for_mode(
    options: DirectLinkLoginOptions,
    *,
    log: LogCallback | None = None,
) -> dict[str, object] | None:
    logger = log or (lambda _message: None)
    mode = options.normalized_mode
    if mode == "playwright":
        return None
    if not options.http_har.exists():
        raise FileNotFoundError(f"HTTP 研究 HAR 不存在: {options.http_har}")
    try:
        return load_har(options.http_har)
    except Exception as exc:
        raise


def capture_account_fields_http(
    options: DirectLinkLoginOptions,
    account: RefreshAccount,
    channel: ChannelConfig,
    har_payload: dict[str, object],
    *,
    stop_event: Event | None = None,
    log: LogCallback | None = None,
) -> DirectLoginFields:
    logger = log or (lambda _message: None)
    logger(f"[{account.name}] 纯 HTTP 刷新")
    fields = http_login_from_har(
        har_payload=har_payload,
        username=account.username,
        password=account.password,
        web_login_url=channel.web_login_url,
        timeout=float(options.http_timeout),
        connect_timeout=float(options.http_connect_timeout),
        read_timeout=float(options.http_read_timeout),
        stop_check=lambda: _raise_if_stopped(stop_event),
    )
    logger(
        f"[{account.name}] HTTP 刷新成功 "
        f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
        f"token_len={len(fields.token)} time_len={len(fields.time)} sign_len={len(fields.sign)}"
    )
    return fields


def create_login_capturer(
    options: DirectLinkLoginOptions,
    har_payload: dict[str, object] | None,
    *,
    playwright_capturer: LoginCapturer,
    http_capturer: HttpCapturer | None = None,
    log: LogCallback | None = None,
    fallback_confirm: FallbackConfirm | None = None,
) -> LoginCapturer:
    logger = log or (lambda _message: None)
    mode = options.normalized_mode
    http_capture = http_capturer or (
        lambda account, channel, payload, stop_event: capture_account_fields_http(
            options,
            account,
            channel,
            payload,
            stop_event=stop_event,
            log=logger,
        )
    )

    def capture(account: RefreshAccount, channel: ChannelConfig, stop_event: Event | None) -> DirectLoginFields:
        _raise_if_stopped(stop_event)
        if mode in {"auto", "http"} and har_payload is not None:
            try:
                return http_capture(account, channel, har_payload, stop_event)
            except Exception as exc:
                logger(_mask_account_values(f"[{account.name}] HTTP 登录失败: {sanitize_probe_text(exc)}", account))
                if mode == "http":
                    raise
                _raise_if_stopped(stop_event)
                if fallback_confirm is None or not fallback_confirm(account.name):
                    raise LoginFailed("HTTP 登录失败，用户未确认回退 Playwright") from exc
                logger(f"[{account.name}] 用户已确认回退 Playwright 登录")
        elif mode in {"auto", "http"}:
            raise FileNotFoundError(f"HTTP 研究 HAR 不可用: {options.http_har}")

        _raise_if_stopped(stop_event)
        return playwright_capturer(account, channel, stop_event)

    return capture


def _raise_if_stopped(stop_event: Event | None) -> None:
    if stop_event is not None and stop_event.is_set():
        raise InterruptedError("用户停止")


def _mask_account_values(message: object, account: RefreshAccount) -> str:
    text = str(message if message is not None else "")
    if account.username:
        text = text.replace(account.username, "***ACCOUNT***")
    if account.password:
        text = text.replace(account.password, "***PASSWORD***")
    return text
