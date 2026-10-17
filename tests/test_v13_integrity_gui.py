"""V1.3 widget regressions with isolated stores and real Qt worker delivery.

These checks run with the offscreen Qt platform. File-dialog choices and write
failures are simulated; they do not claim native file-picker interaction.
"""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import QThread, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from app.integrity_dialog import MaterialIntegrityDialog
from app.main_window import MainWindow
from database.store import Store


class IntegrityWidgetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="V13 材料检查界面 ")
        self.base = Path(self.temp.name)
        self.window = MainWindow(Store(self.base / "资料"))
        self.errors, self.infos = [], []
        self.error_patch = patch.object(self.window, "show_error", side_effect=self.errors.append)
        self.info_patch = patch.object(self.window, "show_info", side_effect=lambda *args: self.infos.append(args))
        self.error_patch.start()
        self.info_patch.start()
        self.dialogs = []

    def tearDown(self):
        self.wait_job()
        for dialog in self.dialogs:
            dialog.reject()
            dialog.deleteLater()
        page_dialog = self.window.pages["materials"].integrity_dialog
        if page_dialog is not None:
            page_dialog.reject()
        self.error_patch.stop()
        self.info_patch.stop()
        self.window.close()
        self.window.deleteLater()
        QTest.qWait(30)
        self.temp.cleanup()

    def wait_job(self):
        deadline = time.monotonic() + 15
        while self.window.busy and time.monotonic() < deadline:
            QTest.qWait(15)
        self.assertFalse(self.window.busy, "后台任务未结束")
        QTest.qWait(15)

    def sample_report(self):
        return {"checked_at": "2026-10-17T12:00:00", "total": 1, "passed": 0, "failed": 1,
                "items": [{"id": "隔离材料", "original_name": "<b>丢失材料</b>.txt", "project_name": "归档项目",
                           "project_archived": True, "version_label": "V2", "relative_path": "materials/id/a.txt",
                           "status": "missing", "expected_size": 12, "actual_size": None,
                           "expected_sha256": "a" * 64, "actual_sha256": None,
                           "reason": "文件缺失，需从有效备份恢复。"}]}

    def make_dialog(self, report=None):
        dialog = MaterialIntegrityDialog(self.window, report or self.sample_report())
        self.dialogs.append(dialog)
        return dialog

    def test_materials_button_audits_all_filters_in_worker_and_displays_on_main_thread(self):
        service = self.window.materials
        active = self.window.portfolio.save_project({"name": "活跃项目"})
        archived = self.window.portfolio.save_project({"name": "已归档项目"})
        ids = []
        for index, project_id in enumerate((active, active, archived)):
            source = self.base / f"材料{index}.txt"
            source.write_text(f"归档内容{index}", encoding="utf-8")
            ids.append(service.import_file(source, project_id, version_label=f"V{index + 1}"))
        changed = service.file_path(ids[1])
        changed.write_text("模拟已变化的受管理文件", encoding="utf-8")
        service.file_path(ids[2]).unlink()
        self.window.portfolio.archive_project(archived)
        self.window.navigate("materials")
        page = self.window.pages["materials"]
        page.search.setText("不存在的筛选条件")
        page.refresh()
        self.assertEqual(page.table.rowCount(), 0)
        original_audit, original_display = service.audit_materials, page.show_integrity_result
        gate = threading.Event()
        on_main = {"audit": None, "display": None}

        def gated_audit():
            on_main["audit"] = QThread.currentThread() == self.application.thread()
            if not gate.wait(3):
                raise TimeoutError("测试同步等待超时")
            return original_audit()

        def display(report):
            on_main["display"] = QThread.currentThread() == self.application.thread()
            original_display(report)

        with patch.object(service, "audit_materials", side_effect=gated_audit), \
                patch.object(page, "show_integrity_result", side_effect=display):
            page.integrity_button.click()
            try:
                self.assertTrue(self.window.busy)
                self.assertFalse(page.integrity_button.isEnabled())
                event = QCloseEvent()
                self.window.closeEvent(event)
                self.assertFalse(event.isAccepted())
            finally:
                gate.set()
            self.wait_job()
        dialog = page.integrity_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(on_main, {"audit": False, "display": True})
        self.assertEqual(dialog.table.rowCount(), 3)
        self.assertIn("一致 1 个，异常 2 个", dialog.summary.text())
        self.assertNotIn("全部材料与归档记录一致", dialog.summary.text())
        self.assertIn("哈希无法重建", dialog.findChild(type(dialog.summary), "integrity_explanation").text())
        self.assertEqual({dialog.table.item(row, 4).text() for row in range(3)}, {"一致", "文件缺失", "内容变化"})
        self.assertIn("已归档", {dialog.table.item(row, 2).text() for row in range(3)})
        self.assertEqual(changed.read_text(encoding="utf-8"), "模拟已变化的受管理文件")
        self.assertEqual(self.errors, [])

    def test_failed_audit_does_not_open_result_or_report_passed(self):
        page = self.window.pages["materials"]
        with patch.object(self.window.materials, "audit_materials", side_effect=OSError("隔离模拟数据库读取失败")):
            page.audit_materials()
            self.wait_job()
        self.assertIsNone(page.integrity_dialog)
        self.assertEqual(self.errors, ["隔离模拟数据库读取失败"])
        self.assertEqual(self.infos, [])
        self.assertNotIn("完成", self.window.statusBar().currentMessage())

    def test_empty_library_is_not_claimed_all_passed_and_text_is_plain(self):
        empty = {"checked_at": "2026-10-17T12:00:00", "total": 0, "passed": 0, "failed": 0, "items": []}
        dialog = self.make_dialog(empty)
        self.assertIn("暂无材料", dialog.summary.text())
        self.assertNotIn("全部材料与归档记录一致", dialog.summary.text())
        self.assertEqual(dialog.table.rowCount(), 0)
        abnormal = self.make_dialog()
        self.assertEqual(abnormal.summary.textFormat(), Qt.PlainText)
        self.assertEqual(abnormal.table.item(0, 0).text(), "<b>丢失材料</b>.txt")

    def test_cancel_report_export_keeps_files_and_does_not_start_worker(self):
        dialog = self.make_dialog()
        before = set(self.base.rglob("*"))
        with patch("app.integrity_dialog.QFileDialog.getSaveFileName", return_value=("", "")), \
                patch.object(self.window.exports, "export_integrity_report") as export:
            dialog.export_report()
        export.assert_not_called()
        self.assertFalse(self.window.busy)
        self.assertFalse(dialog.export_pending)
        self.assertEqual(set(self.base.rglob("*")), before)
        self.assertEqual(dialog.export_result.text(), "尚未导出检查报告。")

    def test_report_export_saves_exact_snapshot_and_blocks_close_while_busy(self):
        dialog = self.make_dialog()
        destination = self.base / "检查结果.json"
        original_export = self.window.exports.export_integrity_report
        gate = threading.Event()
        worker_main = []

        def gated_export(*args):
            worker_main.append(QThread.currentThread() == self.application.thread())
            if not gate.wait(3):
                raise TimeoutError("测试同步等待超时")
            return original_export(*args)

        with patch("app.integrity_dialog.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
                patch.object(self.window.exports, "export_integrity_report", side_effect=gated_export):
            dialog.export_report()
            try:
                self.assertTrue(dialog.export_pending)
                self.assertFalse(dialog.export_button.isEnabled())
                self.assertFalse(dialog.close_button.isEnabled())
                event = QCloseEvent()
                dialog.closeEvent(event)
                self.assertFalse(event.isAccepted())
                dialog.reject()
                self.assertEqual(dialog.result(), 0)
                dialog.accept()
                self.assertEqual(dialog.result(), 0)
            finally:
                gate.set()
            self.wait_job()
        self.assertEqual(worker_main, [False])
        self.assertEqual(json.loads(destination.read_text(encoding="utf-8")), dialog.report)
        self.assertIn("检查报告已保存", dialog.export_result.text())
        self.assertFalse(dialog.export_pending)
        self.assertTrue(dialog.export_button.isEnabled())
        self.assertTrue(dialog.close_button.isEnabled())
        self.assertEqual(self.errors, [])

    def test_report_export_failure_clears_previous_success(self):
        dialog = self.make_dialog()
        dialog.exported(self.base / "上次报告.json")
        destination = self.base / "失败报告.json"
        with patch("app.integrity_dialog.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
                patch.object(self.window.exports, "export_integrity_report", side_effect=OSError("隔离模拟写入失败")):
            dialog.export_report()
            self.wait_job()
        self.assertFalse(destination.exists())
        self.assertIn("未保存", dialog.export_result.text())
        self.assertNotIn("已保存", dialog.export_result.text())
        self.assertEqual(self.errors, ["隔离模拟写入失败"])
        self.assertFalse(dialog.export_pending)
        self.assertTrue(dialog.close_button.isEnabled())

    def test_csv_and_html_failed_exports_clear_old_success_and_open_location(self):
        project_id = self.window.portfolio.save_project({"name": "导出项目"})
        page = self.window.pages["reports"]
        page.refresh()
        page.project.setCurrentIndex(page.project.findData(project_id))
        for label, method, operation, extension in (("CSV", "export_csv", page.export_csv, "csv"),
                                                    ("HTML", "export_html", page.export_html, "html")):
            with self.subTest(label=label):
                page.saved(f"{label} 导出成功", self.base / f"旧文件.{extension}")
                destination = self.base / f"失败文件.{extension}"
                with patch("app.pages.QFileDialog.getSaveFileName", return_value=(str(destination), "")), \
                        patch.object(self.window.exports, method, side_effect=OSError("隔离模拟导出失败")):
                    operation()
                    self.wait_job()
                self.assertIn(f"{label} 导出已开始", page.result.text())
                self.assertNotIn(f"{label} 导出成功", page.result.text())
                self.assertIsNone(page.result_path)
                self.assertFalse(page.open_result_button.isEnabled())
                self.assertFalse(destination.exists())
        self.assertEqual(self.errors, ["隔离模拟导出失败", "隔离模拟导出失败"])

    def test_cancel_csv_and_html_exports_retains_previous_result(self):
        project_id = self.window.portfolio.save_project({"name": "取消导出项目"})
        page = self.window.pages["reports"]
        page.refresh()
        page.project.setCurrentIndex(page.project.findData(project_id))
        old = self.base / "旧成功.json"
        page.saved("上次操作成功", old)
        previous = page.result.text()
        with patch("app.pages.QFileDialog.getSaveFileName", return_value=("", "")), \
                patch.object(self.window.exports, "export_csv") as csv_export, \
                patch.object(self.window.exports, "export_html") as html_export:
            page.export_csv()
            page.export_html()
        csv_export.assert_not_called()
        html_export.assert_not_called()
        self.assertEqual(page.result.text(), previous)
        self.assertEqual(page.result_path, old)
        self.assertTrue(page.open_result_button.isEnabled())


if __name__ == "__main__":
    unittest.main(verbosity=2)
