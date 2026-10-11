"""Native six-page Reviewed flow. Association targets are intercepted, not real editor checks."""
import csv
from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PySide6.QtCore import Qt, QThread
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton, QMessageBox

from app.dialogs import ProjectDialog, MaterialDialog
from app.main_window import MainWindow
from database.store import Store
from services.materials import MaterialService, sha256_file
from services.portfolio import PortfolioService
import tests.test_gui as gui_helpers
from tests.test_reviewed_compatibility import create_original_backup


class ReviewedNativeFlowTests(unittest.TestCase):
    """Reuse existing GUI helper operations, without rerunning inherited historical tests."""
    setUp = gui_helpers.NativeGuiTests.setUp
    tearDown = gui_helpers.NativeGuiTests.tearDown
    click = gui_helpers.NativeGuiTests.click
    navigate = gui_helpers.NativeGuiTests.navigate
    fill_field = gui_helpers.NativeGuiTests.fill_field
    form_action = gui_helpers.NativeGuiTests.form_action
    select_row = gui_helpers.NativeGuiTests.select_row
    wait_job = gui_helpers.NativeGuiTests.wait_job

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setFont(QFont('Microsoft YaHei UI', 10))
        cls.screenshot_dir = Path(__file__).resolve().parents[1] / 'docs' / 'screenshots'
        cls.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def screenshot(self, name, widget=None):
        QTest.qWait(80)
        self.assertTrue((widget or self.window).grab().save(str(self.screenshot_dir / name), 'PNG'))

    def restore_with_ui(self, reports, archive, target):
        target.mkdir()
        with patch('app.pages.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
                patch('app.pages.QFileDialog.getExistingDirectory', return_value=str(target)), \
                patch('app.pages.QMessageBox.question', return_value=QMessageBox.Yes):
            self.click(reports.restore_button)
        self.wait_job()
        self.assertIn(str(target), reports.result.text())
        self.assertIn('恢复与完整性校验成功', reports.result.text())
        return Store(target)

    def test_native_six_pages_preview_exports_both_restores_close_reopen(self):
        self.assertEqual(self.application.platformName(), 'windows')
        self.assertEqual((self.window.width(), self.window.height()), (1366, 768))
        for key in ('dashboard', 'projects', 'tasks', 'achievements', 'materials', 'reports'):
            self.navigate(key)
        projects = self.navigate('projects')
        self.form_action(projects.new_button, {'name': '【演示】修订流程 <项目 &>', 'leader': '临时测试负责人',
                                              'description': '只用于隔离验证 <字符 & 引号" >'})
        pid = self.window.portfolio.list_projects()[0]['id']
        self.select_row(projects)
        self.form_action(projects.edit_button, {'notes': '修订版 GUI 保存验证'})
        projects.search.setText('修订流程')
        self.click(projects.search_button)
        self.assertEqual(projects.table.rowCount(), 1)

        tasks = self.navigate('tasks')
        self.form_action(tasks.new_button, {'project_id': pid, 'title': '【演示】修订任务',
                                           'due_date': date.today().isoformat(), 'status': '进行中'})
        self.assertEqual(len(self.window.portfolio.list_tasks()), 1)
        achievements = self.navigate('achievements')
        self.form_action(achievements.new_button, {'project_id': pid, 'name': '【演示】修订成果 <&>',
                                                 'type': '软件著作权', 'status': '准备中'})
        aid = self.window.portfolio.list_achievements()[0]['id']

        sources = [self.base / '版本一' / '同名 材料.txt', self.base / '版本二' / '同名 材料.txt']
        for index, source in enumerate(sources):
            source.parent.mkdir()
            source.write_text(f'隔离演示材料第 {index + 1} 版', encoding='utf-8')
        materials = self.navigate('materials')
        self.form_action(materials.new_button, {'source': str(sources[0]), 'project_id': pid,
                                               'achievement_id': aid, 'version_label': 'V1'})
        self.wait_job()
        self.select_row(materials)
        self.form_action(materials.version_button, {'source': str(sources[1]), 'version_label': 'V2'})
        self.wait_job()
        materials.search.setText('同名 材料')
        self.click(materials.search_button)
        self.assertEqual(materials.table.rowCount(), 2)
        self.select_row(materials)
        record = materials.selected()
        mid = record['id']
        managed = self.window.materials.file_path(mid, verify=True)
        archive_bytes, archive_hash = managed.read_bytes(), record['sha256']
        routed = []
        def simulated_editor(url):
            target = Path(url.toLocalFile())
            routed.append((target, QThread.currentThread() == self.application.thread()))
            self.assertTrue(target.is_relative_to(self.store.root / 'preview_cache'))
            self.assertNotEqual(target, managed)
            target.write_text('模拟外部编辑器保存预览副本', encoding='utf-8')
            return True
        for archived in (False, True):
            if archived:
                projects = self.navigate('projects')
                self.select_row(projects)
                with patch('app.pages.QMessageBox.question', return_value=QMessageBox.Yes):
                    self.click(projects.archive_button)
                self.assertTrue(self.window.portfolio.get_project(pid)['archived'])
                materials = self.navigate('materials')
                self.select_row(materials)
                self.assertFalse(materials.version_button.isEnabled())
                readonly = MaterialDialog(self.window, self.window.materials.get_material(mid))
                self.assertTrue(readonly.readonly)
                self.assertTrue(readonly.fields['notes'].isReadOnly())
                self.assertTrue(readonly.save_button.isHidden())
                readonly.deleteLater()
                self.assertTrue(materials.open_button.isEnabled())
            with patch('app.main_window.QDesktopServices.openUrl', side_effect=simulated_editor):
                self.click(materials.open_button)
                self.wait_job()
            self.assertEqual(managed.read_bytes(), archive_bytes)
            self.assertEqual(sha256_file(managed), archive_hash)
            self.assertEqual(self.window.materials.get_material(mid)['sha256'], archive_hash)
            self.assertEqual(self.window.materials.get_material(mid)['version_label'], record['version_label'])
        self.assertEqual(len(routed), 2)
        self.assertNotEqual(routed[0][0], routed[1][0])
        self.assertTrue(all(on_main for _, on_main in routed))
        self.assertIn('独立预览副本', self.window.statusBar().currentMessage())
        self.assertIn('另存', self.window.statusBar().currentMessage())
        self.screenshot('reviewed-04-material-preview.png')
        with patch('app.main_window.QDesktopServices.openUrl', return_value=True) as open_folder:
            self.click(materials.folder_button)
            self.wait_job()
        folder = Path(open_folder.call_args.args[0].toLocalFile())
        self.assertTrue(folder.is_relative_to(self.store.root / 'preview_cache'))
        self.assertFalse(folder.is_relative_to(self.store.root / 'materials'))

        reports = self.navigate('reports')
        self.fill_field(reports.project, pid)
        self.fill_field(reports.type, '软件著作权')
        self.fill_field(reports.status, '准备中')
        csv_path, html_path, backup = self.base / '修订台账.csv', self.base / '修订摘要.html', self.base / '修订备份.zip'
        for button, path in ((reports.csv_button, csv_path), (reports.html_button, html_path), (reports.backup_button, backup)):
            with patch('app.pages.QFileDialog.getSaveFileName', return_value=(str(path), '')):
                self.click(button)
            self.wait_job()
            self.assertTrue(path.is_file())
        with csv_path.open(encoding='utf-8-sig', newline='') as stream:
            self.assertEqual(len(list(csv.reader(stream))), 2)
        self.assertIn('&lt;项目 &amp;&gt;', html_path.read_text(encoding='utf-8'))
        with zipfile.ZipFile(backup) as package:
            self.assertFalse(any(name.startswith('preview_cache/') for name in package.namelist()))
        restored = self.restore_with_ui(reports, backup, self.base / '修订恢复')
        self.assertEqual(len(MaterialService(restored).list_materials()), 2)
        self.assertEqual(MaterialService(restored).file_path(mid, verify=True).read_bytes(), archive_bytes)
        self.assertEqual(len(PortfolioService(restored).list_tasks()), 1)

        original_backup, evidence = create_original_backup(self.base)
        old_restored = self.restore_with_ui(reports, original_backup, self.base / '原版恢复')
        self.assertEqual(len(PortfolioService(old_restored).list_projects(include_archived=True)), 1)
        old_material = MaterialService(old_restored)
        old_material.file_path(evidence['material_id'], verify=True)
        self.form_action(self.window.profile_button, {'name': '关闭重开姓名', 'background': '隔离 GUI 背景', 'interests': '隔离 GUI 兴趣'})
        self.assertEqual(self.errors, [])
        self.window.close()
        reopened_store = Store(self.store.root)
        reopened_window = MainWindow(reopened_store)
        try:
            reopened_window.resize(1366, 768)
            reopened_window.show()
            self.assertTrue(QTest.qWaitForWindowExposed(reopened_window, 5000))
            self.assertEqual(reopened_store.config['name'], '关闭重开姓名')
            self.assertIs(reopened_store.config['demo'], True)
            self.assertTrue(reopened_window.demo_label.isVisible())
            self.assertIn('演示数据', reopened_window.windowTitle())
            self.assertEqual(len(reopened_window.materials.list_materials()), 2)
            self.assertEqual(reopened_window.materials.file_path(mid, verify=True).read_bytes(), archive_bytes)
        finally:
            reopened_window.close()
            reopened_window.deleteLater()
            QTest.qWait(40)

    def test_native_leader_form_failure_new_edit_historical_no_success(self):
        for leader in ('', '   '):
            dialog = ProjectDialog(self.window)
            dialog.fields['name'].setText('不应创建的项目')
            dialog.fields['leader'].setText(leader)
            accepted = []
            dialog.accepted.connect(lambda: accepted.append(True))
            dialog.show()
            self.assertTrue(QTest.qWaitForWindowExposed(dialog, 5000))
            self.window.statusBar().showMessage('表单校验进行中')
            self.click(dialog.save_button)
            self.assertEqual(self.errors[-1][0], '负责人不能为空')
            self.assertEqual(accepted, [])
            self.assertEqual(dialog.result(), 0)
            self.assertTrue(dialog.isVisible())
            self.assertEqual(self.window.portfolio.list_projects(), [])
            self.assertNotIn('已保存', self.window.statusBar().currentMessage())
            if leader == '':
                self.screenshot('reviewed-project-leader-form.png', dialog)
            dialog.reject()
            dialog.deleteLater()
            QTest.qWait(30)
            self.errors.clear()
        pid = self.window.portfolio.save_project({'name': '历史空负责人', 'leader': '临时人'})
        with self.store.transaction() as connection:
            connection.execute('UPDATE projects SET leader=? WHERE id=?', ('', pid))
        old = self.window.portfolio.get_project(pid)
        dialog = ProjectDialog(self.window, old)
        dialog.show()
        self.assertTrue(QTest.qWaitForWindowExposed(dialog, 5000))
        self.assertEqual(dialog.fields['leader'].text(), '')
        self.click(dialog.save_button)
        self.assertEqual(self.errors[-1][0], '负责人不能为空')
        self.assertEqual(self.window.portfolio.get_project(pid), old)
        self.errors.clear()
        dialog.fields['leader'].setText('本人核实后填写')
        self.click(dialog.save_button)
        self.assertEqual(dialog.result(), 1)
        self.assertEqual(self.window.portfolio.get_project(pid)['leader'], '本人核实后填写')
        dialog.deleteLater()
        QTest.qWait(30)

    def test_native_real_data_false_stays_unmarked_on_close_reopen(self):
        real = Store(self.base / '独立真实空库')
        self.assertIs(real.config['demo'], False)
        for pass_number in range(2):
            current = Store(real.root)
            window = MainWindow(current)
            try:
                window.show()
                self.assertTrue(QTest.qWaitForWindowExposed(window, 5000))
                self.assertFalse(window.demo_label.isVisible())
                self.assertNotIn('演示数据', window.windowTitle())
                for key in ('dashboard', 'projects', 'tasks', 'achievements', 'materials', 'reports'):
                    window.navigate(key)
                    self.assertTrue(window.pages[key].isVisible())
                self.assertEqual(window.portfolio.list_projects(include_archived=True), [])
                if pass_number == 0:
                    current.save_config({'name': '真实库隔离测试姓名', 'background': '测试背景', 'interests': '测试兴趣'})
                else:
                    self.assertEqual(current.config['name'], '真实库隔离测试姓名')
                    self.assertIs(current.config['demo'], False)
            finally:
                window.close()
                window.deleteLater()
                QTest.qWait(40)


if __name__ == '__main__':
    unittest.main(verbosity=2)
