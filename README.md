# 本科科研项目与成果档案管理系统 V1.0

> **公开版说明**：此仓库基于 2026-10-10 V1.0 Reviewed 修订包整理，仅脱敏个人默认值、本机路径、演示负责人和演示资料；不更改数据库结构或核心业务逻辑。原始 ZIP 仍由作者私下保留。完整 75 项 Windows GUI/兼容性历史验证记录对应原修订版，不等同于本公开脱敏副本已经重新完整通过。部分原始截图含本机状态栏路径，未随公开仓库提供。详见 [公开发布说明](PUBLIC_RELEASE_NOTES.md)。

ResearchPortfolioManager 是面向个人的本地 Windows 桌面资料管理工具。使用 Python、PySide6 和 SQLite，实现项目、任务、成果、材料版本、CSV/HTML 报告和 ZIP 备份恢复。

本目录为 **V1.0 首版修订的公开脱敏版本（Reviewed Public）**，软件界面名称与版本仍是“本科科研项目与成果档案管理系统 V1.0”。仅修复材料预览保护、负责人必填与配置类型校验，保留六页和数据库 schema 版本 1。原版目录及原 ZIP 保留，不覆盖；历史测试批次与本轮测试分别记录。

首次运行真实资料库为空。姓名和背景只是可编辑的个人资料默认值；软件不会自动认定论文录用、授权、获奖、软著登记或成果真实性。

## 环境与启动

原修订版的 Windows 验证环境：Windows、Python 3.11.9、PySide6 6.10.3（Essentials/Addons/Shiboken6 均为 6.10.3）、SQLite 3.45.1。源码无需数据库服务或网络服务。首次交付不含 EXE 或安装包。

在项目目录打开 PowerShell，通常按以下步骤安装和启动：

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe main.py
```

如果 Windows 因项目目录太深而导致依赖安装报路径长度错误，请将仓库放在较短的路径（例如 `C:\Projects\ResearchPortfolioManager`），重新创建 `.venv`。本仓库不包含开发者的本机虚拟环境。

使用项目内虚拟环境启动：

```powershell
& .\.venv\Scripts\python.exe main.py
# 或者
powershell -ExecutionPolicy Bypass -File .\run.ps1
# 使用演示资料
powershell -ExecutionPolicy Bypass -File .\run.ps1 -DataDir .\demo_data
```

指定其他资料目录：

```powershell
& .\.venv\Scripts\python.exe main.py --data-dir "D:\我的科研资料"
# 或使用启动辅助脚本
powershell -ExecutionPolicy Bypass -File .\run.ps1 -DataDir "D:\我的科研资料"
```

资料路径可以包含中文和空格。程序按电脑本地日期显示提醒。同一资料目录由进程锁保护；不同资料目录可以独立打开。

## 数据位置与演示

默认资料根目录是项目内 `user_data/`，包含：

- `portfolio.sqlite3`：项目、任务、成果、材料及 schema 版本。
- `materials/<UUID>/<原文件名>`：导入文件的受管理副本。
- `config/settings.json`：个人资料与演示标志。
- `logs/application.log`：运行与错误日志。
- `preview_cache/<UUID>/<原文件名>`：打开时创建的隔离预览副本；不属于正式材料、不进入备份或交付包。

关闭并重新打开会保留数据和设置。请勿直接移动单个受管理文件；移动完整资料目录后使用 `--data-dir` 指向该目录。

配置统一合并缺省值后校验：`name` 为非空文本，`background` 与 `interests` 为文本，`demo` 为布尔值。真实资料默认 `demo=false`，提供的演示为 `demo=true`。语法合法但类型错误的配置会指出字段并保留原文件，不能把字符串 `"false"` 当作布尔值；需修正实际错误后重新启动。

本次已提供独立 `demo_data` 演示目录，直接启动：

```powershell
& .\.venv\Scripts\python.exe main.py --data-dir demo_data
```

需要重新生成演示时指定另一新建/空目录：

```powershell
& .\.venv\Scripts\python.exe demo.py --data-dir demo_data_new
& .\.venv\Scripts\python.exe main.py --data-dir demo_data_new
```

`demo.py` 只接受新建或空目录，拒绝覆盖已有资料。所有演示项目与成果使用“【演示】”前缀，演示标志在界面醒目显示。已提供目录含 2 个项目、4 个任务、2 个准备中的其他成果、4 个 TXT 材料副本（每项目 V1/V2）。附件均为生成器新建的少量 TXT，状态和日期不代表示例用户的真实履历。演示目录不会与默认真实资料库混合。

## 使用与恢复

按“项目管理 → 任务管理 → 成果台账 → 材料归档”建立记录，再从“报告与备份”选择筛选条件及保存位置。材料导入复制原文件，UUID 目录隔离同名文件与不同版本。项目归档保留关联记录并使其只读，恢复后可继续修改。

项目负责人在新建与编辑时均须为非空文本。仅在调用方没有提供该字段时，使用经过校验的个人姓名作为默认负责人；现存空负责人须由本人在编辑时填写，软件不会猜测或批量补写。

材料打开前在后台核对受管理副本大小和 SHA-256，再生成独立预览副本，由主线程调用系统默认程序打开。目录入口也指向预览目录。外部编辑器保存修改只影响预览；若要保留修改，请另存文件后通过“导入新版本”归档。软件不强制关闭外部程序，也不自动删除已经交给程序的预览文件。受管理原副本若变化或丢失，会明确拒绝预览及完整备份；哈希不能重建文件，须从此前有效备份恢复到新目录，或找到可信原文件后按新版本重新导入。

成果 CSV 使用 UTF-8 BOM，并处理公式开头文本；项目 HTML 摘要转义用户输入。导出内容来自实际保存记录，CSV 筛选条件在页面显示。

备份生成完整 ZIP，使用 SQLite backup API 建立一致快照，附带配置、受管理材料和校验清单。备份期间写入暂停。恢复操作选择新建或空目录，经过临时目录校验后恢复，不覆盖当前资料目录。恢复成功后关闭程序，以 `main.py --data-dir "恢复目录"` 重新启动。首次打开恢复目录后建议检查项目、成果、材料并打开需要的附件。

## 验证与文档

在项目目录运行独立测试（数据全部使用临时目录）：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GUI 验证使用真实 Qt Windows 窗口和 QTest 点击，测试文件选择与确认对话框用受控临时路径替代。实际执行结果、范围和限制见 [验证报告](docs/验证报告.md)。

新增回归可先单独运行，再运行原有四个测试模块：

```powershell
& .\.venv\Scripts\python.exe -m unittest tests.test_preview_regression tests.test_reviewed_validation tests.test_reviewed_compatibility tests.test_reviewed_flow -v
& .\.venv\Scripts\python.exe -m unittest tests.test_portfolio tests.test_files_backup tests.test_database_lock tests.test_gui -v
```

旧版兼容测试依赖原始开发工作区相邻的 `ResearchPortfolioManager/` 原版源码，公开仓库不包含该原版。单独解压修订 ZIP 后若没有该相邻原版目录，涉及旧版生成的用例会明确跳过；这不会影响日常启动、资料管理或恢复功能。只有提供原版并实际运行才能重新证明旧版生成兼容，不能把跳过记为通过。

- [使用说明](docs/使用说明.md)
- [设计说明](docs/设计说明.md)
- [开发记录](docs/开发记录.md)
- [功能与代码对应表](docs/功能与代码对应表.md)
- [首版修订说明](docs/首版修订说明.md)
- [首版验收清单](docs/首版验收清单.md)
- [首版状态](PROJECT_STATUS.md)
- [第三方说明](THIRD_PARTY_NOTICES.md)

本次不生成或提交软著申请材料，不确定开发者与著作权人权属，不承诺登记结果。代码与文档用于本人学习、审阅、修改和本地使用。

## 许可与权利

当前未添加开源许可证（`LICENSE`）。公开 GitHub 仓库不等于自动授予复制、修改或再分发权限；如需开源授权，请权利人确认后选择许可证。第三方依赖许可请参阅 `THIRD_PARTY_NOTICES.md`。
