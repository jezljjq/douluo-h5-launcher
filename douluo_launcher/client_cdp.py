from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import socket
import struct
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


DEFAULT_CDP_PORT = 9222
CDP_ORIGIN = "http://127.0.0.1"
CDP_LOGIN_TARGET_KEYWORDS = ("login.php", "app.xxh5.z7xz.com", "dldl.50pk.com")

SENSITIVE_RE = re.compile(
    r"(?i)((?:token|sign|cookie|IMEI|imei|uid|session|openid|openkey|"
    r"refreshToken|account|traceId)=)[^&\s\"'<>}]+"
)
SENSITIVE_JSON_RE = re.compile(
    r'(?i)("(?:token|sign|cookie|IMEI|imei|uid|session|openid|openkey|'
    r'refreshToken|account|traceId|username|nickname)"\s*:\s*)"[^"]*"'
)


def mask_sensitive_text(value: object) -> str:
    text = str(value if value is not None else "")
    text = SENSITIVE_RE.sub(r"\1***MASKED***", text)
    text = SENSITIVE_JSON_RE.sub(r'\1"***MASKED***"', text)
    return text


def cdp_port_for_index(index: int, *, base_port: int = DEFAULT_CDP_PORT) -> int:
    if int(index) < 0:
        raise ValueError(f"CDP index must be >= 0: {index}")
    return int(base_port) + int(index)


def is_tcp_port_available(port: int, *, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, int(port))) != 0


def cdp_base_url(port: int) -> str:
    return f"http://127.0.0.1:{int(port)}"


def start_x5game_with_cdp(x5game_path: str | Path, cdp_port: int) -> subprocess.Popen:
    exe = Path(x5game_path)
    if not exe.exists():
        raise FileNotFoundError(f"X5Game.exe not found: {exe}")
    return subprocess.Popen(
        [
            str(exe),
            f"--remote-debugging-port={int(cdp_port)}",
            "--remote-allow-origins=*",
        ],
        cwd=str(exe.parent),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def fetch_json(url: str, *, timeout: float = 2.0) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "douluo-client-cdp"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def wait_for_cdp_targets(cdp_port: int, *, timeout: float = 30.0) -> list[dict]:
    base = cdp_base_url(cdp_port)
    deadline = time.time() + float(timeout)
    last_error = ""
    while time.time() < deadline:
        try:
            fetch_json(f"{base}/json/version", timeout=2.0)
            targets = fetch_json(f"{base}/json", timeout=2.0)
            if isinstance(targets, list):
                return targets
        except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            last_error = repr(exc)
        time.sleep(0.5)
    raise TimeoutError(f"CDP port {cdp_port} not reachable. Last error: {last_error}")


def select_page_target(targets: list[dict]) -> dict:
    pages = [
        target
        for target in targets
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl")
    ]
    if not pages:
        raise RuntimeError("No type=page CDP target found")
    for target in pages:
        url = str(target.get("url") or "")
        if any(keyword in url for keyword in CDP_LOGIN_TARGET_KEYWORDS):
            return target
    return pages[0]


@dataclass
class ImportServerIdentity:
    server_id: int | None = None
    has_uid: bool = False
    isolduser: int | None = None


@dataclass
class CdpEventMarkers:
    import_server: bool = False
    game_notice: bool = False
    server_mobile: bool = False
    verjs: bool = False
    game_main: bool = False
    login_js: bool = False
    main_js: bool = False
    main_ui: bool = False
    websocket: bool = False


@dataclass
class CdpResponseInfo:
    request_id: str
    url: str
    status: int
    mime_type: str = ""


class CdpMessageBuilder:
    def __init__(self) -> None:
        self.next_id = 1

    def build(self, method: str, params: dict | None = None) -> str:
        msg_id = self.next_id
        self.next_id += 1
        return json.dumps(
            {"id": msg_id, "method": method, "params": params or {}},
            separators=(",", ":"),
        )


class CdpEventTracker:
    def __init__(self) -> None:
        self.markers = CdpEventMarkers()
        self.responses: dict[str, CdpResponseInfo] = {}
        self.import_server_state: int | None = None
        self.import_server_id = ImportServerIdentity()
        self.server_mobile_state: int | None = None

    def handle_event(self, obj: dict) -> CdpResponseInfo | None:
        method = obj.get("method", "")
        params = obj.get("params") or {}
        if method == "Network.webSocketCreated":
            self.markers.websocket = True
            return None
        if method != "Network.responseReceived":
            return None

        response = params.get("response") or {}
        url = str(response.get("url") or "")
        status = int(response.get("status") or 0)
        request_id = str(params.get("requestId") or "")
        info = CdpResponseInfo(
            request_id=request_id,
            url=url,
            status=status,
            mime_type=str(response.get("mimeType") or ""),
        )
        self.responses[request_id] = info
        self._mark_url(url, status)
        return info

    def record_response_body(self, request_id: str, body: str) -> None:
        info = self.responses.get(str(request_id))
        if not info:
            return
        try:
            payload = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return
        if "importServer" in info.url:
            self.import_server_state = _as_int(payload.get("state"))
            servers = payload.get("server")
            if isinstance(servers, list) and servers:
                server = servers[0]
                if isinstance(server, dict):
                    self.import_server_id = ImportServerIdentity(
                        server_id=_as_int(server.get("serverId")),
                        has_uid=bool(server.get("uid")),
                        isolduser=_as_int(server.get("isolduser")),
                    )
        elif "serverMobile" in info.url:
            self.server_mobile_state = _as_int(payload.get("state"))

    def key_response_ids_needing_body(self) -> list[str]:
        ids = []
        for request_id, info in self.responses.items():
            if "importServer" in info.url or "serverMobile" in info.url:
                if (info.url, request_id) and request_id:
                    ids.append(request_id)
        return ids

    def _mark_url(self, url: str, status: int) -> None:
        if status != 200:
            return
        if "importServer" in url:
            self.markers.import_server = True
        if "gameNotice" in url:
            self.markers.game_notice = True
        if "serverMobile" in url:
            self.markers.server_mobile = True
        if re.search(r"/ver\d+\.js(?:$|\?)", url):
            self.markers.verjs = True
        if re.search(r"/GameMain\.max_[^/]*\.js(?:$|\?)", url):
            self.markers.game_main = True
        if re.search(r"/js/login_[^/]*\.js(?:$|\?)", url):
            self.markers.login_js = True
        if re.search(r"/js/main_[^/]*\.js(?:$|\?)", url):
            self.markers.main_js = True
        if "/res/pages/X5_Main" in url:
            self.markers.main_ui = True


class RawCdpClient:
    def __init__(self, web_socket_debugger_url: str, *, event_tracker: CdpEventTracker | None = None) -> None:
        self.web_socket_debugger_url = web_socket_debugger_url
        self.sock: socket.socket | None = None
        self.builder = CdpMessageBuilder()
        self.event_tracker = event_tracker or CdpEventTracker()

    def connect(self) -> None:
        parsed = urlparse(self.web_socket_debugger_url)
        if parsed.scheme != "ws":
            raise ValueError(f"Only ws:// CDP URL is supported: {self.web_socket_debugger_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 80
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        self.sock = socket.create_connection((host, port), timeout=5)
        self.sock.settimeout(1)
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            f"Origin: {CDP_ORIGIN}:{port}\r\n"
            "\r\n"
        )
        self.sock.sendall(request.encode("ascii"))
        response = self._read_http_response()
        if " 101 " not in response.split("\r\n", 1)[0]:
            raise ConnectionError(f"CDP WebSocket handshake failed: {response.splitlines()[0] if response else 'empty'}")

        expected = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
        ).decode("ascii")
        if expected not in response:
            raise ConnectionError("CDP WebSocket Sec-WebSocket-Accept mismatch")

    def close(self) -> None:
        if not self.sock:
            return
        try:
            self._send_frame(b"", opcode=8)
        except OSError:
            pass
        try:
            self.sock.close()
        finally:
            self.sock = None

    def enable_default_domains(self) -> None:
        self.send("Page.enable")
        self.send("Network.enable")
        self.send("Runtime.enable")

    def navigate(self, url: str) -> dict:
        return self.send("Page.navigate", {"url": url})

    def evaluate(self, expression: str, *, timeout: float = 10.0) -> object:
        result = self.send(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": False},
            timeout=timeout,
        )
        remote = result.get("result") or {}
        if "value" in remote:
            return remote["value"]
        return remote

    def get_response_body(self, request_id: str) -> str:
        result = self.send("Network.getResponseBody", {"requestId": str(request_id)}, timeout=5.0)
        body = str(result.get("body") or "")
        if result.get("base64Encoded"):
            try:
                return base64.b64decode(body).decode("utf-8", errors="replace")
            except Exception:
                return ""
        return body

    def send(self, method: str, params: dict | None = None, *, timeout: float = 10.0) -> dict:
        message = self.builder.build(method, params)
        msg_id = json.loads(message)["id"]
        self._send_frame(message.encode("utf-8"), opcode=1)
        deadline = time.time() + float(timeout)
        while time.time() < deadline:
            obj = self._recv_json(deadline)
            if obj is None:
                continue
            if obj.get("id") == msg_id:
                if "error" in obj:
                    raise RuntimeError(f"{method} failed: {obj['error']}")
                return obj.get("result", {})
            self.event_tracker.handle_event(obj)
        raise TimeoutError(f"Timed out waiting for CDP response: {method}")

    def pump(self, duration: float) -> None:
        deadline = time.time() + float(duration)
        while time.time() < deadline:
            obj = self._recv_json(deadline)
            if obj is None:
                continue
            self.event_tracker.handle_event(obj)

    def _read_http_response(self) -> str:
        assert self.sock is not None
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self.sock.recv(4096)
            if not chunk:
                break
            data += chunk
            if len(data) > 65536:
                break
        return data.decode("iso-8859-1", errors="replace")

    def _recvn(self, n: int) -> bytes:
        assert self.sock is not None
        chunks: list[bytes] = []
        remaining = int(n)
        while remaining:
            chunk = self.sock.recv(remaining)
            if not chunk:
                raise ConnectionError("WebSocket closed while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _send_frame(self, payload: bytes, *, opcode: int = 1) -> None:
        assert self.sock is not None
        first = 0x80 | opcode
        mask_bit = 0x80
        length = len(payload)
        if length < 126:
            header = struct.pack("!BB", first, mask_bit | length)
        elif length < 65536:
            header = struct.pack("!BBH", first, mask_bit | 126, length)
        else:
            header = struct.pack("!BBQ", first, mask_bit | 127, length)
        key = os.urandom(4)
        masked = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
        self.sock.sendall(header + key + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        header = self._recvn(2)
        b1, b2 = header[0], header[1]
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recvn(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recvn(8))[0]
        mask_key = self._recvn(4) if masked else b""
        payload = self._recvn(length) if length else b""
        if masked:
            payload = bytes(byte ^ mask_key[index % 4] for index, byte in enumerate(payload))
        return opcode, payload

    def _recv_json(self, deadline: float) -> dict | None:
        while time.time() < deadline:
            try:
                opcode, payload = self._recv_frame()
            except socket.timeout:
                return None
            if opcode == 8:
                raise ConnectionError("CDP WebSocket closed")
            if opcode == 9:
                self._send_frame(payload, opcode=10)
                continue
            if opcode != 1:
                continue
            try:
                return json.loads(payload.decode("utf-8", errors="replace"))
            except json.JSONDecodeError:
                continue
        return None


def _as_int(value: object) -> int | None:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
