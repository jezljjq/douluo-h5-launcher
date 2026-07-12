from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from .config import AccountConfig
from .direct_link_refresh import RefreshAccount


DEFAULT_GROUP_NAME = "默认组"
SINGLE_GROUP_NAME = "单层账号"


def _normalized_bookmark_path(value: object) -> str:
    return "/".join(part.strip() for part in re.split(r"[\\/]+", str(value or "").strip()) if part.strip())


def logical_group_from_bookmark_path(bookmark_path: object) -> str:
    parts = [part for part in _normalized_bookmark_path(bookmark_path).split("/") if part]
    if not parts:
        return DEFAULT_GROUP_NAME
    if len(parts) <= 2:
        return SINGLE_GROUP_NAME
    return parts[-2]


def stable_refresh_account_key(account: RefreshAccount) -> str:
    username = str(account.username or "").strip().casefold()
    channel = str(account.channel or "").strip().casefold()
    if username:
        digest = hashlib.sha256(f"{channel}\0{username}".encode("utf-8")).hexdigest()
        return f"account:{digest}"
    path = _normalized_bookmark_path(account.bookmark_path).casefold()
    if path:
        return f"bookmark:{path}"
    digest = hashlib.sha256(str(account.name or "").strip().casefold().encode("utf-8")).hexdigest()
    return f"name:{digest}"


@dataclass(frozen=True)
class LoginAccountRow:
    key: str
    account: RefreshAccount
    included: bool
    order_index: int

    @property
    def group(self) -> str:
        return logical_group_from_bookmark_path(self.account.bookmark_path)


class LoginAccountRosterStore:
    """Stores only login participation/order, never refresh credentials or URLs."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._states: dict[str, dict[str, object]] = {}
        self._seen: set[str] = set()
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if not self.path.is_file():
            return
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8-sig"))
        except Exception:
            return
        if not isinstance(payload, dict):
            return
        raw_states = payload.get("accounts", {})
        if isinstance(raw_states, dict):
            self._states = {
                str(key): dict(value)
                for key, value in raw_states.items()
                if isinstance(value, dict)
            }
        raw_seen = payload.get("seen_keys", [])
        if isinstance(raw_seen, list):
            self._seen = {str(key) for key in raw_seen if str(key)}

    def _save(self) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "accounts": self._states,
            "seen_keys": sorted(self._seen),
        }
        temp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self.path)
        return self.path

    def reconcile(self, accounts: Iterable[RefreshAccount]) -> list[LoginAccountRow]:
        self._load()
        source = list(accounts)
        by_key = {stable_refresh_account_key(account): account for account in source}
        present_keys = set(by_key)
        next_order = max((int(value.get("order_index", -1)) for value in self._states.values()), default=-1) + 1
        for account in source:
            key = stable_refresh_account_key(account)
            if key not in self._states:
                self._states[key] = {
                    "included": True,
                    "order_index": next_order,
                }
                next_order += 1
            self._seen.add(key)
        ordered_keys = sorted(
            present_keys,
            key=lambda key: (int(self._states[key].get("order_index", 0)), source.index(by_key[key])),
        )
        for index, key in enumerate(ordered_keys):
            self._states[key]["order_index"] = index
        self._save()
        return [
            LoginAccountRow(
                key=key,
                account=by_key[key],
                included=bool(self._states[key].get("included", True)),
                order_index=index,
            )
            for index, key in enumerate(ordered_keys)
        ]

    def set_included(self, key: str, included: bool) -> None:
        self.set_included_many([key], included)

    def set_included_many(self, keys: Iterable[str], included: bool) -> int:
        self._load()
        unique_keys = list(dict.fromkeys(str(key) for key in keys if str(key)))
        missing = [key for key in unique_keys if key not in self._states]
        if missing:
            raise KeyError(missing[0])
        for key in unique_keys:
            self._states[key]["included"] = bool(included)
        self._save()
        return len(unique_keys)

    def move(self, key: str, direction: int) -> None:
        self._load()
        ordered = sorted(self._states, key=lambda item: int(self._states[item].get("order_index", 0)))
        if key not in ordered:
            raise KeyError(key)
        current = ordered.index(key)
        target = max(0, min(len(ordered) - 1, current + (-1 if direction < 0 else 1)))
        if target != current:
            ordered[current], ordered[target] = ordered[target], ordered[current]
        for index, item in enumerate(ordered):
            self._states[item]["order_index"] = index
        self._save()


def build_launcher_accounts(
    rows: Iterable[LoginAccountRow],
    direct_links: Mapping[str, Mapping[str, object]],
    group_settings: Mapping[str, object] | None = None,
) -> list[AccountConfig]:
    settings = group_settings or {}
    result: list[AccountConfig] = []
    group_counts: dict[str, int] = {}
    for row in sorted(rows, key=lambda item: item.order_index):
        if not row.included:
            continue
        account = row.account
        group = row.group
        group_counts[group] = group_counts.get(group, 0) + 1
        raw_setting = settings.get(group, {"include_in_all": group == DEFAULT_GROUP_NAME})
        if isinstance(raw_setting, dict):
            include_in_all = bool(raw_setting.get("include_in_all", True))
        else:
            include_in_all = bool(raw_setting)
        record = direct_links.get(account.name, {})
        direct_url = str(record.get("direct_url") or "/") if isinstance(record, Mapping) else "/"
        result.append(
            AccountConfig(
                level=group,
                bookmark_no=group_counts[group],
                game_window_no=len(result) + 1,
                url=direct_url,
                bookmark_title=account.name,
                order_index=len(result),
                include_in_all=include_in_all,
                account_key=row.key,
                bookmark_path=_normalized_bookmark_path(account.bookmark_path),
            )
        )
    return result
