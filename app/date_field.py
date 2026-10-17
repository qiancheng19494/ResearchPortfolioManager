"""可留空的日期输入；仅明确确认日历选择时才写入日期。"""
from PySide6.QtCore import QDate, Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCalendarWidget, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class DateSelectionDialog(QDialog):
    """日历浏览与输入值分开，取消或关闭不会改动原值。"""

    def __init__(self, parent=None, current_text=""):
        super().__init__(parent)
        self.setObjectName("date_selection_dialog")
        self.setWindowTitle("选择日期")
        self.setMinimumWidth(340)
        layout = QVBoxLayout(self)
        hint = QLabel("选择日期并确认后才填入；取消不会改变原值。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.calendar = QCalendarWidget()
        self.calendar.setObjectName("date_calendar")
        self.calendar.setGridVisible(True)
        self.calendar.setFirstDayOfWeek(Qt.Monday)
        self.calendar.setHorizontalHeaderFormat(QCalendarWidget.ShortDayNames)
        current = QDate.fromString(current_text.strip(), "yyyy-MM-dd")
        if current.isValid() and current.toString("yyyy-MM-dd") == current_text.strip():
            self.calendar.setSelectedDate(current)
        layout.addWidget(self.calendar)
        self.buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self.select_button = self.buttons.button(QDialogButtonBox.Ok)
        self.select_button.setObjectName("date_confirm")
        self.select_button.setText("使用所选日期")
        self.buttons.button(QDialogButtonBox.Cancel).setText("取消")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)


class NullableDateField(QWidget):
    """保留文本接口和手输校验，不用 QDateEdit 的默认日期代替空值。"""

    textChanged = Signal(str)
    returnPressed = Signal()

    def __init__(self, value="", parent=None):
        super().__init__(parent)
        self._readonly = False
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.editor = QLineEdit("" if value is None else str(value))
        self.editor.setObjectName("date_text")
        self.editor.setPlaceholderText("YYYY-MM-DD（可留空）")
        self.editor.setMinimumWidth(110)
        self.editor.setAccessibleName("日期，可留空")
        self.editor.textChanged.connect(self.textChanged)
        self.editor.returnPressed.connect(self.returnPressed)
        self.calendar_button = QPushButton("日历…")
        self.calendar_button.setObjectName("date_choose")
        self.calendar_button.setToolTip("选择日期；也可在输入框按 Alt+↓")
        self.calendar_button.setAccessibleName("通过日历选择日期")
        self.clear_button = QPushButton("清空")
        self.clear_button.setObjectName("date_clear")
        self.clear_button.setToolTip("清空日期，保存后为未设置")
        for button in (self.calendar_button, self.clear_button):
            button.setAutoDefault(False)
            button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            button.setMinimumWidth(52)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.calendar_button)
        layout.addWidget(self.clear_button)
        self.calendar_button.clicked.connect(self.open_calendar)
        self.clear_button.clicked.connect(self.clear)
        self.shortcut = QShortcut(QKeySequence("Alt+Down"), self)
        self.shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.shortcut.activated.connect(self.open_calendar)
        self.setFocusProxy(self.editor)
        self.setTabOrder(self.editor, self.calendar_button)
        self.setTabOrder(self.calendar_button, self.clear_button)

    def text(self):
        return self.editor.text()

    def setText(self, value):
        self.editor.setText("" if value is None else str(value))

    def clear(self):
        if not self._readonly:
            self.editor.clear()

    def setPlaceholderText(self, text):
        self.editor.setPlaceholderText(text)

    def setReadOnly(self, readonly):
        self._readonly = bool(readonly)
        self.editor.setReadOnly(self._readonly)
        self.calendar_button.setEnabled(not self._readonly)
        self.clear_button.setEnabled(not self._readonly)
        self.shortcut.setEnabled(not self._readonly)

    def isReadOnly(self):
        return self._readonly

    def open_calendar(self):
        if self._readonly or not self.isEnabled():
            return
        dialog = DateSelectionDialog(self, self.text())
        if dialog.exec() == QDialog.Accepted and not self._readonly:
            self.setText(dialog.calendar.selectedDate().toString("yyyy-MM-dd"))
        self.editor.setFocus()
