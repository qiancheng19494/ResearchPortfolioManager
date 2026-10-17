# 本科科研项目与成果档案管理系统 V1.2

ResearchPortfolioManager 是本地 Windows 桌面工具，用于管理科研项目、任务、成果与材料版本，支持 CSV/HTML 导出及完整备份恢复。本版整理版本标识、界面说明和交付文档，保留六页、SQLite schema 1 和备份格式 1。

## 安装与启动

Windows 安装版运行 Setup，安装后从快捷方式启动。便携版解压后运行 `ResearchPortfolioManager.exe`。[v1.2.0 下载页](https://github.com/qiancheng19494/ResearchPortfolioManager/releases/tag/v1.2.0) 已发布安装版、便携版和 SHA256SUMS.txt；具体证据见 [发布结果](docs/V1.2发布结果.md)。

源码需要 Python 3.11。在源码目录打开 PowerShell：

```powershell
py -3.11 -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements.txt
& .\.venv\Scripts\python.exe main.py
# 使用独立演示资料
powershell -ExecutionPolicy Bypass -File .\run.ps1 -DataDir .\demo_data
```

`run.ps1` 使用项目 `.venv`。深目录安装依赖受 Windows 路径长度限制时，可将源码放到较短目录再创建环境。源码默认资料在项目 `user_data/`；安装/便携程序默认在 `%LOCALAPPDATA%\ResearchPortfolioManager\user_data`。`--data-dir` 可指定独立资料目录，状态栏显示当前目录。首次真实资料库为空；演示目录标记为“演示数据”，不代表本人履历。

## 现有功能

- 综合概览：项目、任务、成果与材料统计，今天、逾期和未来七天提醒。
- 项目管理：新建、编辑、筛选、归档与恢复；归档后关联记录只读。
- 任务管理：状态、截止日期、完成时间及到期快捷筛选。
- 成果台账：五类成果、兼容状态、日期范围与证明材料关联。
- 材料归档：UUID 隔离版本、SHA-256 校验、独立预览副本。
- 报告与备份：筛选 CSV、项目 HTML、完整 ZIP 及验证后恢复到新目录。

日期可手工输入 `YYYY-MM-DD`，或点击“日历…”确认选择；“清空”保持未设置日期。任务“未来七天”指明日至第七天，可与其他条件组合。

## 资料保护

材料先在后台核对大小与 SHA-256，再生成隔离预览，由主线程打开默认关联程序。“打开预览目录”同样指向预览副本。需要保留修改时，请另存后“导入新版本”。原记录、旧哈希及旧版本保留；损坏或缺失字节需有效备份或可信原文件恢复，不能凭哈希重建。软件不强制关闭外部编辑器，不自动删除已打开的预览。

负责人必须为非空文本；只有调用方未提供字段时才使用已验证的个人姓名。配置合并默认值后统一校验：`name` 非空文本、`background/interests` 文本、`demo` 布尔值。非法配置明确到字段并保留原文件，不转换字符串布尔值。

完整备份包含数据库、受管理材料、配置与校验清单，排除日志和预览缓存。恢复严格检查内容、大小、哈希、schema、外键与引用，仅写入新建或空目录。恢复后关闭软件，再按成功提示用恢复目录重启。升级前保留有效备份。

## 验证与交付资料

```powershell
& .\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

本机 **108 个不同测试首轮通过，失败/错误/跳过均为 0**；远端 Windows 70 项重复回归通过，打包演示四材料大小/SHA-256、EXE 初始化烟测和安装包编译通过。六页、本版 12 张真实截图、关闭重开及 V1.0/V1.1 实际备份恢复已检查。远端重复测试不累计到 108 项。

范围以 [验证报告](docs/验证报告.md)、[验收清单](docs/V1.2验收清单.md) 和 [发布结果](docs/V1.2发布结果.md) 为准。安装/卸载向导和真实外部编辑器保存未实际操作。旧版备份兼容测试需要相邻原版源码，缺少时会明确跳过，不能计为通过。

- [使用说明](docs/使用说明.md)
- [设计说明](docs/设计说明.md)
- [功能与代码对应表](docs/功能与代码对应表.md)
- [内部接口](docs/接口约定.md)
- [开发记录](docs/开发记录.md)
- [V1.2 修订说明](docs/V1.2修订说明.md)
- [项目状态](PROJECT_STATUS.md)
- [第三方说明](THIRD_PARTY_NOTICES.md)

[公开仓库](https://github.com/qiancheng19494/ResearchPortfolioManager)。历史 V1.0、Reviewed 和 V1.1 交付保留；当前测试不使用历史结果代替。本轮不制作、签署或提交登记申请。
