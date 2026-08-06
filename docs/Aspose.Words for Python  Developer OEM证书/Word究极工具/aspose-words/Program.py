# -*- coding: utf-8 -*-
import os
# 使用官方强烈推荐的安全别名导入
import aspose.words as aw

def try_set_license():
    try:
        lic = aw.License()
        lic.set_license(r"Aspose.License.txt")
        print("✅ Words License OK")
    except Exception as ex:
        print(f"⚠️ License skipped: {ex}")


def create_word_document():
    """
    利用经典的 DocumentBuilder 光标流式模式，创建一个包含文本的标准 .doc 文档
    """
    output_doc_path = "output.doc"
    
    try:
        print("正在初始化全新的空白 Word 文档...")
        # 1. 实例化核心文档容器
        doc = aw.Document()
        
        print("正在将构建光标（DocumentBuilder）绑定至文档...")
        # 2. 将文档对象托管给构建器。构建器会全自动在底层创建必需的 Section 和 Body 节点
        builder = aw.DocumentBuilder(doc)
        
        # 3. 【可选】通过构建器调整接下来要写入的文字视觉样式
        builder.font.size = 14.0            # 设置字号大小
        builder.font.name = "Arial"         # 设置西文字体
        builder.font.bold = False           # 是否加粗
        
        print("光标开始在画布上织入文本段落...")
        # 4. 调用 writeln 写入带有换行符的标准文本段落
        builder.writeln("Hello Aspose.Words! 这是一段通过 Python 动态织入的标准 Word 文本。")
        
        # 换个样式写下一段
        builder.font.size = 12.0
        builder.font.italic = True          # 倾斜样式
        builder.writeln("作为 Aspose 家族的王牌组件，它的文本排版引擎与微软 Office 规范完美对齐，格式兼容性极强。")
        
        print(f"正在驱动排版布局导出管线，正在保存至 {output_doc_path} ...")
        # 5. 【核心通关点】保存文件
        # 底层渲染器会根据你传入的 ".doc" 后缀全自动识别并切换为传统的二进制老旧 OLE 规范进行编码输出
        # 如果需要现代的 OpenXML 格式，直接把后缀改成 ".docx" 即可，无需调整任何其他代码
        doc.save(output_doc_path)
        
        if os.path.exists(output_doc_path):
            print(f"🎉 Word 文档创建成功！请在本地双击查看:\n👉 {os.path.abspath(output_doc_path)}")
        else:
            print("❌ 保存执行完成，但在磁盘上未检测到目标文件。")
            
    except Exception as ex:
        print(f"💥 创建 Word 失败: {type(ex).__name__}: {ex}")


if __name__ == "__main__":
    try_set_license()
    create_word_document()