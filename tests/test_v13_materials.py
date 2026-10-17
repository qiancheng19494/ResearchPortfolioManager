"""V1.3 材料路径、元数据和只读体检（均为隔离临时资料）。"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from database.store import Store
from services.materials import MaterialService, safe_relative_path, sha256_file
from services.portfolio import PortfolioService


class MaterialSafetyV13Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='v13-material-safety-')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'data')
        self.materials = MaterialService(self.store)
        self.portfolio = PortfolioService(self.store)
        self.pid = self.portfolio.save_project({'name': '隔离材料体检'})
        self.source = self.base / '材料.txt'
        self.source.write_bytes(b'original material bytes')
        self.mid = self.materials.import_file(self.source, self.pid)
        self.managed = self.materials.file_path(self.mid, verify=True)
        self.record = self.materials.get_material(self.mid)

    def tearDown(self):
        self.temp.cleanup()

    def assert_unchanged(self):
        self.assertEqual(self.materials.get_material(self.mid), self.record)
        self.assertFalse((self.store.root / 'preview_cache').exists())

    def test_import_rejects_none_empty_and_nontext_required_metadata(self):
        for field in ('category', 'version_label'):
            for value in (None, '', '   ', 123, [], True):
                with self.subTest(field=field, value=value):
                    with self.assertRaisesRegex(ValueError, '类别和版本标签不能为空'):
                        self.materials.import_file(self.source, self.pid, **{field: value})
        self.assertEqual(len(self.materials.list_materials()), 1)
        self.assertEqual(len(list((self.store.root / 'materials').iterdir())), 1)

    def test_update_rejects_invalid_metadata_without_partial_write(self):
        for values in ({'category': None}, {'version_label': None}, {'notes': None},
                       {'category': ' '}, {'version_label': 12}, {'notes': []}):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self.materials.update_material(self.mid, **values)
                self.assertEqual(self.materials.get_material(self.mid), self.record)

    def test_import_rejects_nontext_notes_and_accepts_normal_metadata(self):
        for value in (None, 123, [], True):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, '备注必须为文本'):
                    self.materials.import_file(self.source, self.pid, notes=value)
        mid = self.materials.import_file(self.source, self.pid, category=' 文本 ',
                                         version_label=' V2 ', notes='')
        record = self.materials.get_material(mid)
        self.assertEqual((record['category'], record['version_label'], record['notes']),
                         ('文本', 'V2', ''))

    def test_windows_device_names_and_normalization_aliases_rejected(self):
        invalid = ('NUL.txt', 'con', 'CONIN$.txt', 'CONOUT$', 'LPT9.pdf', 'com1.doc',
                   'COM\u00b9.txt', 'LPT\u00b2.pdf', 'COM\u00b3', 'file.txt.', 'file.txt ',
                   'file?.txt', 'file*.txt', 'file|x.txt', 'file<x.txt', 'file>x.txt',
                   'file"x.txt', 'file\x1fx.txt', 'file.txt:stream', 'CON .txt')
        for name in invalid:
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, '规范的安全相对路径'):
                    safe_relative_path(self.store.root, f'materials/example/{name}',
                                       materials_only=True)

    def test_traversal_and_noncanonical_paths_still_rejected(self):
        for relative in ('../outside.txt', '/materials/a/x.txt', 'materials//a/x.txt',
                         'materials/a/../x.txt', 'materials\\a\\x.txt',
                         'materials/a/./x.txt', 'config/settings.json'):
            with self.subTest(relative=relative):
                with self.assertRaises(ValueError):
                    safe_relative_path(self.store.root, relative, materials_only=True)

    def test_ordinary_unicode_space_and_case_paths_remain_valid(self):
        for name in ('中文 材料.txt', 'CONTEXT.pdf', 'compare1.txt', 'COM10.txt', 'a.b.c'):
            relative = f'materials/example/{name}'
            self.assertEqual(safe_relative_path(self.store.root, relative, materials_only=True),
                             self.store.root / relative)

    @unittest.skipUnless(sys.platform == 'win32', '实际 Windows junction 检查')
    def test_actual_windows_junction_within_root_is_rejected(self):
        target = self.store.root / 'materials' / 'target'
        target.mkdir()
        (target / 'sample.txt').write_bytes(b'junction target remains intact')
        junction = self.store.root / 'materials' / 'junction'
        result = subprocess.run(['cmd.exe', '/c', 'mklink', '/J', str(junction), str(target)],
                                capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        try:
            self.assertFalse(junction.is_symlink())
            with self.assertRaisesRegex(ValueError, '重解析点'):
                safe_relative_path(self.store.root, 'materials/junction/sample.txt',
                                   materials_only=True)
            self.assertEqual((target / 'sample.txt').read_bytes(), b'junction target remains intact')
        finally:
            junction.rmdir()

    def test_actual_hardlinked_managed_file_rejected_before_preview(self):
        alias = self.base / 'external-alias.txt'
        os.link(self.managed, alias)
        self.assertGreater(self.managed.stat().st_nlink, 1)
        with self.assertRaisesRegex(ValueError, '硬链接'):
            self.materials.prepare_preview(self.mid)
        self.assertEqual(alias.read_bytes(), self.source.read_bytes())
        self.assert_unchanged()

    def test_integrity_report_passes_active_and_archived_without_mutation(self):
        second_pid = self.portfolio.save_project({'name': '已归档项目'})
        second = self.materials.import_file(self.source, second_pid, version_label='V2')
        self.portfolio.archive_project(second_pid)
        report = self.materials.audit_materials()
        self.assertEqual((report['total'], report['passed'], report['failed']), (2, 2, 0))
        self.assertTrue(report['checked_at'])
        items = {item['id']: item for item in report['items']}
        self.assertFalse(items[self.mid]['project_archived'])
        self.assertTrue(items[second]['project_archived'])
        self.assertEqual(items[self.mid]['actual_sha256'], self.record['sha256'])
        self.assertEqual(items[self.mid]['actual_size'], self.record['size'])
        self.assert_unchanged()

    def test_integrity_report_handles_missing_and_continues(self):
        other = self.materials.import_file(self.source, self.pid)
        self.managed.unlink()
        report = self.materials.audit_materials()
        self.assertEqual((report['total'], report['passed'], report['failed']), (2, 1, 1))
        items = {item['id']: item for item in report['items']}
        self.assertEqual(items[self.mid]['status'], 'missing')
        self.assertIsNone(items[self.mid]['actual_sha256'])
        self.assertIn('哈希不能重建', items[self.mid]['reason'])
        self.assertEqual(items[other]['status'], 'passed')
        self.assert_unchanged()

    def test_integrity_report_size_change_keeps_old_hash(self):
        self.managed.write_bytes(b'changed')
        report = self.materials.audit_materials()
        item = report['items'][0]
        self.assertEqual((report['passed'], report['failed'], item['status']), (0, 1, 'changed'))
        self.assertEqual(item['expected_sha256'], self.record['sha256'])
        self.assertEqual(item['actual_sha256'], sha256_file(self.managed))
        self.assertNotEqual(item['actual_size'], item['expected_size'])
        self.assert_unchanged()

    def test_integrity_report_same_size_content_change_is_not_passed(self):
        self.managed.write_bytes(b'x' * self.record['size'])
        report = self.materials.audit_materials()
        item = report['items'][0]
        self.assertEqual(item['actual_size'], item['expected_size'])
        self.assertNotEqual(item['actual_sha256'], item['expected_sha256'])
        self.assertEqual((report['failed'], item['status']), (1, 'changed'))
        self.assert_unchanged()

    def test_integrity_report_unsafe_path_and_valid_record_continue(self):
        other = self.materials.import_file(self.source, self.pid)
        with self.store.transaction() as connection:
            connection.execute('UPDATE materials SET relative_path=? WHERE id=?',
                               ('materials/../escape.txt', self.mid))
        before = self.materials.get_material(self.mid)
        report = self.materials.audit_materials()
        items = {item['id']: item for item in report['items']}
        self.assertEqual((report['passed'], report['failed']), (1, 1))
        self.assertEqual(items[self.mid]['status'], 'unsafe_path')
        self.assertEqual(items[other]['status'], 'passed')
        self.assertEqual(self.materials.get_material(self.mid), before)
        self.assertFalse((self.store.root / 'preview_cache').exists())

    def test_integrity_report_hardlink_is_unsafe(self):
        os.link(self.managed, self.base / 'alias.txt')
        item = self.materials.audit_materials()['items'][0]
        self.assertEqual(item['status'], 'unsafe_path')
        self.assertIn('硬链接', item['reason'])
        self.assert_unchanged()

    def test_integrity_report_read_failure_isolated_mock(self):
        other = self.materials.import_file(self.source, self.pid)
        original = sha256_file
        def read_hash(path):
            if Path(path) == self.managed:
                raise PermissionError('模拟读取权限不足')
            return original(path)
        with patch('services.materials.sha256_file', side_effect=read_hash):
            report = self.materials.audit_materials()
        items = {item['id']: item for item in report['items']}
        self.assertEqual((report['passed'], report['failed']), (1, 1))
        self.assertEqual(items[self.mid]['status'], 'error')
        self.assertIn('模拟读取权限不足', items[self.mid]['reason'])
        self.assertEqual(items[other]['status'], 'passed')
        self.assert_unchanged()

    def test_integrity_report_empty_database(self):
        empty_store = Store(self.base / 'empty-data')
        report = MaterialService(empty_store).audit_materials()
        self.assertEqual((report['total'], report['passed'], report['failed'], report['items']),
                         (0, 0, 0, []))
        self.assertFalse((empty_store.root / 'preview_cache').exists())


if __name__ == '__main__':
    unittest.main()
