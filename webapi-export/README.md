# 为知笔记备份工具

一个用于备份为知笔记（包括个人笔记和团队笔记）的Python工具，支持将笔记导出为Markdown格式，保留文件夹结构和附件。

## 功能特点

- 🔐 安全的Token认证，支持加密存储
- 👥 支持个人笔记和团队笔记备份
- 📁 保持原始文件夹结构
- 🔄 支持增量备份（只下载新增或修改的笔记）
- 📝 自动转换HTML到Markdown格式
- 🖼️ 提取并保存图片和附件
- ⚡ 多线程并发下载
- 📊 详细的进度显示和统计信息
- 🔧 灵活的配置选项

## 安装

1. 克隆或下载本项目
2. 安装依赖：

```bash
pip install -r requirements.txt
```

## 配置

首次运行时会自动创建配置文件 `config/config.json`，需要填写您的为知笔记账号信息：

```json
{
    "auth": {
        "username": "your_email@example.com",
        "password": "your_password"
    }
}
```

### 主要配置项说明

- `api.as_url`: 账户服务器地址
- `download.output_dir`: 输出目录路径
- `download.max_concurrent`: 最大并发下载数
- `sync.exclude_folders`: 排除的文件夹列表
- `format.convert_to_markdown`: 是否转换为Markdown格式
- `format.preserve_structure`: 是否保持原始文件夹结构

## 使用方法

### 基本使用

```bash
# 首次运行，交互式配置
python main.py

# 备份所有笔记
python main.py --all

# 备份指定文件夹
python main.py --folders "/My Notes/" "/My Notes/Work/"

# 列出所有文件夹
python main.py --list

# 增量备份（只下载新增或修改的笔记）
python main.py --incremental
```

### 团队笔记备份

```bash
# 列出所有知识库（个人+团队）
python main.py --list-kb

# 备份指定团队的笔记
python main.py --kb <知识库GUID> --all

# 示例：备份团队笔记
python main.py --list-kb  # 先查看所有知识库
python main.py --kb 1a2b3c4d-5e6f-7g8h-9i0j-1k2l3m4n5o6p --all
```

### 高级选项

```bash
# 指定输出目录
python main.py --all --output /path/to/backup

# 不转换为Markdown，保留HTML格式
python main.py --all --no-convert

# 使用自定义配置文件
python main.py --config my_config.json --all
```

## 输出结构

备份的笔记将按照以下结构保存：

```
output/wiznote_backup/
├── Personal/                # 个人笔记
│   ├── My Notes/
│   │   ├── 笔记1.md
│   │   ├── 笔记2.md
│   │   └── assets/
│   │       ├── image1.png
│   │       └── attachment.pdf
│   └── Work/
│       └── 笔记3.md
├── Team Name - 团队笔记/    # 团队笔记
│   ├── Projects/
│   │   └── 项目文档.md
│   └── Shared/
│       └── 共享资料.md
└── _metadata/
    ├── index.json      # 笔记索引
    └── sync_state.json # 同步状态
```

## 注意事项

1. **首次备份**：建议先使用 `--list` 查看文件夹列表，然后选择性备份
2. **大量笔记**：如果笔记数量较多，首次备份可能需要较长时间
3. **API限制**：工具已内置限流机制，避免触发API限制
4. **密码安全**：密码在配置文件中以明文存储，请注意保护配置文件
5. **Token安全**：登录Token会加密存储在本地，有效期24小时

## 故障排除

### 登录失败
- 检查用户名和密码是否正确
- 确认账号是否有效

### 下载失败
- 检查网络连接
- 查看日志文件 `logs/wiznote_backup.log`
- 尝试减少并发数 `download.max_concurrent`

### 转换失败
- 某些复杂的HTML可能无法完美转换
- 可以使用 `--no-convert` 保留原始HTML

## 开发说明

### 项目结构

```
wiznote-team-backup/
├── main.py              # 主程序入口
├── src/
│   ├── auth.py         # 认证模块
│   ├── api_client.py   # API客户端
│   ├── storage.py      # 本地存储管理
│   ├── downloader.py   # 下载器
│   └── converter.py    # 格式转换器
├── config/
│   └── config.json     # 配置文件
├── logs/               # 日志目录
├── requirements.txt    # 依赖列表
└── README.md          # 本文档
```

### 扩展开发

如需扩展功能，可以：

1. 继承 `HTMLToMarkdownConverter` 实现自定义转换逻辑
2. 修改 `LocalStorage` 实现不同的存储策略
3. 扩展 `WizNoteAPIClient` 支持更多API功能

## License

MIT License

## 免责声明

本工具仅供个人备份使用，请遵守为知笔记的服务条款。作者不对因使用本工具造成的任何问题负责。