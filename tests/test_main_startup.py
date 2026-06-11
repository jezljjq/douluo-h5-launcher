import unittest

import main


class MainStartupTests(unittest.TestCase):
    def test_gui_startup_does_not_auto_elevate_so_file_drop_works(self) -> None:
        self.assertFalse(main._should_auto_elevate_gui_on_startup())


if __name__ == "__main__":
    unittest.main()
