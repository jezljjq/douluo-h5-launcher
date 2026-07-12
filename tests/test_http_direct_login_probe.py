from __future__ import annotations

import hashlib
import json
import sys
import types
import unittest
from unittest.mock import patch
from urllib.parse import parse_qsl, quote, urlencode, urlparse

from tools.probe_http_direct_login import (
    PROJECT_ROOT,
    analyze_har_payload,
    calculate_sdk_sign,
    extract_direct_login_fields,
    extract_sdk_config_from_bundle,
    extract_sdk_config_from_har,
    http_login_from_har,
    load_har,
    parse_json_or_jsonp,
    sanitize_probe_text,
)


def _encode_sdk_config(payload: dict[str, str]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    encoded = chr(ord(raw[0]) + len(raw))
    for index in range(1, len(raw)):
        encoded += chr(ord(raw[index]) + ord(raw[index - 1]))
    return quote(encoded, safe="")


def _fake_bundle(*, api_key: str = "K", version: str = "1.2.3") -> str:
    module_payload = json.dumps(
        {
            "version": version,
            "config": _encode_sdk_config(
                {
                    "API_KEY": api_key,
                    "HOST": "https://example.test",
                    "INIT_API": "/h5sdk/active",
                    "ENCRYPT_KEY": "",
                    "ENCRYPT_HOST": "",
                }
            ),
        },
        ensure_ascii=False,
    )
    return (
        "/* 66 */ /***/ (function(module, exports, __webpack_require__) {\n"
        f"module.exports = {module_payload}\n"
        "/***/ }), /* 67 */"
    )


def _request_entry(
    url: str,
    *,
    method: str = "GET",
    response_text: str = "",
    headers: list[dict[str, str]] | None = None,
    cookies: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    return {
        "request": {
            "method": method,
            "url": url,
            "headers": headers or [],
            "cookies": cookies or [],
        },
        "response": {"status": 200, "content": {"text": response_text}},
    }


def _synthetic_har() -> dict[str, object]:
    common = {
        "dev": "d" * 32,
        "gid": "1005172",
        "os": "Windows",
        "over": "10",
        "pid": "1",
        "refer": "1_100172_10552_1",
        "sversion": "1.0.0_h5",
        "time": "1700000000",
        "version": "0.0.1",
    }
    active = {**common, "callback": "C0", "sign": "S0"}
    login = {
        **common,
        "autoLogin": "true",
        "callback": "C1",
        "sign": "S1",
        "uname": "U0",
        "upwd": "P0",
    }
    headers = [
        {"name": "User-Agent", "value": "Synthetic Browser"},
        {"name": "Referer", "value": "http://37.com.cn/h5game/public/"},
        {"name": "Cookie", "value": "sid=C0"},
    ]
    return {
        "log": {
            "entries": [
                _request_entry(
                    "http://37.com.cn/h5game/public/bundle.js",
                    response_text=_fake_bundle(),
                ),
                _request_entry(
                    "https://m-api.37.com.cn/h5sdk/active?" + urlencode(active),
                    response_text='cb({"state":1,"data":{"api":{"login":"https://s-api.37.com.cn/h5sdk/login"}}});',
                    headers=headers,
                ),
                _request_entry(
                    "https://s-api.37.com.cn/h5sdk/login",
                    method="OPTIONS",
                ),
                _request_entry(
                    "https://s-api.37.com.cn/h5sdk/login?" + urlencode(login),
                    response_text='cb({"state":1,"data":{"token":"T0","time":"1","sign":"S0"}});',
                    headers=headers,
                    cookies=[{"name": "sid", "value": "C0"}],
                ),
            ]
        }
    }


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200) -> None:
        self.text = text
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, bundle_text: str) -> None:
        self.bundle_text = bundle_text
        self.headers: dict[str, str] = {}
        self.calls: list[dict[str, object]] = []
        self.closed = False

    def get(self, url: str, **kwargs):
        self.calls.append({"method": "GET", "url": url, **kwargs})
        if url.endswith("/bundle.js"):
            return _FakeResponse(self.bundle_text)
        if "/h5sdk/active" in url:
            return _FakeResponse(
                '{"state":1,"data":{"api":{"login":"https://s-api.37.com.cn/h5sdk/login"}}}'
            )
        if "/h5sdk/login" in url:
            return _FakeResponse(
                '{"state":1,"data":{"token":"T2","time":"2000000000",'
                '"sign":"S2","uid":"10001","uname":"U2"}}'
            )
        return _FakeResponse("<html></html>")

    def request(self, method: str, url: str, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        return _FakeResponse("{}")

    def close(self) -> None:
        self.closed = True


class HttpDirectLoginProbeTests(unittest.TestCase):
    def test_parse_json_or_jsonp(self) -> None:
        self.assertEqual(parse_json_or_jsonp('{"state":1}')["state"], 1)
        self.assertEqual(parse_json_or_jsonp('callback({"state":1});')["state"], 1)

    def test_extract_direct_login_fields(self) -> None:
        fields = extract_direct_login_fields(
            {
                "state": 1,
                "data": {
                    "token": "T1",
                    "time": "1783000000",
                    "sign": "S1",
                    "uid": "10001",
                    "uname": "U1",
                },
            }
        )
        self.assertEqual(fields.token, "T1")
        self.assertEqual(fields.time, "1783000000")
        self.assertEqual(fields.sign, "S1")
        self.assertEqual(fields.uid, "10001")
        self.assertEqual(fields.uname, "U1")

    def test_calculate_sdk_sign_sorts_and_concatenates_without_separator(self) -> None:
        expected = hashlib.md5("a=1b=2K".encode("utf-8")).hexdigest()
        self.assertEqual(
            calculate_sdk_sign(
                {"b": "2", "callback": "C", "sign": "S", "a": "1"},
                "K",
            ),
            expected,
        )

    def test_extract_sdk_config_from_bundle_decodes_module_66(self) -> None:
        config = extract_sdk_config_from_bundle(_fake_bundle())
        self.assertEqual(config.version, "1.2.3")
        self.assertEqual(config.api_key, "K")
        self.assertEqual(config.values["INIT_API"], "/h5sdk/active")

    def test_analyze_har_payload_only_reports_shape(self) -> None:
        report = analyze_har_payload(_synthetic_har())
        login_row = next(
            row for row in report if row["method"] == "GET" and row["path"] == "/h5sdk/login"
        )
        text = str(report)
        self.assertIn("upwd", login_row["query_keys"])
        self.assertIn("uname", login_row["query_keys"])
        self.assertNotIn("U0", text)
        self.assertNotIn("P0", text)
        self.assertNotIn("sid=C0", text)

    def test_sanitize_probe_text_masks_request_credentials(self) -> None:
        text = sanitize_probe_text(
            "GET https://example.test/login?uname=U2&upwd=P2&token=T2"
        )
        self.assertNotIn("uname=U2", text)
        self.assertNotIn("upwd=P2", text)
        self.assertNotIn("token=T2", text)

    def test_http_login_runs_init_bundle_active_then_login_with_fresh_signatures(self) -> None:
        session = _FakeSession(_fake_bundle())
        fake_requests = types.SimpleNamespace(Session=lambda: session)
        with patch.dict(sys.modules, {"requests": fake_requests}), patch(
            "tools.probe_http_direct_login.time.time", return_value=2_000_000_000
        ):
            fields = http_login_from_har(
                har_payload=_synthetic_har(),
                username="U2",
                password="P2",
                timeout=5,
            )

        self.assertEqual(fields.token, "T2")
        self.assertTrue(session.closed)
        self.assertEqual(
            [urlparse(str(call["url"])).path for call in session.calls],
            ["/h5game/public/", "/h5game/public/bundle.js", "/h5sdk/active", "/h5sdk/login"],
        )
        active_params = dict(session.calls[2]["params"])
        login_params = dict(session.calls[3]["params"])
        self.assertEqual(active_params["time"], "2000000000")
        self.assertEqual(login_params["time"], "2000000000")
        self.assertNotEqual(active_params["sign"], "S0")
        self.assertNotEqual(login_params["sign"], "S1")
        self.assertEqual(login_params["uname"], "U2")
        self.assertEqual(login_params["upwd"], "P2")
        self.assertNotIn("cookie", {key.lower() for key in session.calls[3]["headers"]})
        self.assertEqual(active_params["sign"], calculate_sdk_sign(active_params, "K"))
        self.assertEqual(login_params["sign"], calculate_sdk_sign(login_params, "K"))

    def test_http_login_uses_split_connect_and_read_timeouts(self) -> None:
        session = _FakeSession(_fake_bundle())
        fake_requests = types.SimpleNamespace(Session=lambda: session)
        with patch.dict(sys.modules, {"requests": fake_requests}), patch(
            "tools.probe_http_direct_login.time.time", return_value=2_000_000_000
        ):
            http_login_from_har(
                har_payload=_synthetic_har(),
                username="U2",
                password="P2",
                connect_timeout=1.25,
                read_timeout=0.5,
            )

        self.assertTrue(session.calls)
        self.assertTrue(all(call["timeout"] == (1.25, 0.5) for call in session.calls))

    def test_http_login_checks_stop_between_requests_and_closes_session(self) -> None:
        session = _FakeSession(_fake_bundle())
        fake_requests = types.SimpleNamespace(Session=lambda: session)
        checks = 0

        def stop_check() -> None:
            nonlocal checks
            checks += 1
            if checks >= 3:
                raise InterruptedError("用户停止")

        with patch.dict(sys.modules, {"requests": fake_requests}):
            with self.assertRaisesRegex(InterruptedError, "用户停止"):
                http_login_from_har(
                    har_payload=_synthetic_har(),
                    username="U2",
                    password="P2",
                    connect_timeout=1.0,
                    read_timeout=0.25,
                    stop_check=stop_check,
                )

        self.assertEqual(len(session.calls), 1)
        self.assertTrue(session.closed)

    def test_real_har_config_reproduces_recorded_active_and_login_signs(self) -> None:
        har_path = PROJECT_ROOT / "docs" / "111.cn.har"
        if not har_path.exists():
            self.skipTest("真实研究 HAR 不存在")
        payload = load_har(har_path)
        config = extract_sdk_config_from_har(payload)
        matches = {"active": False, "login": False}
        for entry in payload["log"]["entries"]:
            request = entry.get("request", {})
            parsed = urlparse(str(request.get("url") or ""))
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            if parsed.path == "/h5sdk/active":
                matches["active"] = calculate_sdk_sign(query, config.api_key) == query.get("sign")
            elif parsed.path == "/h5sdk/login":
                matches["login"] = calculate_sdk_sign(query, config.api_key) == query.get("sign")
        self.assertEqual(matches, {"active": True, "login": True})


if __name__ == "__main__":
    unittest.main()
