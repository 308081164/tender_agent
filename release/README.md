# Release 1.2.0

本目录包含标书智能体 **v1.2.0** 产品基线发布物。

## 版本规则（自 1.2.0 起）

- 仓库根目录 `VERSION` 与 `release/VERSION.json` 的 **基线** 为 `1.2.0`（非 1.1.0.72.x）。
- CI `main` 推送构建号：`1.2.0.<run_number>`（见 `scripts/ci/compute-version.ps1`）。
- 正式 Desktop 发版打 Git tag：`desktop-v1.2.0`（或带 build 的 `desktop-v1.2.0.<n>`）。

## 1.2.0 主要能力

- Agent P0：项目上下文注入、general 对话 + FAQ RAG、SSE 流式、FloatingChat 项目绑定、Kimi K3（#38）
- 创作工作台：工程目录、文件夹上传、草稿预览与主动开场（#40–#41）
- UI：映射下拉对比度（#39）

安装包与手册文件名见 `VERSION.json` 的 `artifacts` 字段；GitHub Release 标题：**标书智能体 Desktop 1.2.0**。
