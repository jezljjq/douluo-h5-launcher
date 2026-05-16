from __future__ import annotations

import csv
import json
import os
import sys
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable


def app_root() -> Path:
    """返回应用根目录（源码模式=项目根, exe模式=exe所在目录）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def project_root() -> Path:
    """返回项目根目录（始终为源码项目根，与是否打包无关）。"""
    if getattr(sys, "frozen", False):
        # exe在 dist/斗罗大陆H5上号器/ 下，上溯3级到项目根
        return Path(sys.executable).parent.parent.parent
    return Path(__file__).resolve().parent.parent


LEVEL_OFFSETS = {
    "第一层": 0,
    "第二层": 8,
    "第三层": 16,
    "第四层": 24,
}

LEVELS = tuple(LEVEL_OFFSETS.keys())
SINGLE_LEVEL_NAME = "单层账号"
SELECTABLE_LEVELS = (SINGLE_LEVEL_NAME, *LEVELS)
DEFAULT_LEVEL_COUNTS = {
    "第一层": 8,
    "第二层": 8,
    "第三层": 8,
    "第四层": 8,
}
STATUSES = ("未开始", "OCR中", "打开中", "关闭公告", "已提取通行证", "已关闭公告", "输入中", "已输入通行证", "成功", "失败")


@dataclass(frozen=True)
class AccountConfig:
    level: str
    bookmark_no: int
    game_window_no: int
    url: str

    @property
    def key(self) -> str:
        return f"{self.level}-{self.bookmark_no}"

    @property
    def display_name(self) -> str:
        return f"{self.level}-{self.bookmark_no} → 窗口{self.game_window_no}"


@dataclass
class CSVAccount:
    """方式二：账号密码 + 通行证上号 的账号数据。

    password 仅存在内存中，禁止打印日志、写入文件、传入子进程。
    """
    name: str
    url: str
    username: str
    password: str
    game_window_no: int
    passport: str = ""
    status: str = "未开始"

    @property
    def key(self) -> str:
        return self.name

    @property
    def display_name(self) -> str:
        return f"{self.name} → 窗口{self.game_window_no}"

    def __repr__(self) -> str:
        return (f"CSVAccount(name={self.name!r}, url={self.url!r}, "
                f"username={self.username!r}, password='***', "
                f"game_window_no={self.game_window_no})")


@dataclass(frozen=True)
class AutomationSettings:
    bookmark_file: str = ""
    bookmark_root_name: str = "账号"
    log_level: str = "normal"
    level_names: tuple[str, str, str, str] = ("第一层", "第二层", "第三层", "第四层")
    browser: str = "chromium"
    window_width: int = 960
    window_height: int = 720
    columns: int = 4
    max_workers: int = 4
    gap_x: int = 20
    gap_y: int = 40
    page_load_timeout_ms: int = 60000
    after_goto_wait_ms: int = 5000
    qr_login_page_wait_ms: int = 1200
    passport_extract_timeout_ms: int = 30000
    after_passport_extract_wait_ms: int = 1500
    after_notice_wait_ms: int = 800
    after_passport_button_wait_ms: int = 1200
    after_submit_wait_ms: int = 2000
    state_check_timeout_ms: int = 8000
    passport_regex: str = r"本次通行证\s*[:：]\s*([A-Za-z0-9_-]+)"
    enable_ocr_fallback: bool = True
    passport_ocr_region_ratio: tuple[float, float, float, float] = (0.0, 0.75, 1.0, 1.0)
    qr_passport_ocr_region_ratio: tuple[float, float, float, float] = (0.0, 0.65, 1.0, 1.0)
    qr_passport_ocr_scale: int = 3
    qr_passport_ocr_threshold: int = 150
    qr_passport_debug_dir: str = "debug_ocr"
    login_window_title_keyword: str = ""
    passport_region_x_margin: int = 20
    passport_region_y_offset: int = 5
    passport_region_height: int = 45
    notice_selector: str = ""
    notice_visible_text: str = "公告"
    notice_template_path: str = ""
    notice_gone_template_path: str = ""
    passport_button_selector: str = ""
    passport_dialog_selector: str = ""
    passport_dialog_visible_text: str = "通行证登录"
    passport_dialog_template_path: str = ""
    passport_input_template_path: str = ""
    confirm_success_gone_template_path: str = ""
    passport_input_selector: str = ""
    confirm_button_selector: str = ""
    login_success_hidden_selector: str = ""
    login_success_hidden_text: str = "通行证登录"
    notice_close_outside_ratio: tuple[float, float] = (0.08, 0.08)
    notice_close_retries: int = 3
    dm_enabled: bool = True
    dm_prog_id: str = "dm.dmsoft"
    dm_bind_display: str = "normal"
    dm_bind_mouse: str = "windows"
    dm_bind_keypad: str = "windows"
    dm_bind_mode: int = 0
    dm_findpic_delta_color: str = "000000"
    dm_findpic_sim: float = 0.85
    dm_window_title_keyword: str = ""
    passport_button_ratio: tuple[float, float] = (0.90, 0.50)
    passport_input_ratio: tuple[float, float] = (0.50, 0.55)
    confirm_button_ratio: tuple[float, float] = (0.50, 0.70)
    passport_btn_template: str = "debug_ocr/template_passport_btn.png"
    passport_btn_viewport: tuple[int, int] = (683, 290)
    passport_btn_region: tuple[int, int, int, int] = (670, 272, 697, 308)
    passport_dialog_text: str = "通行证登录"
    # 登录页面状态检测（图像特征，不用Tesseract）
    login_state_roi: tuple[int, int, int, int] = (60, 150, 260, 350)
    qr_black_ratio_min: float = 0.35
    qr_edge_density_min: float = 0.08
    qr_variance_min: float = 2500.0
    logged_in_black_ratio_max: float = 0.28
    logged_in_edge_density_max: float = 0.60


def compute_game_window_no(
    level: str,
    bookmark_no: int,
    level_counts: dict[str, int] | None = None,
    level_order: Iterable[str] = LEVELS,
) -> int:
    if level == SINGLE_LEVEL_NAME:
        if bookmark_no < 1:
            raise ValueError(f"收藏编号必须大于等于 1: {bookmark_no}")
        return bookmark_no
    if level not in LEVELS:
        raise ValueError(f"未知层级: {level}")
    counts = _normalize_level_counts(level_counts, level_order)
    max_no = counts[level]
    if bookmark_no < 1 or bookmark_no > max_no:
        raise ValueError(f"{level} 收藏编号必须是 1-{max_no}: {bookmark_no}")

    offset = 0
    for ordered_level in level_order:
        if ordered_level == level:
            break
        offset += counts.get(ordered_level, 0)
    return offset + bookmark_no


def load_accounts(path: str | Path) -> list[AccountConfig]:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"配置文件不存在: {config_path}")

    if config_path.suffix.lower() == ".json":
        rows = _read_json_rows(config_path)
    else:
        rows = _read_csv_rows(config_path)

    accounts = [_row_to_account(row) for row in rows]
    accounts.sort(key=lambda account: account.game_window_no)
    return accounts


def load_accounts_from_bookmarks(
    bookmark_file: str | Path,
    root_name: str,
    level_names: Iterable[str] = LEVELS,
    level_counts: dict[str, int] | None = None,
    log=None,
) -> list[AccountConfig]:
    path = Path(bookmark_file)
    if not path.exists():
        raise FileNotFoundError(f"收藏夹文件不存在: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    root_folder = _find_bookmark_folder(data, root_name)
    if root_folder is None:
        raise ValueError(f"收藏夹里找不到根目录: {root_name}")

    level_order = tuple(level_names)
    counts = _normalize_level_counts(level_counts, level_order)
    accounts: list[AccountConfig] = []
    accounts.extend(_load_single_level_accounts(root_folder, log=log))

    for level in level_order:
        level_folder = _find_direct_child_folder(root_folder, level)
        if level_folder is None:
            if log:
                log(f"收藏夹层级不存在，已跳过：{level}")
            continue
        children_by_no: dict[int, dict[str, object]] = {}
        for child in level_folder.get("children", []):
            if not isinstance(child, dict) or child.get("type") != "url":
                continue
            bookmark_no = _parse_bookmark_no(str(child.get("name", "")).strip(), counts[level])
            if bookmark_no is None:
                if log:
                    log(f"{level} 非数字或超范围收藏项已跳过：{child.get('name', '')}")
                continue
            children_by_no[bookmark_no] = child

        for bookmark_no in range(1, counts[level] + 1):
            child = children_by_no.get(bookmark_no)
            if child is None:
                if log:
                    log(f"{level} 收藏编号 {bookmark_no} 不存在，已跳过。")
                continue
            accounts.append(
                AccountConfig(
                    level=level,
                    bookmark_no=bookmark_no,
                    game_window_no=compute_game_window_no(level, bookmark_no, counts, level_order),
                    url=str(child.get("url", "")).strip(),
                )
            )

    accounts.sort(key=lambda account: account.game_window_no)
    return accounts


def find_default_bookmark_file() -> str:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Default" / "Bookmarks",
        Path(local_app_data) / "Microsoft" / "Edge" / "User Data" / "Default" / "Bookmarks",
        Path(local_app_data) / "Google" / "Chrome" / "User Data" / "Profile 1" / "Bookmarks",
        Path(local_app_data) / "Microsoft" / "Edge" / "User Data" / "Profile 1" / "Bookmarks",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


def load_settings(path: str | Path) -> AutomationSettings:
    settings_path = Path(path)
    if not settings_path.exists():
        return AutomationSettings()

    with settings_path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)

    ratio_fields = {
        "passport_ocr_region_ratio",
        "qr_passport_ocr_region_ratio",
        "notice_close_outside_ratio",
        "notice_close_ratio",
        "passport_button_ratio",
        "passport_input_ratio",
        "confirm_button_ratio",
    }
    normalized = {}
    allowed_fields = {field.name for field in fields(AutomationSettings)}
    for key, value in data.items():
        if key == "notice_close_ratio" and "notice_close_outside_ratio" not in data:
            key = "notice_close_outside_ratio"
        elif key == "notice_close_ratio":
            continue
        if key not in allowed_fields and key not in ratio_fields:
            continue
        if key in ratio_fields:
            normalized[key] = _normalize_region_ratio(value, key) if key.endswith("_region_ratio") else _normalize_ratio(value, key)
        elif key == "level_names":
            normalized[key] = tuple(str(item) for item in value)
        elif key in ("login_state_roi", "passport_btn_region", "passport_btn_viewport", "notice_close_viewport"):
            normalized[key] = tuple(int(item) for item in value)
        else:
            normalized[key] = value
    return AutomationSettings(**normalized)


def filter_accounts(accounts: Iterable[AccountConfig], level: str) -> list[AccountConfig]:
    if level == "全部":
        return list(accounts)
    return [account for account in accounts if account.level == level]


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def _read_json_rows(path: Path) -> list[dict[str, object]]:
    with path.open("r", encoding="utf-8-sig") as file:
        data = json.load(file)
    if isinstance(data, dict):
        data = data.get("accounts", [])
    if not isinstance(data, list):
        raise ValueError("JSON 配置必须是数组，或包含 accounts 数组")
    return data


def _row_to_account(row: dict[str, object]) -> AccountConfig:
    level = str(_pick(row, "层级", "level")).strip()
    bookmark_no = int(_pick(row, "收藏编号", "bookmark_no", "bookmark", "no"))
    url = str(_pick(row, "链接", "url")).strip()
    passport = str(_pick(row, "通行证", "passport")).strip()
    configured_window = _pick_optional(row, "游戏窗口号", "game_window_no", "window_no")
    expected_window = compute_game_window_no(level, bookmark_no)

    if configured_window not in (None, "") and int(configured_window) != expected_window:
        raise ValueError(
            f"{level} 收藏{bookmark_no} 的游戏窗口号应为 {expected_window}，配置中是 {configured_window}"
        )
    if not url:
        raise ValueError(f"{level} 收藏{bookmark_no} 缺少链接")
    if not passport:
        raise ValueError(f"{level} 收藏{bookmark_no} 缺少通行证")

    return AccountConfig(
        level=level,
        bookmark_no=bookmark_no,
        game_window_no=expected_window,
        url=url,
    )


def _pick(row: dict[str, object], *keys: str) -> object:
    value = _pick_optional(row, *keys)
    if value in (None, ""):
        raise ValueError(f"配置缺少字段: {'/'.join(keys)}")
    return value


def _pick_optional(row: dict[str, object], *keys: str) -> object | None:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _normalize_ratio(value: object, field_name: str) -> tuple[float, float]:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{field_name} 必须是两个 0-1 小数，例如 [0.5, 0.7]")
    x, y = float(value[0]), float(value[1])
    if not (0 <= x <= 1 and 0 <= y <= 1):
        raise ValueError(f"{field_name} 必须在 0-1 范围内")
    return (x, y)


def _normalize_region_ratio(value: object, field_name: str) -> tuple[float, float, float, float]:
    if not isinstance(value, list | tuple) or len(value) != 4:
        raise ValueError(f"{field_name} 必须是四个 0-1 小数，例如 [0, 0.75, 1, 1]")
    left, top, right, bottom = (float(item) for item in value)
    if not (0 <= left < right <= 1 and 0 <= top < bottom <= 1):
        raise ValueError(f"{field_name} 必须满足 0 <= left < right <= 1 且 0 <= top < bottom <= 1")
    return (left, top, right, bottom)


def _find_bookmark_folder(data: dict[str, object], folder_name: str) -> dict[str, object] | None:
    roots = data.get("roots", {})
    if not isinstance(roots, dict):
        return None
    for root in roots.values():
        found = _find_folder_recursive(root, folder_name)
        if found is not None:
            return found
    return None


def _find_folder_recursive(node: object, folder_name: str) -> dict[str, object] | None:
    if not isinstance(node, dict):
        return None
    if node.get("type") == "folder" and node.get("name") == folder_name:
        return node
    for child in node.get("children", []):
        found = _find_folder_recursive(child, folder_name)
        if found is not None:
            return found
    return None


def _find_direct_child_folder(parent: dict[str, object], folder_name: str) -> dict[str, object] | None:
    for child in parent.get("children", []):
        if isinstance(child, dict) and child.get("type") == "folder" and child.get("name") == folder_name:
            return child
    return None


def _load_single_level_accounts(root_folder: dict[str, object], log=None) -> list[AccountConfig]:
    accounts: list[AccountConfig] = []
    for child in root_folder.get("children", []):
        if not isinstance(child, dict):
            continue
        if child.get("type") == "folder":
            continue
        if child.get("type") != "url":
            continue
        name = str(child.get("name", "")).strip()
        bookmark_no = _parse_bookmark_no(name)
        if bookmark_no is None:
            if log:
                log(f"单层账号非数字收藏项已跳过：{name}")
            continue
        accounts.append(
            AccountConfig(
                level=SINGLE_LEVEL_NAME,
                bookmark_no=bookmark_no,
                game_window_no=bookmark_no,
                url=str(child.get("url", "")).strip(),
            )
        )
    return sorted(accounts, key=lambda account: account.bookmark_no)


def _normalize_level_counts(
    level_counts: dict[str, int] | None = None,
    level_order: Iterable[str] = LEVELS,
) -> dict[str, int]:
    normalized = DEFAULT_LEVEL_COUNTS.copy()
    if level_counts:
        for level in level_order:
            value = int(level_counts.get(level, normalized.get(level, 8)))
            if value < 0:
                raise ValueError(f"{level} 每层数量不能小于 0")
            normalized[level] = value
    return normalized


def _parse_bookmark_no(name: str, max_no: int | None = None) -> int | None:
    normalized = name.replace("号", "").strip()
    if not normalized.isdigit():
        return None
    number = int(normalized)
    if number < 1:
        return None
    if max_no is None or number <= max_no:
        return number
    return None


def load_csv_accounts(path: str | Path) -> tuple[list[CSVAccount], str | None]:
    """从 CSV 文件加载方式二账号列表。

    CSV 表头必须为: name,url,username,password
    行号 = game_window_no（第1行→窗口1）。

    返回 (accounts, error_message)。成功时 error_message 为 None。
    """
    path = Path(path)
    if not path.exists():
        return [], f"文件不存在: {path}"

    # 尝试常见编码（Windows 中文环境常用 GBK）
    for encoding in ("utf-8-sig", "gbk", "gb2312", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as f:
                reader = csv.DictReader(f)
                fieldnames = reader.fieldnames
                if fieldnames is None:
                    return [], "CSV文件为空"
                expected = ["name", "url", "username", "password"]
                actual = [h.strip().lower() for h in fieldnames]
                if actual != expected:
                    return [], (
                        "CSV格式错误，第一行必须是 name,url,username,password\n"
                        f"当前表头: {', '.join(fieldnames)}"
                    )
                accounts: list[CSVAccount] = []
                for idx, row in enumerate(reader, start=1):
                    name = (row.get("name") or "").strip()
                    url = (row.get("url") or "").strip()
                    username = (row.get("username") or "").strip()
                    password = (row.get("password") or "").strip()
                    if not name:
                        continue
                    missing = []
                    if not username:
                        missing.append("username")
                    if not password:
                        missing.append("password")
                    if missing:
                        accounts.append(CSVAccount(
                            name=name, url=url, username=username, password=password,
                            game_window_no=idx, status=f"配置缺失: {', '.join(missing)}"
                        ))
                    else:
                        accounts.append(CSVAccount(
                            name=name, url=url, username=username, password=password,
                            game_window_no=idx
                        ))
                return accounts, None
        except (UnicodeDecodeError, UnicodeError):
            continue
        except Exception as exc:
            return [], f"读取CSV失败: {exc}"
    return [], "CSV编码无法识别，请保存为 UTF-8 或 GBK 编码"
    return None
