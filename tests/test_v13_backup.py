"""Protected output locations and atomic integrity-report export, in temporary data."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from database.store import Store
from services.export_backup import ExportBackupService
from services.portfolio import PortfolioService


class OutputProtectionV13Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='rpm-v13-output-')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / 'data')
        self.service = ExportBackupService(self.store)
        self.pid = PortfolioService(self.store).save_project({'name': '临时导出验证'})
        self.report = {'checked_at': '2026-10-17T12:00:00', 'total': 0,
                       'passed': 0, 'failed': 0, 'items': []}

    def tearDown(self):
        self.temp.cleanup()

    def junction(self, link, destination):
        if os.name != 'nt':
            self.skipTest('Real Windows directory-junction check')
        result = subprocess.run(['cmd', '/c', 'mklink', '/J', str(link), str(destination)],
                                capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_all_exports_refuse_actual_protected_directory_location(self):
        protected = self.store.root / 'materials'
        protected.rmdir()
        external = self.base / 'material-storage'
        external.mkdir()
        self.junction(protected, external)
        output = external / 'preserved.txt'
        output.write_bytes(b'preserved managed directory file')
        operations = [lambda: self.service.export_csv(output),
                      lambda: self.service.export_html(output, self.pid),
                      lambda: self.service.backup(output),
                      lambda: self.service.export_integrity_report(output, self.report)]
        for operation in operations:
            with self.subTest(operation=operation):
                with self.assertRaisesRegex(ValueError, '受管理材料位置'):
                    operation()
                self.assertEqual(output.read_bytes(), b'preserved managed directory file')

    def test_restore_refuses_empty_child_of_actual_protected_location(self):
        protected = self.store.root / 'materials'
        protected.rmdir()
        external = self.base / 'storage'
        external.mkdir()
        self.junction(protected, external)
        archive = self.service.backup(self.base / 'valid.zip')
        target = external / 'empty'
        target.mkdir()
        with self.assertRaisesRegex(ValueError, '受管理目录'):
            self.service.restore(archive, target)
        self.assertEqual(list(target.iterdir()), [])

    def test_restore_refuses_direct_junction_target(self):
        archive = self.service.backup(self.base / 'valid.zip')
        empty = self.base / 'empty'
        empty.mkdir()
        link = self.base / 'link'
        self.junction(link, empty)
        with self.assertRaisesRegex(ValueError, '目录联接'):
            self.service.restore(archive, link)
        self.assertEqual(list(empty.iterdir()), [])

    def test_json_report_roundtrip_and_protected_destination(self):
        output = self.service.export_integrity_report(self.base / '检查.json', self.report)
        self.assertEqual(json.loads(output.read_text(encoding='utf-8')), self.report)
        with self.assertRaises(ValueError):
            self.service.export_integrity_report(self.store.config_path, self.report)

    def test_invalid_report_or_failed_replace_preserves_existing_file(self):
        output = self.base / 'report.json'
        output.write_bytes(b'previous report')
        for invalid in ([], {'value': float('nan')}, {'value': object()}):
            with self.subTest(invalid=invalid):
                with self.assertRaises((TypeError, ValueError)):
                    self.service.export_integrity_report(output, invalid)
                self.assertEqual(output.read_bytes(), b'previous report')
        with patch.object(Path, 'replace', side_effect=OSError('simulated destination error')):
            with self.assertRaises(OSError):
                self.service.export_integrity_report(output, self.report)
        self.assertEqual(output.read_bytes(), b'previous report')
        self.assertEqual(list(self.base.glob('.integrity-*.tmp')), [])

    def test_noncanonical_windows_member_names_rejected(self):
        for name in ('materials/id/COM\u00b9.txt', 'materials/id/CON .txt',
                     'materials/id/file\x01.txt', 'materials/id/CONIN$.txt',
                     'materials/id/file.txt ', 'materials/id/file.txt.'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    self.service._zip_path(name)
