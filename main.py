"""Desktop entry point; an exclusive lock protects each data directory."""
from __future__ import annotations

import argparse
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from database.store import Store
from runtime_paths import default_data_dir

APP_NAME = '本科科研项目与成果档案管理系统 V1.2'


def main(argv=None):
    parser = argparse.ArgumentParser(description=APP_NAME)
    parser.add_argument('--data-dir', type=Path, default=default_data_dir(), help='资料目录（源码默认项目内 user_data；安装版默认当前用户的本地应用资料目录）')
    args = parser.parse_args(argv)
    application = QApplication(sys.argv[:1])
    application.setApplicationName(APP_NAME)
    application.setOrganizationName('ResearchPortfolioManager')
    application.setFont(QFont('Microsoft YaHei UI', 10))
    root = args.data_dir.expanduser().resolve()
    try:
        root.mkdir(parents=True, exist_ok=True)
        lock = QLockFile(str(root / '.instance.lock'))
        lock.setStaleLockTime(0)
        if not lock.tryLock(0):
            QMessageBox.critical(None, '资料目录正在使用', '该资料目录已由其他程序实例使用，或目录不可写。请关闭另一实例或选择其他 --data-dir。')
            return 2
        (root / 'logs').mkdir(exist_ok=True)
        handler = RotatingFileHandler(root / 'logs' / 'application.log', maxBytes=2_000_000, backupCount=3, encoding='utf-8')
        logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(name)s %(message)s', force=True)
        logging.info('启动 %s; data_dir=%s', APP_NAME, root)
        store = Store(root)
        from app.main_window import MainWindow
        window = MainWindow(store)
        application._data_lock = lock
        window.show()
        result = application.exec()
        lock.unlock()
        return result
    except Exception as exc:
        logging.exception('启动失败')
        QMessageBox.critical(None, '启动失败', f'无法打开资料目录：{exc}\n原有资料未被重建或覆盖。')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
