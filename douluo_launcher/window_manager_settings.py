from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .config import app_root


SETTINGS_FILE_NAME = "window_manager_settings.json"


@dataclass(frozen=True)
class WindowManagerSettings:
    game_path: str = ""
    launch_count: int = 31
    launch_interval: int = 300
    auto_tile_after_launch: bool = True
    auto_rename_after_tile: bool = True
    title_template: str = "斗罗大陆H5-{index}号"
    window_width: int = 320
    window_height: int = 540
    start_x: int = 250
    start_y: int = 0
    offset_x: int = 320
    offset_y: int = 525
    per_row: int = 8


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
    defaults = WindowManagerSettings()
    values: dict[str, Any] = {}
    for field in fields(WindowManagerSettings):
        default_value = getattr(defaults, field.name)
        raw_value = data.get(field.name, getattr(defaults, field.name))
        if isinstance(default_value, bool):
            values[field.name] = _to_bool(raw_value)
        elif isinstance(default_value, int):
            values[field.name] = int(raw_value)
        elif isinstance(default_value, str):
            values[field.name] = str(raw_value)
        else:
            values[field.name] = raw_value
    return WindowManagerSettings(**values)


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "y"}
    return bool(value)
