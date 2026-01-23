# 为知笔记迁移工具使用说明

## 功能介绍

这个Python脚本可以将为知笔记的备份数据转换为**按笔记拆分**的Markdown文件，图片以内嵌Base64方式写入，方便导入到其他笔记软件（如Obsidian、Logseq等）。

## 主要特性

- ✅ 完整迁移笔记内容（HTML转Markdown）
- ✅ 图片转Base64并内嵌进Markdown
- ✅ 每篇笔记输出为独立Markdown文件
- ✅ 生成迁移日志和统计信息
- ✅ 错误处理和重试机制

## 环境要求

- Python 3.6+
- 需要安装的依赖包：
  ```bash
  pip install beautifulsoup4 html2text
  ```

## 使用方法

1. **基本用法**
   ```bash
   python wiznote_migration.py <源目录> [目标目录]
   ```

2. **示例**
   ```bash
   # 使用默认输出目录（./notes）
   python wiznote_migration.py ./wiznote
   
   # 指定输出目录
   python wiznote_migration.py ./wiznote ./my_notes
   ```

## 输出结构

```
notes/
├── My Notes/
│   ├── 技术笔记/
│   │   ├── Python入门.md
│   │   └── assets/       # 附件（非图片）
│   └── 日常记录/
│       └── 2024年计划.md
└── ...
```

## Markdown文件格式

每个Markdown文件对应一篇笔记：

- 文件名为原始标题
- 正文内容为笔记原始内容（图片以 data:image/...;base64,... 形式内嵌）

## 注意事项

1. **备份数据**：执行前请确保已备份原始数据
2. **空间需求**：图片内嵌会增大文件体积
3. **运行时间**：取决于笔记数量，可能需要几分钟到几小时
4. **附件导出**：非图片附件会导出到 `assets/`，图片附件会跳过
5. **日志文件**：`wiznote_migration.log` 记录详细过程

## 故障排除

1. **编码错误**：脚本会自动尝试多种编码
2. **图片未内嵌**：检查日志文件中的图片警告信息
3. **内存不足**：可以修改脚本分批处理

## 后续步骤

迁移完成后，可以：
1. 导入到Obsidian：直接打开输出目录作为Vault
2. 导入到Logseq：复制Markdown文件到pages目录
3. 使用Git管理：初始化Git仓库进行版本控制
