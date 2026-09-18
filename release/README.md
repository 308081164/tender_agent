# Release 1.1.0.70

本目录包含标书智能体 **v1.1.0.70** 发布物（含内置 Tesseract OCR）。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v1.1.0.70.exe` | Windows 离线安装包（约 264 MB，内置 OCR） |
| `TenderAgentSetup.exe` | 同上（通用文件名副本） |
| `tender-agent-manual-v1.1.0.70.md` | 用户手册 |
| `tender-agent-release-v1.1.0.70.zip` | 手册 + 验收脚本 + 版本信息 |
| `VERSION.json` | 版本元数据 |

## GitHub Releases

https://github.com/308081164/tender_agent/releases/tag/desktop-v1.1.0.70.79

> 说明：`*.exe` 体积超过 Git 单文件限制，仓库内 `release/` 在本地打包后会包含安装包；远程仓库提交版本元数据，完整安装包请从 GitHub Releases 下载。

## 安装

1. 下载 `TenderAgentSetup-v1.1.0.70.exe`
2. 运行安装向导（可选自定义安装目录）
3. 首次升级建议删除旧数据：`%LOCALAPPDATA%\TenderAgent\data`
4. 启动「标书智能体」，在 **系统设置 → 运行环境自检** 确认 OCR 为正常

## 本版本要点

- 安装目录 `tools/tesseract` 内置 Tesseract，含简体中文（chi_sim）与英文语言包
- 支持资质图像/PDF 完整 OCR 识别与 AI 智能填表

## 验收

```powershell
.\scripts\verify_windows_features.ps1
```
