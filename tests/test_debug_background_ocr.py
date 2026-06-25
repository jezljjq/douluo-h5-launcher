import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from douluo_launcher.automation import PassportOcrResult
from douluo_launcher.config import AutomationSettings
from tools import debug_background_ocr


class DebugBackgroundOcrToolTests(unittest.TestCase):
    def test_tool_calls_shared_login_image_extractor(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "latest_ocr_input.png"
            image_path.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (768, 1056), "white").save(image_path)

            with mock.patch("tools.debug_background_ocr.load_settings", return_value=AutomationSettings()), mock.patch(
                "tools.debug_background_ocr.AccountRunner.detect_login_page_state",
                return_value=("qr_page", {"fallback_qr_box": (1, 2, 3, 4), "passport_bar_box": (5, 6, 7, 8)}),
            ), mock.patch(
                "tools.debug_background_ocr.extract_passport_from_login_image",
                return_value=PassportOcrResult(passport="d40786fa", raw_output="raw", text_region_box=(10, 528, 758, 1046)),
            ) as shared_extract:
                exit_code = debug_background_ocr.main(
                    [str(image_path), "--debug-dir", str(root), "--settings", str(root / "automation_settings.json")]
                )

        self.assertEqual(exit_code, 0)
        shared_extract.assert_called_once()
        self.assertEqual(shared_extract.call_args.kwargs["mode"], "offline")
        self.assertTrue(shared_extract.call_args.kwargs["save_debug_artifacts"])


if __name__ == "__main__":
    unittest.main()
