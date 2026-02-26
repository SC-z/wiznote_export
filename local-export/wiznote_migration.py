#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记迁移工具
将为知笔记备份数据转换为Markdown格式
"""

import os
import sys
import sqlite3
import zipfile
import json
import re
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging
from dataclasses import dataclass
import html2text
from bs4 import BeautifulSoup
import base64
import mimetypes
from urllib.parse import unquote

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('wiznote_migration.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


@dataclass
class WizDocument:
    """为知笔记文档数据结构"""
    guid: str
    title: str
    location: str
    created: datetime
    modified: datetime
    accessed: datetime
    tags: List[str]
    attachment_count: int
    data_md5: str


@dataclass
class WizAttachment:
    """为知笔记附件数据结构"""
    guid: str
    document_guid: str
    name: str
    data_md5: str


@dataclass
class WizDataSource:
    """导入数据源描述"""
    source_type: str
    source_name: str
    db_path: Path
    notes_dir: Path
    attachments_dir: Optional[Path]
    output_prefix: Optional[Path]


class WizNoteMigrator:
    """为知笔记迁移主类"""
    
    def __init__(self, source_dir: str, target_dir: str):
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.data_dir = None
        self.user_dir = None
        self.db_path = None
        self.notes_dir = None
        self.attachments_dir = None
        self.current_source_name = "个人笔记"
        self.current_output_prefix = None
        
        # 统计信息
        self.stats = {
            'total_notes': 0,
            'migrated_notes': 0,
            'failed_notes': 0,
            'total_attachments': 0,
            'migrated_attachments': 0,
            'failed_attachments': 0
        }
        
        # HTML转Markdown配置
        self.h2t = html2text.HTML2Text()
        self.h2t.body_width = 0  # 不自动换行
        self.h2t.unicode_snob = True
        self.h2t.skip_internal_links = False
        self.h2t.inline_links = True
        self.h2t.protect_links = True
        self.h2t.wrap_links = False
        
        # 若误传为文件路径，则退回到其父目录
        if self.target_dir.suffix.lower() == '.md':
            logger.warning(f"目标路径为文件，将使用其父目录: {self.target_dir.parent}")
            self.target_dir = self.target_dir.parent
        
    def find_user_data(self) -> bool:
        """查找用户数据目录"""
        # 查找邮箱目录（通常是第一个目录）
        for item in self.source_dir.iterdir():
            if item.is_dir() and '@' in item.name:
                self.user_dir = item
                self.data_dir = item / 'data'
                if self.data_dir.exists():
                    self.db_path = self.data_dir / 'index.db'
                    self.notes_dir = self.data_dir / 'notes'
                    self.attachments_dir = self.data_dir / 'attachments'
                    logger.info(f"找到用户数据目录: {self.data_dir}")
                    return True
        
        logger.error("未找到有效的用户数据目录")
        return False

    def find_group_data_sources(self) -> List[WizDataSource]:
        """查找群组数据源"""
        if not self.user_dir:
            return []

        group_root = self.user_dir / 'group'
        if not group_root.exists():
            logger.info("未找到群组目录，跳过群组导出")
            return []

        group_sources: List[WizDataSource] = []
        used_output_names = set()
        for group_dir in sorted(group_root.iterdir()):
            if not group_dir.is_dir():
                continue

            db_path = group_dir / 'index.db'
            notes_dir = group_dir / 'notes'
            if not db_path.exists() or not notes_dir.exists():
                logger.warning(f"群组目录缺少 index.db 或 notes，已跳过: {group_dir}")
                continue

            group_id = group_dir.name
            group_name = self.get_meta_value(db_path, 'DATABASE', 'NAME') or group_id
            safe_group_name = self.sanitize_path_component(group_name)
            output_name = safe_group_name
            if output_name in used_output_names:
                output_name = f"{safe_group_name}__{group_id[:8]}"
            used_output_names.add(output_name)

            attachments_dir = group_dir / 'attachments'
            source = WizDataSource(
                source_type='group',
                source_name=f"群组:{group_name}({group_id[:8]})",
                db_path=db_path,
                notes_dir=notes_dir,
                attachments_dir=attachments_dir if attachments_dir.exists() else None,
                output_prefix=Path('group') / output_name
            )
            group_sources.append(source)
            logger.info(f"发现群组数据源: {source.source_name}")

        logger.info(f"共发现 {len(group_sources)} 个群组数据源")
        return group_sources

    def get_meta_value(self, db_path: Path, meta_name: str, meta_key: str) -> Optional[str]:
        """读取 WIZ_META 指定键值"""
        conn = None
        try:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT META_VALUE
                FROM WIZ_META
                WHERE META_NAME = ? AND META_KEY = ?
                LIMIT 1
            """, (meta_name, meta_key))
            row = cursor.fetchone()
            if row and row[0]:
                value = str(row[0]).strip()
                if value:
                    return value
        except Exception as e:
            logger.warning(f"读取元数据失败 {db_path}: {e}")
        finally:
            if conn is not None:
                conn.close()
        return None

    def sanitize_path_component(self, name: str) -> str:
        """清理单个目录名"""
        if not name:
            return "UnnamedGroup"
        clean = name.strip().replace('/', '_').replace('\\', '_')
        illegal_chars = '<>:"|?*\r\n'
        for char in illegal_chars:
            clean = clean.replace(char, '_')
        clean = clean.strip().strip('.')
        if not clean:
            clean = "UnnamedGroup"
        return clean[:200]

    def set_active_source(self, source: WizDataSource):
        """切换当前导出数据源"""
        self.db_path = source.db_path
        self.notes_dir = source.notes_dir
        self.attachments_dir = source.attachments_dir
        self.current_source_name = source.source_name
        self.current_output_prefix = source.output_prefix
    
    def create_target_structure(self):
        """创建目标目录结构"""
        self.target_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"创建目标目录: {self.target_dir}")
    
    def connect_database(self) -> sqlite3.Connection:
        """连接为知笔记数据库"""
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")
        
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        logger.info(f"[{self.current_source_name}] 成功连接数据库")
        return conn
    
    def get_all_documents(self, conn: sqlite3.Connection) -> List[WizDocument]:
        """获取所有文档信息"""
        cursor = conn.cursor()
        
        # 查询文档基本信息
        cursor.execute("""
            SELECT 
                DOCUMENT_GUID,
                DOCUMENT_TITLE,
                DOCUMENT_LOCATION,
                DT_CREATED,
                DT_MODIFIED,
                DT_ACCESSED,
                DOCUMENT_ATTACHEMENT_COUNT,
                DOCUMENT_DATA_MD5
            FROM WIZ_DOCUMENT
            ORDER BY DT_CREATED DESC
        """)
        
        documents = []
        for row in cursor.fetchall():
            doc = WizDocument(
                guid=row['DOCUMENT_GUID'],
                title=row['DOCUMENT_TITLE'],
                location=row['DOCUMENT_LOCATION'],
                created=datetime.fromisoformat(row['DT_CREATED']),
                modified=datetime.fromisoformat(row['DT_MODIFIED']),
                accessed=datetime.fromisoformat(row['DT_ACCESSED']),
                tags=[],
                attachment_count=row['DOCUMENT_ATTACHEMENT_COUNT'] or 0,
                data_md5=row['DOCUMENT_DATA_MD5']
            )
            documents.append(doc)
        
        # 获取标签信息
        for doc in documents:
            cursor.execute("""
                SELECT t.TAG_NAME
                FROM WIZ_DOCUMENT_TAG dt
                JOIN WIZ_TAG t ON dt.TAG_GUID = t.TAG_GUID
                WHERE dt.DOCUMENT_GUID = ?
            """, (doc.guid,))
            doc.tags = [row['TAG_NAME'] for row in cursor.fetchall()]
        
        logger.info(f"获取到 {len(documents)} 个文档")
        return documents
    
    def get_document_attachments(self, conn: sqlite3.Connection, doc_guid: str) -> List[WizAttachment]:
        """获取文档的附件信息"""
        cursor = conn.cursor()
        cursor.execute("""
            SELECT 
                ATTACHMENT_GUID,
                DOCUMENT_GUID,
                ATTACHMENT_NAME,
                ATTACHMENT_DATA_MD5
            FROM WIZ_DOCUMENT_ATTACHMENT
            WHERE DOCUMENT_GUID = ?
        """, (doc_guid,))
        
        attachments = []
        for row in cursor.fetchall():
            att = WizAttachment(
                guid=row['ATTACHMENT_GUID'],
                document_guid=row['DOCUMENT_GUID'],
                name=row['ATTACHMENT_NAME'],
                data_md5=row['ATTACHMENT_DATA_MD5']
            )
            attachments.append(att)
        
        return attachments
    
    def extract_note_content(self, doc_guid: str) -> Tuple[Optional[str], Dict[str, bytes]]:
        """解压并提取笔记内容和图片"""
        # 为知笔记文件名格式是 {GUID}
        note_filename = f"{{{doc_guid}}}"
        note_path = self.notes_dir / note_filename
        if not note_path.exists():
            logger.warning(f"笔记文件不存在: {note_path}")
            return None, {}
        
        html_content = None
        images = {}
        
        try:
            with zipfile.ZipFile(note_path, 'r') as zf:
                # 查找index.html文件和图片文件
                for filename in zf.namelist():
                    if filename.endswith('index.html'):
                        with zf.open(filename) as f:
                            # 尝试不同的编码
                            content = f.read()
                            for encoding in ['utf-8', 'utf-16-le', 'gbk', 'gb2312']:
                                try:
                                    html_content = content.decode(encoding)
                                    break
                                except UnicodeDecodeError:
                                    continue
                            
                            # 如果都失败，使用错误处理
                            if html_content is None:
                                html_content = content.decode('utf-8', errors='ignore')
                    
                    # 提取图片文件
                    elif any(filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp']):
                        with zf.open(filename) as f:
                            images[filename] = f.read()
                            
        except Exception as e:
            logger.error(f"解压笔记失败 {doc_guid}: {e}")
            return None, {}
        
        return html_content, images
    
    def html_to_markdown(self, html_content: str, doc: WizDocument, images: Dict[str, bytes]) -> str:
        """将HTML内容转换为Markdown"""
        if not html_content:
            return ""
        
        # 解析HTML
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # 提取body内容
        body = soup.find('body')
        if not body:
            body = soup
        
        # 构建图片 data URL 映射（不落盘）
        image_data_urls = self.build_image_data_urls(images)
        
        # 处理HTML中的图片引用
        for img in body.find_all('img'):
            src = (img.get('src') or '').strip()
            if not src:
                continue
            
            # 已经是 data URL 的图片直接保留
            if src.startswith('data:'):
                continue
            
            # 处理本地图片引用，替换为 data URL
            src_unquoted = unquote(src).replace('\\', '/')
            src_unquoted = src_unquoted.split('?', 1)[0].split('#', 1)[0]
            candidates = [src_unquoted, os.path.basename(src_unquoted)]
            replaced = False
            for key in candidates:
                data_url = image_data_urls.get(key)
                if data_url:
                    img['src'] = data_url
                    replaced = True
                    break
            
            if not replaced and image_data_urls:
                logger.warning(f"未找到图片数据: {src}")
        
        # 转换为Markdown
        markdown_content = self.h2t.handle(str(body))
        markdown_content = self.unescape_list_markers(markdown_content)
        markdown_content = self.normalize_blank_lines(markdown_content)
        
        # 不添加元数据，直接返回内容
        return markdown_content

    def unescape_list_markers(self, text: str) -> str:
        """恢复被转义的列表符号与分割线"""
        if not text:
            return text
        lines = []
        pattern = re.compile(r'^(\s*)\\-\s+')
        hr_pattern = re.compile(r'^\s*\\([*_\\-]{3,})\s*$')
        fence_pattern = re.compile(r'^\s*(```|~~~)')
        in_fence = False
        for line in text.splitlines():
            if fence_pattern.match(line):
                in_fence = not in_fence
                lines.append(line)
                continue
            if in_fence:
                lines.append(line)
                continue
            line = pattern.sub(r'\1- ', line)
            if hr_pattern.match(line):
                line = line.replace('\\', '')
            lines.append(line)
        return "\n".join(lines)

    def normalize_blank_lines(self, text: str) -> str:
        """压缩多余空行，保留结构所需的单个空行"""
        if not text:
            return text
        lines = text.splitlines()
        out = []
        blank_count = 0
        in_fence = False
        fence_pattern = re.compile(r'^\s*(```|~~~)')
        for line in lines:
            if fence_pattern.match(line):
                in_fence = not in_fence
                out.append(line)
                blank_count = 0
                continue
            if in_fence:
                out.append(line)
                continue
            if line.strip() == '':
                blank_count += 1
                if blank_count <= 1:
                    out.append('')
                continue
            blank_count = 0
            out.append(line)
        return "\n".join(out).rstrip() + "\n"
    
    def build_image_data_urls(self, images: Dict[str, bytes]) -> Dict[str, str]:
        """将图片二进制转换为 data URL 映射"""
        image_data_urls = {}
        for img_path, img_data in images.items():
            data_url = self.image_bytes_to_data_url(img_data, img_path)
            if not data_url:
                continue
            normalized_path = img_path.replace('\\', '/')
            image_data_urls[normalized_path] = data_url
            image_data_urls[os.path.basename(normalized_path)] = data_url
        return image_data_urls
    
    def image_bytes_to_data_url(self, img_data: bytes, img_path: str) -> Optional[str]:
        """将图片二进制转换为 data URL"""
        try:
            mime_type, _ = mimetypes.guess_type(img_path)
            if not mime_type:
                mime_type = 'image/png'
            encoded = base64.b64encode(img_data).decode('ascii')
            return f"data:{mime_type};base64,{encoded}"
        except Exception as e:
            logger.error(f"图片转Base64失败 {img_path}: {e}")
            return None
    
    def get_document_dir(self, doc: WizDocument) -> Path:
        """获取文档的目标目录"""
        # 将路径转换为合法的目录名
        location = doc.location.strip('/')
        if not location:
            location = 'Uncategorized'
        
        # 替换路径分隔符
        location = location.replace('/', os.sep)
        
        # 创建目录
        if self.current_output_prefix is None:
            doc_dir = self.target_dir / location
        else:
            doc_dir = self.target_dir / self.current_output_prefix / location
        doc_dir.mkdir(parents=True, exist_ok=True)
        
        return doc_dir
    
    def sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        # 移除非法字符
        illegal_chars = '<>:"|?*\r\n'
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        
        # 限制长度
        name, ext = os.path.splitext(filename)
        if len(name) > 200:
            name = name[:200]
        
        return name + ext
    
    def save_document(self, doc: WizDocument, content: str) -> bool:
        """保存文档为Markdown文件"""
        try:
            doc_dir = self.get_document_dir(doc)
            
            # 生成文件名
            filename = self.sanitize_filename(doc.title)
            if not filename.endswith('.md'):
                filename += '.md'
            
            filepath = doc_dir / filename
            
            # 处理重名
            counter = 1
            while filepath.exists():
                name, ext = os.path.splitext(filename)
                filepath = doc_dir / f"{name}_{counter}{ext}"
                counter += 1
            
            block = self.format_document_block(doc, content)
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(block)
            
            logger.info(f"保存文档: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"保存文档失败 {doc.title}: {e}")
            return False
    
    def format_document_block(self, doc: WizDocument, content: str) -> str:
        """构建单篇文档的Markdown块"""
        if not content:
            return ""
        return content.strip() + "\n"
    
    def copy_attachment(self, doc: WizDocument, attachment: WizAttachment) -> bool:
        """复制附件文件"""
        try:
            # 查找附件文件
            source_files = [
                self.attachments_dir / f"{attachment.guid}{attachment.name}",
                self.attachments_dir / attachment.name
            ]
            
            source_file = None
            for f in source_files:
                if f.exists():
                    source_file = f
                    break
            
            if not source_file:
                logger.warning(f"附件文件不存在: {attachment.name}")
                return False
            
            # 目标路径
            doc_dir = self.get_document_dir(doc)
            assets_dir = doc_dir / 'assets'
            assets_dir.mkdir(parents=True, exist_ok=True)
            
            target_file = assets_dir / attachment.name
            
            # 复制文件
            shutil.copy2(source_file, target_file)
            logger.info(f"复制附件: {attachment.name}")
            return True
            
        except Exception as e:
            logger.error(f"复制附件失败 {attachment.name}: {e}")
            return False

    def is_image_file(self, filename: str) -> bool:
        """判断是否为图片文件"""
        ext = os.path.splitext(filename)[1].lower()
        return ext in {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp', '.svg'}

    def migrate_data_source(self, source: WizDataSource):
        """迁移单个数据源"""
        self.set_active_source(source)
        logger.info(f"开始迁移数据源: {source.source_name}")
        if not self.attachments_dir:
            logger.warning(f"[{source.source_name}] 未找到附件目录，附件复制将跳过")

        conn = self.connect_database()
        try:
            # 获取所有文档
            documents = self.get_all_documents(conn)
            self.stats['total_notes'] += len(documents)

            # 迁移每个文档
            for i, doc in enumerate(documents, 1):
                logger.info(f"[{source.source_name}] 处理文档 {i}/{len(documents)}: {doc.title}")

                # 提取内容和图片
                html_content, images = self.extract_note_content(doc.guid)
                if not html_content:
                    self.stats['failed_notes'] += 1
                    continue

                # 转换为Markdown
                markdown_content = self.html_to_markdown(html_content, doc, images)

                # 保存文档
                if self.save_document(doc, markdown_content):
                    self.stats['migrated_notes'] += 1
                else:
                    self.stats['failed_notes'] += 1
                    continue

                # 处理附件（图片附件跳过）
                if doc.attachment_count > 0:
                    attachments = self.get_document_attachments(conn, doc.guid)
                    self.stats['total_attachments'] += len(attachments)
                    if not self.attachments_dir:
                        continue

                    for att in attachments:
                        if self.is_image_file(att.name):
                            logger.info(f"[{source.source_name}] 跳过图片附件: {att.name}")
                            continue
                        if self.copy_attachment(doc, att):
                            self.stats['migrated_attachments'] += 1
                        else:
                            self.stats['failed_attachments'] += 1
        finally:
            conn.close()
    
    def migrate(self):
        """执行迁移"""
        logger.info("开始迁移为知笔记...")
        
        # 查找数据目录
        if not self.find_user_data():
            return
        
        # 创建目标结构
        self.create_target_structure()

        # 组装数据源（个人库 + 全部群组）
        data_sources = [
            WizDataSource(
                source_type='personal',
                source_name='个人笔记',
                db_path=self.db_path,
                notes_dir=self.notes_dir,
                attachments_dir=self.attachments_dir if self.attachments_dir.exists() else None,
                output_prefix=None
            )
        ]
        data_sources.extend(self.find_group_data_sources())

        for source in data_sources:
            self.migrate_data_source(source)
        
        # 打印统计信息
        self.print_stats()
    
    def save_metadata(self, documents: List[WizDocument]):
        """保存元数据"""
        metadata_dir = self.target_dir / '_metadata'
        
        # 保存文档索引
        index_data = []
        for doc in documents:
            index_data.append({
                'guid': doc.guid,
                'title': doc.title,
                'location': doc.location,
                'created': doc.created.isoformat(),
                'modified': doc.modified.isoformat(),
                'tags': doc.tags
            })
        
        with open(metadata_dir / 'index.json', 'w', encoding='utf-8') as f:
            json.dump(index_data, f, ensure_ascii=False, indent=2)
        
        # 保存标签列表
        all_tags = set()
        for doc in documents:
            all_tags.update(doc.tags)
        
        with open(metadata_dir / 'tags.json', 'w', encoding='utf-8') as f:
            json.dump(sorted(list(all_tags)), f, ensure_ascii=False, indent=2)
        
        logger.info("元数据保存完成")
    
    def print_stats(self):
        """打印统计信息"""
        print("\n" + "="*50)
        print("迁移完成统计")
        print("="*50)
        print(f"总笔记数: {self.stats['total_notes']}")
        print(f"成功迁移: {self.stats['migrated_notes']}")
        print(f"失败数量: {self.stats['failed_notes']}")
        print(f"总附件数: {self.stats['total_attachments']}")
        print(f"成功复制: {self.stats['migrated_attachments']}")
        print(f"失败附件: {self.stats['failed_attachments']}")
        print("图片附件: 已跳过导出")
        print("="*50)


def main():
    """主函数"""
    if len(sys.argv) < 2:
        print("使用方法:")
        print("  python wiznote_migration.py <源目录> [目标目录]")
        print("\n示例:")
        print("  python wiznote_migration.py ./wiznote ./notes")
        sys.exit(1)
    
    source_dir = sys.argv[1]
    target_dir = sys.argv[2] if len(sys.argv) > 2 else "notes"
    
    # 创建迁移器并执行
    migrator = WizNoteMigrator(source_dir, target_dir)
    
    try:
        migrator.migrate()
    except Exception as e:
        logger.error(f"迁移失败: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
