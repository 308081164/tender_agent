# Release 1.1.0.71

本目录包含标书智能体 **v1.1.0.71** 发布物。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v1.1.0.71.exe` | Windows 离线安装包（约 264 MB，内置 OCR） |
| `TenderAgentSetup.exe` | 同上（通用文件名副本） |
| `tender-agent-manual-v1.1.0.71.md` | 用户手册 |
| `tender-agent-release-v1.1.0.71.zip` | 手册 + 验收脚本 + 版本信息 |
| `tender-agent-test-materials-v1.1.0.71.zip` | 系统验收与功能测试用完整材料包 |
| `VERSION.json` | 版本元数据 |

## GitHub Releases

https://github.com/308081164/tender_agent/releases/tag/desktop-v1.1.0.71.85

> 说明：`*.exe` 体积超过 Git 单文件限制，仓库内 `release/` 在本地打包后会包含安装包；远程仓库提交版本元数据，完整安装包请从 GitHub Releases 下载。

## 安装

1. 下载 `TenderAgentSetup-v1.1.0.71.exe`
2. 运行安装向导（可选自定义安装目录）
3. 首次升级建议删除旧数据：`%LOCALAPPDATA%\TenderAgent\data`
4. 启动「标书智能体」，在 **系统设置 → 运行环境自检** 确认 OCR 为正常

## 本版本要点

### 模板映射预览增强（PR #31）
- 文档预览选中占位符时，侧栏自动滚动并高亮对应映射卡片
- 统一模板类型的格式/结构识别，支持空白填写区域检测（签字、盖章、日期、下划线等）
- 映射预览正确渲染目录与表格，过滤 TOC/HYPERLINK 字段代码

### 向导与文档预览优化（PR #32）
- PDF 预览去除深色边框，使用浅色背景令牌
- 向导信息录入步骤自动从公司资料填充缺失字段
- 敏感字段（报价/工期/脱敏）黄色高亮并显示「请核实」标记

## 验收

```powershell
.\scripts\verify_windows_features.ps1
```
