# Release 附件

## 测试材料包

| 文件 | 说明 |
|------|------|
| `tender-agent-test-materials-v1.0.0.zip` | 系统验收与功能测试用完整材料包 |

### 包含内容

- **一键导入包** `heyuanzhineng_20260729/`：企业档案、字段定义、工程化模板、历史标书、资质、校验清单、FAQ
- **手动上传样例** `manual_upload/`：可直接用于模板管理 / Agent 上传测试的 DOCX
- **使用说明** `README-测试材料使用说明.md`

### 重新生成

```bash
pip install python-docx openpyxl   # 若环境未安装
python scripts/build_test_materials_pack.py
```

生成脚本：`scripts/build_test_materials_pack.py`
