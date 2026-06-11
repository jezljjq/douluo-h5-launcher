import tempfile
import unittest
from pathlib import Path

from douluo_launcher.path_utils import first_dropped_file_path, parse_dropped_file_paths, resolve_game_executable_path


class PathUtilsTests(unittest.TestCase):
    def test_exe_path_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / "X5Game.exe"
            exe.write_text("", encoding="utf-8")

            result = resolve_game_executable_path(exe)

        self.assertEqual(result.path, str(exe))
        self.assertEqual(result.source, "exe")

    def test_lnk_resolves_to_target_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shortcut = Path(tmp) / "斗罗大陆.lnk"
            shortcut.write_text("", encoding="utf-8")
            target = Path(tmp) / "X5Game.exe"
            target.write_text("", encoding="utf-8")

            result = resolve_game_executable_path(
                shortcut,
                shortcut_resolver=lambda path: str(target),
            )

        self.assertEqual(result.path, str(target))
        self.assertEqual(result.source, "shortcut")
        self.assertIn("已解析快捷方式", result.message)

    def test_lnk_target_missing_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shortcut = Path(tmp) / "斗罗大陆.lnk"
            shortcut.write_text("", encoding="utf-8")
            missing = Path(tmp) / "missing.exe"

            with self.assertRaisesRegex(ValueError, "目标文件不存在"):
                resolve_game_executable_path(shortcut, shortcut_resolver=lambda path: str(missing))

    def test_lnk_target_not_exe_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            shortcut = Path(tmp) / "斗罗大陆.lnk"
            shortcut.write_text("", encoding="utf-8")
            target = Path(tmp) / "readme.txt"
            target.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "目标不是游戏程序"):
                resolve_game_executable_path(shortcut, shortcut_resolver=lambda path: str(target))

    def test_folder_finds_x5game_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            exe = folder / "X5Game.exe"
            exe.write_text("", encoding="utf-8")

            result = resolve_game_executable_path(folder)

        self.assertEqual(result.path, str(exe))
        self.assertEqual(result.source, "folder")

    def test_folder_without_x5game_exe_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "未在该目录找到 X5Game.exe，请手动选择游戏程序"):
                resolve_game_executable_path(Path(tmp))

    def test_invalid_file_uses_customer_friendly_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            text_file = Path(tmp) / "readme.txt"
            text_file.write_text("", encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "请选择游戏程序 exe、游戏快捷方式或游戏安装目录"):
                resolve_game_executable_path(text_file)

    def test_drop_path_with_braces_is_parsed(self) -> None:
        self.assertEqual(
            parse_dropped_file_paths(r"{C:\Users\Desktop\斗罗大陆.lnk}"),
            [r"C:\Users\Desktop\斗罗大陆.lnk"],
        )

    def test_drop_path_with_spaces_is_parsed(self) -> None:
        self.assertEqual(
            parse_dropped_file_paths(r"{E:\Program Files\DLH5\X5Game.exe}"),
            [r"E:\Program Files\DLH5\X5Game.exe"],
        )

    def test_drop_path_with_chinese_is_parsed(self) -> None:
        self.assertEqual(
            parse_dropped_file_paths(r"{D:\游戏目录\斗罗大陆\X5Game.exe}"),
            [r"D:\游戏目录\斗罗大陆\X5Game.exe"],
        )

    def test_multiple_dropped_files_use_first(self) -> None:
        self.assertEqual(
            first_dropped_file_path(r"{C:\A\first.lnk} {C:\B\second.exe}"),
            r"C:\A\first.lnk",
        )


if __name__ == "__main__":
    unittest.main()
