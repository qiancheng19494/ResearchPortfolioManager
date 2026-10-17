# 第三方依赖与来源说明

本项目自编应用源码使用下列依赖。版本来自本次实际安装环境的包元数据；完整依赖环境不作为原创业务代码，也未复制第三方完整管理系统源码。

| 依赖 | 本次版本 | 官方包元数据中的许可/来源 |
| --- | --- | --- |
| Python | 3.11.9 | Python Software Foundation License；[Python 官方许可证](https://docs.python.org/3/license.html) |
| SQLite（Python 自带 sqlite3 使用） | 3.45.1 | Public Domain；[SQLite 官方版权说明](https://www.sqlite.org/copyright.html) |
| PySide6 | 6.10.3 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`；Qt for Python Team |
| PySide6_Essentials | 6.10.3 | 同上，Qt for Python Team |
| PySide6_Addons | 6.10.3 | 同上，Qt for Python Team |
| shiboken6 | 6.10.3 | `LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only`；Qt for Python Team |

PySide6 的官方首页为 [Qt for Python](https://www.qt.io/qt-for-python)，源码与官方文档可从 [Qt 文档](https://doc.qt.io/qtforpython-6/) 和 [官方仓库](https://code.qt.io/cgit/pyside/pyside-setup.git/) 获取；[Qt 官方许可说明](https://doc.qt.io/qt-6/licensing.html) 列明模块许可背景。安装依赖时保留官方 wheel 中的 `*.dist-info/licenses/`、Qt 许可和第三方通知；本次没有修改这些库。

GUI 使用 QtCore、QtGui、QtWidgets 和测试用 QtTest。PySide6 元包自动安装 Essentials、Addons 和 Shiboken，Addons 不是本应用新增的业务模块。程序使用系统字体，不打包字体、第三方图片或图标；样式由本次代码实现。演示附件为本次生成的新文本文件。

V1.2 提供应用源码及依赖安装说明，并由 Windows 构建流程生成安装版与便携版。运行环境及第三方二进制不计入应用自编源码；分发时应保留依赖随附的版权、许可与第三方通知。本文记录依赖来源，不确定应用权属。
