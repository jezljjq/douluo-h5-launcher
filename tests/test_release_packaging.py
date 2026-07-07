import unittest
from pathlib import Path

from douluo_launcher.version import APP_VERSION


ROOT = Path(__file__).resolve().parent.parent


class ReleasePackagingTests(unittest.TestCase):
    def test_version_is_v130(self) -> None:
        self.assertEqual(APP_VERSION, "1.3.0")

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


if __name__ == "__main__":
    unittest.main()
