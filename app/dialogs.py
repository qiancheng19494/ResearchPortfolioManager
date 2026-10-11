"""表单和只读详情；验证结果以业务服务为准。"""
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtCore import QUrl
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QLineEdit, QTextEdit,
    QComboBox, QPushButton, QLabel, QMessageBox, QFileDialog, QDialogButtonBox,
    QTabWidget, QTableWidget, QTableWidgetItem, QAbstractItemView, QScrollArea, QWidget,
)
from services.portfolio import (
    PROJECT_CATEGORIES, PROJECT_STATUSES, TASK_STATUSES, PRIORITIES,
    ACHIEVEMENT_STATUSES,
)


def named(widget, name):
    widget.setObjectName(name)
    return widget


def combo(values):
    control = QComboBox()
    for value in values:
        control.addItem(str(value), value)
    return control


def value_of(control):
    if isinstance(control, QComboBox):
        return control.currentData()
    if isinstance(control, QTextEdit):
        return control.toPlainText().strip()
    return control.text().strip()


class FormDialog(QDialog):
    def __init__(self, owner, title, readonly=False):
        super().__init__(owner)
        self.owner = owner
        self.readonly = readonly
        self.setWindowTitle(title)
        self.setMinimumWidth(560)
        self.setMaximumHeight(700)
        self.fields = {}
        self.layout = QVBoxLayout(self)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        form_widget = QWidget()
        form_layout = QVBoxLayout(form_widget)
        self.form = QFormLayout()
        self.form.setSpacing(10)
        self.form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form_layout.addLayout(self.form)
        self.scroll.setWidget(form_widget)
        self.layout.addWidget(self.scroll, 1)
        self.note = QLabel("带 * 的字段必须填写。日期格式：YYYY-MM-DD；空日期不参与到期提醒。")
        self.note.setWordWrap(True)
        self.note.setObjectName("form_note")
        self.layout.addWidget(self.note)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Cancel | QDialogButtonBox.Save)
        self.save_button = self.buttons.button(QDialogButtonBox.Save)
        self.save_button.setText("保存")
        self.save_button.setObjectName("dialog_save")
        self.buttons.button(QDialogButtonBox.Cancel).setText("关闭" if readonly else "取消")
        self.buttons.rejected.connect(self.reject)
        self.save_button.clicked.connect(self.save)
        self.layout.addWidget(self.buttons)
        if readonly:
            self.save_button.hide()
            self.note.setText("所属项目已归档，记录仅供查看。恢复项目后可编辑。")

    def add(self, key, label, value="", choices=None, multiline=False):
        if choices is not None:
            field = combo(choices)
            index = field.findData(value)
            if index >= 0:
                field.setCurrentIndex(index)
        elif multiline:
            field = QTextEdit()
            field.setPlainText(str(value or ""))
            field.setMinimumHeight(60)
            field.setMaximumHeight(90)
        else:
            field = QLineEdit(str(value or ""))
            if "date" in key:
                field.setPlaceholderText("YYYY-MM-DD（可留空）")
        field.setObjectName("field_" + key)
        if self.readonly:
            if hasattr(field, "setReadOnly"):
                field.setReadOnly(True)
            else:
                field.setEnabled(False)
        self.fields[key] = field
        self.form.addRow(label, field)
        return field

    def project_field(self, selected=None, lock=False):
        projects = self.owner.portfolio.list_projects(include_archived=True)
        field = QComboBox()
        field.addItem("请选择项目", None)
        for project in projects:
            if not project["archived"] or project["id"] == selected:
                field.addItem(project["name"] + ("（已归档）" if project["archived"] else ""), project["id"])
        index = field.findData(selected)
        if index >= 0:
            field.setCurrentIndex(index)
        field.setObjectName("field_project_id")
        field.setEnabled(not (lock or self.readonly))
        self.fields["project_id"] = field
        self.form.addRow("项目 *", field)
        return field

    def data(self):
        return {key: value_of(field) for key, field in self.fields.items()}

    def save(self):
        try:
            self.commit(self.data())
        except Exception as exc:
            self.owner.show_error(str(exc))
            return
        self.accept()


class ProjectDialog(FormDialog):
    def __init__(self, owner, record=None):
        self.record = record or {}
        super().__init__(owner, "项目详情" if self.record.get("archived") else ("编辑项目" if record else "新建项目"), bool(self.record.get("archived")))
        self.add("name", "项目名称 *", self.record.get("name"))
        self.add("category", "类别 *", self.record.get("category", "研究"), PROJECT_CATEGORIES)
        self.add("description", "简介", self.record.get("description"), multiline=True)
        self.add("leader", "负责人 *", self.record.get("leader", owner.store.config.get("name", "示例用户")))
        self.add("start_date", "开始日期", self.record.get("start_date"))
        self.add("end_date", "计划结束日期", self.record.get("end_date"))
        self.add("status", "状态 *", self.record.get("status", "计划中"), PROJECT_STATUSES)
        self.add("notes", "备注", self.record.get("notes"), multiline=True)
        if record:
            self.form.addRow("记录时间", QLabel(f"创建：{record.get('created_at', '')}\n更新：{record.get('updated_at', '')}"))

    def commit(self, data):
        if not isinstance(data.get("leader"), str) or not data["leader"].strip():
            raise ValueError("负责人不能为空")
        self.owner.portfolio.save_project(data, self.record.get("id"))


class TaskDialog(FormDialog):
    def __init__(self, owner, record=None, project_id=None):
        self.record = record or {}
        selected = self.record.get("project_id", project_id)
        archived = selected and owner.portfolio.get_project(selected)["archived"]
        super().__init__(owner, "任务详情" if archived else ("编辑任务" if record else "新增任务"), bool(archived))
        self.project_field(selected, lock=bool(record))
        self.add("title", "任务标题 *", self.record.get("title"))
        self.add("description", "任务说明", self.record.get("description"), multiline=True)
        self.add("due_date", "截止日期", self.record.get("due_date"))
        self.add("priority", "优先级 *", self.record.get("priority", "中"), PRIORITIES)
        self.add("status", "状态 *", self.record.get("status", "待办"), TASK_STATUSES)
        if record:
            self.form.addRow("完成时间", QLabel(record.get("completed_at") or "尚未完成"))

    def commit(self, data):
        self.owner.portfolio.save_task(data, self.record.get("id"))


class AchievementDialog(FormDialog):
    def __init__(self, owner, record=None, project_id=None):
        self.record = record or {}
        selected = self.record.get("project_id", project_id)
        archived = selected and owner.portfolio.get_project(selected)["archived"]
        super().__init__(owner, "成果详情" if archived else ("编辑成果" if record else "登记成果"), bool(archived))
        self.project_field(selected, lock=bool(record))
        self.add("name", "成果名称 *", self.record.get("name"))
        type_field = self.add("type", "成果类型 *", self.record.get("type", "论文"), ACHIEVEMENT_STATUSES.keys())
        self.add("status", "事实状态 *", self.record.get("status", "准备中"), ACHIEVEMENT_STATUSES[type_field.currentData()])
        type_field.currentIndexChanged.connect(self.update_statuses)
        self.add("related_date", "相关日期", self.record.get("related_date"))
        self.add("reference", "编号或链接", self.record.get("reference"))
        self.add("contribution", "贡献说明", self.record.get("contribution"), multiline=True)
        self.add("notes", "备注", self.record.get("notes"), multiline=True)
        if not self.readonly:
            self.note.setText("请依据可靠资料登记真实状态。软件不会认定论文录用、登记、授权或奖项。改变类型将重置不兼容状态。")

    def update_statuses(self):
        field = self.fields["status"]
        selected = field.currentData()
        field.clear()
        for status in ACHIEVEMENT_STATUSES[self.fields["type"].currentData()]:
            field.addItem(status, status)
        index = field.findData(selected)
        if index >= 0:
            field.setCurrentIndex(index)

    def commit(self, data):
        self.owner.portfolio.save_achievement(data, self.record.get("id"))


class MaterialDialog(FormDialog):
    def __init__(self, owner, record=None, version_of=None):
        self.record = record or {}
        preset = record or version_of or {}
        selected = preset.get("project_id")
        archived = selected and owner.portfolio.get_project(selected)["archived"]
        title = "编辑材料信息" if record else ("导入新版本" if version_of else "导入材料")
        super().__init__(owner, title, bool(archived))
        self.setObjectName("material_dialog")
        if not record:
            field = self.add("source", "源文件 *")
            browse = named(QPushButton("选择文件…"), "material_browse")
            browse.clicked.connect(self.browse)
            self.form.addRow("", browse)
        project = self.project_field(selected, lock=bool(record or version_of))
        achievement = QComboBox()
        achievement.setObjectName("field_achievement_id")
        achievement.setEnabled(not self.readonly)
        self.fields["achievement_id"] = achievement
        self.form.addRow("关联成果", achievement)
        project.currentIndexChanged.connect(self.update_achievements)
        self.update_achievements()
        index = achievement.findData(preset.get("achievement_id"))
        if index >= 0:
            achievement.setCurrentIndex(index)
        self.add("category", "材料类别 *", preset.get("category", "其他"))
        self.add("version_label", "版本标签 *", self.record.get("version_label", "新版本" if version_of else "V1"))
        self.add("notes", "备注", preset.get("notes"), multiline=True)
        if not self.readonly:
            self.note.setText("文件会复制到资料目录，原文件保留。同名文件与新版本分别保存。允许常见文档、图片和 ZIP；不导入脚本或可执行文件。")
        if record:
            self.form.addRow("原文件名", QLabel(record["original_name"]))
            digest = QLineEdit(record["sha256"])
            digest.setReadOnly(True)
            self.form.addRow("SHA-256", digest)
            self.form.addRow("归档时间", QLabel(record["imported_at"]))

    def browse(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择待归档文件", "", "支持的材料 (*.pdf *.docx *.xlsx *.csv *.txt *.png *.jpg *.jpeg *.zip *.md *.pptx);;所有文件 (*)")
        if path:
            self.fields["source"].setText(path)

    def update_achievements(self):
        field = self.fields["achievement_id"]
        field.clear()
        field.addItem("不关联成果", None)
        project_id = value_of(self.fields["project_id"])
        if project_id is not None:
            for record in self.owner.portfolio.list_achievements(project_id=project_id):
                field.addItem(record["name"], record["id"])

    def save(self):
        data = self.data()
        if self.record:
            super().save()
            return
        if not data["source"] or not data["project_id"]:
            self.owner.show_error("请选择源文件和所属项目。")
            return
        if not data["category"] or not data["version_label"]:
            self.owner.show_error("材料类别和版本标签不能为空。")
            return
        self.accept()
        self.owner.run_job("正在复制材料并计算 SHA-256…", lambda: self.owner.materials.import_file(
            data["source"], data["project_id"], data["achievement_id"], data["category"], data["version_label"], data["notes"]
        ), self.owner.material_imported)

    def commit(self, data):
        self.owner.materials.update_material(self.record["id"], achievement_id=data["achievement_id"], category=data["category"], version_label=data["version_label"], notes=data["notes"])


def record_table(records, columns, on_open=None):
    table = QTableWidget(0, len(columns))
    table.setHorizontalHeaderLabels([label for key, label in columns])
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().hide()
    table.setAlternatingRowColors(True)
    table.setRowCount(len(records))
    for row, record in enumerate(records):
        for col, (key, label) in enumerate(columns):
            item = QTableWidgetItem(str(record.get(key) or "—"))
            item.setData(Qt.UserRole, record)
            table.setItem(row, col, item)
    table.resizeColumnsToContents()
    table.horizontalHeader().setStretchLastSection(True)
    if on_open:
        table.cellDoubleClicked.connect(lambda row, col: on_open(records[row]))
    return table


class ProjectDetailDialog(QDialog):
    def __init__(self, owner, project_id):
        super().__init__(owner)
        detail = owner.portfolio.project_detail(project_id)
        project = detail["project"]
        self.setWindowTitle("项目详情 · " + project["name"])
        self.resize(840, 610)
        layout = QVBoxLayout(self)
        heading = QLabel(project["name"] + ("（已归档，只读）" if project["archived"] else ""))
        heading.setTextFormat(Qt.PlainText)
        heading.setObjectName("detail_heading")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setMaximumHeight(180)
        summary.setPlainText(f"类别：{project['category']}   状态：{project['status']}   负责人：{project['leader']}\n开始日期：{project.get('start_date') or '未设置'}   计划结束：{project.get('end_date') or '未设置'}\n简介：{project.get('description') or '无'}\n备注：{project.get('notes') or '无'}\n创建：{project['created_at']}   更新：{project['updated_at']}")
        layout.addWidget(summary)
        tabs = QTabWidget()
        tabs.addTab(record_table(detail["tasks"], [("title", "任务"), ("due_date", "截止日期"), ("priority", "优先级"), ("status", "状态")], lambda row: owner.show_task(row["id"])), f"任务（{len(detail['tasks'])}）")
        tabs.addTab(record_table(detail["achievements"], [("name", "成果"), ("type", "类型"), ("status", "状态"), ("related_date", "相关日期")], lambda row: owner.show_achievement(row["id"])), f"成果（{len(detail['achievements'])}）")
        tabs.addTab(record_table(detail["materials"], [("original_name", "文件"), ("category", "类别"), ("version_label", "版本")], lambda row: owner.open_material(row["id"])), f"材料（{len(detail['materials'])}）")
        layout.addWidget(tabs)
        hint = QLabel("双击关联任务或成果查看详情；双击材料经校验后打开独立预览。修改后请另存，再导入新版本。")
        hint.setWordWrap(True)
        hint.setWordWrap(True)
        layout.addWidget(hint)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("关闭")
        close.rejected.connect(self.reject)
        layout.addWidget(close)


class AchievementDetailDialog(QDialog):
    def __init__(self, owner, achievement_id):
        super().__init__(owner)
        record = owner.portfolio.get_achievement(achievement_id)
        materials = owner.materials.list_materials(achievement_id=achievement_id)
        self.setWindowTitle("成果详情 · " + record["name"])
        self.resize(780, 520)
        layout = QVBoxLayout(self)
        summary = QTextEdit()
        summary.setReadOnly(True)
        summary.setPlainText(f"名称：{record['name']}\n类型：{record['type']}   状态：{record['status']}\n相关日期：{record.get('related_date') or '未设置'}\n编号或链接：{record.get('reference') or '未设置'}\n贡献说明：{record.get('contribution') or '无'}\n备注：{record.get('notes') or '无'}\n创建：{record['created_at']}   更新：{record['updated_at']}")
        layout.addWidget(summary)
        preview_hint = QLabel(f"关联证明材料（{len(materials)} 项，双击校验并打开独立预览）\n保留修改请另存，再通过材料归档页导入新版本。")
        preview_hint.setWordWrap(True)
        layout.addWidget(preview_hint)
        layout.addWidget(record_table(materials, [("original_name", "文件"), ("category", "材料类别"), ("version_label", "版本"), ("imported_at", "导入时间")], lambda row: owner.open_material(row["id"])))
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.button(QDialogButtonBox.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class ProfileDialog(FormDialog):
    def __init__(self, owner):
        super().__init__(owner, "个人资料与设置")
        self.add("name", "个人姓名 *", owner.store.config.get("name", "示例用户"))
        self.add("background", "学习背景", owner.store.config.get("background", "示例学校 / 示例专业 / 本科"), multiline=True)
        self.add("interests", "研究兴趣", owner.store.config.get("interests", "机器学习、数据挖掘与智能预测"), multiline=True)
        self.note.setText("这些信息仅作为个人学习背景，不表示学校背书或著作权归属。姓名用于新建项目的默认负责人。")
        location = QLineEdit(str(owner.store.root))
        location.setReadOnly(True)
        self.form.addRow("当前资料目录", location)

    def commit(self, data):
        if not data["name"]:
            raise ValueError("个人姓名不能为空。")
        config = dict(self.owner.store.config)
        config.update(data)
        self.owner.store.save_config(config)


class AboutDialog(QDialog):
    def __init__(self, owner):
        super().__init__(owner)
        self.setWindowTitle("关于软件")
        self.resize(580, 370)
        layout = QVBoxLayout(self)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText("本科科研项目与成果档案管理系统 V1.0\n内部项目名：ResearchPortfolioManager\n\n供本科生个人在本地管理科研项目、任务、成果和材料版本，支持检索、报告导出、完整备份与验证恢复。\n\n个人学习背景：示例学校、示例专业、本科。学校名称仅表示学习背景，不表示背书或合作关系。\n\n软件不认定成果真实性，不保证软件著作权登记结果。第三方依赖及许可见 THIRD_PARTY_NOTICES.md。")
        layout.addWidget(text)
        close = QDialogButtonBox(QDialogButtonBox.Close)
        close.button(QDialogButtonBox.Close).setText("关闭")
        close.rejected.connect(self.reject)
        layout.addWidget(close)
