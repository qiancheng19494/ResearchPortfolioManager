"""主窗口、导航、错误处理与后台任务生命周期。"""
import logging
from pathlib import Path
from PySide6.QtCore import Qt, QUrl, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QFrame, QLabel,
    QPushButton, QStackedWidget, QMessageBox, QProgressBar,
)
from services.portfolio import PortfolioService
from services.materials import MaterialService
from services.export_backup import ExportBackupService
from app.workers import JobThread
from app.dialogs import (
    TaskDialog, ProjectDetailDialog, AchievementDetailDialog,
    ProfileDialog, AboutDialog, named,
)
from app.pages import (
    DashboardPage, ProjectsPage, TasksPage, AchievementsPage,
    MaterialsPage, ReportsPage,
)

APP_NAME = "本科科研项目与成果档案管理系统 V1.1"


class MainWindow(QMainWindow):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.portfolio = PortfolioService(store)
        self.materials = MaterialService(store)
        self.exports = ExportBackupService(store)
        self.busy = False
        self.job = None
        self.last_job_result = None
        self.last_job_error = None
        self._job_success_callback = None
        self.setObjectName("main_window")
        self.setWindowTitle(APP_NAME + (" · 演示数据" if store.config.get("demo") else ""))
        self.resize(1250, 720)
        self.setMinimumSize(1000, 620)
        stylesheet = Path(__file__).resolve().parent.parent / "resources" / "style.qss"
        if stylesheet.is_file():
            self.setStyleSheet(stylesheet.read_text(encoding="utf-8"))
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.sidebar = named(QFrame(), "sidebar")
        self.sidebar.setFixedWidth(190)
        side = QVBoxLayout(self.sidebar)
        side.setContentsMargins(14, 24, 14, 18)
        side.setSpacing(9)
        brand = QLabel("科研档案")
        brand.setObjectName("brand")
        side.addWidget(brand)
        subtitle = QLabel("Research Portfolio\n个人本地资料管理 · V1.1")
        subtitle.setObjectName("brand_subtitle")
        side.addWidget(subtitle)
        side.addSpacing(26)
        self.nav_buttons = {}
        names = [("dashboard", "综合概览"), ("projects", "项目管理"), ("tasks", "任务管理"), ("achievements", "成果台账"), ("materials", "材料归档"), ("reports", "报告与备份")]
        for index, (key, title) in enumerate(names):
            button = named(QPushButton(title), "nav_" + key)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, current=key: self.navigate(current))
            side.addWidget(button)
            self.nav_buttons[key] = button
        side.addStretch()
        self.profile_button = named(QPushButton("个人资料与设置"), "profile_button")
        self.profile_button.clicked.connect(self.profile)
        self.about_button = named(QPushButton("关于软件"), "about_button")
        self.about_button.clicked.connect(lambda: AboutDialog(self).exec())
        side.addWidget(self.profile_button)
        side.addWidget(self.about_button)
        local = QLabel("资料保存在本地\n请定期备份")
        local.setObjectName("brand_subtitle")
        side.addSpacing(10)
        side.addWidget(local)
        outer.addWidget(self.sidebar)
        self.content = QWidget()
        content_layout = QVBoxLayout(self.content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        header = named(QFrame(), "header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(22, 17, 20, 14)
        self.page_title = named(QLabel("综合概览"), "page_title")
        header_layout.addWidget(self.page_title)
        full_title = QLabel(APP_NAME)
        full_title.setObjectName("full_title")
        header_layout.addWidget(full_title)
        content_layout.addWidget(header)
        self.demo_label = named(QLabel("演示数据 · 当前资料仅供功能演示，不代表本人真实履历或成果。"), "demo_banner")
        self.demo_label.setWordWrap(True)
        self.demo_label.setVisible(bool(store.config.get("demo")))
        content_layout.addWidget(self.demo_label)
        self.stack = QStackedWidget()
        self.pages = {
            "dashboard": DashboardPage(self),
            "projects": ProjectsPage(self),
            "tasks": TasksPage(self),
            "achievements": AchievementsPage(self),
            "materials": MaterialsPage(self),
            "reports": ReportsPage(self),
        }
        for page in self.pages.values():
            self.stack.addWidget(page)
        content_layout.addWidget(self.stack, 1)
        outer.addWidget(self.content, 1)
        self.progress = named(QProgressBar(), "job_progress")
        self.progress.setRange(0, 0)
        self.progress.setFixedWidth(150)
        self.progress.hide()
        self.statusBar().addPermanentWidget(self.progress)
        self.location_label = QLabel("资料目录：" + str(store.root))
        self.location_label.setTextFormat(Qt.PlainText)
        self.location_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.location_label.setToolTip(str(store.root))
        self.statusBar().addPermanentWidget(self.location_label, 1)
        self.refresh_all()
        self.navigate("dashboard")

    def navigate(self, key):
        self.stack.setCurrentWidget(self.pages[key])
        for current, button in self.nav_buttons.items():
            button.setChecked(current == key)
        self.page_title.setText(self.nav_buttons[key].text())
        self.pages[key].refresh()

    def refresh_all(self):
        for page in self.pages.values():
            page.refresh()

    def show_error(self, message):
        logging.getLogger(__name__).warning("界面操作失败：%s", message)
        self.statusBar().showMessage("操作失败：" + message, 15000)
        QMessageBox.warning(self, "操作未完成", message)

    def show_info(self, title, message):
        QMessageBox.information(self, title, message)

    def perform(self, function):
        try:
            result = function()
            self.refresh_all()
            self.statusBar().showMessage("操作已保存。", 6000)
            return result
        except Exception as exc:
            logging.getLogger(__name__).exception("业务操作失败")
            self.show_error(str(exc))

    def show_project(self, project_id):
        try:
            ProjectDetailDialog(self, project_id).exec()
            self.refresh_all()
        except Exception as exc:
            self.show_error(str(exc))

    def show_task(self, task_id):
        try:
            if TaskDialog(self, self.portfolio.get_task(task_id)).exec():
                self.refresh_all()
        except Exception as exc:
            self.show_error(str(exc))

    def show_achievement(self, achievement_id):
        try:
            AchievementDetailDialog(self, achievement_id).exec()
        except Exception as exc:
            self.show_error(str(exc))

    def open_material(self, material_id, folder=False):
        # 校验、复制在工作线程执行；成功回调由 Qt 主线程调用关联程序。
        def open_preview(path):
            target = path.parent if folder else path
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
                self.show_error("系统没有可用的关联程序，未能打开预览文件或目录。")
                return
            self.statusBar().showMessage(
                "已打开独立预览副本。保留修改请另存，再通过“导入新版本”归档；原归档副本保持不变。", 20000)
        self.run_job("正在校验归档材料并复制独立预览…",
                     lambda: self.materials.prepare_preview(material_id), open_preview)

    def profile(self):
        if ProfileDialog(self).exec():
            self.refresh_all()
            self.statusBar().showMessage("个人资料与设置已保存。", 6000)

    def run_job(self, label, function, on_success=None):
        if self.busy:
            self.show_error("已有后台操作正在进行，请等待完成。")
            return
        self.busy = True
        self.last_job_result = None
        self.last_job_error = None
        self.stack.setEnabled(False)
        self.sidebar.setEnabled(False)
        self.progress.show()
        self.statusBar().showMessage(label)
        self.job = JobThread(function, self)
        self._job_success_callback = on_success
        self.job.succeeded.connect(self.job_succeeded, Qt.QueuedConnection)
        self.job.failed.connect(self.job_failed, Qt.QueuedConnection)
        self.job.finished.connect(self.job_finished, Qt.QueuedConnection)
        self.job.start()

    @Slot(object)
    def job_succeeded(self, result):
        self.last_job_result = result
        callback = self._job_success_callback
        try:
            self.refresh_all()
            self.statusBar().showMessage("后台操作完成。", 8000)
            if callback:
                callback(result)
        except Exception as exc:
            logging.getLogger(__name__).exception("后台操作后的界面刷新失败")
            self.show_error(f"操作已完成，但结果显示失败：{exc}")

    @Slot(str)
    def job_failed(self, error):
        self.last_job_error = error
        self.show_error(error)

    @Slot()
    def job_finished(self):
        self.busy = False
        self.stack.setEnabled(True)
        self.sidebar.setEnabled(True)
        self.progress.hide()
        thread = self.job
        self.job = None
        self._job_success_callback = None
        if thread:
            thread.deleteLater()

    def material_imported(self, material_id):
        record = self.materials.get_material(material_id)
        self.show_info("材料归档成功", f"{record['original_name']}\n版本：{record['version_label']}\n材料副本已保存并记录 SHA-256。原文件保留。")

    def closeEvent(self, event):
        if self.busy:
            self.show_info("操作正在进行", "正在处理材料或备份，请等待操作结束后再关闭软件。")
            event.ignore()
        else:
            event.accept()
