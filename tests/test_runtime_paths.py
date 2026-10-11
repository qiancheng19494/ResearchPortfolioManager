"""Source and Windows packaged runtime paths must not collide."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import runtime_paths


class RuntimePathsTest(unittest.TestCase):
    def test_source_default_is_project_local(self):
        with patch.object(sys, 'frozen', False, create=True):
            self.assertEqual(runtime_paths.default_data_dir(), Path(runtime_paths.__file__).parent / 'user_data')

    def test_frozen_default_is_per_user(self):
        with patch.object(sys, 'frozen', True, create=True), patch.dict(os.environ, {'LOCALAPPDATA': r'C:\Users\Test User\AppData\Local'}):
            self.assertEqual(runtime_paths.default_data_dir(), Path(r'C:\Users\Test User\AppData\Local') / 'ResearchPortfolioManager' / 'user_data')

    def test_frozen_restore_does_not_include_main_py(self):
        with patch.object(sys, 'frozen', True, create=True), patch.object(sys, 'executable', r'C:\Program Files\ResearchPortfolioManager\ResearchPortfolioManager.exe'):
            result = runtime_paths.restore_launch_command("D:\\资料\\O'Brien")
            self.assertIn('ResearchPortfolioManager.exe', result)
            self.assertNotIn('main.py', result)
            self.assertIn("O''Brien", result)

    def test_source_restore_includes_main_py(self):
        with patch.object(sys, 'frozen', False, create=True):
            result = runtime_paths.restore_launch_command('my data')
            self.assertIn('main.py', result)
            self.assertIn("'my data'", result)


if __name__ == '__main__':
    unittest.main()
