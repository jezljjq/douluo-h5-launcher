#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, unquote, urljoin, urlparse, urlunparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from douluo_launcher.direct_link_refresh import (
    CaptureFailed,
    DirectLoginFields,
    LoginFailed,
    build_client_direct_url,
    default_channel_config,
    redact_sensitive_text,
)

LOGIN_ENDPOINT = "s-api.37.com.cn/h5sdk/login"
ACTIVE_ENDPOINT = "m-api.37.com.cn/h5sdk/active"
SDK_BUNDLE_PATH = "/h5game/public/bundle.js"
REFERENCE_HAR = PROJECT_ROOT / "docs" / "111.cn.har"
DEFAULT_HAR = REFERENCE_HAR
DEFAULT_WEB_LOGIN_URL = "http://37.com.cn/h5game/public/?pid=1&gid=1005172&refer=1_100172_10552_1"
USERNAME_KEYS = {"username", "user", "account", "loginname", "login_name", "uname", "passport"}
PASSWORD_KEYS = {"password", "passwd", "pwd", "pass", "upwd"}
SAFE_HEADER_NAMES = {
    "accept",
    "accept-language",
    "content-type",
    "origin",
    "referer",
    "user-agent",
    "x-requested-with",
}
SENSITIVE_FIELD_NAMES = USERNAME_KEYS | PASSWORD_KEYS | {
    "token",
    "sign",
    "cookie",
    "session",
    "authorization",
    "direct_url",
}


@dataclass(frozen=True)
class HarRequestTemplate:
    method: str
    base_url: str
    query: dict[str, str]
    body: dict[str, str]
    headers: dict[str, str]
    mime_type: str


@dataclass(frozen=True)
class SdkConfig:
    version: str
    values: dict[str, str]

    @property
    def api_key(self) -> str:
        value = str(self.values.get("API_KEY") or "")
        if not value:
            raise ValueError("SDK 配置缺少 API_KEY")
        return value


def sanitize_probe_text(value: object) -> str:
    text = redact_sensitive_text(str(value or ""))
    for name in sorted(SENSITIVE_FIELD_NAMES, key=len, reverse=True):
        text = re.sub(
            rf"(?i)({re.escape(name)}\s*[=:]\s*)[^&\s\"'<>}}]+",
            r"\1***",
            text,
        )
    return text


def parse_json_or_jsonp(text: str) -> dict[str, Any]:
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


def extract_direct_login_fields(payload: dict[str, Any]) -> DirectLoginFields:
    state = payload.get("state")
    if str(state) not in {"1", "True", "true"}:
        raise LoginFailed(str(payload.get("msg") or "登录接口返回失败"))
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


def _name_value_map(items: object) -> dict[str, str]:
    result: dict[str, str] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if name:
            result[name] = str(item.get("value") or "")
    return result


def _flatten_keys(value: object, prefix: str = "") -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            name = f"{prefix}.{key}" if prefix else str(key)
            keys.append(name)
            keys.extend(_flatten_keys(child, name))
    elif isinstance(value, list) and value:
        keys.extend(_flatten_keys(value[0], f"{prefix}[]"))
    return keys


def _post_data_map(post_data: object) -> tuple[dict[str, str], str]:
    if not isinstance(post_data, dict):
        return {}, ""
    mime_type = str(post_data.get("mimeType") or "")
    params = _name_value_map(post_data.get("params"))
    if params:
        return params, mime_type
    text = str(post_data.get("text") or "")
    if not text:
        return {}, mime_type
    if "json" in mime_type.lower():
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}, mime_type
        if isinstance(payload, dict):
            return {str(key): str(value) for key, value in payload.items()}, mime_type
        return {}, mime_type
    return {key: value for key, value in parse_qsl(text, keep_blank_values=True)}, mime_type


def _har_content_text(content: object) -> str:
    if not isinstance(content, dict):
        return ""
    text = str(content.get("text") or "")
    if not text or str(content.get("encoding") or "").lower() != "base64":
        return text
    try:
        return base64.b64decode(text).decode("utf-8", errors="replace")
    except Exception:
        return ""


def analyze_har_payload(payload: dict[str, Any]) -> list[dict[str, object]]:
    log = payload.get("log") if isinstance(payload, dict) else None
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        raise ValueError("HAR 缺少 log.entries")
    report: list[dict[str, object]] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        request = entry.get("request")
        response = entry.get("response")
        if not isinstance(request, dict):
            continue
        parsed = urlparse(str(request.get("url") or ""))
        query = {key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)}
        body, mime_type = _post_data_map(request.get("postData"))
        headers = _name_value_map(request.get("headers"))
        cookies = _name_value_map(request.get("cookies"))
        response_keys: list[str] = []
        if isinstance(response, dict):
            response_text = _har_content_text(response.get("content"))
            if response_text and LOGIN_ENDPOINT in f"{parsed.netloc}{parsed.path}":
                try:
                    response_keys = sorted(set(_flatten_keys(parse_json_or_jsonp(response_text))))
                except Exception:
                    response_keys = []
        report.append(
            {
                "index": index,
                "method": str(request.get("method") or "GET").upper(),
                "host": parsed.netloc,
                "path": parsed.path,
                "status": int(response.get("status") or 0) if isinstance(response, dict) else 0,
                "query_keys": sorted(query),
                "body_keys": sorted(body),
                "query_value_lengths": {key: len(value) for key, value in sorted(query.items())},
                "body_value_lengths": {key: len(value) for key, value in sorted(body.items())},
                "header_names": sorted({name.lower() for name in headers}),
                "cookie_names": sorted(cookies),
                "mime_type": mime_type,
                "response_keys": response_keys,
            }
        )
    return report


def load_har(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError("HAR 根节点不是对象")
    return payload


def calculate_sdk_sign(params: dict[str, object], api_key: str) -> str:
    clean = {
        str(key): str(value)
        for key, value in params.items()
        if str(key).lower() not in {"callback", "sign"}
    }
    source = "".join(f"{key}={clean[key]}" for key in sorted(clean)) + str(api_key)
    return hashlib.md5(source.encode("utf-8")).hexdigest()


def _decode_sdk_config(encoded: str) -> dict[str, str]:
    code = unquote(str(encoded or ""))
    if not code:
        raise ValueError("SDK 编码配置为空")
    decoded = chr(ord(code[0]) - len(code))
    for character in code[1:]:
        decoded += chr(ord(character) - ord(decoded[-1]))
    payload = json.loads(decoded)
    if not isinstance(payload, dict):
        raise ValueError("SDK 解码配置不是对象")
    return {str(key): str(value) for key, value in payload.items()}


def extract_sdk_config_from_bundle(bundle_text: str) -> SdkConfig:
    module_match = re.search(
        r"/\*\s*66\s*\*/\s*/\*\*\*/\s*\(function\(module, exports[^)]*\)\s*\{(.*?)"
        r"\n\s*/\*\*\*/\s*\}\),\s*/\*\s*67\s*\*/",
        str(bundle_text or ""),
        re.S,
    )
    if not module_match:
        raise ValueError("bundle.js 中未找到 SDK 配置模块 66")
    payload_match = re.search(r"module\.exports\s*=\s*(\{.*\})\s*$", module_match.group(1), re.S)
    if not payload_match:
        raise ValueError("SDK 配置模块 66 缺少 module.exports")
    module_payload = json.loads(payload_match.group(1))
    if not isinstance(module_payload, dict):
        raise ValueError("SDK 配置模块 66 不是对象")
    version = str(module_payload.get("version") or "")
    values = _decode_sdk_config(str(module_payload.get("config") or ""))
    config = SdkConfig(version=version, values=values)
    config.api_key
    return config


def _har_entries(payload: dict[str, Any]) -> list[dict[str, Any]]:
    log = payload.get("log") if isinstance(payload, dict) else None
    entries = log.get("entries") if isinstance(log, dict) else None
    if not isinstance(entries, list):
        raise ValueError("HAR 缺少 log.entries")
    return [entry for entry in entries if isinstance(entry, dict)]


def _find_bundle_entry(payload: dict[str, Any]) -> tuple[str, str]:
    for entry in _har_entries(payload):
        request = entry.get("request")
        response = entry.get("response")
        if not isinstance(request, dict):
            continue
        parsed = urlparse(str(request.get("url") or ""))
        if parsed.path != SDK_BUNDLE_PATH:
            continue
        text = _har_content_text(response.get("content")) if isinstance(response, dict) else ""
        return urlunparse((parsed.scheme or "http", parsed.netloc, parsed.path, "", parsed.query, "")), text
    raise ValueError("HAR 中未找到 37 SDK bundle.js")


def extract_sdk_config_from_har(payload: dict[str, Any]) -> SdkConfig:
    _bundle_url, bundle_text = _find_bundle_entry(payload)
    if not bundle_text:
        raise ValueError("HAR 的 bundle.js 缺少响应内容")
    return extract_sdk_config_from_bundle(bundle_text)


def _normalized_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value or "").lower())


def _key_matches(key: str, candidates: set[str]) -> bool:
    raw = str(key or "").lower()
    normalized = _normalized_key(raw)
    for candidate in candidates:
        candidate_raw = str(candidate).lower()
        candidate_normalized = _normalized_key(candidate_raw)
        if normalized == candidate_normalized:
            return True
        if any(raw.endswith(separator + candidate_raw) for separator in ("_", "-", ".")):
            return True
        if len(candidate_normalized) >= 5 and normalized.endswith(candidate_normalized):
            return True
    return False


def _template_has_credentials(template: HarRequestTemplate) -> bool:
    keys = [*template.query, *template.body]
    return any(_key_matches(key, USERNAME_KEYS) for key in keys) and any(
        _key_matches(key, PASSWORD_KEYS) for key in keys
    )


def find_request_template(
    payload: dict[str, Any],
    endpoint: str,
    *,
    require_credentials: bool = False,
) -> HarRequestTemplate:
    fallback: HarRequestTemplate | None = None
    for entry in _har_entries(payload):
        request = entry.get("request")
        if not isinstance(request, dict):
            continue
        raw_url = str(request.get("url") or "")
        if endpoint not in raw_url:
            continue
        method = str(request.get("method") or "GET").upper()
        if method == "OPTIONS":
            continue
        parsed = urlparse(raw_url)
        body, mime_type = _post_data_map(request.get("postData"))
        raw_headers = _name_value_map(request.get("headers"))
        headers = {
            name: value
            for name, value in raw_headers.items()
            if name.lower() in SAFE_HEADER_NAMES
        }
        template = HarRequestTemplate(
            method=method,
            base_url=urlunparse((parsed.scheme or "https", parsed.netloc, parsed.path, "", "", "")),
            query={key: value for key, value in parse_qsl(parsed.query, keep_blank_values=True)},
            body=body,
            headers=headers,
            mime_type=mime_type,
        )
        if not require_credentials or _template_has_credentials(template):
            return template
        if fallback is None:
            fallback = template
    if fallback is not None:
        return fallback
    raise ValueError(f"HAR 中未找到真实请求: {endpoint}")


def find_login_request_template(payload: dict[str, Any]) -> HarRequestTemplate:
    return find_request_template(payload, LOGIN_ENDPOINT, require_credentials=True)


def derive_active_template(login_template: HarRequestTemplate, sdk_config: SdkConfig) -> HarRequestTemplate:
    host = str(sdk_config.values.get("HOST") or "https://m-api.37.com.cn")
    init_api = str(sdk_config.values.get("INIT_API") or "/h5sdk/active")
    active_url = urljoin(host.rstrip("/") + "/", init_api.lstrip("/"))
    query = {
        key: value
        for key, value in login_template.query.items()
        if key.lower() not in {"autologin"}
        and not _key_matches(key, USERNAME_KEYS)
        and not _key_matches(key, PASSWORD_KEYS)
    }
    body = {
        key: value
        for key, value in login_template.body.items()
        if key.lower() not in {"autologin"}
        and not _key_matches(key, USERNAME_KEYS)
        and not _key_matches(key, PASSWORD_KEYS)
    }
    return HarRequestTemplate(
        method="GET",
        base_url=active_url,
        query=query,
        body=body,
        headers=dict(login_template.headers),
        mime_type="",
    )


def _find_key(values: dict[str, str], candidates: set[str], explicit: str = "") -> str:
    if explicit:
        expected = _normalized_key(explicit)
        for key in values:
            if _normalized_key(key) == expected:
                return key
        raise ValueError(f"请求中未找到指定字段: {explicit}")
    for key in values:
        if _key_matches(key, candidates):
            return key
    return ""


def _refresh_jsonp_callback(query: dict[str, str]) -> None:
    for key in list(query):
        if "callback" not in key.lower():
            continue
        old = query[key]
        if old:
            query[key] = f"jQuery{int(time.time() * 1000)}_{int(time.time() * 1000)}"


def _set_param(query: dict[str, str], body: dict[str, str], key: str, value: object) -> None:
    if key in body:
        body[key] = str(value)
    else:
        query[key] = str(value)


def _safe_request_headers(template: HarRequestTemplate, referer: str) -> dict[str, str]:
    headers = {
        name: value
        for name, value in template.headers.items()
        if name.lower() not in {"cookie", "authorization", "referer"}
    }
    headers["Referer"] = referer
    return headers


def _send_template_request(
    session: object,
    template: HarRequestTemplate,
    *,
    query: dict[str, str],
    body: dict[str, str],
    headers: dict[str, str],
    timeout: float | tuple[float, float],
    base_url: str | None = None,
):
    url = str(base_url or template.base_url)
    method = template.method.upper()
    if method == "GET":
        return session.get(url, params=query, headers=headers, timeout=timeout)
    if "json" in template.mime_type.lower():
        return session.request(method, url, params=query, json=body, headers=headers, timeout=timeout)
    return session.request(method, url, params=query, data=body, headers=headers, timeout=timeout)


def _prepare_signed_request(
    template: HarRequestTemplate,
    *,
    api_key: str,
    timestamp: int,
    sdk_version: str,
) -> tuple[dict[str, str], dict[str, str]]:
    query = dict(template.query)
    body = dict(template.body)
    if "time" in query or "time" in body:
        _set_param(query, body, "time", timestamp)
    if sdk_version and ("version" in query or "version" in body):
        _set_param(query, body, "version", sdk_version)
    combined = {**query, **body}
    sign = calculate_sdk_sign(combined, api_key)
    _set_param(query, body, "sign", sign)
    _refresh_jsonp_callback(query)
    return query, body


def http_login_from_har(
    *,
    har_payload: dict[str, Any],
    username: str,
    password: str,
    web_login_url: str = DEFAULT_WEB_LOGIN_URL,
    timeout: float = 30.0,
    connect_timeout: float | None = None,
    read_timeout: float | None = None,
    stop_check: Callable[[], None] | None = None,
    username_key: str = "",
    password_key: str = "",
) -> DirectLoginFields:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("缺少 requests，请先执行: pip install requests") from exc

    request_timeout = (
        float(connect_timeout if connect_timeout is not None else timeout),
        float(read_timeout if read_timeout is not None else timeout),
    )
    check_stopped = stop_check or (lambda: None)
    check_stopped()
    login_template = find_login_request_template(har_payload)
    reference_payload = har_payload
    try:
        bundle_url, har_bundle_text = _find_bundle_entry(har_payload)
    except ValueError:
        if not REFERENCE_HAR.exists():
            raise
        reference_payload = load_har(REFERENCE_HAR)
        bundle_url, har_bundle_text = _find_bundle_entry(reference_payload)
    header_lookup = {name.lower(): value for name, value in login_template.headers.items()}
    session = requests.Session()
    try:
        session.headers.update({"User-Agent": header_lookup.get("user-agent", "Mozilla/5.0")})
        check_stopped()
        init_response = session.get(web_login_url, timeout=request_timeout, allow_redirects=True)
        init_response.raise_for_status()
        check_stopped()

        bundle_text = har_bundle_text
        try:
            bundle_response = session.get(
                bundle_url,
                headers={"Referer": web_login_url},
                timeout=request_timeout,
            )
            bundle_response.raise_for_status()
            check_stopped()
            if str(bundle_response.text or "").strip():
                bundle_text = bundle_response.text
        except InterruptedError:
            raise
        except Exception:
            if not bundle_text:
                raise
        sdk_config = extract_sdk_config_from_bundle(bundle_text)
        try:
            active_template = find_request_template(har_payload, ACTIVE_ENDPOINT)
        except ValueError:
            try:
                active_template = find_request_template(reference_payload, ACTIVE_ENDPOINT)
            except ValueError:
                active_template = derive_active_template(login_template, sdk_config)

        timestamp = int(time.time())
        active_query, active_body = _prepare_signed_request(
            active_template,
            api_key=sdk_config.api_key,
            timestamp=timestamp,
            sdk_version=sdk_config.version,
        )
        check_stopped()
        active_response = _send_template_request(
            session,
            active_template,
            query=active_query,
            body=active_body,
            headers=_safe_request_headers(active_template, web_login_url),
            timeout=request_timeout,
        )
        active_response.raise_for_status()
        check_stopped()
        active_payload = parse_json_or_jsonp(active_response.text)
        if str(active_payload.get("state")) not in {"1", "True", "true"}:
            raise CaptureFailed(str(active_payload.get("msg") or "h5sdk/active 初始化失败"))

        login_query = dict(login_template.query)
        login_body = dict(login_template.body)
        combined = {**login_query, **login_body}
        user_field = _find_key(combined, USERNAME_KEYS, username_key)
        pass_field = _find_key(combined, PASSWORD_KEYS, password_key)
        if not user_field or not pass_field:
            raise ValueError(
                "无法自动识别账号密码字段；"
                f"query_keys={sorted(login_query)} body_keys={sorted(login_body)}，"
                "请使用 --username-key / --password-key 指定"
            )
        _set_param(login_query, login_body, user_field, username)
        _set_param(login_query, login_body, pass_field, password)
        _set_param(login_query, login_body, "time", int(time.time()))
        if sdk_config.version and ("version" in login_query or "version" in login_body):
            _set_param(login_query, login_body, "version", sdk_config.version)
        _set_param(
            login_query,
            login_body,
            "sign",
            calculate_sdk_sign({**login_query, **login_body}, sdk_config.api_key),
        )
        _refresh_jsonp_callback(login_query)

        login_url = login_template.base_url
        active_data = active_payload.get("data")
        if isinstance(active_data, dict):
            api = active_data.get("api")
            if isinstance(api, dict) and str(api.get("login") or "").strip():
                login_url = str(api["login"]).rstrip("/")
        check_stopped()
        response = _send_template_request(
            session,
            login_template,
            query=login_query,
            body=login_body,
            headers=_safe_request_headers(login_template, web_login_url),
            timeout=request_timeout,
            base_url=login_url,
        )
        response.raise_for_status()
        check_stopped()
        return extract_direct_login_fields(parse_json_or_jsonp(response.text))
    finally:
        close = getattr(session, "close", None)
        if callable(close):
            close()


def _format_length_map(value: object) -> str:
    if not isinstance(value, dict):
        return "<none>"
    return ",".join(f"{key}:{length}" for key, length in value.items()) or "<none>"


def _print_har_summary(payload: dict[str, Any]) -> None:
    report = analyze_har_payload(payload)
    login_rows = [row for row in report if row["host"] == "s-api.37.com.cn" and row["path"] == "/h5sdk/login"]
    print(f"[HAR] entries={len(report)} login_requests={len(login_rows)}")
    for row in login_rows:
        print(
            "[HAR] "
            f"index={row['index']} method={row['method']} status={row['status']} "
            f"query_keys={','.join(row['query_keys']) or '<none>'} "
            f"body_keys={','.join(row['body_keys']) or '<none>'} "
            f"query_lengths={_format_length_map(row['query_value_lengths'])} "
            f"body_lengths={_format_length_map(row['body_value_lengths'])} "
            f"headers={','.join(row['header_names']) or '<none>'} "
            f"cookies={','.join(row['cookie_names']) or '<none>'} "
            f"response_keys={','.join(row['response_keys']) or '<none>'}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="纯 HTTP 刷新客户端直登凭证 POC；不修改 GUI 和现有 Playwright 流程。")
    parser.add_argument("--har", type=Path, default=DEFAULT_HAR, help=f"登录 HAR。默认：{DEFAULT_HAR}")
    parser.add_argument("--analyze-only", action="store_true", help="只脱敏分析 HAR，不发起网络请求。")
    parser.add_argument("--web-login-url", default=DEFAULT_WEB_LOGIN_URL, help="37 网页登录入口。")
    parser.add_argument("--username-key", default="", help="HAR 中的账号字段名；自动识别失败时使用。")
    parser.add_argument("--password-key", default="", help="HAR 中的密码字段名；自动识别失败时使用。")
    parser.add_argument("--timeout", type=float, default=30.0, help="单次 HTTP 超时秒数。默认 30。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.har.exists():
        raise FileNotFoundError(f"HAR 不存在: {args.har}")
    payload = load_har(args.har)
    _print_har_summary(payload)
    if args.analyze_only:
        return 0

    username = input("登录账号（不保存）: ").strip()
    password = getpass.getpass("登录密码（不保存、不回显）: ")
    if not username or not password:
        raise ValueError("账号和密码不能为空")
    fields = http_login_from_har(
        har_payload=payload,
        username=username,
        password=password,
        web_login_url=args.web_login_url,
        timeout=args.timeout,
        username_key=args.username_key,
        password_key=args.password_key,
    )
    direct_url = build_client_direct_url(fields, channel=default_channel_config())
    parsed = urlparse(direct_url)
    print(
        "[HTTP] success=True "
        f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
        f"token_len={len(fields.token)} time_len={len(fields.time)} sign_len={len(fields.sign)}"
    )
    print(
        "[DIRECT] ready=True "
        f"host={parsed.netloc} path={parsed.path} "
        f"query_keys={','.join(sorted(key for key, _value in parse_qsl(parsed.query, keep_blank_values=True)))}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {sanitize_probe_text(exc)}", file=sys.stderr)
        raise SystemExit(1)
