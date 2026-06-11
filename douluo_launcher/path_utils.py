from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable
import sys


@dataclass(frozen=True)
class ResolvedGamePath:
    path: str
    source: str
    message: str = ""


def resolve_shortcut_target(shortcut_path: str | Path) -> str:
    """Resolve a Windows .lnk shortcut target path."""
    if sys.platform != "win32":
        raise RuntimeError("快捷方式解析仅支持 Windows")
    try:
        import win32com.client  # type: ignore

        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(str(shortcut_path))
        return str(shortcut.Targetpath or "").strip()
    except Exception as exc:
        raise ValueError(f"解析快捷方式失败：{exc}") from exc


def resolve_game_executable_path(
    raw_path: str | Path,
    shortcut_resolver: Callable[[str | Path], str] = resolve_shortcut_target,
) -> ResolvedGamePath:
    path = Path(str(raw_path).strip().strip('"')).expanduser()
    if not path.exists():
        raise ValueError(f"路径不存在：{path}")

    if path.is_dir():
        exe = path / "X5Game.exe"
        if exe.is_file():
            return ResolvedGamePath(path=str(exe), source="folder", message=f"已从目录找到游戏程序：{exe}")
        raise ValueError("未在该目录找到 X5Game.exe，请手动选择游戏程序。")

    suffix = path.suffix.lower()
    if suffix == ".exe":
        return ResolvedGamePath(path=str(path), source="exe", message=f"已选择游戏程序：{path}")

    if suffix == ".lnk":
        target_text = str(shortcut_resolver(path) or "").strip().strip('"')
        if not target_text:
            raise ValueError("无效快捷方式：Targetpath 为空。")
        target = Path(target_text).expanduser()
        if not target.exists():
            raise ValueError(f"快捷方式目标文件不存在：{target}")
        if target.suffix.lower() != ".exe":
            raise ValueError(f"快捷方式目标不是游戏程序 exe：{target}")
        if not target.is_file():
            raise ValueError(f"快捷方式目标不是有效文件：{target}")
        return ResolvedGamePath(
            path=str(target),
            source="shortcut",
            message=f"已解析快捷方式：{path.name} -> {target}",
        )

    raise ValueError("请选择游戏程序 exe、游戏快捷方式或游戏安装目录。")


def parse_dropped_file_paths(drop_text: str, splitlist: Callable[[str], tuple[str, ...] | list[str]] | None = None) -> list[str]:
    r"""Parse DND file data such as `{C:\A B\foo.lnk} {D:\中文\X5Game.exe}`."""
    text = str(drop_text or "").strip()
    if not text:
        return []
    if splitlist is not None:
        try:
            return [str(path) for path in splitlist(text) if str(path)]
        except Exception:
            pass

    paths: list[str] = []
    index = 0
    while index < len(text):
        while index < len(text) and text[index].isspace():
            index += 1
        if index >= len(text):
            break
        if text[index] == "{":
            end = text.find("}", index + 1)
            if end == -1:
                paths.append(text[index + 1 :])
                break
            paths.append(text[index + 1 : end])
            index = end + 1
            continue
        end = index
        while end < len(text) and not text[end].isspace():
            end += 1
        paths.append(text[index:end])
        index = end
    return [path for path in paths if path]


def first_dropped_file_path(drop_text: str, splitlist: Callable[[str], tuple[str, ...] | list[str]] | None = None) -> str:
    paths = parse_dropped_file_paths(drop_text, splitlist=splitlist)
    return paths[0] if paths else ""
