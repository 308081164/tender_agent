# Release 1.1.0.69

本目录包含标书智能体 **v1.1.0.69** 发布物（含 PR #25 模板工程化 AI 映射升级）。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v1.1.0.69.exe` | Windows 离线安装包（约 200 MB） |
| `TenderAgentSetup.exe` | 同上（通用文件名副本） |
| `tender-agent-manual-v1.1.0.69.md` | 用户手册 |
| `tender-agent-release-v1.1.0.69.zip` | 手册 + 验收脚本 + 版本信息 |
| `tender-agent-test-materials-v1.1.0.69.zip` | 验收与功能测试材料包 |
| `VERSION.json` | 版本元数据 |

## GitHub Releases

安装包已同步发布至：

https://github.com/308081164/tender_agent/releases/tag/desktop-v1.1.0.69

> 说明：`*.exe` 体积超过 Git 单文件限制，仓库内 `release/` 目录在本地打包后会包含安装包；远程仓库仅提交版本元数据，完整安装包请从 GitHub Releases 下载。

## 安装

1. 下载 `TenderAgentSetup-v1.1.0.69.exe`
2. 运行安装向导（可选自定义安装目录）
3. 首次升级建议删除旧数据：`%LOCALAPPDATA%\TenderAgent\data`
4. 启动「标书智能体」，确认版本号为 **v1.1.0.69**

## Windows 本地重新打包

```powershell
.\package-desktop.ps1 -AppVersion "1.1.0.69"
```

## 验收

```powershell
.\scripts\verify_windows_features.ps1
```
