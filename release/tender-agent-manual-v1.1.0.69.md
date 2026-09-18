# 标书智能体系统 — 用户手册

> 版本：1.1.0 · 文档引擎 v2 · DeepSeek 默认模型 `deepseek-v4-pro`

## 1. 产品简介

标书智能体是面向铁路等行业的投标文书辅助编写系统，支持：

- 六步向导：选模板 → 录入信息 → AI 创作 → 插入资质 → 校验审阅 → 导出 Word
- 文档引擎 v2：SDT 锚点、表格槽、按章节插资质、OCR 匹配、Agent 多轮修订
- 模板工程化：占位符识别、历史标书智能替换
- Agent 工作区：对话写标书、OnlyOffice 在线编辑（Docker 部署可选）

## 2. 部署方式

### 2.1 Windows 桌面版（推荐终端用户）

1. 从 `release/` 目录下载 `TenderAgentSetup.exe`（或 GitHub Releases）
2. 双击安装，启动 **TenderAgent**
3. 打开 **系统设置**，配置 DeepSeek API Key
4. 点击 **运行环境自检**，确认 Aspose / OCR / AI 状态

**无需额外安装**：Python、Docker、LibreOffice、PostgreSQL（已内置）。

**需要自行准备**：DeepSeek 或通义千问 API Key（云端服务）。

### 2.2 Docker 部署（团队/服务器）

```bash
docker compose up -d --build
```

访问 http://localhost:3000 。已内置 Tesseract OCR、LibreOffice、OnlyOffice（8080）。

## 3. 系统设置

| 配置项 | 说明 |
|--------|------|
| 优先模型 | 自动 / 仅 DeepSeek / 仅千问 |
| DeepSeek 模型 | 推荐 `deepseek-v4-pro`（V4 Pro） |
| API Key | 留空保存不覆盖已有 Key |

**环境自检**：检测 Aspose、OCR、文档引擎、AI、OnlyOffice 等组件。

## 4. 六步向导

### 步骤 1：选择起点

选择已工程化的模板或历史标书模板。

### 步骤 2：信息录入

填写项目字段；若模板含 **表格槽**，在「表格数据」区域编辑行或点击 **AI 生成全部表格**。

### 步骤 3：AI 内容生成

- **智能创作**：填写招标条款/评分点，按 manifest 分块生成章节与表格
- **一键生成**：传统全章节生成

### 步骤 4：插入资质

点选资质材料；导出时按 `section_hint` 插入对应章节，图片槽按 OCR/名称匹配。

### 步骤 5：条目校验

- **清单校验**：红/黄/绿条目
- **LLM 文档审阅**：导出前质量闸门

### 步骤 6：导出 Word

校验通过后可导出 `.docx`。

## 5. Agent 写标书（/chat）

1. 说「帮我写标书」→ 选模板 → 填关键字段
2. 创作型模板：补充 **编写要求** → 智能创作
3. 查看 **文档审阅摘要**（含 issue 列表）
4. **多轮修订**卡片或对话框输入修改指令
5. 发送「完成」结束修订

## 6. 管理端

### 模板

- **智能识别**：从完整标书生成 `{{key}}` 占位符
- **图片槽绑定**：模板详情 → 配置资质名称/分类/章节提示
- **重新分析 Manifest**：更新文档引擎 v2 块清单

### 资质库

上传资质文件时自动 OCR 写入 `ocr_text`（需 Tesseract；桌面版已捆绑）。

## 7. 运行环境说明

| 组件 | 桌面版 | Docker |
|------|--------|--------|
| Aspose.Words | 内置 | 挂载授权 |
| Tesseract OCR | 安装包捆绑 | 镜像内置 |
| PostgreSQL / MinIO | 内置 | Compose |
| OnlyOffice | 未默认启用 | 可选 8080 |
| AI API | 用户配置 Key | 用户配置 Key |

## 8. Windows 验收脚本

安装后可在 PowerShell 执行：

```powershell
.\scripts\verify_windows_features.ps1 -Port 18765
```

将检测健康检查、环境自检、设置 API、文档引擎测试等。

## 9. 常见问题

**Q：未配置 API Key 能用吗？**  
A：可以完成模板、字段、资质、导出流程，AI 章节将使用本地模板兜底。

**Q：OCR 不生效？**  
A：在系统设置执行环境自检；桌面版需使用含 Tesseract 的最新安装包。

**Q：导出失败？**  
A：先执行步骤 5 文档审阅，处理红色 issue 后再导出。

## 10. 版本与更新

- 当前版本见 `release/VERSION` 或安装目录 `resources\tender-agent\version.json`
- 更新：下载 `release/` 下最新 `TenderAgentSetup.exe` 覆盖安装
