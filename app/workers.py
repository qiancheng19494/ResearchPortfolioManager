"""长耗时文件工作；业务服务在工作线程中自行建立数据库连接。"""
from PySide6.QtCore import QThread, Signal


class JobThread(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, function, parent=None):
        super().__init__(parent)
        self.function = function

    def run(self):
        try:
            self.succeeded.emit(self.function())
        except Exception as exc:
            import logging
            logging.getLogger(__name__).exception("后台操作失败")
            self.failed.emit(str(exc))
