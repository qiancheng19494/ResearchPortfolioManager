"""V1.1 日期控件与保存回归；此批不显示窗口、不调用外部应用。"""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from PySide6.QtCore import QDate
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QWidget

from app.date_field import DateSelectionDialog, NullableDateField
from app.dialogs import AchievementDialog, ProjectDialog, TaskDialog, value_of
from database.store import Store
from services.portfolio import PortfolioService


class DateFieldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def test_empty_and_existing_text_are_preserved(self):
        for text in (None, "", "2024-02-29", "不是合法日期"):
            with self.subTest(text=text):
                field = NullableDateField(text)
                self.assertEqual(field.text(), text or "")
                self.assertEqual(value_of(field), text or "")

    def test_explicit_calendar_confirmation_sets_iso_date(self):
        field = NullableDateField()
        def confirm(dialog):
            dialog.calendar.setSelectedDate(QDate(2028, 2, 29))
            return QDialog.Accepted
        with patch.object(DateSelectionDialog, "exec", confirm):
            field.calendar_button.click()
        self.assertEqual(field.text(), "2028-02-29")

    def test_cancel_keeps_empty_existing_or_invalid_text(self):
        for text in ("", "2026-11-09", "2026-02-30"):
            with self.subTest(text=text):
                field = NullableDateField(text)
                def cancel(dialog):
                    dialog.calendar.setSelectedDate(QDate(2030, 1, 1))
                    return QDialog.Rejected
                with patch.object(DateSelectionDialog, "exec", cancel):
                    field.open_calendar()
                self.assertEqual(field.text(), text)

    def test_calendar_starts_at_existing_date_without_writing(self):
        field = NullableDateField("2024-02-29")
        dialog = DateSelectionDialog(field, field.text())
        self.assertEqual(dialog.calendar.selectedDate(), QDate(2024, 2, 29))
        self.assertEqual(field.text(), "2024-02-29")
        dialog.calendar.setSelectedDate(QDate(2031, 7, 10))
        dialog.reject()
        self.assertEqual(field.text(), "2024-02-29")

    def test_one_click_clear_and_text_changed_interface(self):
        field = NullableDateField("2026-10-17")
        changes = []
        field.textChanged.connect(changes.append)
        field.clear_button.click()
        self.assertEqual(field.text(), "")
        field.setText("2026-10-18")
        self.assertEqual(changes, ["", "2026-10-18"])
        self.assertEqual(value_of(field), "2026-10-18")

    def test_readonly_blocks_keyboard_calendar_and_clear(self):
        field = NullableDateField("2026-10-17")
        field.setReadOnly(True)
        self.assertTrue(field.isReadOnly())
        self.assertTrue(field.editor.isReadOnly())
        self.assertFalse(field.calendar_button.isEnabled())
        self.assertFalse(field.clear_button.isEnabled())
        self.assertFalse(field.shortcut.isEnabled())
        QTest.keyClicks(field.editor, "2030-12-31")
        with patch.object(DateSelectionDialog, "exec") as opener:
            field.calendar_button.click()
            field.open_calendar()
            field.clear_button.click()
            field.clear()
        opener.assert_not_called()
        self.assertEqual(field.text(), "2026-10-17")
        field.setReadOnly(False)
        self.assertTrue(field.calendar_button.isEnabled())
        self.assertTrue(field.clear_button.isEnabled())
        field.clear_button.click()
        self.assertEqual(field.text(), "")


class DialogDatePersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="V1.1 日期隔离 ")
        self.root = Path(self.temp.name) / "资料"
        self.owner = QWidget()
        self.owner.store = Store(self.root)
        self.owner.portfolio = PortfolioService(self.owner.store)
        self.errors = []
        self.owner.show_error = self.errors.append
        self.portfolio = self.owner.portfolio

    def tearDown(self):
        self.owner.close()
        self.owner.deleteLater()
        self.application.processEvents()
        self.temp.cleanup()

    def project(self):
        return self.portfolio.save_project({"name": "【测试】日期项目"})

    def dialogs(self, pid):
        project = ProjectDialog(self.owner)
        project.fields["name"].setText("【测试】表单新项目")
        task = TaskDialog(self.owner, project_id=pid)
        task.fields["title"].setText("【测试】表单任务")
        achievement = AchievementDialog(self.owner, project_id=pid)
        achievement.fields["name"].setText("【测试】表单成果")
        return ((project, "start_date"), (task, "due_date"), (achievement, "related_date"))

    def test_all_four_form_date_fields_use_nullable_widget(self):
        pid = self.project()
        dialogs = self.dialogs(pid)
        for dialog, key in dialogs:
            with self.subTest(key=key):
                self.assertIsInstance(dialog.fields[key], NullableDateField)
                self.assertEqual(dialog.fields[key].text(), "")
                self.assertEqual(dialog.fields[key].objectName(), "field_" + key)
        self.assertIsInstance(dialogs[0][0].fields["end_date"], NullableDateField)
        self.assertEqual(dialogs[0][0].fields["end_date"].text(), "")

    def test_empty_form_dates_save_null_and_reopen_empty(self):
        pid = self.project()
        for dialog, key in self.dialogs(pid):
            dialog.save()
            self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(self.errors, [])
        reopened = PortfolioService(Store(self.root))
        project = next(row for row in reopened.list_projects() if row["name"] == "【测试】表单新项目")
        task = reopened.list_tasks()[0]
        achievement = reopened.list_achievements()[0]
        for key in ("start_date", "end_date"):
            self.assertIsNone(project[key])
        self.assertIsNone(task["due_date"])
        self.assertIsNone(achievement["related_date"])
        for dialog, keys in ((ProjectDialog(self.owner, project), ("start_date", "end_date")),
                             (TaskDialog(self.owner, task), ("due_date",)),
                             (AchievementDialog(self.owner, achievement), ("related_date",))):
            for key in keys:
                self.assertEqual(dialog.fields[key].text(), "")

    def test_invalid_manual_date_creation_fails_without_success_or_row(self):
        pid = self.project()
        for dialog, key in self.dialogs(pid):
            with self.subTest(key=key):
                before = (len(self.portfolio.list_projects()), len(self.portfolio.list_tasks()),
                          len(self.portfolio.list_achievements()))
                dialog.fields[key].setText("2026-02-30")
                dialog.save()
                self.assertEqual(dialog.result(), QDialog.Rejected)
                self.assertIn("日期必须", self.errors[-1])
                after = (len(self.portfolio.list_projects()), len(self.portfolio.list_tasks()),
                         len(self.portfolio.list_achievements()))
                self.assertEqual(after, before)

    def test_invalid_manual_date_edit_keeps_original_record(self):
        pid = self.project()
        tid = self.portfolio.save_task({"project_id": pid, "title": "【测试】原任务"})
        aid = self.portfolio.save_achievement({"project_id": pid, "name": "【测试】原成果"})
        cases = ((ProjectDialog, self.portfolio.get_project, pid, "end_date"),
                 (TaskDialog, self.portfolio.get_task, tid, "due_date"),
                 (AchievementDialog, self.portfolio.get_achievement, aid, "related_date"))
        for dialog_type, getter, record_id, key in cases:
            with self.subTest(key=key):
                old = getter(record_id)
                dialog = dialog_type(self.owner, old)
                dialog.fields[key].setText("2026-13-01")
                dialog.save()
                self.assertEqual(dialog.result(), QDialog.Rejected)
                self.assertIn("日期必须", self.errors[-1])
                self.assertEqual(getter(record_id), old)

    def test_historical_empty_dates_survive_other_field_edit(self):
        pid = self.project()
        tid = self.portfolio.save_task({"project_id": pid, "title": "【测试】历史任务"})
        aid = self.portfolio.save_achievement({"project_id": pid, "name": "【测试】历史成果"})
        cases = ((ProjectDialog, self.portfolio.get_project, pid, "notes", ("start_date", "end_date")),
                 (TaskDialog, self.portfolio.get_task, tid, "description", ("due_date",)),
                 (AchievementDialog, self.portfolio.get_achievement, aid, "notes", ("related_date",)))
        for dialog_type, getter, record_id, other, dates in cases:
            with self.subTest(dialog=dialog_type.__name__):
                dialog = dialog_type(self.owner, getter(record_id))
                for key in dates:
                    self.assertEqual(dialog.fields[key].text(), "")
                if hasattr(dialog.fields[other], "setPlainText"):
                    dialog.fields[other].setPlainText("只改其他字段")
                else:
                    dialog.fields[other].setText("只改其他字段")
                dialog.save()
                self.assertEqual(dialog.result(), QDialog.Accepted)
                for key in dates:
                    self.assertIsNone(getter(record_id)[key])

    def test_valid_dates_can_save_then_clear_to_null_after_reopen(self):
        pid = self.project()
        tid = self.portfolio.save_task({"project_id": pid, "title": "【测试】清空任务"})
        aid = self.portfolio.save_achievement({"project_id": pid, "name": "【测试】清空成果"})
        cases = ((ProjectDialog, self.portfolio.get_project, pid, ("start_date", "end_date")),
                 (TaskDialog, self.portfolio.get_task, tid, ("due_date",)),
                 (AchievementDialog, self.portfolio.get_achievement, aid, ("related_date",)))
        for dialog_type, getter, record_id, keys in cases:
            with self.subTest(dialog=dialog_type.__name__):
                dialog = dialog_type(self.owner, getter(record_id))
                for key in keys:
                    dialog.fields[key].setText("2028-02-29")
                dialog.save()
                self.assertEqual(dialog.result(), QDialog.Accepted)
                for key in keys:
                    self.assertEqual(getter(record_id)[key], "2028-02-29")
                dialog = dialog_type(self.owner, getter(record_id))
                for key in keys:
                    dialog.fields[key].clear_button.click()
                dialog.save()
                self.assertEqual(dialog.result(), QDialog.Accepted)
        reopened = PortfolioService(Store(self.root))
        for getter, record_id, keys in ((reopened.get_project, pid, ("start_date", "end_date")),
                                        (reopened.get_task, tid, ("due_date",)),
                                        (reopened.get_achievement, aid, ("related_date",))):
            for key in keys:
                self.assertIsNone(getter(record_id)[key])
        self.assertEqual(self.errors, [])

    def test_archived_form_dates_remain_readonly(self):
        pid = self.portfolio.save_project({"name": "【测试】归档项目", "start_date": "2026-01-01"})
        tid = self.portfolio.save_task({"project_id": pid, "title": "【测试】归档任务", "due_date": "2026-12-01"})
        aid = self.portfolio.save_achievement({"project_id": pid, "name": "【测试】归档成果", "related_date": "2026-10-01"})
        self.portfolio.archive_project(pid)
        cases = ((ProjectDialog(self.owner, self.portfolio.get_project(pid)), ("start_date", "end_date")),
                 (TaskDialog(self.owner, self.portfolio.get_task(tid)), ("due_date",)),
                 (AchievementDialog(self.owner, self.portfolio.get_achievement(aid)), ("related_date",)))
        for dialog, keys in cases:
            self.assertTrue(dialog.readonly)
            self.assertTrue(dialog.save_button.isHidden())
            for key in keys:
                with self.subTest(key=key):
                    field = dialog.fields[key]
                    old = field.text()
                    self.assertTrue(field.isReadOnly())
                    self.assertFalse(field.calendar_button.isEnabled())
                    self.assertFalse(field.clear_button.isEnabled())
                    field.clear_button.click()
                    self.assertEqual(field.text(), old)


if __name__ == "__main__":
    unittest.main(verbosity=2)
