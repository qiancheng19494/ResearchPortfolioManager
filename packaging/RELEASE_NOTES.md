# ResearchPortfolioManager v1.0.1 — Windows 安装版

这是 V1.0 的 **Windows 安装及便携打包维护版本**，不是数据库升级。保留原有六页及 SQLite schema 版本 1。

- **Windows_Setup.exe**：64 位 Windows 用户安装包（免安装 Python），按当前用户安装，不需要管理员权限。
- **Windows_Portable.zip**：解压后运行 `ResearchPortfolioManager.exe`，请保留完整目录，不要只移动 exe。
- **SHA256SUMS.txt**：安装包与便携包校验值。

默认真实资料目录为 `%LOCALAPPDATA%\ResearchPortfolioManager\user_data`，不写进程序安装目录；卸载程序不会主动删除这份用户资料。若需打开原项目目录下的资料，请使用 `--data-dir "原资料路径"`；请先备份，不要直接用旧目录覆盖新目录。

保留原有备份恢复逻辑，并修复安装版恢复成功提示中的启动命令。演示用数据模板包含在便携目录中，使用时应先复制到可写位置，再通过 `--data-dir` 打开，避免直接修改安装目录内的模板。

此版本根据 Windows GitHub Actions 流水线自动构建和进行启动烟测，尚未在用户个人电脑上实测外部编辑器、多 DPI、海量文件或 SmartScreen。安装包未进行 Windows 商业代码签名，系统可能提示未知发布者；请从此项目 GitHub Release 下载并核对 SHA-256。Qt / PySide6 组件遵守各自许可证，具体参见 THIRD_PARTY_NOTICES.md。

项目源码仍未附加独立开源许可证；公开可见不表示授权第三方任意复制或再发布。
