"""Configuration writes preserve existing files and commit only complete settings."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from database.store import Store


class ConfigWriteSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rpm-v13-config-')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'data')

    def tearDown(self):
        self.temp.cleanup()

    def test_existing_fixed_temp_name_is_not_reused_or_deleted(self):
        sentinel = self.store.config_path.with_suffix('.tmp')
        sentinel.write_bytes(b'existing unrelated file')
        self.store.save_config({'name': '更新姓名'})
        self.assertEqual(sentinel.read_bytes(), b'existing unrelated file')
        self.assertEqual(Store(self.store.root).config['name'], '更新姓名')
        self.assertEqual(list(self.store.config_path.parent.glob('.settings-*.tmp')), [])

    def test_existing_hardlinked_temp_name_does_not_change_linked_file(self):
        original = self.base / 'preserved.txt'
        original.write_bytes(b'preserve these bytes')
        alias = self.store.config_path.with_suffix('.tmp')
        os.link(original, alias)
        self.store.save_config({'name': '独立临时文件'})
        self.assertEqual(original.read_bytes(), b'preserve these bytes')
        self.assertEqual(alias.read_bytes(), b'preserve these bytes')

    def test_failed_replace_preserves_disk_and_memory_and_cleans_own_temp(self):
        before = self.store.config_path.read_bytes()
        memory = dict(self.store.config)
        with patch.object(Path, 'replace', side_effect=OSError('simulated save failure')):
            with self.assertRaises(OSError):
                self.store.save_config({'name': '不会提交'})
        self.assertEqual(self.store.config_path.read_bytes(), before)
        self.assertEqual(self.store.config, memory)
        self.assertEqual(list(self.store.config_path.parent.glob('.settings-*.tmp')), [])

    def test_serialization_failure_preserves_previous_settings(self):
        before = self.store.config_path.read_bytes()
        with self.assertRaises(TypeError):
            self.store.save_config({'extra': object()})
        self.assertEqual(self.store.config_path.read_bytes(), before)
        self.assertNotIn('extra', self.store.config)
        self.assertEqual(list(self.store.config_path.parent.glob('.settings-*.tmp')), [])
