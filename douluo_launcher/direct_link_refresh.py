from __future__ import annotations

import csv
import copy
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import uuid
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Callable, Iterable
from urllib.parse import urlencode, urlparse, urlunparse

from .config import AccountConfig, app_root, project_root, source_project_root, user_data_dir
from .protected_json import DataProtector, ProtectedJsonFile


DEFAULT_CHANNEL_NAME = "正式服"
CLIENT_DIRECT_EXPIRE_DAYS = 22
LOGIN_ENDPOINT = "s-api.37.com.cn/h5sdk/login"
REFRESH_DATA_ENV = "H5_LAUNCHER_REFRESH_DATA_DIR"
REFRESH_DATA_DIR_NAME = "refresh_data"
SENSITIVE_VALUE_RE = re.compile(r"(?i)((?:token|sign|password|pwd|direct_url)=)[^&\s\"'<>}]+")


@dataclass(frozen=True)
class RefreshDataPaths:
    data_dir: Path
    accounts_path: Path
    direct_links_path: Path
    channels_path: Path
    summary_path: Path
    url_dir: Path
    grouped_url_dir: Path
    backups_dir: Path
    logs_dir: Path
    login_accounts_path: Path


@dataclass(frozen=True)
class ChannelConfig:
    name: str
    web_login_url: str
    client_base_url: str
    client_params: dict[str, str]


@dataclass(frozen=True)
class DirectLoginFields:
    token: str
    time: str
    sign: str
    uid: str = ""
    uname: str = ""

    def validate(self) -> None:
        missing = [
            name
            for name, value in (
                ("token", self.token),
                ("time", self.time),
                ("sign", self.sign),
            )
            if not str(value or "").strip()
        ]
        if missing:
            raise ValueError("h5sdk/login 响应缺少字段: " + ", ".join(missing))


@dataclass(frozen=True)
class RefreshAccount:
    name: str
    username: str
    password: str
    channel: str = DEFAULT_CHANNEL_NAME
    bookmark_path: str = ""
    enabled: bool = True
    remark: str = ""
    last_refresh_time: str = ""
    expire_hint: str = ""
    last_status: str = "待刷新"
    order_index: int = 0

    @property
    def refresh_mode(self) -> str:
        return "收藏夹" if str(self.bookmark_path or "").strip() else "本地链接"


@dataclass(frozen=True)
class ImportFailure:
    row_number: int
    name: str = ""
    status: str = "import_failed"
    message: str = ""


@dataclass(frozen=True)
class ImportAccountsResult:
    accounts: list[RefreshAccount]
    failures: list[ImportFailure]


@dataclass(frozen=True)
class RefreshResult:
    name: str
    channel: str
    generated_at: datetime
    expire_hint: datetime
    status: str
    message: str = ""
    direct_url: str = ""
    uid: str = ""
    uname: str = ""
    uid_len: int = 0
    uname_len: int = 0
    token_len: int = 0
    time_len: int = 0
    sign_len: int = 0
    bookmark_path: str = ""
    url_file: str = ""

    @property
    def refresh_mode(self) -> str:
        return "收藏夹" if str(self.bookmark_path or "").strip() else "本地链接"

    @property
    def success(self) -> bool:
        return bool(self.direct_url) or self.status in {
            "success",
            "local_success",
            "bookmark_success",
            "bookmark_update_skipped",
        }


@dataclass(frozen=True)
class RefreshRunSummary:
    total: int
    success: int
    failure: int
    local_links: int
    bookmark_success: int
    bookmark_failure: int
    results: list[RefreshResult]
    bookmark_skipped: int = 0


@dataclass
class AccountDeletionResult:
    name: str
    account_removed: bool = False
    direct_link_removed: bool = False
    url_files_removed: list[str] = field(default_factory=list)
    bindings_removed: int = 0
    cache_entries_removed: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BookmarkUpdateResult:
    status: str
    message: str
    backup_path: str = ""
    matched_path: str = ""


@dataclass(frozen=True)
class BookmarkWriteContext:
    bookmark_file: Path
    browser: str = ""
    profile: str = ""
    root_path: str = ""
    root_name: str = ""
    root_guid: str = ""
    root_parent_path: str = ""
    allow_create_root: bool = False


@dataclass(frozen=True)
class BookmarkBatchItem:
    account_key: str
    bookmark_path: str
    direct_url: str


@dataclass(frozen=True)
class BookmarkBatchResult:
    status: str
    message: str
    updated: int = 0
    created: int = 0
    conflicts: int = 0
    skipped: int = 0
    backup_path: str = ""
    root_guid: str = ""
    root_path: str = ""
    root_name: str = ""


@dataclass(frozen=True)
class ResolvedDirectUrl:
    name: str
    direct_url: str
    status: str
    message: str
    expire_hint: str = ""
    expired: bool = False
    bookmark_path: str = ""


@dataclass(frozen=True)
class RefreshSummaryRow:
    name: str
    generated_at: datetime
    status: str
    message: str = ""

    @property
    def expire_hint(self) -> datetime:
        return self.generated_at + timedelta(days=CLIENT_DIRECT_EXPIRE_DAYS)


class LoginFailed(RuntimeError):
    pass


class CaptureFailed(RuntimeError):
    pass


def default_refresh_data_dir(
    *,
    environ: dict[str, str] | None = None,
    frozen: bool | None = None,
) -> Path:
    env = os.environ if environ is None else environ
    override = str(env.get(REFRESH_DATA_ENV, "") or "").strip()
    if override:
        return Path(override)
    packaged = bool(getattr(sys, "frozen", False)) if frozen is None else bool(frozen)
    if packaged:
        return user_data_dir(env) / REFRESH_DATA_DIR_NAME
    return project_root() / "上号器数据"


def legacy_refresh_data_dirs(*, environ: dict[str, str] | None = None) -> list[Path]:
    env = os.environ if environ is None else environ
    packaged = bool(getattr(sys, "frozen", False))
    if packaged:
        release_root = app_root()
        data_root = user_data_dir(env)
        candidates = [
            release_root / "上号器数据",
            release_root / "_internal" / "上号器数据",
            data_root / "上号器数据",
            data_root,
        ]
    else:
        source_root = source_project_root()
        candidates = [*([] if source_root is None else [source_root / "上号器数据"]), user_data_dir(env) / "上号器数据", user_data_dir(env)]
    unique: list[Path] = []
    for candidate in candidates:
        allowed_root = release_root if packaged and candidate.is_relative_to(release_root) else user_data_dir(env)
        try:
            if candidate.exists() and not candidate.resolve(strict=True).is_relative_to(allowed_root.resolve()):
                continue
        except OSError:
            continue
        if candidate not in unique:
            unique.append(candidate)
    return unique


def default_channel_config() -> ChannelConfig:
    return ChannelConfig(
        name=DEFAULT_CHANNEL_NAME,
        web_login_url="http://37.com.cn/h5game/public/?pid=1&gid=1005172&refer=1_100172_10552_1",
        client_base_url="https://dldl.50pk.com/login.php",
        client_params={
            "gid": "1002997",
            "pid": "1",
            "platCode": "37wan",
            "appVer": "",
            "IMEI": "",
            "isPcLauncher": "true",
        },
    )


def ensure_refresh_data_dir(data_dir: str | Path | None = None) -> RefreshDataPaths:
    base = Path(data_dir) if data_dir is not None else default_refresh_data_dir()
    paths = RefreshDataPaths(
        data_dir=base,
        accounts_path=base / "accounts.enc.json",
        direct_links_path=base / "direct_links.enc.json",
        channels_path=base / "channels.json",
        summary_path=base / "refresh_summary.csv",
        url_dir=base / "直登链接",
        grouped_url_dir=base / "分组",
        backups_dir=base / "backups",
        logs_dir=base / "logs",
        login_accounts_path=base / "login_accounts.json",
    )
    for folder in (paths.data_dir, paths.url_dir, paths.grouped_url_dir, paths.backups_dir, paths.logs_dir):
        folder.mkdir(parents=True, exist_ok=True)
    if data_dir is None and bool(getattr(sys, "frozen", False)):
        migrate_refresh_data(paths.data_dir, legacy_refresh_data_dirs(), backups_dir=paths.backups_dir)
    if not paths.channels_path.exists():
        _atomic_write_text(
            paths.channels_path,
            json.dumps(_channels_to_payload({DEFAULT_CHANNEL_NAME: default_channel_config()}), ensure_ascii=False, indent=2),
        )
    return paths


def migrate_refresh_data(
    destination: str | Path,
    sources: Iterable[str | Path],
    *,
    backups_dir: str | Path | None = None,
) -> dict[str, int]:
    target_root = Path(destination)
    backup_root = Path(backups_dir) if backups_dir is not None else target_root / "backups"
    counts = {"copied": 0, "replaced": 0, "skipped_newer": 0}
    allowed_files = {
        "accounts.enc.json",
        "direct_links.enc.json",
        "channels.json",
        "refresh_summary.csv",
    }
    allowed_dirs = {"直登链接", "分组"}
    target_root.mkdir(parents=True, exist_ok=True)
    for source_value in sources:
        source_root = Path(source_value)
        try:
            resolved_source = source_root.resolve(strict=True)
            resolved_target = target_root.resolve()
            if not source_root.is_dir() or resolved_source == resolved_target:
                continue
        except OSError:
            continue
        candidates = [path for path in source_root.iterdir() if path.is_file() and path.name in allowed_files]
        for directory_name in allowed_dirs:
            source_dir = source_root / directory_name
            if source_dir.is_dir():
                candidates.extend(path for path in source_dir.rglob("*") if path.is_file())
        for source_file in candidates:
            try:
                resolved_file = source_file.resolve(strict=True)
                resolved_file.relative_to(resolved_source)
                relative = source_file.relative_to(source_root)
            except (OSError, ValueError):
                continue
            target_file = target_root / relative
            if target_file.exists():
                try:
                    if target_file.stat().st_mtime >= source_file.stat().st_mtime:
                        counts["skipped_newer"] += 1
                        continue
                except OSError:
                    counts["skipped_newer"] += 1
                    continue
                backup_root.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
                backup_name = f"migration_{_safe_file_component(relative.as_posix())}_{stamp}.bak"
                shutil.copy2(target_file, backup_root / backup_name)
                counts["replaced"] += 1
            else:
                counts["copied"] += 1
            target_file.parent.mkdir(parents=True, exist_ok=True)
            temp_target = target_file.with_name(f".{target_file.name}.migration.tmp")
            shutil.copy2(source_file, temp_target)
            temp_target.replace(target_file)
    return counts


def load_channels(data_dir: str | Path | None = None) -> dict[str, ChannelConfig]:
    paths = ensure_refresh_data_dir(data_dir)
    try:
        payload = json.loads(paths.channels_path.read_text(encoding="utf-8-sig"))
    except Exception:
        payload = {}
    raw_channels = payload.get("channels") if isinstance(payload, dict) else None
    channels: dict[str, ChannelConfig] = {}
    if isinstance(raw_channels, dict):
        for name, raw in raw_channels.items():
            if not isinstance(raw, dict):
                continue
            clean_name = str(raw.get("name") or name or "").strip()
            web_login_url = str(raw.get("web_login_url") or "").strip()
            client_base_url = str(raw.get("client_base_url") or "").strip()
            client_params = raw.get("client_params")
            if not clean_name or not web_login_url or not client_base_url or not isinstance(client_params, dict):
                continue
            channels[clean_name] = ChannelConfig(
                name=clean_name,
                web_login_url=web_login_url,
                client_base_url=client_base_url,
                client_params={str(key): str(value) for key, value in client_params.items()},
            )
    if DEFAULT_CHANNEL_NAME not in channels:
        channels[DEFAULT_CHANNEL_NAME] = default_channel_config()
    return channels


def build_client_direct_url(fields: DirectLoginFields, *, channel: ChannelConfig | None = None) -> str:
    fields.validate()
    selected_channel = channel or default_channel_config()
    parsed = urlparse(selected_channel.client_base_url)
    query = dict(selected_channel.client_params)
    query["token"] = str(fields.token)
    query["time"] = str(fields.time)
    query["sign"] = str(fields.sign)
    return urlunparse(
        (
            parsed.scheme or "https",
            parsed.netloc,
            parsed.path or "/login.php",
            "",
            urlencode(query),
            "",
        )
    )


def import_accounts_from_file(path: str | Path, *, channel: str = DEFAULT_CHANNEL_NAME) -> ImportAccountsResult:
    source = Path(path)
    if source.suffix.lower() == ".xlsx":
        return _import_accounts_from_xlsx(source, channel=channel)
    for encoding in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
        try:
            return import_accounts_from_text(source.read_text(encoding=encoding), channel=channel)
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("账号文件编码无法识别，请保存为 UTF-8 或 GBK 编码")


def import_accounts_from_text(text: str, *, channel: str = DEFAULT_CHANNEL_NAME) -> ImportAccountsResult:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return ImportAccountsResult([], [])
    delimiter = "\t" if lines[0].count("\t") > lines[0].count(",") else ","
    rows = list(csv.reader(lines, delimiter=delimiter))
    if not rows:
        return ImportAccountsResult([], [])
    header = [_normalize_header(value) for value in rows[0]]
    has_header = {"name", "username", "password"}.issubset(set(header))
    accounts: list[RefreshAccount] = []
    failures: list[ImportFailure] = []
    data_rows = rows[1:] if has_header else rows
    for index, row in enumerate(data_rows, start=2 if has_header else 1):
        if not any(str(value or "").strip() for value in row):
            continue
        if has_header:
            values = {header[column_index]: str(row[column_index]).strip() if column_index < len(row) else "" for column_index in range(len(header))}
            name = values.get("name", "")
            username = values.get("username", "")
            password = values.get("password", "")
            bookmark_path = values.get("bookmark_path", "")
        else:
            cells = [str(value or "").strip() for value in row]
            name = cells[0] if len(cells) > 0 else ""
            username = cells[1] if len(cells) > 1 else ""
            password = cells[2] if len(cells) > 2 else ""
            bookmark_path = cells[3] if len(cells) > 3 else ""
        missing = [field for field, value in (("name", name), ("username", username), ("password", password)) if not value]
        if missing:
            failures.append(ImportFailure(row_number=index, name=name, message="缺少字段: " + ", ".join(missing)))
            continue
        accounts.append(
            RefreshAccount(
                name=name,
                username=username,
                password=password,
                channel=channel,
                bookmark_path=bookmark_path,
                order_index=len(accounts),
            )
        )
    return ImportAccountsResult(merge_accounts_by_name(accounts), failures)


def merge_accounts_by_name(accounts: Iterable[RefreshAccount]) -> list[RefreshAccount]:
    merged: dict[str, RefreshAccount] = {}
    order: list[str] = []
    for account in accounts:
        name = str(account.name or "").strip()
        if not name:
            continue
        if name not in merged:
            order.append(name)
        merged[name] = replace(account, name=name)
    return [replace(merged[name], order_index=index) for index, name in enumerate(order)]


class AccountsStore:
    def __init__(self, path: str | Path, *, protector: DataProtector | None = None) -> None:
        self.path = Path(path)
        self.protected_file = ProtectedJsonFile(self.path, protector=protector)
        self.load_error: Exception | None = None

    def load(self) -> list[RefreshAccount]:
        if not self.path.exists():
            return []
        try:
            payload = self.protected_file.read()
            self.load_error = None
        except Exception as exc:
            self.load_error = exc
            return []
        rows = payload.get("accounts", payload) if isinstance(payload, dict) else payload
        if not isinstance(rows, list):
            return []
        accounts: list[RefreshAccount] = []
        for row_index, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            accounts.append(
                RefreshAccount(
                    name=str(row.get("name") or "").strip(),
                    username=str(row.get("username") or "").strip(),
                    password=str(row.get("password") or ""),
                    channel=str(row.get("channel") or DEFAULT_CHANNEL_NAME).strip() or DEFAULT_CHANNEL_NAME,
                    bookmark_path=str(row.get("bookmark_path") or "").strip(),
                    enabled=bool(row.get("enabled", True)),
                    remark=str(row.get("remark") or ""),
                    last_refresh_time=str(row.get("last_refresh_time") or ""),
                    expire_hint=str(row.get("expire_hint") or ""),
                    last_status=str(row.get("last_status") or "待刷新"),
                    order_index=int(row.get("order_index") if row.get("order_index") is not None else row_index),
                )
            )
        return sorted(
            (account for account in accounts if account.name),
            key=lambda account: account.order_index,
        )

    def save(self, accounts: Iterable[RefreshAccount]) -> Path:
        if self.load_error is not None and self.path.exists():
            raise RuntimeError("账号受保护数据无法读取，已阻止覆盖原文件") from self.load_error
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "accounts": [asdict(account) for account in merge_accounts_by_name(accounts)],
        }
        return self.protected_file.write(payload)


class DirectLinkStore:
    def __init__(self, path: str | Path, *, protector: DataProtector | None = None) -> None:
        self.path = Path(path)
        self.protected_file = ProtectedJsonFile(self.path, protector=protector)
        self.load_error: Exception | None = None
        self.links: dict[str, dict[str, object]] = {}
        self.load()

    def load(self) -> dict[str, dict[str, object]]:
        if not self.path.exists():
            self.links = {}
            return self.links
        try:
            payload = self.protected_file.read()
            self.load_error = None
        except Exception as exc:
            self.load_error = exc
            self.links = {}
            return self.links
        links = payload.get("links", payload) if isinstance(payload, dict) else {}
        self.links = dict(links) if isinstance(links, dict) else {}
        return self.links

    def save(self) -> Path:
        if self.load_error is not None and self.path.exists():
            raise RuntimeError("直登链接受保护数据无法读取，已阻止覆盖原文件") from self.load_error
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "links": self.links}
        return self.protected_file.write(payload)

    def update_from_result(self, result: RefreshResult) -> None:
        name = str(result.name or "").strip()
        if not name:
            return
        existing = dict(self.links.get(name, {}))
        record = {
            **existing,
            "name": name,
            "channel": result.channel,
            "generated_at": _iso(result.generated_at),
            "expire_hint": _iso(result.expire_hint),
            "status": result.status,
            "message": result.message,
            "uid": result.uid,
            "uname": result.uname,
            "uid_len": result.uid_len,
            "uname_len": result.uname_len,
            "token_len": result.token_len,
            "time_len": result.time_len,
            "sign_len": result.sign_len,
            "bookmark_path": result.bookmark_path,
            "url_file": result.url_file or existing.get("url_file", ""),
        }
        if result.success and result.direct_url:
            record["direct_url"] = result.direct_url
        elif "direct_url" in existing:
            record["direct_url"] = existing["direct_url"]
        self.links[name] = record
        self.save()

    def get(self, name: str) -> dict[str, object] | None:
        record = self.links.get(str(name or "").strip())
        return dict(record) if isinstance(record, dict) else None


class RefreshSummaryWriter:
    fieldnames = [
        "name",
        "channel",
        "refresh_mode",
        "generated_at",
        "expire_hint",
        "status",
        "message",
        "uid_len",
        "uname_len",
        "token_len",
        "time_len",
        "sign_len",
        "url_file",
        "bookmark_path",
    ]

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def write(self, results: Iterable[RefreshResult]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=self.fieldnames)
            writer.writeheader()
            for result in results:
                writer.writerow(
                    {
                        "name": result.name,
                        "channel": result.channel,
                        "refresh_mode": result.refresh_mode,
                        "generated_at": _iso(result.generated_at),
                        "expire_hint": _iso(result.expire_hint),
                        "status": result.status,
                        "message": redact_sensitive_text(result.message),
                        "uid_len": result.uid_len,
                        "uname_len": result.uname_len,
                        "token_len": result.token_len,
                        "time_len": result.time_len,
                        "sign_len": result.sign_len,
                        "url_file": result.url_file,
                        "bookmark_path": result.bookmark_path,
                    }
                )
        return self.path


def calculate_chromium_bookmarks_checksum(payload: dict[str, object]) -> str:
    digest = hashlib.md5()
    roots = payload.get("roots") if isinstance(payload, dict) else None
    if not isinstance(roots, dict):
        return digest.hexdigest()
    ordered_keys = [key for key in ("bookmark_bar", "other", "synced") if key in roots]
    ordered_keys.extend(sorted(key for key in roots if key not in ordered_keys))
    for key in ordered_keys:
        node = roots.get(key)
        if isinstance(node, dict):
            _update_bookmark_checksum(digest, node)
    return digest.hexdigest()


def _update_bookmark_checksum(digest, node: dict[str, object]) -> None:
    for key in ("id", "name", "type"):
        digest.update(str(node.get(key) or "").encode("utf-8"))
    if str(node.get("type") or "") == "url":
        digest.update(str(node.get("url") or "").encode("utf-8"))
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _update_bookmark_checksum(digest, child)


def _normalize_bookmark_path(value: object) -> str:
    return "/".join(part.strip() for part in re.split(r"[\\/]+", str(value or "").strip()) if part.strip())


def _find_bookmark_url_nodes(
    payload: dict[str, object],
    bookmark_path: str,
    context: BookmarkWriteContext,
) -> list[dict[str, object]]:
    segments = [part for part in _normalize_bookmark_path(bookmark_path).split("/") if part]
    if not segments:
        return []
    roots = _bookmark_root_candidates(payload, context)
    if not roots:
        return []
    root_names = {str(root.get("name") or "") for root in roots}
    if segments and (segments[0] == str(context.root_name or "") or segments[0] in root_names):
        segments = segments[1:]
    if not segments:
        return []

    candidates = roots
    for index, segment in enumerate(segments):
        is_last = index == len(segments) - 1
        next_candidates: list[dict[str, object]] = []
        for parent in candidates:
            children = parent.get("children")
            if not isinstance(children, list):
                continue
            for child in children:
                if not isinstance(child, dict) or str(child.get("name") or "") != segment:
                    continue
                expected_type = "url" if is_last else "folder"
                if str(child.get("type") or "") == expected_type:
                    next_candidates.append(child)
        candidates = next_candidates
        if not candidates:
            break
    return candidates


def _next_bookmark_node_id(payload: dict[str, object]) -> str:
    maximum = 0

    def visit(node: object) -> None:
        nonlocal maximum
        if not isinstance(node, dict):
            return
        try:
            maximum = max(maximum, int(str(node.get("id") or "0")))
        except ValueError:
            pass
        for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
            visit(child)

    roots = payload.get("roots")
    if isinstance(roots, dict):
        for root in roots.values():
            visit(root)
    return str(maximum + 1)


def _chromium_date_now() -> str:
    epoch = datetime(1601, 1, 1)
    now = datetime.now()
    return str(int((now - epoch).total_seconds() * 1_000_000))


def _create_bookmark_url_path(
    payload: dict[str, object],
    bookmark_path: str,
    direct_url: str,
    context: BookmarkWriteContext,
) -> dict[str, object]:
    segments = [part for part in _normalize_bookmark_path(bookmark_path).split("/") if part]
    roots = _bookmark_root_candidates(payload, context)
    if len(roots) != 1:
        raise ValueError(f"收藏夹账号根目录匹配数量为 {len(roots)}，无法安全新增")
    root = roots[0]
    root_name = str(root.get("name") or "")
    if segments and segments[0] in {str(context.root_name or ""), root_name}:
        segments = segments[1:]
    if not segments:
        raise ValueError("收藏夹路径缺少最终收藏项名称")
    parent = root
    for segment in segments[:-1]:
        children = parent.setdefault("children", [])
        if not isinstance(children, list):
            raise ValueError("收藏夹目录 children 结构无效")
        same_name = [child for child in children if isinstance(child, dict) and str(child.get("name") or "") == segment]
        folders = [child for child in same_name if str(child.get("type") or "") == "folder"]
        if len(folders) > 1 or (same_name and len(folders) != len(same_name)):
            raise ValueError(f"收藏夹目录 {segment} 存在同名冲突")
        if folders:
            parent = folders[0]
            continue
        parent = {
            "children": [],
            "date_added": _chromium_date_now(),
            "date_modified": "0",
            "guid": str(uuid.uuid4()),
            "id": _next_bookmark_node_id(payload),
            "name": segment,
            "type": "folder",
        }
        children.append(parent)
    children = parent.setdefault("children", [])
    if not isinstance(children, list):
        raise ValueError("收藏夹目录 children 结构无效")
    leaf = segments[-1]
    if any(isinstance(child, dict) and str(child.get("name") or "") == leaf for child in children):
        raise ValueError(f"收藏夹最终名称 {leaf} 存在同名冲突")
    target = {
        "date_added": _chromium_date_now(),
        "guid": str(uuid.uuid4()),
        "id": _next_bookmark_node_id(payload),
        "name": leaf,
        "type": "url",
        "url": str(direct_url),
    }
    children.append(target)
    return target


def _bookmark_root_candidates(
    payload: dict[str, object],
    context: BookmarkWriteContext,
) -> list[dict[str, object]]:
    root_guid = str(context.root_guid or "").strip()
    if root_guid:
        guid_matches = [node for node in _find_nodes_by_guid(payload, root_guid) if str(node.get("type") or "") == "folder"]
        if guid_matches:
            return guid_matches
    root_name = str(context.root_name or "").strip()
    if root_name:
        roots = payload.get("roots")
        matches: list[dict[str, object]] = []
        if isinstance(roots, dict):
            for root in roots.values():
                if isinstance(root, dict):
                    _collect_named_bookmark_folders(root, root_name, matches)
        if matches:
            return matches
    if str(context.root_path or "").strip():
        node = _bookmark_node_from_structural_path(payload, context.root_path)
        if node is not None and str(node.get("type") or "") == "folder" and (not root_name or str(node.get("name") or "") == root_name):
            return [node]
        return []
    if not root_name:
        return []
    roots = payload.get("roots")
    if not isinstance(roots, dict):
        return []
    matches: list[dict[str, object]] = []
    for root in roots.values():
        if isinstance(root, dict):
            _collect_named_bookmark_folders(root, root_name, matches)
    return matches


def _find_structural_path_for_node(payload: dict[str, object], target: dict[str, object]) -> str:
    roots = payload.get("roots")
    if not isinstance(roots, dict):
        return ""
    def visit(node: object, path: str) -> str:
        if node is target:
            return path
        if not isinstance(node, dict):
            return ""
        children = node.get("children")
        if isinstance(children, list):
            for index, child in enumerate(children):
                found = visit(child, f"{path}/children/{index}")
                if found:
                    return found
        return ""
    for key, root in roots.items():
        found = visit(root, f"roots/{key}")
        if found:
            return found
    return ""


def _create_bookmark_root(payload: dict[str, object], context: BookmarkWriteContext) -> tuple[dict[str, object], str]:
    parent_path = str(context.root_parent_path or "").strip()
    parent = _bookmark_node_from_structural_path(payload, parent_path)
    if parent is None or str(parent.get("type") or "") != "folder":
        raise ValueError("无法明确确认收藏夹账号根目录的父节点")
    children = parent.setdefault("children", [])
    if not isinstance(children, list):
        raise ValueError("收藏夹父目录 children 结构无效")
    name = str(context.root_name or "").strip()
    if not name:
        raise ValueError("收藏夹账号根目录名称为空")
    same_name = [child for child in children if isinstance(child, dict) and str(child.get("name") or "") == name]
    if same_name:
        raise ValueError("收藏夹账号根目录名称冲突")
    root = {
        "children": [], "date_added": _chromium_date_now(), "date_modified": "0",
        "guid": str(uuid.uuid4()), "id": _next_bookmark_node_id(payload), "name": name, "type": "folder",
    }
    children.append(root)
    return root, f"{parent_path}/children/{len(children) - 1}"


def _bookmark_node_from_structural_path(
    payload: dict[str, object],
    root_path: str,
) -> dict[str, object] | None:
    clean_path = str(root_path or "").strip()
    if clean_path.endswith("::direct"):
        clean_path = clean_path[:-8]
    parts = [part for part in clean_path.split("/") if part]
    if len(parts) < 2 or parts[0] != "roots":
        return None
    roots = payload.get("roots")
    if not isinstance(roots, dict):
        return None
    node = roots.get(parts[1])
    if not isinstance(node, dict):
        return None
    index = 2
    while index < len(parts):
        if parts[index] != "children" or index + 1 >= len(parts):
            return None
        try:
            child_index = int(parts[index + 1])
        except ValueError:
            return None
        children = node.get("children")
        if not isinstance(children, list) or child_index < 0 or child_index >= len(children):
            return None
        child = children[child_index]
        if not isinstance(child, dict):
            return None
        node = child
        index += 2
    return node


def _collect_named_bookmark_folders(
    node: dict[str, object],
    name: str,
    matches: list[dict[str, object]],
) -> None:
    if str(node.get("type") or "") == "folder" and str(node.get("name") or "") == name:
        matches.append(node)
    children = node.get("children")
    if isinstance(children, list):
        for child in children:
            if isinstance(child, dict):
                _collect_named_bookmark_folders(child, name, matches)


def _find_nodes_by_guid(payload: dict[str, object], guid: str) -> list[dict[str, object]]:
    if not guid:
        return []
    matches: list[dict[str, object]] = []
    def visit(node: object) -> None:
        if not isinstance(node, dict):
            return
        if str(node.get("guid") or "") == guid:
            matches.append(node)
        for child in node.get("children", []) if isinstance(node.get("children"), list) else []:
            visit(child)
    roots = payload.get("roots")
    if isinstance(roots, dict):
        for root in roots.values():
            visit(root)
    return matches


def _write_bookmark_temp_file(bookmark_file: Path, payload: dict[str, object]) -> Path:
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        delete=False,
        dir=str(bookmark_file.parent),
        prefix=f"{bookmark_file.name}.",
        suffix=".tmp",
    ) as temp_file:
        json.dump(payload, temp_file, ensure_ascii=False, indent=2)
        temp_file.write("\n")
        return Path(temp_file.name)


def _safe_file_component(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return text.strip("._") or "unknown"


def _is_browser_running(browser: str) -> bool:
    executable = {
        "edge": "msedge.exe",
        "microsoft edge": "msedge.exe",
        "chrome": "chrome.exe",
        "google chrome": "chrome.exe",
    }.get(str(browser or "").strip().lower())
    if not executable:
        return False
    try:
        completed = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {executable}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            check=False,
        )
    except Exception:
        return True
    return executable.lower() in str(completed.stdout or "").lower()


class BookmarkUrlUpdater:
    def __init__(
        self,
        *,
        context: BookmarkWriteContext | None = None,
        backups_dir: str | Path | None = None,
        dry_run: bool = True,
        browser_running_checker: Callable[[str], bool] | None = None,
        temp_json_validator: Callable[[Path], None] | None = None,
        log: LogCallback | None = None,
    ) -> None:
        self.context = context
        self.backups_dir = Path(backups_dir) if backups_dir is not None else None
        self.dry_run = bool(dry_run)
        self.browser_running_checker = browser_running_checker or _is_browser_running
        self.temp_json_validator = temp_json_validator
        self.log = log or (lambda _message: None)
        self._backup_path: Path | None = None
        self.last_batch_result: BookmarkBatchResult | None = None

    @property
    def mapping_path(self) -> Path | None:
        if self.backups_dir is None:
            return None
        return self.backups_dir.parent / "bookmark_mappings.json"

    @property
    def backup_path(self) -> Path | None:
        return self._backup_path

    def preview(self, bookmark_path: str) -> BookmarkUpdateResult:
        clean_path = _normalize_bookmark_path(bookmark_path)
        if not clean_path:
            return BookmarkUpdateResult("local_success", "仅刷新本地链接")
        if self.context is None:
            return BookmarkUpdateResult("bookmark_write_failed", "未配置收藏夹文件和根目录")
        bookmark_file = Path(self.context.bookmark_file)
        if not bookmark_file.is_file():
            return BookmarkUpdateResult("bookmark_write_failed", "收藏夹文件不存在")
        try:
            payload = json.loads(bookmark_file.read_text(encoding="utf-8-sig"))
        except Exception:
            return BookmarkUpdateResult("bookmark_write_failed", "收藏夹 JSON 无法读取")
        if not isinstance(payload, dict):
            return BookmarkUpdateResult("bookmark_write_failed", "收藏夹 JSON 根节点无效")
        matches = _find_bookmark_url_nodes(payload, clean_path, self.context)
        if not matches:
            return BookmarkUpdateResult("bookmark_not_found", "收藏夹路径未找到")
        if len(matches) > 1:
            return BookmarkUpdateResult("bookmark_conflict", f"收藏夹路径存在 {len(matches)} 个匹配")
        return BookmarkUpdateResult("bookmark_match_unique", "收藏夹路径唯一命中", matched_path=clean_path)

    def update(self, bookmark_path: str, direct_url: str) -> BookmarkUpdateResult:
        result = self.apply_batch([BookmarkBatchItem("", bookmark_path, direct_url)])
        matched_path = _normalize_bookmark_path(bookmark_path)
        return BookmarkUpdateResult(result.status, result.message, result.backup_path, matched_path)

    def apply_batch(
        self,
        items: Iterable[BookmarkBatchItem],
        *,
        root_create_confirm: Callable[[str], bool] | None = None,
        plan_confirm: Callable[[int, int, int, int], bool] | None = None,
    ) -> BookmarkBatchResult:
        source_items = list(items)
        batch = [
            BookmarkBatchItem(str(item.account_key or ""), _normalize_bookmark_path(item.bookmark_path), str(item.direct_url or ""))
            for item in source_items
            if _normalize_bookmark_path(item.bookmark_path)
        ]
        skipped = sum(1 for item in source_items if not _normalize_bookmark_path(item.bookmark_path))
        if not batch:
            return BookmarkBatchResult("local_success", "仅刷新本地链接", skipped=skipped)
        if self.dry_run:
            return BookmarkBatchResult("bookmark_update_skipped", "已刷新本地链接，收藏夹处于 dry-run", skipped=len(batch))
        if self.context is None:
            return BookmarkBatchResult("bookmark_write_failed", "已刷新本地链接，但未提供收藏夹文件上下文", conflicts=len(batch))
        bookmark_file = Path(self.context.bookmark_file)
        if not bookmark_file.is_file():
            return BookmarkBatchResult("bookmark_write_failed", "已刷新本地链接，但收藏夹文件不存在", conflicts=len(batch))
        if self.browser_running_checker(str(self.context.browser or "")):
            return BookmarkBatchResult("bookmark_browser_running", "已刷新本地链接，浏览器正在运行，收藏夹未写回", skipped=len(batch))
        original_bytes = bookmark_file.read_bytes()
        original_hash = hashlib.sha256(original_bytes).hexdigest()
        try:
            payload = json.loads(original_bytes.decode("utf-8-sig"))
        except Exception as exc:
            return BookmarkBatchResult("bookmark_write_failed", "收藏夹 JSON 读取失败: " + redact_sensitive_text(exc), conflicts=len(batch))
        roots = _bookmark_root_candidates(payload, self.context)
        if len(roots) > 1:
            return BookmarkBatchResult("bookmark_conflict", f"收藏夹账号根目录匹配数量为 {len(roots)}，禁止猜测", conflicts=len(batch))
        root = roots[0] if roots else None
        if root is not None and self.context.root_name and str(root.get("name") or "") != self.context.root_name:
            return BookmarkBatchResult("bookmark_conflict", "收藏夹根目录 GUID 命中但名称不一致", conflicts=len(batch))
        mappings = self._load_mappings()
        updated_payload = copy.deepcopy(payload)
        effective_context = self.context
        if root is None:
            if not self.context.allow_create_root or root_create_confirm is None or not root_create_confirm(self.context.root_name):
                return BookmarkBatchResult("bookmark_update_skipped", f"未找到收藏夹账号根目录“{self.context.root_name}”，用户未确认创建", skipped=len(batch))
            try:
                created_root, actual_root_path = _create_bookmark_root(updated_payload, self.context)
            except ValueError as exc:
                return BookmarkBatchResult("bookmark_conflict", str(exc), conflicts=len(batch))
            effective_context = replace(
                self.context,
                root_guid=str(created_root.get("guid") or ""),
                root_path=actual_root_path,
            )
        else:
            actual_root_path = _find_structural_path_for_node(payload, root)
            effective_context = replace(
                self.context,
                root_guid=str(root.get("guid") or ""),
                root_path=actual_root_path,
            )
        updated = created = conflicts = 0
        planned_paths: set[str] = set()
        mapping_updates: dict[str, dict[str, str]] = {}
        for item in batch:
            folded = item.bookmark_path.casefold()
            if folded in planned_paths:
                conflicts += 1
                continue
            planned_paths.add(folded)
            matches = _find_bookmark_url_nodes(updated_payload, item.bookmark_path, effective_context)
            mapped = mappings.get(item.account_key) if item.account_key else None
            if mapped:
                expected_path = _normalize_bookmark_path(mapped.get("path", ""))
                guid = str(mapped.get("guid") or "")
                guid_matches = _find_nodes_by_guid(updated_payload, guid)
                if expected_path.casefold() != folded or len(guid_matches) != 1 or guid_matches[0] not in matches:
                    conflicts += 1
                    continue
            if len(matches) > 1:
                conflicts += 1
                continue
            if matches:
                target = matches[0]
                target["url"] = item.direct_url
                updated += 1
            else:
                try:
                    target = _create_bookmark_url_path(updated_payload, item.bookmark_path, item.direct_url, effective_context)
                    created += 1
                except ValueError:
                    conflicts += 1
                    continue
            if item.account_key:
                mapping_updates[item.account_key] = {"guid": str(target.get("guid") or ""), "path": item.bookmark_path}
        if conflicts:
            return BookmarkBatchResult("bookmark_conflict", f"收藏夹整批计划存在 {conflicts} 项冲突，未写回", updated, created, conflicts, skipped)
        if plan_confirm is not None and not plan_confirm(updated, created, 0, skipped):
            return BookmarkBatchResult("bookmark_update_skipped", "用户取消收藏夹整批写入", updated, created, 0, skipped)
        updated_payload["checksum"] = calculate_chromium_bookmarks_checksum(updated_payload)
        temp_path: Path | None = None
        try:
            backup_path = self._ensure_backup(bookmark_file)
            temp_path = _write_bookmark_temp_file(bookmark_file, updated_payload)
            reloaded = json.loads(temp_path.read_text(encoding="utf-8-sig"))
            for item in batch:
                matches = _find_bookmark_url_nodes(reloaded, item.bookmark_path, effective_context)
                if len(matches) != 1 or str(matches[0].get("url") or "") != item.direct_url:
                    raise ValueError("临时收藏夹整批复读验证失败")
            if self.temp_json_validator is not None:
                self.temp_json_validator(temp_path)
            if hashlib.sha256(bookmark_file.read_bytes()).hexdigest() != original_hash:
                raise RuntimeError("收藏夹文件在处理期间被外部修改")
            temp_path.replace(bookmark_file)
            written = json.loads(bookmark_file.read_text(encoding="utf-8-sig"))
            for item in batch:
                matches = _find_bookmark_url_nodes(written, item.bookmark_path, effective_context)
                if len(matches) != 1 or str(matches[0].get("url") or "") != item.direct_url:
                    shutil.copy2(backup_path, bookmark_file)
                    raise ValueError("收藏夹写后验证失败，已恢复原文件")
            mappings.update(mapping_updates)
            self._save_mappings(mappings)
            self.log(f"[收藏夹写回] batch_success updated={updated} created={created} skipped={skipped}")
            result = BookmarkBatchResult(
                "bookmark_success", f"收藏夹整批完成：更新 {updated}，新增 {created}，冲突 0，跳过 {skipped}",
                updated, created, 0, skipped, str(backup_path), effective_context.root_guid,
                effective_context.root_path, effective_context.root_name,
            )
            self.last_batch_result = result
            return result
        except Exception as exc:
            return BookmarkBatchResult("bookmark_write_failed", "收藏夹整批写入失败: " + redact_sensitive_text(exc), updated, created, 0, skipped, str(self._backup_path or ""))
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _load_mappings(self) -> dict[str, dict[str, str]]:
        path = self.mapping_path
        if path is None or not path.is_file():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            raw = payload.get("accounts", {}) if isinstance(payload, dict) else {}
            return {str(key): {"guid": str(value.get("guid") or ""), "path": str(value.get("path") or "")} for key, value in raw.items() if isinstance(value, dict)}
        except Exception:
            return {}

    def _save_mappings(self, mappings: dict[str, dict[str, str]]) -> None:
        path = self.mapping_path
        if path is not None:
            _atomic_write_text(path, json.dumps({"schema_version": 1, "accounts": mappings}, ensure_ascii=False, indent=2))

    def _legacy_update(self, bookmark_path: str, direct_url: str) -> BookmarkUpdateResult:
        clean_path = _normalize_bookmark_path(bookmark_path)
        if not clean_path:
            return BookmarkUpdateResult("local_success", "已刷新本地链接")
        if self.dry_run:
            self.log(f"[收藏夹写回] dry-run path={clean_path}")
            return BookmarkUpdateResult("bookmark_update_skipped", "已刷新本地链接，收藏夹处于 dry-run")
        if self.context is None:
            return BookmarkUpdateResult("bookmark_write_failed", "已刷新本地链接，但未提供收藏夹文件上下文")

        bookmark_file = Path(self.context.bookmark_file)
        if not bookmark_file.is_file():
            return BookmarkUpdateResult("bookmark_write_failed", "已刷新本地链接，但收藏夹文件不存在")
        if self.browser_running_checker(str(self.context.browser or "")):
            self.log(f"[收藏夹写回] browser_running browser={self.context.browser or 'unknown'}")
            return BookmarkUpdateResult(
                "bookmark_browser_running",
                "已刷新本地链接，浏览器正在运行，收藏夹未写回",
            )

        try:
            payload = json.loads(bookmark_file.read_text(encoding="utf-8-sig"))
        except Exception as exc:
            return BookmarkUpdateResult(
                "bookmark_write_failed",
                "已刷新本地链接，收藏夹 JSON 读取失败: " + redact_sensitive_text(exc),
            )
        if not isinstance(payload, dict):
            return BookmarkUpdateResult("bookmark_write_failed", "已刷新本地链接，收藏夹 JSON 根节点无效")

        matches = _find_bookmark_url_nodes(payload, clean_path, self.context)
        if len(matches) > 1:
            self.log(f"[收藏夹写回] bookmark_conflict path={clean_path} matches={len(matches)}")
            return BookmarkUpdateResult("bookmark_conflict", "已刷新本地链接，收藏夹路径存在多个匹配")

        target = matches[0] if matches else None
        if target is not None and str(target.get("url") or "") == str(direct_url or ""):
            return BookmarkUpdateResult(
                "bookmark_success",
                "本地链接和收藏夹地址均已是最新",
                backup_path=str(self._backup_path or ""),
                matched_path=clean_path,
            )

        updated_payload = copy.deepcopy(payload)
        updated_matches = _find_bookmark_url_nodes(updated_payload, clean_path, self.context)
        created = False
        if len(updated_matches) > 1:
            return BookmarkUpdateResult("bookmark_conflict", "已刷新本地链接，收藏夹路径在写入前不再唯一")
        if updated_matches:
            updated_matches[0]["url"] = str(direct_url)
        else:
            try:
                _create_bookmark_url_path(updated_payload, clean_path, str(direct_url), self.context)
                created = True
            except ValueError as exc:
                self.log(f"[收藏夹写回] bookmark_conflict path={clean_path}: {exc}")
                return BookmarkUpdateResult("bookmark_conflict", "已刷新本地链接，" + str(exc))
        updated_payload["checksum"] = calculate_chromium_bookmarks_checksum(updated_payload)

        temp_path: Path | None = None
        try:
            backup_path = self._ensure_backup(bookmark_file)
            temp_path = _write_bookmark_temp_file(bookmark_file, updated_payload)
            reloaded = json.loads(temp_path.read_text(encoding="utf-8-sig"))
            if reloaded != updated_payload:
                raise ValueError("临时收藏夹 JSON 与预期内容不一致")
            reloaded_matches = _find_bookmark_url_nodes(reloaded, clean_path, self.context)
            if len(reloaded_matches) != 1 or str(reloaded_matches[0].get("url") or "") != str(direct_url):
                raise ValueError("临时收藏夹 JSON 目标地址校验失败")
            if self.temp_json_validator is not None:
                self.temp_json_validator(temp_path)
            temp_path.replace(bookmark_file)
            self.log(
                f"[收藏夹写回] bookmark_success file={bookmark_file.name} "
                f"backup={backup_path.name} path={clean_path}"
            )
            return BookmarkUpdateResult(
                "bookmark_success",
                "本地链接和收藏夹地址均已新增" if created else "本地链接和收藏夹地址均已更新",
                backup_path=str(backup_path),
                matched_path=clean_path,
            )
        except Exception as exc:
            self.log(f"[收藏夹写回] bookmark_write_failed file={bookmark_file.name}: {redact_sensitive_text(exc)}")
            return BookmarkUpdateResult(
                "bookmark_write_failed",
                "已刷新本地链接，收藏夹写入失败: " + redact_sensitive_text(exc),
                backup_path=str(self._backup_path or ""),
                matched_path=clean_path,
            )
        finally:
            if temp_path is not None and temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass

    def _ensure_backup(self, bookmark_file: Path) -> Path:
        if self._backup_path is not None:
            return self._backup_path
        backup_dir = self.backups_dir or bookmark_file.parent / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        browser = _safe_file_component(self.context.browser if self.context is not None else "browser")
        profile = _safe_file_component(self.context.profile if self.context is not None else "profile")
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = backup_dir / f"Bookmarks_{browser}_{profile}_{stamp}.json"
        shutil.copy2(bookmark_file, backup_path)
        self._backup_path = backup_path
        return backup_path


LoginCapturer = Callable[[RefreshAccount, ChannelConfig, Event | None], DirectLoginFields]
ProgressCallback = Callable[[RefreshResult], None]
LogCallback = Callable[[str], None]


def _stable_bookmark_account_key(account: RefreshAccount) -> str:
    username = str(account.username or "").strip().casefold()
    channel = str(account.channel or "").strip().casefold()
    if username:
        return "account:" + hashlib.sha256(f"{channel}\0{username}".encode("utf-8")).hexdigest()
    return "bookmark:" + _normalize_bookmark_path(account.bookmark_path).casefold()


class DirectLinkRefreshService:
    def __init__(
        self,
        *,
        data_dir: str | Path | None = None,
        login_capturer: LoginCapturer,
        bookmark_updater: BookmarkUrlUpdater | None = None,
        expire_days: int = CLIENT_DIRECT_EXPIRE_DAYS,
        log: LogCallback | None = None,
        root_create_confirm: Callable[[str], bool] | None = None,
        bookmark_plan_confirm: Callable[[int, int, int, int], bool] | None = None,
    ) -> None:
        self.paths = ensure_refresh_data_dir(data_dir)
        self.channels = load_channels(self.paths.data_dir)
        self.login_capturer = login_capturer
        self.bookmark_updater = bookmark_updater or BookmarkUrlUpdater(dry_run=True)
        self.expire_days = int(expire_days or CLIENT_DIRECT_EXPIRE_DAYS)
        self.log = log or (lambda _message: None)
        self.root_create_confirm = root_create_confirm
        self.bookmark_plan_confirm = bookmark_plan_confirm

    def refresh_accounts(
        self,
        accounts: Iterable[RefreshAccount],
        *,
        channel_name: str = DEFAULT_CHANNEL_NAME,
        names: set[str] | None = None,
        limit: int = 0,
        retries: int = 1,
        stop_event: Event | None = None,
        progress: ProgressCallback | None = None,
    ) -> RefreshRunSummary:
        selected_accounts = [account for account in accounts if not names or account.name in names]
        if limit and int(limit) > 0:
            selected_accounts = selected_accounts[: int(limit)]
        account_store = AccountsStore(self.paths.accounts_path)
        direct_store = DirectLinkStore(self.paths.direct_links_path)
        results: list[RefreshResult] = []
        saved_accounts = account_store.load()
        account_by_name = {account.name: account for account in saved_accounts}
        for account in selected_accounts:
            account_by_name[account.name] = account
        all_accounts = list(account_by_name.values())
        used_url_paths: set[Path] = set()
        selected_names = {account.name for account in selected_accounts}
        for account in saved_accounts:
            if account.name in selected_names:
                continue
            try:
                used_url_paths.add(_account_url_shortcut_target(self.paths, account))
            except ValueError:
                continue
        for record_name, record in direct_store.links.items():
            if record_name in selected_names or not isinstance(record, dict):
                continue
            candidate = _generated_url_candidate_from_record(self.paths, str(record.get("url_file") or ""))
            if candidate is not None:
                used_url_paths.add(candidate)

        for account in selected_accounts:
            if stop_event is not None and stop_event.is_set():
                break
            previous_record = direct_store.get(account.name) or {}
            result = self._refresh_one(
                account,
                channel_name=channel_name,
                retries=retries,
                stop_event=stop_event,
                used_url_paths=used_url_paths,
                previous_url_file=str(previous_record.get("url_file") or ""),
            )
            results.append(result)
            try:
                direct_store.update_from_result(result)
            except Exception as exc:
                self.log(f"[刷新地址] {account.name} 直登链接库保存失败，已保留 .url 并继续: {redact_sensitive_text(exc)}")
            all_accounts = update_accounts_after_result(all_accounts, result)
            try:
                account_store.save(all_accounts)
            except Exception as exc:
                self.log(f"[刷新地址] {account.name} 账号状态保存失败，已继续下一账号: {redact_sensitive_text(exc)}")
            if progress is not None:
                progress(result)

        bookmark_items = [
            BookmarkBatchItem(_stable_bookmark_account_key(account), result.bookmark_path, result.direct_url)
            for account, result in ((account_by_name.get(result.name), result) for result in results)
            if account is not None and result.direct_url and result.bookmark_path
        ]
        if bookmark_items and not (stop_event is not None and stop_event.is_set()):
            bookmark_result = self.bookmark_updater.apply_batch(
                bookmark_items,
                root_create_confirm=self.root_create_confirm,
                plan_confirm=self.bookmark_plan_confirm,
            )
            results = [
                replace(result, status=bookmark_result.status, message=f"{bookmark_result.message}; {result.message}")
                if result.direct_url and result.bookmark_path else result
                for result in results
            ]
            for result in results:
                all_accounts = update_accounts_after_result(all_accounts, result)
                try:
                    direct_store.update_from_result(result)
                except Exception as exc:
                    self.log(f"[刷新地址] {result.name} 整批收藏夹状态保存失败: {redact_sensitive_text(exc)}")
            account_store.save(all_accounts)

        RefreshSummaryWriter(self.paths.summary_path).write(results)
        return summarize_results(results)

    def _refresh_one(
        self,
        account: RefreshAccount,
        *,
        channel_name: str,
        retries: int,
        stop_event: Event | None,
        used_url_paths: set[Path],
        previous_url_file: str = "",
    ) -> RefreshResult:
        generated_at = datetime.now().astimezone()
        expire_hint = generated_at + timedelta(days=self.expire_days)
        channel = self.channels.get(account.channel or channel_name) or self.channels.get(channel_name) or default_channel_config()
        missing = [field for field, value in (("name", account.name), ("username", account.username), ("password", account.password)) if not str(value or "").strip()]
        if missing:
            return RefreshResult(
                name=account.name,
                channel=channel.name,
                generated_at=generated_at,
                expire_hint=expire_hint,
                status="config_failed",
                message="缺少字段: " + ", ".join(missing),
                bookmark_path=account.bookmark_path,
            )
        if not account.enabled:
            return RefreshResult(
                name=account.name,
                channel=channel.name,
                generated_at=generated_at,
                expire_hint=expire_hint,
                status="skipped",
                message="账号已禁用",
                bookmark_path=account.bookmark_path,
            )

        max_attempts = max(1, int(retries or 0) + 1)
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            if stop_event is not None and stop_event.is_set():
                return RefreshResult(
                    name=account.name,
                    channel=channel.name,
                    generated_at=generated_at,
                    expire_hint=expire_hint,
                    status="stopped",
                    message="用户停止",
                    bookmark_path=account.bookmark_path,
                )
            try:
                self.log(f"[刷新地址] {account.name} attempt={attempt}/{max_attempts}")
                fields = self.login_capturer(account, channel, stop_event)
                fields.validate()
                direct_url = build_client_direct_url(fields, channel=channel)
                url_path = write_account_url_shortcut(
                    self.paths,
                    account,
                    direct_url,
                    used_paths=used_url_paths,
                    previous_url_file=previous_url_file,
                )
                relative_url_path = url_path.relative_to(self.paths.data_dir).as_posix()
                status = "local_success"
                message = (
                    "已刷新本地链接，收藏夹等待整批处理; "
                    f"uid_len={len(fields.uid)} uname_len={len(fields.uname)} "
                    f"token_len={len(fields.token)} time_len={len(fields.time)} sign_len={len(fields.sign)} "
                    f"url_file={relative_url_path}"
                )
                return RefreshResult(
                    name=account.name,
                    channel=channel.name,
                    generated_at=generated_at,
                    expire_hint=expire_hint,
                    status=status,
                    message=message,
                    direct_url=direct_url,
                    uid=fields.uid,
                    uname=fields.uname,
                    uid_len=len(fields.uid),
                    uname_len=len(fields.uname),
                    token_len=len(fields.token),
                    time_len=len(fields.time),
                    sign_len=len(fields.sign),
                    bookmark_path=account.bookmark_path,
                    url_file=relative_url_path,
                )
            except Exception as exc:
                if isinstance(exc, InterruptedError) or (stop_event is not None and stop_event.is_set()):
                    return RefreshResult(
                        name=account.name,
                        channel=channel.name,
                        generated_at=generated_at,
                        expire_hint=expire_hint,
                        status="stopped",
                        message="用户停止",
                        bookmark_path=account.bookmark_path,
                    )
                last_error = exc
                self.log(f"[刷新地址] {account.name} failed attempt={attempt}/{max_attempts}: {redact_sensitive_text(exc)}")
        assert last_error is not None
        return RefreshResult(
            name=account.name,
            channel=channel.name,
            generated_at=generated_at,
            expire_hint=expire_hint,
            status=_status_for_exception(last_error),
            message=redact_sensitive_text(str(last_error)),
            bookmark_path=account.bookmark_path,
        )


def update_accounts_after_result(accounts: Iterable[RefreshAccount], result: RefreshResult) -> list[RefreshAccount]:
    updated: list[RefreshAccount] = []
    found = False
    for account in accounts:
        if account.name != result.name:
            updated.append(account)
            continue
        found = True
        updated.append(
            replace(
                account,
                last_refresh_time=_iso(result.generated_at),
                expire_hint=_iso(result.expire_hint),
                last_status=result.status,
            )
        )
    if not found and result.name:
        updated.append(
            RefreshAccount(
                name=result.name,
                username="",
                password="",
                channel=result.channel,
                last_refresh_time=_iso(result.generated_at),
                expire_hint=_iso(result.expire_hint),
                last_status=result.status,
            )
        )
    return updated


def summarize_results(results: Iterable[RefreshResult]) -> RefreshRunSummary:
    result_list = list(results)
    success = sum(1 for result in result_list if result.success)
    bookmark_success_statuses = {"bookmark_success"}
    bookmark_failure_statuses = {
        "bookmark_not_found",
        "bookmark_conflict",
        "bookmark_browser_running",
        "bookmark_write_failed",
    }
    return RefreshRunSummary(
        total=len(result_list),
        success=success,
        failure=len(result_list) - success,
        local_links=sum(1 for result in result_list if result.direct_url),
        bookmark_success=sum(1 for result in result_list if result.status in bookmark_success_statuses),
        bookmark_failure=sum(1 for result in result_list if result.status in bookmark_failure_statuses),
        results=result_list,
        bookmark_skipped=sum(1 for result in result_list if result.status == "bookmark_update_skipped"),
    )


def resolve_client_direct_url_for_account(
    account: AccountConfig,
    direct_links_path: str | Path | None = None,
    *,
    now: datetime | None = None,
) -> ResolvedDirectUrl:
    return resolve_client_direct_url_for_identity(
        account,
        direct_links_path,
        now=now,
    )


def resolve_client_direct_url_for_identity(
    account: AccountConfig,
    direct_links_path: str | Path | None = None,
    *,
    account_key: str = "",
    refresh_account_name: str = "",
    bookmark_path: str = "",
    slot_index: int = 0,
    now: datetime | None = None,
) -> ResolvedDirectUrl:
    store = DirectLinkStore(direct_links_path or ensure_refresh_data_dir().direct_links_path)
    candidates = _account_direct_link_names(account)
    for value in (account_key, refresh_account_name):
        clean = str(value or "").strip()
        if clean and clean not in candidates:
            candidates.append(clean)
    current = now or datetime.now().astimezone()
    matches: list[tuple[str, dict[str, object], str]] = []
    expected_path = _normalize_bookmark_path(bookmark_path).casefold()
    level = str(getattr(account, "level", "") or "").strip().casefold()
    leaf_values = {
        str(value or "").strip().casefold()
        for value in (
            getattr(account, "bookmark_title", ""),
            getattr(account, "bookmark_no", ""),
            slot_index,
        )
        if str(value or "").strip()
    }
    candidate_names = {str(name or "").strip().casefold() for name in candidates if str(name or "").strip()}
    for store_name, raw_record in store.links.items():
        if not isinstance(raw_record, dict):
            continue
        record = dict(raw_record)
        direct_url = str(record.get("direct_url") or "").strip()
        if not direct_url:
            continue
        record_name = str(record.get("name") or store_name or "").strip()
        record_path = _normalize_bookmark_path(record.get("bookmark_path", "")).casefold()
        path_parts = [part for part in record_path.split("/") if part]
        name_match = str(store_name or "").strip().casefold() in candidate_names or record_name.casefold() in candidate_names
        exact_path_match = bool(expected_path and record_path == expected_path)
        suffix_match = bool(
            level
            and leaf_values
            and len(path_parts) >= 2
            and path_parts[-2] == level
            and path_parts[-1] in leaf_values
        )
        if name_match or exact_path_match or suffix_match:
            matches.append((str(store_name or record_name), record, direct_url))
    distinct_urls = {direct_url for _name, _record, direct_url in matches}
    if len(distinct_urls) > 1:
        return ResolvedDirectUrl(
            name=candidates[0] if candidates else "",
            direct_url="",
            status="conflict",
            message="本地直登链接存在多个候选，已保留收藏夹原链接",
        )
    if matches:
        name, record, direct_url = matches[0]
        expire_hint = str(record.get("expire_hint") or "")
        expired = _is_expired(expire_hint, current)
        return ResolvedDirectUrl(
            name=name,
            direct_url=direct_url,
            status="expired" if expired else "found",
            message="链接可能已过期，请先刷新地址" if expired else "已从本地直登链接库读取最新链接",
            expire_hint=expire_hint,
            expired=expired,
            bookmark_path=str(record.get("bookmark_path") or ""),
        )
    return ResolvedDirectUrl(
        name=candidates[0] if candidates else "",
        direct_url="",
        status="missing",
        message="未找到该账号直登链接，请先刷新地址",
    )


def write_url_shortcut(output_dir: str | Path, name: str, url: str, *, used_paths: set[Path] | None = None) -> Path:
    clean_name = _safe_shortcut_name(name)
    if not clean_name:
        raise ValueError("账号 name 为空，无法生成 .url 文件名")
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{clean_name}.url"
    if used_paths is not None:
        suffix = 2
        while target in used_paths:
            target = target_dir / f"{clean_name}_{suffix}.url"
            suffix += 1
        used_paths.add(target)
    _atomic_write_text(target, f"[InternetShortcut]\nURL={url}\n")
    return target


def write_account_url_shortcut(
    paths: RefreshDataPaths,
    account: RefreshAccount,
    url: str,
    *,
    used_paths: set[Path] | None = None,
    previous_url_file: str = "",
) -> Path:
    target = _account_url_shortcut_target(paths, account)
    target = _deduplicate_generated_url_path(target, used_paths)
    _atomic_write_text(target, f"[InternetShortcut]\nURL={url}\n")
    written = target.read_text(encoding="utf-8")
    if written != f"[InternetShortcut]\nURL={url}\n":
        raise OSError("生成的直登链接复读校验失败")
    _remove_previous_generated_url(paths, previous_url_file, keep=target, protected_paths=used_paths)
    return target


def delete_refresh_account_resources(
    paths: RefreshDataPaths,
    name: str,
    *,
    account_keys: set[str] | None = None,
    client_batch_store=None,
    runtime_cache: dict | None = None,
    unlink_file: Callable[[Path], None] | None = None,
) -> AccountDeletionResult:
    clean_name = str(name or "").strip()
    if not clean_name:
        raise ValueError("删除账号名称不能为空")
    errors: list[str] = []
    account_store = AccountsStore(paths.accounts_path)
    accounts = account_store.load()
    if account_store.load_error is not None:
        return AccountDeletionResult(name=clean_name, errors=["accounts:read_failed"])
    target_accounts = [account for account in accounts if account.name == clean_name]
    if len(target_accounts) > 1:
        return AccountDeletionResult(name=clean_name, errors=["accounts:identity_conflict"])
    target_account = target_accounts[0] if len(target_accounts) == 1 else None
    account_removed = False
    if target_account is not None:
        try:
            account_store.save([account for account in accounts if account.name != clean_name])
            account_removed = True
        except Exception as exc:
            errors.append(f"accounts:{type(exc).__name__}")

    direct_store = DirectLinkStore(paths.direct_links_path)
    direct_record = direct_store.get(clean_name) or {}
    protected_candidates: list[Path] = []
    if direct_store.load_error is None:
        for other_name, other_record in direct_store.links.items():
            if other_name == clean_name or not isinstance(other_record, dict):
                continue
            other_candidate = _generated_url_candidate_from_record(paths, str(other_record.get("url_file") or ""))
            if other_candidate is not None:
                protected_candidates.append(other_candidate)
    for other_account in accounts:
        if other_account.name == clean_name:
            continue
        try:
            protected_candidates.append(_account_url_shortcut_target(paths, other_account))
        except ValueError:
            continue
    direct_link_removed = False
    if direct_store.load_error is not None:
        errors.append("direct_links:read_failed")
    elif clean_name in direct_store.links:
        try:
            direct_store.links.pop(clean_name, None)
            direct_store.save()
            direct_link_removed = True
        except Exception as exc:
            errors.append(f"direct_links:{type(exc).__name__}")

    candidates: set[Path] = set()
    if direct_record or (target_account is not None and not str(target_account.bookmark_path or "").strip()):
        candidates.add(paths.url_dir / (_safe_generated_path_segment(clean_name) + ".url"))
    recorded_candidate = _generated_url_candidate_from_record(paths, str(direct_record.get("url_file") or ""))
    if recorded_candidate is not None:
        candidates.add(recorded_candidate)
    if target_account is not None:
        try:
            candidates.add(_account_url_shortcut_target(paths, target_account))
        except ValueError as exc:
            errors.append(f"url_path:{type(exc).__name__}")

    remover = unlink_file or (lambda path: path.unlink())
    removed_files: list[str] = []
    protected_path_keys: set[str] = set()
    for candidate in protected_candidates:
        try:
            protected_path_keys.add(str(candidate.resolve()).casefold())
        except OSError:
            continue
    resolved_candidates: dict[str, Path] = {}
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
            resolved_candidates[str(resolved).casefold()] = resolved
        except OSError as exc:
            errors.append(f"url_file:{candidate.name}:{type(exc).__name__}")
    for resolved in sorted(resolved_candidates.values(), key=lambda path: path.as_posix()):
        try:
            if str(resolved).casefold() in protected_path_keys:
                continue
            allowed_roots = (paths.url_dir.resolve(), paths.grouped_url_dir.resolve())
            if resolved.suffix.lower() != ".url" or not any(root in resolved.parents for root in allowed_roots):
                continue
            if not resolved.is_file():
                continue
            remover(resolved)
            removed_files.append(resolved.relative_to(paths.data_dir.resolve()).as_posix())
            _remove_empty_group_parents(resolved.parent, paths.grouped_url_dir.resolve())
        except Exception as exc:
            errors.append(f"url_file:{resolved.name}:{type(exc).__name__}")

    stable_keys = {str(key or "").strip() for key in (account_keys or set()) if str(key or "").strip()}
    bindings_removed = 0
    if client_batch_store is not None:
        original_bindings: list[tuple[object, list[object]]] = []
        try:
            for batch in list(getattr(client_batch_store, "batches", []) or []):
                original = list(getattr(batch, "bindings", []) or [])
                original_bindings.append((batch, original))
                kept = []
                for binding in original:
                    binding_key = str(getattr(binding, "account_key", "") or "").strip()
                    refresh_name = str(getattr(binding, "refresh_account_name", "") or "").strip()
                    bookmark_path = str(getattr(binding, "bookmark_path", "") or "").strip()
                    exact_bookmark = bool(
                        target_account is not None
                        and target_account.bookmark_path
                        and bookmark_path == target_account.bookmark_path
                    )
                    if stable_keys and binding_key:
                        remove_binding = binding_key in stable_keys
                    else:
                        remove_binding = refresh_name == clean_name or exact_bookmark
                    if remove_binding:
                        bindings_removed += 1
                        continue
                    kept.append(binding)
                batch.bindings = kept
            if bindings_removed:
                client_batch_store.save()
        except Exception as exc:
            for batch, original in original_bindings:
                batch.bindings = original
            bindings_removed = 0
            errors.append(f"bindings:{type(exc).__name__}")

    cache_entries_removed = 0
    if runtime_cache is not None:
        for key in {clean_name, *stable_keys}:
            if key in runtime_cache:
                runtime_cache.pop(key, None)
                cache_entries_removed += 1

    return AccountDeletionResult(
        name=clean_name,
        account_removed=account_removed,
        direct_link_removed=direct_link_removed,
        url_files_removed=removed_files,
        bindings_removed=bindings_removed,
        cache_entries_removed=cache_entries_removed,
        errors=errors,
    )


def _account_url_shortcut_target(paths: RefreshDataPaths, account: RefreshAccount) -> Path:
    bookmark_path = str(account.bookmark_path or "").strip()
    if bookmark_path:
        segments = _bookmark_mirror_segments(bookmark_path)
        return paths.grouped_url_dir.joinpath(*segments[:-1], segments[-1] + ".url")
    return paths.url_dir / (_safe_generated_path_segment(account.name) + ".url")


def _generated_url_candidate_from_record(paths: RefreshDataPaths, url_file: str) -> Path | None:
    raw = str(url_file or "").strip().replace("\\", "/")
    if not raw:
        return None
    relative = Path(raw)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return None
    if len(relative.parts) == 1:
        return paths.url_dir / relative.name
    return paths.data_dir / relative


def _bookmark_mirror_segments(bookmark_path: str) -> list[str]:
    raw = str(bookmark_path or "").strip()
    if not raw:
        raise ValueError("bookmark_path 为空")
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise ValueError("bookmark_path 不允许绝对路径、盘符或 UNC")
    raw_segments = [segment.strip() for segment in re.split(r"[\\/]+", raw) if segment.strip()]
    if not raw_segments or any(segment in {".", ".."} for segment in raw_segments):
        raise ValueError("bookmark_path 包含非法路径段")
    return [_safe_generated_path_segment(segment) for segment in raw_segments]


def _safe_generated_path_segment(value: object) -> str:
    text = str(value or "").strip()
    for char in '<>:"/\\|?*':
        text = text.replace(char, "_")
    text = text.rstrip(" .")
    if not text or text in {".", ".."}:
        raise ValueError("生成文件路径段为空或非法")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    if text.upper() in reserved:
        text += "_"
    return text


def _deduplicate_generated_url_path(target: Path, used_paths: set[Path] | None) -> Path:
    if used_paths is None:
        return target
    candidate = target
    suffix = 2
    while candidate in used_paths:
        candidate = target.with_name(f"{target.stem}_{suffix}{target.suffix}")
        suffix += 1
    used_paths.add(candidate)
    return candidate


def _remove_previous_generated_url(
    paths: RefreshDataPaths,
    previous_url_file: str,
    *,
    keep: Path,
    protected_paths: set[Path] | None = None,
) -> None:
    candidate = _generated_url_candidate_from_record(paths, previous_url_file)
    if candidate is None:
        return
    try:
        resolved = candidate.resolve()
        keep_resolved = keep.resolve()
        allowed_roots = (paths.url_dir.resolve(), paths.grouped_url_dir.resolve())
        if resolved == keep_resolved or resolved.suffix.lower() != ".url":
            return
        protected_keys = {
            str(path.resolve()).casefold()
            for path in (protected_paths or set())
        }
        if str(resolved).casefold() in protected_keys:
            return
        if not any(resolved == root or root in resolved.parents for root in allowed_roots):
            return
        if resolved.is_file():
            resolved.unlink()
        _remove_empty_group_parents(resolved.parent, paths.grouped_url_dir.resolve())
    except OSError:
        return


def _remove_empty_group_parents(start: Path, grouped_root: Path) -> None:
    current = start
    while current != grouped_root and grouped_root in current.parents:
        try:
            current.rmdir()
        except OSError:
            break
        current = current.parent


def update_summary_csv(path: str | Path, rows: list[RefreshSummaryRow]) -> Path:
    results = [
        RefreshResult(
            name=row.name,
            channel=DEFAULT_CHANNEL_NAME,
            generated_at=row.generated_at,
            expire_hint=row.expire_hint,
            status=row.status,
            message=row.message,
        )
        for row in rows
    ]
    return RefreshSummaryWriter(path).write(results)


def redact_sensitive_text(value: object) -> str:
    text = str(value if value is not None else "")
    text = SENSITIVE_VALUE_RE.sub(r"\1***MASKED***", text)
    text = re.sub(r"(?i)(https?://[^\s]+(?:token|sign)[^\s]+)", "<direct_url_masked>", text)
    return text


def _channels_to_payload(channels: dict[str, ChannelConfig]) -> dict[str, object]:
    return {"schema_version": 1, "channels": {name: asdict(channel) for name, channel in channels.items()}}


def _import_accounts_from_xlsx(path: Path, *, channel: str) -> ImportAccountsResult:
    try:
        import openpyxl  # type: ignore
    except Exception as exc:
        raise ValueError("当前环境未安装 openpyxl，暂不支持 xlsx 导入") from exc
    workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet = workbook.active
    rows = []
    for row in sheet.iter_rows(values_only=True):
        values = ["" if value is None else str(value) for value in row]
        if any(value.strip() for value in values):
            rows.append(",".join(_csv_escape(value) for value in values))
    return import_accounts_from_text("\n".join(rows), channel=channel)


def _csv_escape(value: str) -> str:
    if any(char in value for char in ',\n"'):
        return '"' + value.replace('"', '""') + '"'
    return value


def _normalize_header(value: object) -> str:
    return str(value or "").strip().lower().replace(" ", "_")


def _safe_shortcut_name(name: str) -> str:
    text = str(name or "").strip()
    for char in '<>:"/\\|?*':
        text = text.replace(char, "_")
    return text.rstrip(" .")


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), suffix=".tmp") as tmp:
        tmp.write(text)
        tmp_path = Path(tmp.name)
    tmp_path.replace(path)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.isoformat(timespec="seconds")


def _parse_iso(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _is_expired(expire_hint: object, now: datetime) -> bool:
    expire_time = _parse_iso(expire_hint)
    if expire_time is None:
        return False
    current = now
    if current.tzinfo is None and expire_time.tzinfo is not None:
        current = current.astimezone()
    if current.tzinfo is not None and expire_time.tzinfo is None:
        expire_time = expire_time.replace(tzinfo=current.tzinfo)
    return expire_time <= current


def _account_direct_link_names(account: AccountConfig) -> list[str]:
    names: list[str] = []
    for value in (
        getattr(account, "bookmark_title", ""),
        getattr(account, "key", ""),
        str(getattr(account, "bookmark_no", "") or ""),
        getattr(account, "display_name", ""),
    ):
        clean = str(value or "").strip()
        if clean and clean not in names:
            names.append(clean)
    return names


def _status_for_exception(exc: Exception) -> str:
    if isinstance(exc, LoginFailed):
        return "login_failed"
    if isinstance(exc, OSError):
        return "write_failed"
    return "capture_failed"
