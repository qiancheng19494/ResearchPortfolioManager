"""材料完整性检查结果与只读检查报告导出。"""
from datetime import date

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QPushButton,
    QFileDialog,
)


class MaterialIntegrityDialog(QDialog):
    def __init__(self, owner, report):
        super().__init__(owner)
        self.owner = owner
        self.report = report
        self.export_pending = False
        self.setObjectName("material_integrity_dialog")
        self.setWindowTitle("材料完整性检查结果")
        self.resize(950, 540)
        layout = QVBoxLayout(self)
        self.summary = QLabel()
        self.summary.setObjectName("integrity_summary")
        self.summary.setTextFormat(Qt.PlainText)
        self.summary.setWordWrap(True)
        total, passed, failed = report["total"], report["passed"], report["failed"]
        outcome = f"发现 {failed} 项异常，请查看原因。" if failed else (
            "全部材料与归档记录一致。" if total else "资料库中暂无材料。")
        self.summary.setText(
            f"检查时间：{report['checked_at']}\n"
            f"共 {total} 个材料版本，一致 {passed} 个，异常 {failed} 个。{outcome}")
        layout.addWidget(self.summary)
        explanation = QLabel(
            "检查覆盖全部项目及材料版本（含已归档项目），不受列表筛选影响。"
            "结果反映本次读取时刻，不自动修复或替换归档文件，也不更新旧哈希。"
            "异常材料需从可信原始文件或有效备份恢复；哈希无法重建丢失内容。")
        explanation.setObjectName("integrity_explanation")
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.table = QTableWidget(0, 6)
        self.table.setObjectName("integrity_items")
        self.table.setHorizontalHeaderLabels(["材料名称", "所属项目", "项目状态", "版本", "检查结果", "原因"])
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().hide()
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        for index, width in enumerate((190, 150, 90, 70, 100, 260)):
            self.table.setColumnWidth(index, width)
        statuses = {"passed": "一致", "missing": "文件缺失", "changed": "内容变化",
                    "unsafe_path": "路径异常", "error": "读取失败"}
        self.table.setRowCount(len(report["items"]))
        for row, record in enumerate(report["items"]):
            values = (record["original_name"], record["project_name"],
                      "已归档" if record["project_archived"] else "活跃",
                      record["version_label"], statuses.get(record["status"], "检查异常"),
                      record["reason"])
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.table.setItem(row, column, item)
        layout.addWidget(self.table, 1)
        self.export_result = QLabel("尚未导出检查报告。")
        self.export_result.setObjectName("integrity_export_result")
        self.export_result.setTextFormat(Qt.PlainText)
        self.export_result.setWordWrap(True)
        self.export_result.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.export_result)
        buttons = QHBoxLayout()
        self.export_button = QPushButton("导出 JSON 检查报告…")
        self.export_button.setObjectName("integrity_export")
        self.export_button.clicked.connect(self.export_report)
        buttons.addWidget(self.export_button)
        buttons.addStretch()
        self.close_button = QPushButton("关闭")
        self.close_button.setObjectName("integrity_close")
        self.close_button.clicked.connect(self.accept)
        buttons.addWidget(self.close_button)
        layout.addLayout(buttons)

    def export_report(self):
        if self.export_pending or self.owner.busy:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出材料检查报告", f"材料检查报告-{date.today().isoformat()}.json", "JSON 文件 (*.json)")
        if not path:
            return
        self.export_pending = True
        self.export_button.setEnabled(False)
        self.close_button.setEnabled(False)
        self.export_result.setText("正在导出检查报告，尚无本次成功结果。")
        self.owner.run_job(
            "正在保存材料检查报告…",
            lambda: self.owner.exports.export_integrity_report(path, self.report), self.exported)
        self.owner.job.finished.connect(self.export_finished, Qt.QueuedConnection)

    def exported(self, path):
        self.export_result.setText(f"检查报告已保存：{path}")

    def export_finished(self):
        self.export_pending = False
        self.export_button.setEnabled(True)
        self.close_button.setEnabled(True)
        if self.owner.last_job_error:
            self.export_result.setText("检查报告未保存，请查看错误提示。")

    def done(self, result):
        if not self.export_pending:
            super().done(result)

    def closeEvent(self, event):
        if self.export_pending:
            event.ignore()
        else:
            super().closeEvent(event)
