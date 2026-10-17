# 本科科研项目与成果档案管理系统 V1.1

ResearchPortfolioManager 是面向个人的本地 Windows 桌面工具，用于管理科研项目、任务、成果和材料版本，支持 CSV/HTML 导出、完整 ZIP 备份及验证恢复。

V1.1 在独立升级副本中改进三个现有操作：日期日历选择与清空、任务到期快捷筛选、备份恢复指引。保留六页、SQLite schema 1、成果类型状态规则、项目归档只读、材料版本管理，以及 Reviewed 的材料预览保护、负责人必填和统一配置校验。原 V1.0 与 Reviewed 交付保留。

本版同时接续公开仓库 v1.0.2 的运行目录及打包维护规则；未将私人资料或本机依赖环境作为公开源码。V1.1 已上传 GitHub，Windows v1.1.0 安装版与便携版已构建并发布。[下载安装包或便携版](https://github.com/qiancheng19494/ResearchPortfolioManager/releases/tag/v1.1.0)，同页提供 `SHA256SUMS.txt`。远端 70 项测试及打包 EXE 初始化烟测通过；安装/卸载向导和打包后完整 GUI 流程尚未实际操作。仓库原有 v1.0.2 安装包保留原版本身份，不能当作 V1.1 安装包使用。

## 安装与启动

源码运行需要 Windows、Python 3.11 和 `requirements.txt` 中的依赖。在项目目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe main.py
```

可使用启动脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\run.ps1
# 指向独立演示资料
powershell -ExecutionPolicy Bypass -File .\run.ps1 -DataDir .\demo_data
# 指定自己选择的资料目录
powershell -ExecutionPolicy Bypass -File .\run.ps1 -DataDir 'D:\科研资料'
```

`run.ps1` 优先使用项目 `.venv`；本工作区专用环境只作为本机开发便利，不打包进交付。Windows 深目录安装依赖若受路径长度限制，可将源码放到较短目录后创建专用环境。

源码模式默认使用项目内 `user_data/`；冻结安装版按既有维护规则使用 `%LOCALAPPDATA%\ResearchPortfolioManager\user_data`，不向安装目录写入资料。`--data-dir` 始终可指定独立位置；当前资料目录显示在状态栏。不要仅因打开了不同版本就假设已经切换到同一资料库。

首次真实资料库为空；默认个人资料可修改。姓名或演示记录不构成成果真实性、开发者或著作权人结论。

## 日期与任务

项目起止日期、任务截止日期、成果相关日期和成果日期范围可手工输入 `YYYY-MM-DD`，也可点击“日历…”选择。日历只有点击“使用所选日期”才填入；取消或关闭不会改动原值。点击“清空”保留未设置日期，保存为空值。归档只读表单不能通过日历或清空绕过限制。非法日期和起止逆序继续由业务层拒绝。

任务页可快速查看今天到期、已逾期、“未来七天（明日至第七天）”的任务；未来七天按明日至第七天计算，与综合概览一致。快捷提醒只针对未完成且项目未归档的任务，无截止日期不进入到期结果；仍可结合关键词、项目和状态检索。清除快捷条件后可回到通常列表。

## 材料与资料安全

导入材料复制源文件，使用 UUID 隔离同名文件与不同版本。打开前在后台核对受管理副本的大小和 SHA-256，生成 `preview_cache/<UUID>/` 独立预览，再由主线程调用默认程序；“打开预览目录”也指向预览目录。预览修改要保留时，请另存后通过“导入新版本”归档，归档项目须先恢复。软件不强制终止编辑器，也不自动删除已交给编辑器的预览。

材料缺失或变化会明确拒绝预览及完整备份；旧记录、旧哈希和版本保留。哈希不能重建丢失字节，恢复需要此前有效备份或可信原文件。预览缓存不属于正式材料，不进入完整备份或交付。

负责人在新建和编辑时必须是非空文本，显式空白或 `None` 不会保存为成功记录。只有调用方没有提供字段时才使用已验证个人姓名。历史空负责人不猜测、不批量补写。

配置合并缺省值后统一校验：`name` 为非空文本、`background` 与 `interests` 为文本、`demo` 为布尔值。非法配置指出字段并保留原文件，不把字符串 `"false"` 转为布尔值。真实资料 `demo=false`，独立演示 `demo=true`。

## 导出、备份与恢复

“报告与备份”支持按当前记录导出成果 CSV、项目 HTML 摘要。CSV 使用 UTF-8 BOM 和公式文本保护，HTML 转义输入。完整备份包含数据库一致快照、受管理材料、配置和校验清单，排除日志、预览缓存等运行文件。

恢复分为选择完整 ZIP、选择新建或空资料目录、等待校验、用恢复目录重启。程序验证文件清单、大小和哈希、数据库 schema/外键及材料引用，不覆盖当前资料。恢复完成不会自动切换正在运行的窗口；请复制成功提示中的启动命令，关闭后运行，再核对记录、材料与演示标记。先保留当前可用资料和备份，不要手工解压覆盖正在使用的资料库。

V1.1 保持 schema 1 和既有备份格式，旧版兼容的本轮实测结果见 [V1.1 升级说明](docs/V1.1升级说明.md) 与 [验证报告](docs/验证报告.md)。

## 验证与文档

在项目目录使用安装了依赖的 Python 运行测试：

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

本轮先运行新增 29 项，再运行继承/维护 79 项，共 **108 个不同测试最终全通过，失败 0、跳过 0**；两次原生交互测试失败和修正经过在验证报告保留。本机 offscreen 70 项为重复的工作流配置检查，不累计，也不等同远端构建或安装烟测。

测试使用临时或隔离资料，不读取真实科研库。旧版兼容用例需要相邻原版源码；缺少时会明确跳过，不能记为通过。GUI 操作、对话框替代、关联调用模拟与真实外部应用检查按实际证据区分。V1.0 的 75 项 unittest 是 2026-10-10 批次；2026-10-17 的 128 MiB 补充检查包含 28 个脚本检查点，不是 28 项新增 unittest，也不能替代 V1.1 本轮复跑。

- [使用说明](docs/使用说明.md)
- [设计说明](docs/设计说明.md)
- [功能与代码对应表](docs/功能与代码对应表.md)
- [开发记录](docs/开发记录.md)
- [验证报告](docs/验证报告.md)
- [V1.1 升级说明](docs/V1.1升级说明.md)
- [V1.1 验收清单](docs/V1.1验收清单.md)
- [V1.1 发布结果](docs/V1.1发布结果.md)
- [项目状态](PROJECT_STATUS.md)
- [第三方说明](THIRD_PARTY_NOTICES.md)

公开仓库：[qiancheng19494/ResearchPortfolioManager](https://github.com/qiancheng19494/ResearchPortfolioManager)。[功能提交](https://github.com/qiancheng19494/ResearchPortfolioManager/commit/f02ee895588898f9ba8def5bf2986353ba03f787)、[成功的 Actions](https://github.com/qiancheng19494/ResearchPortfolioManager/actions/runs/39011393460) 和 [发布结果](docs/V1.1发布结果.md) 可核对本轮上传；旁置回执保存交付核对信息。

代码、测试和文档由 Codex AI 辅助完成，人工贡献、署名和权属仍由本人据实确认。本轮不制作、签署或提交登记申请资料，不承诺登记结果。
