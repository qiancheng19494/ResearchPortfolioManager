"""Native Windows Qt interaction test; user data is never opened by this suite."""
import csv
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt, QTimer, QThread
from PySide6.QtGui import QFont
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QComboBox, QTextEdit, QMessageBox, QPushButton

from database.store import Store
from services.portfolio import PortfolioService
from services.materials import MaterialService
from app.main_window import MainWindow


class NativeGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setFont(QFont("Microsoft YaHei UI", 10))
        cls.screenshot_dir = Path(__file__).resolve().parents[1] / "docs" / "screenshots"
        cls.screenshot_dir.mkdir(parents=True, exist_ok=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="GUI 科研 中文 ")
        self.base = Path(self.temp.name)
        self.store = Store(self.base / "测试资料")
        self.store.save_config(dict(self.store.config, demo=True))
        self.window = MainWindow(self.store)
        self.window.resize(1366, 768)
        self.window.show()
        self.assertTrue(QTest.qWaitForWindowExposed(self.window, 5000), "Qt 主窗口没有实际显示")
        QTest.qWait(120)
        self.messages = []
        self.errors = []
        self.info_patch = patch.object(self.window, "show_info", side_effect=lambda *args: self.messages.append(args))
        self.error_patch = patch.object(self.window, "show_error", side_effect=lambda *args: self.errors.append(args))
        self.info_patch.start()
        self.error_patch.start()

    def tearDown(self):
        self.info_patch.stop()
        self.error_patch.stop()
        self.window.close()
        self.application.processEvents()
        self.window.deleteLater()
        QTest.qWait(40)
        self.temp.cleanup()

    def click(self, control):
        self.assertTrue(control.isEnabled(), control.objectName() + " 未启用")
        self.assertTrue(control.isVisible(), control.objectName() + " 不可见")
        QTest.mouseClick(control, Qt.LeftButton)
        self.application.processEvents()

    def navigate(self, key):
        self.click(self.window.findChild(QPushButton, "nav_" + key))
        QTest.qWait(30)
        page = self.window.pages[key]
        self.assertTrue(page.isVisible())
        return page

    def fill_field(self, field, value):
        if isinstance(field, QComboBox):
            index = field.findData(value)
            if index < 0:
                index = field.findText(str(value))
            self.assertGreaterEqual(index, 0, f"未找到表单选项 {value!r}")
            field.setCurrentIndex(index)
        elif isinstance(field, QTextEdit):
            field.setPlainText(str(value))
        else:
            field.setText(str(value))

    def form_action(self, control, fields, extra=None):
        callback_errors = []

        def operate():
            dialog = QApplication.activeModalWidget()
            try:
                self.assertIsInstance(dialog, QDialog)
                for key, value in fields.items():
                    self.fill_field(dialog.fields[key], value)
                if extra:
                    extra(dialog)
                self.click(dialog.save_button)
            except BaseException as exc:
                callback_errors.append(exc)
                if isinstance(dialog, QDialog):
                    dialog.reject()

        QTimer.singleShot(40, operate)
        self.click(control)
        if callback_errors:
            raise callback_errors[0]
        self.assertEqual(self.errors, [], f"界面报告错误：{self.errors}")

    def close_detail(self, control):
        opened = []
        def close():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QDialog):
                opened.append(dialog.windowTitle())
                dialog.reject()
        QTimer.singleShot(60, close)
        self.click(control)
        self.assertTrue(opened, "详情或关于弹窗没有实际打开")

    def select_row(self, page, row=0):
        self.assertGreater(page.table.rowCount(), row)
        item = page.table.item(row, 0)
        page.table.scrollToItem(item)
        QTest.mouseClick(page.table.viewport(), Qt.LeftButton, pos=page.table.visualItemRect(item).center())
        self.application.processEvents()
        self.assertIsNotNone(page.selected())

    def wait_job(self):
        until = time.monotonic() + 20
        while self.window.busy and time.monotonic() < until:
            QTest.qWait(30)
        self.assertFalse(self.window.busy, "后台操作未在限定时间完成")
        QTest.qWait(60)
        self.assertEqual(self.errors, [])
        self.assertFalse(self.window.last_job_error)

    def screenshot(self, name):
        # V1.0 screenshots are historical; current V1.1 evidence has separate names.
        return

    def test_native_six_pages_actions_end_to_end(self):
        self.assertEqual(self.application.platformName(), "windows", "此项必须由原生 Windows Qt 平台运行")
        self.assertEqual((self.window.width(), self.window.height()), (1366, 768))
        self.screenshot("00-empty-dashboard.png")
        for key in ("dashboard", "projects", "tasks", "achievements", "materials", "reports"):
            self.navigate(key)

        projects = self.navigate("projects")
        self.form_action(projects.new_button, {
            "name": "【演示】GUI 完整流程", "category": "研究", "description": "由 GUI 测试创建的隔离演示资料",
            "start_date": "2026-10-01", "end_date": "2026-12-01", "status": "进行中"})
        self.assertEqual(len(self.window.portfolio.list_projects()), 1)
        pid = self.window.portfolio.list_projects()[0]["id"]
        self.select_row(projects)
        self.form_action(projects.edit_button, {"notes": "经 GUI 编辑保存"})
        self.assertEqual(self.window.portfolio.get_project(pid)["notes"], "经 GUI 编辑保存")
        projects.search.setText("不存在")
        self.click(projects.search_button)
        self.assertEqual(projects.table.rowCount(), 0)
        projects.search.setText("完整流程")
        self.click(projects.search_button)
        self.assertEqual(projects.table.rowCount(), 1)
        self.select_row(projects)
        self.close_detail(projects.detail_button)
        self.screenshot("01-projects.png")

        tasks = self.navigate("tasks")
        self.form_action(tasks.new_button, {"project_id": pid, "title": "【演示】GUI 添加任务", "due_date": "2026-10-10"})
        tid = self.window.portfolio.list_tasks()[0]["id"]
        self.select_row(tasks)
        self.form_action(tasks.edit_button, {"description": "任务编辑验证", "status": "进行中"})
        self.assertEqual(self.window.portfolio.get_task(tid)["status"], "进行中")
        self.screenshot("02-tasks.png")

        achievements = self.navigate("achievements")
        self.form_action(achievements.new_button, {"project_id": pid, "name": "【演示】GUI 成果", "type": "论文",
                                                 "status": "已投稿", "related_date": "2026-10-10", "notes": "示例状态不代表真实履历"})
        aid = self.window.portfolio.list_achievements()[0]["id"]
        self.select_row(achievements)

        def check_status(dialog):
            self.assertEqual(dialog.fields["status"].currentData(), "准备中")
            self.assertEqual(dialog.fields["status"].findData("已投稿"), -1)
        self.form_action(achievements.edit_button, {"type": "软件著作权"}, extra=check_status)
        self.assertEqual(self.window.portfolio.get_achievement(aid)["type"], "软件著作权")
        achievements.search.setText("GUI")
        self.click(achievements.search_button)
        self.assertEqual(achievements.table.rowCount(), 1)
        self.select_row(achievements)
        self.close_detail(achievements.detail_button)
        self.screenshot("03-achievements.png")

        source1 = self.base / "源 一" / "同名 演示.txt"
        source2 = self.base / "源 二" / source1.name
        for source, content in ((source1, "GUI 第一版"), (source2, "GUI 第二版")):
            source.parent.mkdir()
            source.write_text(content, encoding="utf-8")
        materials = self.navigate("materials")
        self.form_action(materials.new_button, {"source": str(source1), "project_id": pid, "achievement_id": aid,
                                               "category": "证明材料", "version_label": "V1"})
        self.wait_job()
        self.select_row(materials)
        self.form_action(materials.version_button, {"source": str(source2), "version_label": "V2"})
        self.wait_job()
        self.assertEqual(materials.table.rowCount(), 2)
        self.assertEqual(source1.read_text(encoding="utf-8"), "GUI 第一版")
        self.assertEqual(source2.read_text(encoding="utf-8"), "GUI 第二版")
        for record in self.window.materials.list_materials():
            self.assertTrue(self.window.materials.file_path(record["id"], verify=True).is_file())
        self.select_row(materials)
        self.click(materials.verify_button)
        self.wait_job()
        with patch("app.main_window.QDesktopServices.openUrl", return_value=True) as opener:
            self.click(materials.open_button)
            self.wait_job()
            self.assertTrue(opener.called)
            opened = Path(opener.call_args.args[0].toLocalFile())
            self.assertTrue(opened.is_relative_to(self.store.root / "preview_cache"))
            opened.write_text("模拟外部应用编辑预览", encoding="utf-8")
            for record in self.window.materials.list_materials():
                self.assertTrue(self.window.materials.file_path(record["id"], verify=True).is_file())
        self.screenshot("04-materials.png")

        projects = self.navigate("projects")
        self.select_row(projects)
        with patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(projects.archive_button)
        self.assertTrue(self.window.portfolio.get_project(pid)["archived"])
        self.assertEqual(projects.table.rowCount(), 0)
        self.click(projects.archived)
        self.select_row(projects)
        self.assertFalse(projects.edit_button.isEnabled())
        with patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(projects.archive_button)
        self.assertFalse(self.window.portfolio.get_project(pid)["archived"])

        reports = self.navigate("reports")
        self.fill_field(reports.project, pid)
        self.fill_field(reports.type, "软件著作权")
        self.fill_field(reports.status, "准备中")
        csv_path = self.base / "导出 台账.csv"
        html_path = self.base / "导出 摘要.html"
        backup = self.base / "GUI 完整备份.zip"
        for button, path in ((reports.csv_button, csv_path), (reports.html_button, html_path), (reports.backup_button, backup)):
            with patch("app.pages.QFileDialog.getSaveFileName", return_value=(str(path), "")):
                self.click(button)
            self.wait_job()
            self.assertTrue(path.is_file())
            self.assertIn(str(path), reports.result.text())
        with csv_path.open(encoding="utf-8-sig", newline="") as file:
            self.assertEqual(len(list(csv.reader(file))), 2)
        self.assertIn("GUI 成果", html_path.read_text(encoding="utf-8"))
        target = self.base / "GUI 恢复目录"
        target.mkdir()
        with patch("app.pages.QFileDialog.getOpenFileName", return_value=(str(backup), "")), \
                patch("app.pages.QFileDialog.getExistingDirectory", return_value=str(target)), \
                patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(reports.restore_button)
        self.wait_job()
        restored = Store(target)
        self.assertEqual(len(PortfolioService(restored).list_projects()), 1)
        self.assertEqual(len(MaterialService(restored).list_materials()), 2)
        for material in MaterialService(restored).list_materials():
            self.assertTrue(MaterialService(restored).file_path(material["id"], verify=True).is_file())
        self.assertIn("恢复", reports.result.text())
        self.screenshot("05-reports.png")
        self.navigate("dashboard")
        self.screenshot("06-dashboard.png")
        self.assertEqual(self.errors, [])

    def test_native_settings_delete_unlink_details_and_missing_file(self):
        pid = self.window.portfolio.save_project(dict(name="【演示】补充操作项目", category="研究", status="进行中"))
        tid = self.window.portfolio.save_task(dict(project_id=pid, title="【演示】可删除任务", status="待办"))
        aid = self.window.portfolio.save_achievement(dict(project_id=pid, name="【演示】可解除材料关联成果",
                                                        type="其他成果", status="准备中"))
        source = self.base / "补充演示.txt"
        source.write_text("独立临时演示附件", encoding="utf-8")
        mid = self.window.materials.import_file(source, pid, aid)
        self.window.refresh_all()
        self.form_action(self.window.profile_button, {"name": "测试姓名", "background": "测试背景", "interests": "测试兴趣"})
        self.assertEqual(Store(self.store.root).config["name"], "测试姓名")
        self.close_detail(self.window.about_button)

        dashboard = self.navigate("dashboard")
        table = dashboard.tables["recent_projects"]
        opened = []
        def close_dashboard_detail():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, QDialog):
                opened.append(dialog.windowTitle())
                dialog.reject()
        QTimer.singleShot(60, close_dashboard_detail)
        QTest.mouseClick(table.viewport(), Qt.LeftButton, pos=table.visualItemRect(table.item(0, 0)).center())
        self.application.processEvents()
        self.assertTrue(opened, "概览单击项目没有实际打开详情")

        tasks = self.navigate("tasks")
        tasks.search.setText("可删除")
        self.click(tasks.search_button)
        self.select_row(tasks)
        with patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(tasks.delete_button)
        self.assertEqual(self.window.portfolio.list_tasks(), [])
        self.assertTrue(self.window.portfolio.get_project(pid))

        achievements = self.navigate("achievements")
        self.select_row(achievements)
        with patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(achievements.delete_button)
        self.assertTrue(self.errors)
        self.assertIn("关联材料", self.errors[-1][0])
        self.errors.clear()
        self.assertEqual(len(self.window.portfolio.list_achievements()), 1)

        materials = self.navigate("materials")
        self.select_row(materials)
        self.form_action(materials.edit_button, {"achievement_id": None, "notes": "通过 GUI 解除成果关联"})
        self.assertIsNone(self.window.materials.get_material(mid)["achievement_id"])
        self.assertTrue(self.window.materials.file_path(mid, verify=True).is_file())
        achievements = self.navigate("achievements")
        self.select_row(achievements)
        with patch("app.pages.QMessageBox.question", return_value=QMessageBox.Yes):
            self.click(achievements.delete_button)
        self.assertEqual(self.window.portfolio.list_achievements(), [])
        self.assertEqual(len(self.window.materials.list_materials()), 1)

        materials = self.navigate("materials")
        self.select_row(materials)
        self.window.materials.file_path(mid).unlink()
        self.click(materials.open_button)
        until = time.monotonic() + 20
        while self.window.busy and time.monotonic() < until:
            QTest.qWait(30)
        self.assertFalse(self.window.busy, "材料校验后台任务未完成")
        self.assertTrue(self.errors)
        self.assertIn("缺失", self.errors[-1][0])
        self.errors.clear()
        self.assertTrue(self.window.isVisible())
        self.assertEqual(self.errors, [])

    def test_background_completion_main_thread_and_failure_recovery(self):
        observed = []
        self.window.run_job("测试后台任务", lambda: 42,
                            lambda result: observed.append((result, QThread.currentThread() == self.application.thread())))
        self.assertTrue(self.window.busy)
        self.assertFalse(self.window.stack.isEnabled())
        self.wait_job()
        self.assertEqual(observed, [(42, True)])
        self.assertTrue(self.window.stack.isEnabled())
        self.assertTrue(self.window.sidebar.isEnabled())
        def failing_job():
            raise ValueError("后台失败测试")
        self.window.run_job("测试失败处理", failing_job)
        until = time.monotonic() + 10
        while self.window.busy and time.monotonic() < until:
            QTest.qWait(30)
        self.assertFalse(self.window.busy)
        self.assertIn("后台失败测试", self.window.last_job_error)
        self.assertTrue(self.errors)
        self.assertTrue(self.window.stack.isEnabled())
        self.assertTrue(self.window.sidebar.isEnabled())
        self.errors.clear()


if __name__ == "__main__":
    unittest.main(verbosity=2)
