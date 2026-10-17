"""六个导航页面及其实际业务操作。"""
from datetime import date
from pathlib import Path
from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QLineEdit,
    QPushButton, QComboBox, QCheckBox, QTableWidget, QTableWidgetItem,
    QAbstractItemView, QHeaderView, QMessageBox, QFileDialog, QGroupBox,
    QScrollArea,
)
from services.portfolio import PROJECT_CATEGORIES, PROJECT_STATUSES, TASK_STATUSES, TASK_DUE_FILTERS, ACHIEVEMENT_STATUSES
from app.dialogs import (
    ProjectDialog, TaskDialog, AchievementDialog, MaterialDialog, named,
)
from runtime_paths import restore_launch_command
from app.date_field import NullableDateField
from app.integrity_dialog import MaterialIntegrityDialog


def filter_combo(label, values=()):
    control = QComboBox()
    control.addItem(label, "")
    for value in values:
        control.addItem(value, value)
    return control


def populate_projects(control, owner):
    selected = control.currentData()
    control.blockSignals(True)
    control.clear()
    control.addItem("全部项目", None)
    for row in owner.portfolio.list_projects(include_archived=True):
        control.addItem(row["name"] + ("（已归档）" if row["archived"] else ""), row["id"])
    index = control.findData(selected)
    control.setCurrentIndex(max(0, index))
    control.blockSignals(False)


def fill_table(table, records, columns):
    selected = None
    if table.currentRow() >= 0 and table.item(table.currentRow(), 0):
        selected = table.item(table.currentRow(), 0).data(Qt.UserRole).get("id")
    table.setSortingEnabled(False)
    table.setRowCount(len(records))
    for row, record in enumerate(records):
        for col, (key, label) in enumerate(columns):
            raw = record.get(key)
            if key == "archived":
                raw = "已归档" if raw else "活跃"
            if key == "size":
                raw = (f"{raw} B" if raw < 1024 else f"{raw / 1024:.1f} KB") if raw is not None else ""
            item = QTableWidgetItem(str(raw) if raw not in (None, "") else "—")
            item.setData(Qt.UserRole, record)
            item.setToolTip(str(raw) if raw is not None else "")
            table.setItem(row, col, item)
        if record.get("id") == selected:
            table.selectRow(row)
    table.setSortingEnabled(True)


def make_table(columns, name):
    table = named(QTableWidget(0, len(columns)), name)
    table.setHorizontalHeaderLabels([label for key, label in columns])
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setAlternatingRowColors(True)
    table.verticalHeader().hide()
    table.verticalHeader().setDefaultSectionSize(35)
    table.horizontalHeader().setStretchLastSection(True)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
    for index in range(len(columns)):
        table.setColumnWidth(index, 120)
    table.setColumnWidth(0, 260)
    return table


class ListPage(QWidget):
    def __init__(self, owner, key, description, columns):
        super().__init__()
        self.owner, self.key, self.columns = owner, key, columns
        self.setObjectName(key + "_page")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(20, 12, 20, 16)
        self.layout.setSpacing(12)
        label = QLabel(description)
        label.setWordWrap(True)
        label.setObjectName("page_description")
        self.layout.addWidget(label)
        self.filters = QHBoxLayout()
        self.search = named(QLineEdit(), key + "_search")
        self.search.setPlaceholderText("输入关键词检索")
        self.filters.addWidget(self.search, 2)
        self.layout.addLayout(self.filters)
        self.actions = QHBoxLayout()
        self.layout.addLayout(self.actions)
        self.table = make_table(columns, key + "_table")
        self.layout.addWidget(self.table, 1)
        self.empty = QLabel()
        self.empty.setObjectName(key + "_empty")
        self.layout.addWidget(self.empty)
        self.table.itemSelectionChanged.connect(self.update_actions)
        self.search.returnPressed.connect(self.refresh)

    def add_action(self, label, key, callback):
        button = named(QPushButton(label), self.key + "_" + key)
        button.clicked.connect(callback)
        self.actions.addWidget(button)
        return button

    def add_filter_button(self):
        self.search_button = named(QPushButton("检索"), self.key + "_search_button")
        self.filters.addWidget(self.search_button)
        self.search_button.clicked.connect(self.refresh)
        self.reset_button = named(QPushButton("重置"), self.key + "_reset")
        self.filters.addWidget(self.reset_button)
        self.reset_button.clicked.connect(self.reset)

    def selected(self):
        row = self.table.currentRow()
        if row >= 0 and self.table.item(row, 0):
            return self.table.item(row, 0).data(Qt.UserRole)
        return None

    def show_rows(self, records):
        fill_table(self.table, records, self.columns)
        self.empty.setText(f"共 {len(records)} 条记录。双击行可查看详情。" if records else "当前条件下没有记录。可新建记录，或调整筛选条件。")
        self.update_actions()

    def run_dialog(self, dialog):
        if dialog.exec():
            self.owner.refresh_all()

    def update_actions(self):
        pass


class ProjectsPage(ListPage):
    def __init__(self, owner):
        super().__init__(owner, "projects", "管理项目与关联档案。归档保留全部记录，归档期间只能查看；恢复后可继续编辑。", [("name", "项目名称"), ("category", "类别"), ("status", "状态"), ("leader", "负责人"), ("end_date", "计划结束"), ("archived", "归档标记"), ("updated_at", "更新时间")])
        self.category = named(filter_combo("全部类别", PROJECT_CATEGORIES), "projects_category")
        self.status = named(filter_combo("全部状态", PROJECT_STATUSES), "projects_status")
        self.archived = named(QCheckBox("包含已归档"), "projects_include_archived")
        for control in (self.category, self.status, self.archived):
            self.filters.addWidget(control)
        self.category.currentIndexChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.archived.toggled.connect(self.refresh)
        self.add_filter_button()
        self.new_button = self.add_action("新建项目", "new", self.new)
        self.edit_button = self.add_action("编辑", "edit", self.edit)
        self.detail_button = self.add_action("查看关联详情", "detail", self.detail)
        self.archive_button = self.add_action("归档项目", "archive", self.archive)
        self.actions.addStretch()
        self.table.cellDoubleClicked.connect(lambda *_: self.detail())

    def refresh(self):
        self.show_rows(self.owner.portfolio.list_projects(self.search.text().strip(), self.category.currentData(), self.status.currentData(), self.archived.isChecked()))

    def reset(self):
        self.search.clear()
        self.category.setCurrentIndex(0)
        self.status.setCurrentIndex(0)
        self.archived.setChecked(False)
        self.refresh()

    def update_actions(self):
        row = self.selected()
        if hasattr(self, "edit_button"):
            self.edit_button.setEnabled(bool(row and not row["archived"]))
            self.detail_button.setEnabled(bool(row))
            self.archive_button.setEnabled(bool(row))
            self.archive_button.setText("恢复项目" if row and row["archived"] else "归档项目")

    def new(self):
        self.run_dialog(ProjectDialog(self.owner))

    def edit(self):
        row = self.selected()
        if row:
            self.run_dialog(ProjectDialog(self.owner, self.owner.portfolio.get_project(row["id"])))

    def detail(self):
        row = self.selected()
        if row:
            self.owner.show_project(row["id"])

    def archive(self):
        row = self.selected()
        if not row:
            return
        restoring = bool(row["archived"])
        action = "恢复" if restoring else "归档"
        message = f"确定{action}项目“{row['name']}”？\n" + ("恢复后可继续编辑关联记录。" if restoring else "全部任务、成果和材料将保留，并进入只读状态；任务不再进入活跃提醒统计。")
        if QMessageBox.question(self, action + "项目", message, QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.owner.perform(lambda: self.owner.portfolio.archive_project(row["id"], not restoring))


class TasksPage(ListPage):
    def __init__(self, owner):
        super().__init__(owner, "tasks", "截止日期可留空。到期快捷筛选仅显示未完成、未归档项目中有截止日期的任务；未来七天为明日至第七天。选择“全部到期情况”可查看全部记录。", [("title", "任务标题"), ("project_name", "所属项目"), ("due_date", "截止日期"), ("priority", "优先级"), ("status", "状态"), ("reminder", "提醒"), ("completed_at", "完成时间")])
        self.project = named(QComboBox(), "tasks_project")
        self.status = named(filter_combo("全部状态", TASK_STATUSES), "tasks_status")
        self.due_filter = named(QComboBox(), "tasks_due_filter")
        self.due_filter.addItem("全部到期情况", "")
        for value, label in TASK_DUE_FILTERS.items():
            self.due_filter.addItem(label, value)
        self.due_filter.setToolTip("仅今天到期、已逾期和未来七天筛选排除已完成、归档项目及无截止日期任务；可叠加关键词、项目和状态。")
        self.filters.addWidget(self.project, 1)
        self.filters.addWidget(self.status)
        self.filters.addWidget(self.due_filter)
        self.add_filter_button()
        self.project.currentIndexChanged.connect(self.refresh)
        self.status.currentIndexChanged.connect(self.refresh)
        self.due_filter.currentIndexChanged.connect(self.refresh)
        self.new_button = self.add_action("新增任务", "new", self.new)
        self.edit_button = self.add_action("编辑 / 查看", "edit", self.edit)
        self.delete_button = self.add_action("删除任务", "delete", self.delete)
        self.actions.addStretch()
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())

    def refresh(self):
        populate_projects(self.project, self.owner)
        records = self.owner.portfolio.list_tasks(keyword=self.search.text().strip(), project_id=self.project.currentData(), status=self.status.currentData(), due_filter=self.due_filter.currentData())
        today = date.today().isoformat()
        for row in records:
            row["reminder"] = ""
            if row.get("project_archived"):
                row["reminder"] = "项目已归档"
            elif row["status"] != "已完成" and row["due_date"]:
                row["reminder"] = "已逾期" if row["due_date"] < today else ("今天到期" if row["due_date"] == today else "")
        self.show_rows(records)

    def reset(self):
        self.search.clear()
        self.project.setCurrentIndex(0)
        self.status.setCurrentIndex(0)
        self.due_filter.setCurrentIndex(0)
        self.refresh()

    def update_actions(self):
        row = self.selected()
        if hasattr(self, "edit_button"):
            selected_project = self.project.currentData()
            self.new_button.setEnabled(selected_project is None or not self.owner.portfolio.get_project(selected_project)["archived"])
            self.edit_button.setEnabled(bool(row))
            self.delete_button.setEnabled(bool(row and not row.get("project_archived")))

    def new(self):
        self.run_dialog(TaskDialog(self.owner, project_id=self.project.currentData()))

    def edit(self):
        row = self.selected()
        if row:
            self.owner.show_task(row["id"])

    def delete(self):
        row = self.selected()
        if row and QMessageBox.question(self, "删除任务", f"确定删除任务“{row['title']}”？\n只删除该任务，不影响项目及其他记录。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.owner.perform(lambda: self.owner.portfolio.delete_task(row["id"]))


class AchievementsPage(ListPage):
    def __init__(self, owner):
        super().__init__(owner, "achievements", "按真实资料登记成果。状态由本人依据事实选择，软件不自动认定成果真实性。删除前请先解除关联材料。", [("name", "成果名称"), ("project_name", "所属项目"), ("type", "类型"), ("status", "事实状态"), ("related_date", "相关日期"), ("reference", "编号或链接")])
        self.project = named(QComboBox(), "achievements_project")
        self.type = named(filter_combo("全部类型", ACHIEVEMENT_STATUSES.keys()), "achievements_type")
        self.status = named(filter_combo("全部状态"), "achievements_status")
        self.filters.addWidget(self.project, 1)
        self.filters.addWidget(self.type)
        self.filters.addWidget(self.status)
        self.add_filter_button()
        date_row = QHBoxLayout()
        date_row.addWidget(QLabel("相关日期范围"))
        self.date_from = named(NullableDateField(), "achievements_date_from")
        self.date_to = named(NullableDateField(), "achievements_date_to")
        self.date_from.setPlaceholderText("起始 YYYY-MM-DD，可留空")
        self.date_to.setPlaceholderText("结束 YYYY-MM-DD，可留空")
        date_row.addWidget(self.date_from)
        date_row.addWidget(QLabel("至"))
        date_row.addWidget(self.date_to)
        date_row.addStretch()
        self.layout.insertLayout(2, date_row)
        self.project.currentIndexChanged.connect(self.refresh)
        self.type.currentIndexChanged.connect(self.type_changed)
        self.status.currentIndexChanged.connect(self.refresh)
        self.date_from.returnPressed.connect(self.refresh)
        self.date_to.returnPressed.connect(self.refresh)
        self.type_changed()
        self.new_button = self.add_action("登记成果", "new", self.new)
        self.edit_button = self.add_action("编辑 / 查看", "edit", self.edit)
        self.detail_button = self.add_action("查看证明材料", "detail", self.detail)
        self.delete_button = self.add_action("删除成果", "delete", self.delete)
        self.actions.addStretch()
        self.table.cellDoubleClicked.connect(lambda *_: self.detail())

    def type_changed(self):
        selected = self.status.currentData()
        values = ACHIEVEMENT_STATUSES.get(self.type.currentData(), sorted({status for group in ACHIEVEMENT_STATUSES.values() for status in group}))
        self.status.blockSignals(True)
        self.status.clear()
        self.status.addItem("全部状态", "")
        for value in values:
            self.status.addItem(value, value)
        self.status.setCurrentIndex(max(0, self.status.findData(selected)))
        self.status.blockSignals(False)
        if hasattr(self, "date_from"):
            self.refresh()

    def refresh(self):
        populate_projects(self.project, self.owner)
        try:
            records = self.owner.portfolio.list_achievements(keyword=self.search.text().strip(), project_id=self.project.currentData(), type=self.type.currentData(), status=self.status.currentData(), date_from=self.date_from.text().strip(), date_to=self.date_to.text().strip())
        except Exception as exc:
            self.owner.show_error(str(exc))
            return
        self.show_rows(records)

    def reset(self):
        self.search.clear()
        self.date_from.clear()
        self.date_to.clear()
        self.project.setCurrentIndex(0)
        self.type.setCurrentIndex(0)
        self.status.setCurrentIndex(0)
        self.refresh()

    def update_actions(self):
        row = self.selected()
        if hasattr(self, "edit_button"):
            selected_project = self.project.currentData()
            self.new_button.setEnabled(selected_project is None or not self.owner.portfolio.get_project(selected_project)["archived"])
            self.edit_button.setEnabled(bool(row))
            self.detail_button.setEnabled(bool(row))
            self.delete_button.setEnabled(bool(row and not row.get("project_archived")))

    def new(self):
        self.run_dialog(AchievementDialog(self.owner, project_id=self.project.currentData()))

    def edit(self):
        row = self.selected()
        if row:
            self.run_dialog(AchievementDialog(self.owner, self.owner.portfolio.get_achievement(row["id"])))

    def detail(self):
        row = self.selected()
        if row:
            self.owner.show_achievement(row["id"])

    def delete(self):
        row = self.selected()
        if row and QMessageBox.question(self, "删除成果", f"确定删除成果“{row['name']}”？\n有关联材料时须先在材料归档页解除成果关联，材料文件不会被删除。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) == QMessageBox.Yes:
            self.owner.perform(lambda: self.owner.portfolio.delete_achievement(row["id"]))


class MaterialsPage(ListPage):
    def __init__(self, owner):
        super().__init__(owner, "materials", "每个版本独立归档，原文件保留。打开前校验并复制独立预览；保留修改请另存，再导入新版本。归档项目的材料信息只读。", [("original_name", "原文件名"), ("project_name", "所属项目"), ("achievement_name", "关联成果"), ("category", "材料类别"), ("version_label", "版本"), ("size", "大小"), ("imported_at", "导入时间")])
        self.project = named(QComboBox(), "materials_project")
        self.achievement = named(QComboBox(), "materials_achievement")
        self.achievement.addItem("全部成果", None)
        self.category = named(QLineEdit(), "materials_category")
        self.category.setPlaceholderText("材料类别，可留空")
        self.category.setMaximumWidth(160)
        self.filters.addWidget(self.project, 1)
        self.filters.addWidget(self.achievement, 1)
        self.filters.addWidget(self.category)
        self.add_filter_button()
        self.project.currentIndexChanged.connect(self.project_changed)
        self.achievement.currentIndexChanged.connect(self.refresh)
        self.category.returnPressed.connect(self.refresh)
        self.new_button = self.add_action("导入材料", "new", self.new)
        self.version_button = self.add_action("导入新版本", "version", self.version)
        self.edit_button = self.add_action("编辑信息 / 解除成果关联", "edit", self.edit)
        self.open_button = self.add_action("打开预览副本", "open", self.open)
        self.folder_button = self.add_action("打开预览目录", "folder", self.folder)
        for button in (self.open_button, self.folder_button):
            button.setToolTip("后台校验归档材料并复制到独立预览目录；修改后请另存，再通过“导入新版本”归档。预览缓存不进入备份。")
        self.verify_button = self.add_action("校验 SHA-256", "verify", self.verify)
        self.actions.addStretch()
        audit_actions = QHBoxLayout()
        self.integrity_button = named(QPushButton("检查全部材料…"), "materials_integrity")
        self.integrity_button.setToolTip("后台检查所有材料版本的大小和 SHA-256，包括已归档项目；不修改文件或旧哈希。")
        self.integrity_button.clicked.connect(self.audit_materials)
        audit_actions.addWidget(self.integrity_button)
        audit_actions.addWidget(QLabel("检查全部版本（含归档项目），不受当前筛选影响。"))
        audit_actions.addStretch()
        self.layout.insertLayout(3, audit_actions)
        self.integrity_dialog = None
        self.table.cellDoubleClicked.connect(lambda *_: self.edit())

    def project_changed(self):
        self.update_achievements()
        self.refresh()

    def update_achievements(self):
        selected = self.achievement.currentData()
        self.achievement.blockSignals(True)
        self.achievement.clear()
        self.achievement.addItem("全部成果", None)
        for row in self.owner.portfolio.list_achievements(project_id=self.project.currentData()):
            self.achievement.addItem(row["name"], row["id"])
        self.achievement.setCurrentIndex(max(0, self.achievement.findData(selected)))
        self.achievement.blockSignals(False)

    def refresh(self):
        populate_projects(self.project, self.owner)
        self.update_achievements()
        self.show_rows(self.owner.materials.list_materials(keyword=self.search.text().strip(), project_id=self.project.currentData(), achievement_id=self.achievement.currentData(), category=self.category.text().strip()))

    def reset(self):
        self.search.clear()
        self.category.clear()
        self.project.setCurrentIndex(0)
        self.achievement.setCurrentIndex(0)
        self.refresh()

    def update_actions(self):
        row = self.selected()
        if hasattr(self, "edit_button"):
            active = bool(row and not row.get("project_archived"))
            self.edit_button.setEnabled(bool(row))
            self.version_button.setEnabled(active)
            for button in (self.open_button, self.folder_button, self.verify_button):
                button.setEnabled(bool(row))

    def new(self):
        self.run_dialog(MaterialDialog(self.owner))

    def version(self):
        row = self.selected()
        if row:
            self.run_dialog(MaterialDialog(self.owner, version_of=row))

    def edit(self):
        row = self.selected()
        if row:
            self.run_dialog(MaterialDialog(self.owner, self.owner.materials.get_material(row["id"])))

    def open(self):
        row = self.selected()
        if row:
            self.owner.open_material(row["id"])

    def folder(self):
        row = self.selected()
        if row:
            self.owner.open_material(row["id"], folder=True)

    def verify(self):
        row = self.selected()
        if row:
            self.owner.run_job("正在校验材料 SHA-256…", lambda: self.owner.materials.file_path(row["id"], verify=True), lambda path: self.owner.show_info("材料校验通过", f"SHA-256 与归档记录一致。\n{path}"))

    def audit_materials(self):
        self.owner.run_job("正在检查全部材料的大小和 SHA-256…",
                           self.owner.materials.audit_materials, self.show_integrity_result)

    def show_integrity_result(self, report):
        self.integrity_dialog = MaterialIntegrityDialog(self.owner, report)
        self.integrity_dialog.setAttribute(Qt.WA_DeleteOnClose)
        self.integrity_dialog.open()


class DashboardPage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("dashboard_page")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(12)
        self.description = QLabel()
        self.description.setTextFormat(Qt.PlainText)
        self.description.setObjectName("page_description")
        self.description.setWordWrap(True)
        layout.addWidget(self.description)
        cards = QHBoxLayout()
        self.count_labels = {}
        for key, title in [("projects_count", "未归档项目"), ("tasks_count", "未完成任务"), ("overdue_count", "逾期任务"), ("achievements_count", "成果记录"), ("materials_count", "材料版本")]:
            box = QGroupBox(title)
            box_layout = QVBoxLayout(box)
            number = named(QLabel("0"), "count_" + key)
            number.setProperty("role", "count")
            number.setAlignment(Qt.AlignCenter)
            box_layout.addWidget(number)
            cards.addWidget(box)
            self.count_labels[key] = number
        layout.addLayout(cards)
        grid = QGridLayout()
        self.tables = {}
        self.hints = {}
        self.task_columns = [("title", "任务"), ("project_name", "项目"), ("due_date", "截止日期")]
        self.project_columns = [("name", "项目"), ("status", "状态"), ("updated_at", "更新时间")]
        for index, (key, title) in enumerate([("today_tasks", "今天到期"), ("overdue_tasks", "逾期任务"), ("upcoming_tasks", "未来七天到期（明日至第七天）"), ("recent_projects", "最近更新项目")]):
            group = QGroupBox(title)
            box_layout = QVBoxLayout(group)
            columns = self.project_columns if key == "recent_projects" else self.task_columns
            table = make_table(columns, "dashboard_" + key)
            table.setMinimumHeight(115)
            table.setColumnWidth(0, 180)
            table.setColumnWidth(1, 135)
            self.tables[key] = table
            box_layout.addWidget(table, 1)
            self.hints[key] = QLabel()
            box_layout.addWidget(self.hints[key])
            grid.addWidget(group, index // 2, index % 2)
            table.cellClicked.connect(lambda row, col, current=key: self.open_row(current, row))
        layout.addLayout(grid, 1)
        self.refresh_button = named(QPushButton("刷新概览"), "dashboard_refresh")
        self.refresh_button.clicked.connect(self.refresh)
        layout.addWidget(self.refresh_button, alignment=Qt.AlignRight)

    def refresh(self):
        summary = self.owner.portfolio.dashboard()
        self.description.setText(f"{self.owner.store.config.get('name', '示例用户')}，这里是当前资料库的科研进展。今天：{date.today().isoformat()}。点击任务或项目进入详情。")
        for key, label in self.count_labels.items():
            label.setText(str(summary[key]))
        for key, table in self.tables.items():
            records = summary[key]
            fill_table(table, records, self.project_columns if key == "recent_projects" else self.task_columns)
            self.hints[key].setText(f"{len(records)} 条记录" if records else "暂无记录")

    def open_row(self, key, row):
        table = self.tables[key]
        if table.item(row, 0):
            record = table.item(row, 0).data(Qt.UserRole)
            if key == "recent_projects":
                self.owner.show_project(record["id"])
            else:
                self.owner.show_task(record["id"])


class ReportsPage(QWidget):
    def __init__(self, owner):
        super().__init__()
        self.owner = owner
        self.setObjectName("reports_page")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        content = QWidget()
        self.scroll.setWidget(content)
        outer.addWidget(self.scroll)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 12, 20, 16)
        layout.setSpacing(14)
        description = QLabel("导出实际已保存的信息；备份包含数据库一致快照、材料副本和用户配置。恢复仅写入新的或空的资料目录。")
        description.setWordWrap(True)
        description.setObjectName("page_description")
        layout.addWidget(description)
        export = QGroupBox("成果台账与项目摘要")
        export_layout = QVBoxLayout(export)
        filters = QHBoxLayout()
        self.project = named(QComboBox(), "reports_project")
        self.type = named(filter_combo("全部成果类型", ACHIEVEMENT_STATUSES.keys()), "reports_type")
        self.status = named(filter_combo("全部状态"), "reports_status")
        filters.addWidget(self.project, 2)
        filters.addWidget(self.type)
        filters.addWidget(self.status)
        export_layout.addLayout(filters)
        self.conditions = named(QLabel(), "reports_conditions")
        self.conditions.setTextFormat(Qt.PlainText)
        self.conditions.setWordWrap(True)
        export_layout.addWidget(self.conditions)
        buttons = QHBoxLayout()
        self.csv_button = named(QPushButton("导出成果台账 CSV…"), "reports_csv")
        self.html_button = named(QPushButton("导出所选项目摘要 HTML…"), "reports_html")
        buttons.addWidget(self.csv_button)
        buttons.addWidget(self.html_button)
        buttons.addStretch()
        export_layout.addLayout(buttons)
        export_layout.addWidget(QLabel("CSV 使用 UTF-8 BOM，并防护表格公式文本；HTML 会转义用户输入。HTML 摘要包含所选项目的全部任务、成果和材料目录。"))
        layout.addWidget(export)
        backup = QGroupBox("完整备份与验证恢复")
        backup_layout = QVBoxLayout(backup)
        explanation = QLabel("建议顺序：① 创建完整 ZIP 备份并保存在资料目录之外；② 将备份恢复到新建或空目录；③ 关闭软件，使用结果中的完整命令打开恢复目录；④ 核对项目、任务、成果、材料和真实／演示标记。\n备份时暂停业务写入；恢复前验证哈希、数据库结构、关联与材料引用。恢复不会切换或覆盖当前资料库。")
        explanation.setObjectName("reports_backup_guidance")
        explanation.setWordWrap(True)
        backup_layout.addWidget(explanation)
        backup_buttons = QHBoxLayout()
        self.backup_button = named(QPushButton("创建完整 ZIP 备份…"), "reports_backup")
        self.restore_button = named(QPushButton("恢复到新的资料目录…"), "reports_restore")
        backup_buttons.addWidget(self.backup_button)
        backup_buttons.addWidget(self.restore_button)
        backup_buttons.addStretch()
        backup_layout.addLayout(backup_buttons)
        layout.addWidget(backup)
        result = QGroupBox("最近操作结果")
        result_layout = QVBoxLayout(result)
        self.result = named(QLabel("尚未进行导出、备份或恢复。"), "reports_result")
        self.result.setTextFormat(Qt.PlainText)
        self.result.setWordWrap(True)
        self.result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        result_layout.addWidget(self.result)
        self.open_result_button = named(QPushButton("打开保存位置"), "reports_open_result")
        self.open_result_button.setEnabled(False)
        self.open_result_button.clicked.connect(self.open_result)
        result_layout.addWidget(self.open_result_button, alignment=Qt.AlignLeft)
        self.result_path = None
        layout.addWidget(result)
        layout.addStretch()
        self.csv_button.clicked.connect(self.export_csv)
        self.html_button.clicked.connect(self.export_html)
        self.backup_button.clicked.connect(self.backup)
        self.restore_button.clicked.connect(self.restore)
        self.project.currentIndexChanged.connect(self.update_conditions)
        self.type.currentIndexChanged.connect(self.type_changed)
        self.status.currentIndexChanged.connect(self.update_conditions)
        self.type_changed()

    def refresh(self):
        populate_projects(self.project, self.owner)
        self.update_conditions()

    def type_changed(self):
        selected = self.status.currentData()
        self.status.blockSignals(True)
        self.status.clear()
        self.status.addItem("全部状态", "")
        for value in ACHIEVEMENT_STATUSES.get(self.type.currentData(), sorted({status for group in ACHIEVEMENT_STATUSES.values() for status in group})):
            self.status.addItem(value, value)
        self.status.setCurrentIndex(max(0, self.status.findData(selected)))
        self.status.blockSignals(False)
        self.update_conditions()

    def update_conditions(self):
        self.conditions.setText(f"CSV 筛选条件：项目 = {self.project.currentText() or '全部项目'}；类型 = {self.type.currentText()}；状态 = {self.status.currentText()}。")
        self.html_button.setEnabled(self.project.currentData() is not None)

    def saved(self, label, path, extra=""):
        self.result_path = Path(path)
        self.result.setText(f"{label}\n保存位置：{path}\n{extra}".strip())
        self.open_result_button.setEnabled(True)
        self.owner.statusBar().showMessage(f"{label}：{path}", 12000)

    def open_result(self):
        if self.result_path:
            path = self.result_path if self.result_path.is_dir() else self.result_path.parent
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(path))):
                self.owner.show_error("系统未能打开保存位置。")

    def export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "导出成果台账", "成果台账.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        project_id, type_, status = self.project.currentData(), self.type.currentData(), self.status.currentData()
        conditions = self.conditions.text()
        self.prepare_result("CSV 导出")
        self.owner.run_job("正在导出成果台账…", lambda: self.owner.exports.export_csv(path, project_id=project_id, type=type_, status=status), lambda output: self.saved("CSV 导出成功", output, conditions))

    def export_html(self):
        project_id = self.project.currentData()
        if project_id is None:
            self.owner.show_error("请先选择一个项目。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出项目摘要", "项目摘要.html", "HTML 文件 (*.html)")
        if path:
            project_name = self.project.currentText()
            self.prepare_result("HTML 导出")
            self.owner.run_job("正在导出项目摘要…", lambda: self.owner.exports.export_html(path, project_id), lambda output: self.saved("HTML 导出成功", output, f"项目：{project_name}；包含该项目全部保存记录。"))

    def backup(self):
        path, _ = QFileDialog.getSaveFileName(self, "创建完整备份", f"科研档案备份-{date.today().isoformat()}.zip", "ZIP 备份 (*.zip)")
        if path:
            self.prepare_result("完整备份")
            self.owner.run_job("正在创建数据库快照、复制材料并校验备份…", lambda: self.owner.exports.backup(path), lambda output: self.saved("完整备份成功", output, "建议将此备份恢复到独立空目录，关闭软件后重启核对，再确认备份可用。"))

    def restore(self):
        archive, _ = QFileDialog.getOpenFileName(self, "选择完整 ZIP 备份", "", "ZIP 备份 (*.zip)")
        if not archive:
            return
        target = QFileDialog.getExistingDirectory(self, "选择新建或空的资料目录（可在窗口中新建文件夹）")
        if not target:
            return
        if QMessageBox.question(self, "验证并恢复", f"将验证备份并恢复到：\n{target}\n\n目标必须为空；恢复后当前资料库继续使用，切换需要重新启动。", QMessageBox.Yes | QMessageBox.No, QMessageBox.No) != QMessageBox.Yes:
            return
        self.prepare_result("备份恢复")
        self.owner.run_job("正在验证备份并恢复到新目录…", lambda: self.owner.exports.restore(archive, target), self.restored)

    def prepare_result(self, operation):
        self.result_path = None
        self.open_result_button.setEnabled(False)
        self.result.setText(f"{operation}已开始，尚无本次成功结果。完成后显示保存位置；如失败，请查看错误提示。")

    def restored(self, path):
        command = restore_launch_command(path)
        checklist = "重启后请本人核对：\n□ 项目及归档状态\n□ 任务及截止日期\n□ 成果及事实状态\n□ 材料版本与预览\n□ 真实／演示标记"
        instructions = f"当前资料库继续使用，未自动切换。请先关闭软件，再运行：\n{command}\n\n{checklist}"
        self.saved("恢复与完整性校验成功", path, instructions)
        self.owner.show_info("恢复成功", f"记录、关联与材料哈希已通过验证。\n目标资料目录：{path}\n\n{instructions}")
