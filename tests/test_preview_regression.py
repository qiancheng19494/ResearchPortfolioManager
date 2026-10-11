"""材料预览保护：服务校验及 Qt 实际路由（外部编辑为模拟，独立临时资料）。"""
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from database.store import Store
from services.export_backup import ExportBackupService
from services.materials import MaterialService, sha256_file
from services.portfolio import PortfolioService


class PreviewServiceRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='材料预览 回归 ')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / '隔离资料')
        self.portfolio = PortfolioService(self.store)
        self.materials = MaterialService(self.store)
        self.exports = ExportBackupService(self.store)
        self.pid = self.portfolio.save_project({'name': '独立预览测试'})
        self.aid = self.portfolio.save_achievement({'project_id': self.pid, 'name': '测试成果',
                                                  'type': '其他成果', 'status': '准备中'})
        self.source = self.base / '中文 文件.txt'
        self.original_bytes = '新生成的测试材料，不是个人真实资料。'.encode('utf-8')
        self.source.write_bytes(self.original_bytes)
        self.mid = self.materials.import_file(self.source, self.pid, self.aid, version_label='V1')
        self.managed = self.materials.file_path(self.mid, verify=True)
        self.original_record = self.materials.get_material(self.mid)

    def tearDown(self):
        self.temp.cleanup()

    def assert_original_intact(self):
        self.assertEqual(self.source.read_bytes(), self.original_bytes)
        self.assertEqual(self.managed.read_bytes(), self.original_bytes)
        self.assertEqual(sha256_file(self.managed), self.original_record['sha256'])
        self.assertEqual(self.materials.get_material(self.mid), self.original_record)

    def preview_edit_roundtrip(self, archived):
        if archived:
            self.portfolio.archive_project(self.pid)
            self.original_record = self.materials.get_material(self.mid)
        preview = self.materials.prepare_preview(self.mid)
        self.assertTrue(preview.is_relative_to(self.store.root / 'preview_cache'))
        self.assertFalse(preview.is_relative_to(self.store.root / 'materials'))
        self.assertEqual(preview.read_bytes(), self.original_bytes)
        preview.write_text('模拟在外部程序保存预览修改', encoding='utf-8')
        self.assert_original_intact()
        archive = self.exports.backup(self.base / '预览修改后备份.zip')
        with zipfile.ZipFile(archive) as package:
            self.assertFalse(any('preview_cache' in name for name in package.namelist()))
        restored_root = self.exports.restore(archive, self.base / '恢复新目录')
        restored = Store(restored_root)
        restored_materials = MaterialService(restored)
        self.assertEqual(restored_materials.get_material(self.mid), self.original_record)
        self.assertEqual(restored_materials.file_path(self.mid, verify=True).read_bytes(), self.original_bytes)
        self.assertEqual(PortfolioService(restored).get_project(self.pid)['archived'], int(archived))
        self.assertFalse((restored.root / 'preview_cache').exists())

    def test_active_preview_edit_keeps_archive_and_backup_restore_intact(self):
        self.preview_edit_roundtrip(False)

    def test_archived_preview_edit_keeps_archive_and_backup_restore_intact(self):
        self.preview_edit_roundtrip(True)

    def test_each_open_isolated_preserves_previous_edited_preview(self):
        first = self.materials.prepare_preview(self.mid)
        first.write_bytes(b'edited first preview')
        second = self.materials.prepare_preview(self.mid)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), b'edited first preview')
        self.assertEqual(second.read_bytes(), self.original_bytes)
        self.assert_original_intact()

    def test_managed_size_change_is_rejected_without_rewriting_record(self):
        self.managed.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'SHA-256.*哈希不能重建'):
            self.materials.prepare_preview(self.mid)
        self.assertEqual(self.materials.get_material(self.mid), self.original_record)
        self.assertFalse((self.store.root / 'preview_cache').exists())

    def test_managed_hash_change_same_size_is_rejected(self):
        self.managed.write_bytes(b'x' * len(self.original_bytes))
        with self.assertRaisesRegex(ValueError, '校验失败'):
            self.materials.prepare_preview(self.mid)
        self.assertEqual(self.materials.get_material(self.mid), self.original_record)

    def test_managed_missing_is_rejected_with_honest_recovery_conditions(self):
        self.managed.unlink()
        with self.assertRaisesRegex(FileNotFoundError, '缺失.*哈希不能重建.*完整备份'):
            self.materials.prepare_preview(self.mid)
        self.assertEqual(self.materials.get_material(self.mid), self.original_record)

    def test_copy_failure_cleans_only_unexposed_partial_and_keeps_prior_preview(self):
        previous = self.materials.prepare_preview(self.mid)
        previous.write_bytes(b'previous preview user changes')
        def failed_copy(source, destination):
            Path(destination).write_bytes(b'partial')
            raise OSError('模拟复制失败')
        with patch('services.materials.shutil.copyfile', side_effect=failed_copy):
            with self.assertRaisesRegex(OSError, '模拟复制失败'):
                self.materials.prepare_preview(self.mid)
        self.assertEqual(list((self.store.root / 'preview_cache').iterdir()), [previous.parent])
        self.assertEqual(previous.read_bytes(), b'previous preview user changes')
        self.assert_original_intact()

    def test_original_changes_during_copy_recheck_rejects_before_exposure(self):
        copyfile = shutil.copyfile
        def changing_copy(source, destination):
            copyfile(source, destination)
            Path(source).write_bytes(b'changed during preview')
        with patch('services.materials.shutil.copyfile', side_effect=changing_copy):
            with self.assertRaisesRegex(ValueError, '校验失败'):
                self.materials.prepare_preview(self.mid)
        self.assertEqual(list((self.store.root / 'preview_cache').iterdir()), [])
        self.assertEqual(self.materials.get_material(self.mid), self.original_record)
        self.assertEqual(self.source.read_bytes(), self.original_bytes)


class PreviewGuiRoutingRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='GUI 预览路径 ')
        self.base = Path(self.temp.name)
        self.store = Store(self.base / '隔离资料')
        self.window = MainWindow(self.store)
        self.window.show()
        self.assertTrue(QTest.qWaitForWindowExposed(self.window, 5000))
        self.pid = self.window.portfolio.save_project({'name': 'GUI 路径测试'})
        self.source = self.base / '路由.txt'
        self.source.write_text('GUI 路由测试独立材料', encoding='utf-8')
        self.mid = self.window.materials.import_file(self.source, self.pid)
        self.original = self.window.materials.file_path(self.mid, verify=True)
        self.original_bytes = self.original.read_bytes()
        self.original_hash = sha256_file(self.original)
        self.errors = []
        self.error_patch = patch.object(self.window, 'show_error', side_effect=self.errors.append)
        self.error_patch.start()

    def tearDown(self):
        self.error_patch.stop()
        self.window.close()
        self.application.processEvents()
        self.window.deleteLater()
        QTest.qWait(30)
        self.temp.cleanup()

    def wait_job(self):
        until = time.monotonic() + 20
        while self.window.busy and time.monotonic() < until:
            QTest.qWait(20)
        self.assertFalse(self.window.busy, '预览后台任务未完成')

    def routed_edit(self, archived=False, folder=False):
        if archived:
            self.window.portfolio.archive_project(self.pid)
        observed = []
        def capture_target(url):
            observed.append((Path(url.toLocalFile()), QThread.currentThread() == self.application.thread()))
            return True
        with patch('app.main_window.QDesktopServices.openUrl', side_effect=capture_target):
            self.window.open_material(self.mid, folder=folder)
            self.assertTrue(self.window.busy)
            self.wait_job()
        self.assertEqual(self.errors, [])
        self.assertEqual(len(observed), 1)
        target, main_thread = observed[0]
        self.assertTrue(main_thread, '关联程序必须在 Qt 主线程打开')
        self.assertTrue(target.is_relative_to(self.store.root / 'preview_cache'))
        self.assertFalse(target.is_relative_to(self.store.root / 'materials'))
        preview = next(target.iterdir()) if folder else target
        preview.write_text('模拟编辑实际路由的目标并保存', encoding='utf-8')
        self.assertEqual(self.original.read_bytes(), self.original_bytes)
        self.assertEqual(sha256_file(self.original), self.original_hash)
        self.assertEqual(self.window.materials.get_material(self.mid)['sha256'], self.original_hash)
        self.assertIn('导入新版本', self.window.statusBar().currentMessage())
        self.window.close()
        self.assertTrue(preview.is_file(), '关闭软件不能自动删除已暴露的预览')

    def test_active_actual_qt_target_is_preview_simulated_save_preserves_original(self):
        self.routed_edit()

    def test_archived_actual_qt_target_is_preview_simulated_save_preserves_original(self):
        self.routed_edit(archived=True)

    def test_folder_actual_qt_target_is_preview_directory(self):
        self.routed_edit(folder=True)

    def test_copy_and_hash_prepare_runs_in_background_open_runs_main_thread(self):
        prepare = self.window.materials.prepare_preview
        observed = []
        def background_prepare(mid):
            observed.append(QThread.currentThread() != self.application.thread())
            return prepare(mid)
        with patch.object(self.window.materials, 'prepare_preview', side_effect=background_prepare), \
                patch('app.main_window.QDesktopServices.openUrl', return_value=True):
            self.window.open_material(self.mid)
            self.wait_job()
        self.assertEqual(observed, [True])
        self.assertEqual(self.errors, [])

    def test_corrupt_or_missing_managed_file_does_not_launch_program(self):
        for missing in (False, True):
            with self.subTest(missing=missing):
                if missing:
                    self.original.unlink()
                else:
                    self.original.write_bytes(b'corrupted archive')
                with patch('app.main_window.QDesktopServices.openUrl', return_value=True) as opener:
                    self.window.open_material(self.mid)
                    self.wait_job()
                    opener.assert_not_called()
                self.assertTrue(self.errors)
                self.assertIn('哈希不能重建', self.errors[-1])
                self.assertIn('缺失' if missing else '校验失败', self.errors[-1])
                self.errors.clear()


if __name__ == '__main__':
    unittest.main(verbosity=2)
