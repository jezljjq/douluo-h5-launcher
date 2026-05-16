from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .config import app_root


SETTINGS_FILE_NAME = "window_manager_settings.json"
TILE_MODE_FIXED = "fixed"
TILE_MODE_ROW_COUNT = "row_count"


@dataclass(frozen=True)
class FixedModeSettings:
    launch_count: int = 31
    window_width: str = "320"
    window_height: str = "540"
    start_x: int = 250
    start_y: int = 0
    offset_x: int = 320
    offset_y: int = 525
    per_row: int = 8


@dataclass(frozen=True)
class RowCountModeSettings:
    launch_count: int = 9
    per_row: int = 5


@dataclass(frozen=True)
class WindowManagerSettings:
    game_path: str = ""
    launch_count: int = 31
    launch_interval: int = 300
    auto_tile_after_launch: bool = True
    auto_rename_after_tile: bool = True
    title_template: str = "斗罗大陆H5-{index}号"
    last_tile_mode: str = TILE_MODE_FIXED
    prevent_overflow: bool = True
    fixed_mode: FixedModeSettings = FixedModeSettings()
    row_count_mode: RowCountModeSettings = RowCountModeSettings()


def window_manager_settings_path() -> Path:
    return app_root() / SETTINGS_FILE_NAME


def load_window_manager_settings(
    path: Path | None = None,
) -> tuple[WindowManagerSettings, str | None]:
    settings_path = path or window_manager_settings_path()
    if not settings_path.exists():
        return WindowManagerSettings(), None

    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("配置文件内容不是 JSON 对象")
        return _settings_from_dict(data), None
    except Exception as exc:
        return WindowManagerSettings(), f"{settings_path}: {exc}"


def save_window_manager_settings(
    settings: WindowManagerSettings,
    path: Path | None = None,
) -> Path:
    settings_path = path or window_manager_settings_path()
    settings_path.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return settings_path


def _settings_from_dict(data: dict[str, Any]) -> WindowManagerSettings:
    fixed_data = data.get("fixed_mode")
    if not isinstance(fixed_data, dict):
        fixed_data = data

    row_data = data.get("row_count_mode")
    if not isinstance(row_data, dict):
        row_data = {}

    last_tile_mode = str(
        data.get("last_tile_mode")
        or _legacy_tile_mode_to_key(data.get("tile_mode"))
        or TILE_MODE_FIXED
    )
    if last_tile_mode not in {TILE_MODE_FIXED, TILE_MODE_ROW_COUNT}:
        last_tile_mode = TILE_MODE_FIXED

    return WindowManagerSettings(
        game_path=str(data.get("game_path", "")),
        launch_count=_to_int(data.get("launch_count"), 31),
        launch_interval=_to_int(data.get("launch_interval"), 300),
        auto_tile_after_launch=_to_bool(data.get("auto_tile_after_launch", True)),
        auto_rename_after_tile=_to_bool(data.get("auto_rename_after_tile", True)),
        title_template=str(data.get("title_template", "斗罗大陆H5-{index}号")),
        last_tile_mode=last_tile_mode,
        prevent_overflow=_to_bool(data.get("prevent_overflow", True)),
        fixed_mode=FixedModeSettings(
            launch_count=_to_int(fixed_data.get("launch_count", data.get("launch_count")), 31),
            window_width=str(fixed_data.get("window_width", "320")),
            window_height=str(fixed_data.get("window_height", "540")),
            start_x=_to_int(fixed_data.get("start_x"), 250),
            start_y=_to_int(fixed_data.get("start_y"), 0),
            offset_x=_to_int(fixed_data.get("offset_x"), 320),
            offset_y=_to_int(fixed_data.get("offset_y"), 525),
            per_row=_to_int(fixed_data.get("per_row"), 8),
        ),
        row_count_mode=RowCountModeSettings(
            launch_count=_to_int(row_data.get("launch_count", data.get("launch_count")), 9),
            per_row=_to_int(row_data.get("per_row"), 5),
        ),
    )


def _legacy_tile_mode_to_key(value: Any) -> str | None:
    text = str(value or "").strip()
    if text == "固定参数排列":
        return TILE_MODE_FIXED
    if text == "根据行数排列":
        return TILE_MODE_ROW_COUNT
    return None


def _to_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)
