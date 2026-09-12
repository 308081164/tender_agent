# Release 1.1.0

本目录包含标书智能体 **v1.1.0** 发布物。

## 下载清单

| 文件 | 说明 |
|------|------|
| `TenderAgentSetup-v1.1.0.exe` | Windows 离线安装包（在 Windows 上运行 `package-desktop.ps1` 生成后复制至此） |
| `tender-agent-manual-v1.1.0.md` | 用户手册 |
| `tender-agent-release-v1.1.0.zip` | 手册 + 验收脚本 + 版本信息压缩包 |
| `tender-agent-test-materials-v1.1.0.zip` | 系统验收与功能测试用完整材料包 |
| `VERSION.json` | 版本元数据 |

## 测试材料包使用

1. 解压 `tender-agent-test-materials-v1.1.0.zip`
2. 将 `heyuanzhineng_20260729/` 复制到桌面版 `%LOCALAPPDATA%\TenderAgent\customer_data\`
3. 打开系统 → **数据管理 → 导入/备份** → **强制重新导入**
4. 也可使用 `manual_upload/` 中的 DOCX 手动测试模板上传

详细说明见压缩包内 `README-测试材料使用说明.md`。

## Windows 打包命令

```powershell
.\package-desktop.ps1 -AppVersion "1.1.0"
```

打包完成后安装包会复制到本目录。

## 验收

```powershell
.\scripts\verify_windows_features.ps1
```

