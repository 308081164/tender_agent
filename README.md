# 标书智能体系统

铁路行业标书 AI 辅助编写系统（React + FastAPI + PostgreSQL + MinIO），支持 Docker Compose 一键部署。

## 快速启动

```bash
docker compose up -d --build
```

启动后访问：

- 前端：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs
- MinIO 控制台：http://localhost:9001（minioadmin / minioadmin）
- OnlyOffice Document Server：http://localhost:8080（Community 版，用于 Word 在线编辑验证）

### OnlyOffice 技术验证（免费 Community 版）

1. 复制 `.env.example` 为 `.env`，按需调整 `ONLYOFFICE_*` 变量
2. `docker compose up -d` 会同时启动 `onlyoffice` 服务（端口 8080）
3. 进入 **文档 Agent 工作区**（`/chat`），上传 DOCX 后左侧默认进入 **Word 编辑** 模式
4. 本机跑后端（`scripts/start_dev.sh`）时，请保持 `ONLYOFFICE_INTERNAL_URL=http://host.docker.internal:8000`，以便 Document Server 能回调保存

> 验证期使用 Community 版即可；商用嵌入产品需购买 OnlyOffice Developer 授权。

## 可选：配置 AI API Key

复制 `.env.example` 为 `.env`，填入：

```
DEEPSEEK_API_KEY=sk-xxx
QWEN_API_KEY=sk-xxx
```

未配置时系统自动使用本地模板引擎生成章节内容，不影响完整流程演示。

## 模拟材料

`sample_data/` 目录已内置完整模拟参考材料，系统启动时自动导入模板、历史标书、资质库、字段定义、校验清单与 FAQ。

重新生成模拟材料：

```bash
python3 scripts/generate_sample_data.py
```

## 六步向导

1. 选择起点（模板 / 历史标书）
2. 信息录入
3. AI 审核生成
4. 插入资质
5. 条目校验
6. 导出 Word
