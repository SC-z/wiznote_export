# 为知笔记迁移工具使用说明

## 功能介绍

这个Python脚本可以将为知笔记的备份数据转换为标准的Markdown格式文件，方便导入到其他笔记软件（如Obsidian、Logseq等）。

## 主要特性

- ✅ 完整迁移笔记内容（HTML转Markdown）
- ✅ 保留原始文件夹结构
- ✅ 保留笔记元数据（标题、创建时间、标签等）
- ✅ 自动处理附件和图片
- ✅ 支持Base64内嵌图片提取
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
├── My Notes/              # 原始文件夹结构
│   ├── 技术笔记/
│   │   ├── Python入门.md
│   │   └── assets/       # 附件和图片
│   │       └── image.png
│   └── 日常记录/
│       └── 2024年计划.md
└── _metadata/            # 元数据
    ├── index.json       # 笔记索引
    └── tags.json        # 标签列表
```

## Markdown文件格式

每个转换后的Markdown文件包含：


1. **正文内容**
   - 保留原始格式（标题、列表、表格等）
   - 图片链接自动调整为相对路径
   - 附件链接保持可用

## 注意事项

1. **备份数据**：执行前请确保已备份原始数据
2. **空间需求**：需要与原始数据相当的磁盘空间
3. **运行时间**：取决于笔记数量，可能需要几分钟到几小时
4. **日志文件**：`wiznote_migration.log` 记录详细过程

## 故障排除

1. **编码错误**：脚本会自动尝试多种编码
2. **附件丢失**：检查日志文件中的警告信息
3. **内存不足**：可以修改脚本分批处理

## 后续步骤

迁移完成后，可以：
1. 导入到Obsidian：直接打开notes文件夹作为Vault
2. 导入到Logseq：复制文件到Logseq的pages目录
3. 使用Git管理：初始化Git仓库进行版本控制%
