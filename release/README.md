# Release 1.1.0.72

本目录包含标书智能体 **v1.1.0.72** 发布物。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v1.1.0.72.exe` | Windows 离线安装包（约 264 MB，内置 OCR） |
| `TenderAgentSetup.exe` | 同上（通用文件名副本） |
| `tender-agent-manual-v1.1.0.72.md` | 用户手册 |
| `tender-agent-release-v1.1.0.72.zip` | 手册 + 验收脚本 + 版本信息 |
| `tender-agent-test-materials-v1.1.0.72.zip` | 系统验收与功能测试用完整材料包 |
| `VERSION.json` | 版本元数据 |

## GitHub Releases

https://github.com/308081164/tender_agent/releases/tag/desktop-v1.1.0.72.89

> 说明：`*.exe` 体积超过 Git 单文件限制，仓库内 `release/` 在本地打包后会包含安装包；远程仓库提交版本元数据，完整安装包请从 GitHub Releases 下载。

## 安装

1. 下载 `TenderAgentSetup-v1.1.0.72.exe`
2. 运行安装向导（可选自定义安装目录）
3. 首次升级建议删除旧数据：`%LOCALAPPDATA%\TenderAgent\data`
4. 启动「标书智能体」，在 **系统设置 → 运行环境自检** 确认 OCR 为正常

## 本版本要点

### 向导信息录入自动预填修复（PR #33）
- 修复企业档案数据未自动填入信息录入步骤的问题
- 新增字段 key → 企业档案列规范映射（投标人、地址、电话、传真、网址、法定代表人等）
- 启动时自动补齐旧库 `field_defs` 的企业档案映射标记
- 当字段值为旧静态种子默认值（如 `XX铁路工程有限公司`）时，自动替换为企业档案最新值
- 用户手填内容不会被覆盖

## 验收

```powershell
.\scripts\verify_windows_features.ps1
```
