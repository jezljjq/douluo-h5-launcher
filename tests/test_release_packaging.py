import json
import unittest
from pathlib import Path

from douluo_launcher.version import APP_VERSION


ROOT = Path(__file__).resolve().parent.parent


class ReleasePackagingTests(unittest.TestCase):
    def test_version_is_v1420(self) -> None:
        self.assertEqual(APP_VERSION, "1.4.20")

    def test_main_window_title_uses_app_version(self) -> None:
        text = (ROOT / "douluo_launcher" / "gui.py").read_text(encoding="utf-8")

        self.assertIn(
            'self.title(f"斗罗大陆H5上号器 - 客户端直登批次版 v{APP_VERSION}")',
            text,
        )

    def test_template_disables_global_context_menu_blocking(self) -> None:
        data = json.loads((ROOT / "automation_settings.template.json").read_text(encoding="utf-8"))

        self.assertFalse(data["block_browser_context_menu"])
        self.assertIn("speed_panel_hotkey", data)
        self.assertEqual(data["speed_panel_hotkey"], "")
        self.assertEqual(data["speed_rate_hotkeys"], [])

    def test_launcher_spec_uses_template_not_private_settings(self) -> None:
        text = (ROOT / "Launcher.spec").read_text(encoding="utf-8")

        self.assertIn("automation_settings.template.json", text)
        self.assertNotIn("('automation_settings.json', '.')", text)

    def test_build_scripts_do_not_bundle_private_settings(self) -> None:
        for path in [ROOT / "scripts" / "build_exe.ps1", ROOT / "scripts" / "build_exe_32bit.ps1"]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("automation_settings.template.json", text)
            self.assertNotIn("--add-data\", \"automation_settings.json;.", text)
            self.assertNotIn("copied: automation_settings.json", text)

    def test_release_directory_is_derived_from_app_version_without_legacy_literal(self) -> None:
        for path in [ROOT / "scripts" / "build_exe.ps1", ROOT / "scripts" / "build_exe_32bit.ps1"]:
            text = path.read_text(encoding="utf-8")
            self.assertIn("douluo_launcher.version import APP_VERSION", text)
            self.assertIn('"\u6597\u7f57\u5927\u9646H5\u4e0a\u53f7\u5668-v$AppVersion"', text)
            self.assertNotIn("v1.3.0", text)
            self.assertIn('"--hidden-import", "requests"', text)
        main_script = (ROOT / "scripts" / "build_exe.ps1").read_text(encoding="utf-8")
        self.assertIn('"--specpath", $MainSpecDir', main_script)
        spec = (ROOT / "Launcher.spec").read_text(encoding="utf-8")
        self.assertIn("from douluo_launcher.version import APP_VERSION", spec)
        self.assertIn("name=f'\u6597\u7f57\u5927\u9646H5\u4e0a\u53f7\u5668-v{APP_VERSION}'", spec)
        self.assertNotIn("v1.3.0", spec)

    def test_build_bat_remains_ascii_only_powershell_launcher(self) -> None:
        data = (ROOT / "scripts" / "build_exe.bat").read_bytes()
        data.decode("ascii")
        text = data.decode("ascii")
        self.assertIn('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_exe.ps1"', text)
        self.assertNotIn("\npyinstaller ", text.lower())
        self.assertNotIn(" -m pyinstaller", text.lower())


if __name__ == "__main__":
    unittest.main()
