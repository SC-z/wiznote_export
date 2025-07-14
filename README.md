# 为知笔记迁移工具使用说明

## 功能介绍

这个Python脚本可以将为知笔记的备份数据转换为标准的Markdown格式文件，方便导入到其他笔记软件（如Obsidian、Logseq等）。

## 主要特性

- ✅ 完整迁移笔记内容（HTML转Markdown）
- ✅ 保留原始文件夹结构
- ✅ 自动处理附件和图片
- ✅ 支持Base64内嵌图片提取
- ✅ 生成迁移日志和统计信息
- ✅ 错误处理和重试机制


## 项目dir

### webapi-export

- 通过webapi 的接口登陆下载账号内的笔记
- 具体使用查看`./webapi-export/README.md`


### local-export

- 使用方法相对简单，找到本地路径下的本地缓存，执行脚本即可导出。
- 具体使用查看`./local-export/README.md`
