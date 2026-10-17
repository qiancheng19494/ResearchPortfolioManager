"""Native V1.3 UI checks. File pickers are controlled; external editors are not checked."""
from datetime import date, timedelta
from pathlib import Path
import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate, QTimer, Qt
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QDialogButtonBox, QTableView, QMessageBox

from app.date_field import DateSelectionDialog, NullableDateField
from app.dialogs import ProjectDialog
from database.store import Store
import tests.test_gui as gui_helpers


class V11NativeTests(unittest.TestCase):
    setUp = gui_helpers.NativeGuiTests.setUp
    tearDown = gui_helpers.NativeGuiTests.tearDown
    click = gui_helpers.NativeGuiTests.click
    navigate = gui_helpers.NativeGuiTests.navigate
    wait_job = gui_helpers.NativeGuiTests.wait_job

    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setFont(QFont('Microsoft YaHei UI', 10))
        cls.screenshot_dir = Path(__file__).resolve().parents[1] / 'docs' / 'screenshots'
        cls.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def capture(self, name, widget=None):
        # Hide only the local-path label for public screenshots of the actual window.
        visible = self.window.location_label.isVisible()
        self.window.location_label.hide()
        try:
            QTest.qWait(80)
            self.assertTrue((widget or self.window).grab().save(str(self.screenshot_dir / name), 'PNG'))
        finally:
            self.window.location_label.setVisible(visible)

    def choose_day(self, dialog, day):
        view = dialog.calendar.findChild(QTableView, 'qt_calendar_calendarview')
        self.assertIsNotNone(view)
        matches = [view.model().index(row, col) for row in range(view.model().rowCount())
                   for col in range(view.model().columnCount())
                   if str(view.model().index(row, col).data()) == str(day)]
        self.assertEqual(len(matches), 1)
        QTest.mouseClick(view.viewport(), Qt.LeftButton, pos=view.visualRect(matches[0]).center())
        self.application.processEvents()

    def test_native_calendar_confirm_cancel_clear_and_null_reopen(self):
        self.assertEqual(self.application.platformName(), 'windows')
        dialog = ProjectDialog(self.window)
        dialog.fields['name'].setText('【演示】V1.3 日历项目')
        dialog.show()
        self.assertTrue(QTest.qWaitForWindowExposed(dialog, 5000))
        field = dialog.fields['start_date']
        self.assertEqual(field.text(), '')
        failures = []

        def select(confirm, day, screenshot=False):
            current = QApplication.activeModalWidget()
            try:
                self.assertIsInstance(current, DateSelectionDialog)
                self.assertTrue(current.isVisible())
                current.calendar.setCurrentPage(2028, 2)
                self.choose_day(current, day)
                self.assertEqual(current.calendar.selectedDate(), QDate(2028, 2, day))
                if screenshot:
                    self.capture('v13-calendar.png', current)
                button = current.select_button if confirm else current.buttons.button(QDialogButtonBox.Cancel)
                self.click(button)
            except BaseException as exc:
                failures.append(exc)
                if isinstance(current, QDialog):
                    current.reject()

        QTimer.singleShot(80, lambda: select(True, 15, True))
        self.click(field.calendar_button)
        if failures:
            raise failures[0]
        self.assertEqual(field.text(), '2028-02-15')
        QTimer.singleShot(80, lambda: select(False, 16))
        self.click(field.calendar_button)
        if failures:
            raise failures[0]
        self.assertEqual(field.text(), '2028-02-15')
        dialog.fields['end_date'].setText('2028-03-01')
        self.click(dialog.fields['end_date'].clear_button)
        self.assertEqual(dialog.fields['end_date'].text(), '')
        self.capture('v13-date-form.png', dialog)
        self.click(dialog.save_button)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        project = self.window.portfolio.list_projects()[0]
        self.assertEqual(project['start_date'], '2028-02-15')
        self.assertIsNone(project['end_date'])
        reopened = Store(self.store.root)
        with reopened.connection() as connection:
            self.assertEqual(tuple(connection.execute('SELECT start_date,end_date FROM projects').fetchone()),
                             ('2028-02-15', None))
        dialog.deleteLater()

    def test_native_task_due_selector_intersections_and_reset(self):
        pid = self.window.portfolio.save_project({'name': '【演示】V1.3 任务筛选'})
        current = date.today()
        for label, offset in [('昨天', -1), ('今天', 0), ('明天', 1), ('第七天', 7), ('第八天', 8)]:
            self.window.portfolio.save_task({'project_id': pid, 'title': f'【演示】{label}',
                                            'due_date': (current + timedelta(days=offset)).isoformat()})
        self.window.portfolio.save_task({'project_id': pid, 'title': '【演示】无日期'})
        page = self.navigate('tasks')
        for key, expected in [('today', 1), ('overdue', 1), ('upcoming', 2)]:
            # Native popup auto-closes on this unattended desktop. Exercise the
            # supported keyboard route without mocking the control or its signal.
            page.due_filter.setFocus()
            QTest.keyClick(page.due_filter, Qt.Key_Home)
            for _ in range(page.due_filter.findData(key)):
                QTest.keyClick(page.due_filter, Qt.Key_Down)
            QTest.qWait(50)
            self.assertEqual(page.due_filter.currentData(), key)
            self.assertEqual(page.table.rowCount(), expected)
        page.due_filter.setCurrentIndex(page.due_filter.findData('today'))
        self.capture('v13-task-filter.png')
        self.click(page.reset_button)
        self.assertEqual(page.due_filter.currentData(), '')
        self.assertEqual(page.table.rowCount(), 6)
        self.assertEqual(self.errors, [])

    def test_native_six_pages_date_range_and_real_backup_restore_guidance(self):
        for key in ('dashboard', 'projects', 'tasks', 'achievements', 'materials', 'reports'):
            self.navigate(key)
        self.assertIn('V1.3', self.window.windowTitle())
        pid = self.window.portfolio.save_project({'name': '【演示】V1.3 备份核对'})
        aid = self.window.portfolio.save_achievement({'project_id': pid, 'name': '【演示】范围筛选',
                                                    'related_date': '2028-02-15'})
        page = self.navigate('achievements')
        self.assertIsInstance(page.date_from, NullableDateField)
        self.assertIsInstance(page.date_to, NullableDateField)
        page.date_from.setText('2028-02-15')
        page.date_to.setText('2028-02-15')
        self.click(page.search_button)
        self.assertEqual(page.table.rowCount(), 1)
        self.click(page.date_from.clear_button)
        self.click(page.date_to.clear_button)
        self.click(page.search_button)
        self.assertEqual(page.table.rowCount(), 1)
        self.capture('v13-achievement-dates.png')
        reports = self.navigate('reports')
        self.capture('v13-backup-guide.png')
        archive = self.base / 'V1.3 完整备份.zip'
        with patch('app.pages.QFileDialog.getSaveFileName', return_value=(str(archive), '')):
            self.click(reports.backup_button)
        self.wait_job()
        self.assertTrue(archive.is_file())
        target = self.base / 'V1.3 恢复目录'
        target.mkdir()
        with patch('app.pages.QFileDialog.getOpenFileName', return_value=(str(archive), '')), \
                patch('app.pages.QFileDialog.getExistingDirectory', return_value=str(target)), \
                patch('app.pages.QMessageBox.question', return_value=QMessageBox.Yes):
            self.click(reports.restore_button)
        self.wait_job()
        for fragment in ('恢复与完整性校验成功', '--data-dir', '□ 项目', '□ 任务', '□ 成果', '□ 材料', '□ 真实／演示标记'):
            self.assertIn(fragment, reports.result.text())
        self.assertEqual(self.window.height(), 768)
        self.assertEqual(self.store.root, self.window.store.root)
        restored = Store(target)
        with restored.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM achievements').fetchone()[0], 1)
        self.assertEqual(self.errors, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
