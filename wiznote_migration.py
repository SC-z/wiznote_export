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


class WizNoteMigrator:
    """为知笔记迁移主类"""
    
    def __init__(self, source_dir: str, target_dir: str):
        self.source_dir = Path(source_dir)
        self.target_dir = Path(target_dir)
        self.data_dir = None
        self.db_path = None
        self.notes_dir = None
        self.attachments_dir = None
        
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
        
    def find_user_data(self) -> bool:
        """查找用户数据目录"""
        # 查找邮箱目录（通常是第一个目录）
        for item in self.source_dir.iterdir():
            if item.is_dir() and '@' in item.name:
                self.data_dir = item / 'data'
                if self.data_dir.exists():
                    self.db_path = self.data_dir / 'index.db'
                    self.notes_dir = self.data_dir / 'notes'
                    self.attachments_dir = self.data_dir / 'attachments'
                    logger.info(f"找到用户数据目录: {self.data_dir}")
                    return True
        
        logger.error("未找到有效的用户数据目录")
        return False
    
    def create_target_structure(self):
        """创建目标目录结构"""
        self.target_dir.mkdir(parents=True, exist_ok=True)
        (self.target_dir / '_metadata').mkdir(exist_ok=True)
        logger.info(f"创建目标目录: {self.target_dir}")
    
    def connect_database(self) -> sqlite3.Connection:
        """连接为知笔记数据库"""
        if not self.db_path.exists():
            raise FileNotFoundError(f"数据库文件不存在: {self.db_path}")
        
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        logger.info("成功连接数据库")
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
        
        # 保存提取的图片
        saved_images = {}
        doc_dir = self.get_document_dir(doc)
        assets_dir = doc_dir / 'assets'
        
        if images:
            assets_dir.mkdir(parents=True, exist_ok=True)
            for img_path, img_data in images.items():
                # 获取图片文件名
                img_filename = os.path.basename(img_path)
                # 保存图片
                local_img_path = assets_dir / img_filename
                try:
                    with open(local_img_path, 'wb') as f:
                        f.write(img_data)
                    saved_images[img_path] = f"./assets/{img_filename}"
                except Exception as e:
                    logger.error(f"保存图片失败 {img_filename}: {e}")
        
        # 处理HTML中的图片引用
        for img in body.find_all('img'):
            src = img.get('src', '')
            
            # 处理data URL图片
            if src.startswith('data:image'):
                img_path = self.save_base64_image(src, doc)
                if img_path:
                    img['src'] = img_path
            # 处理本地图片引用
            else:
                # 首先检查是否是index_files格式的引用
                if 'index_files/' in src:
                    # 提取文件名
                    img_filename = os.path.basename(src)
                    # 查找对应的保存路径
                    for original_path, new_path in saved_images.items():
                        if img_filename == os.path.basename(original_path):
                            img['src'] = new_path
                            break
                else:
                    # 其他格式的图片引用
                    for original_path, new_path in saved_images.items():
                        if src.endswith(os.path.basename(original_path)):
                            img['src'] = new_path
                            break
        
        # 转换为Markdown
        markdown_content = self.h2t.handle(str(body))
        
        # 不添加元数据，直接返回内容
        return markdown_content
    
    def save_base64_image(self, data_url: str, doc: WizDocument) -> Optional[str]:
        """保存base64编码的图片"""
        try:
            # 解析data URL
            header, data = data_url.split(',', 1)
            file_type = header.split('/')[1].split(';')[0]
            
            # 解码base64
            image_data = base64.b64decode(data)
            
            # 生成文件名
            image_filename = f"image_{datetime.now().strftime('%Y%m%d%H%M%S')}.{file_type}"
            
            # 确定保存路径
            doc_dir = self.get_document_dir(doc)
            assets_dir = doc_dir / 'assets'
            assets_dir.mkdir(parents=True, exist_ok=True)
            
            image_path = assets_dir / image_filename
            
            # 保存图片
            with open(image_path, 'wb') as f:
                f.write(image_data)
            
            # 返回相对路径
            return f"./assets/{image_filename}"
        
        except Exception as e:
            logger.error(f"保存base64图片失败: {e}")
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
        doc_dir = self.target_dir / location
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
            
            # 保存文件
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            
            logger.info(f"保存文档: {filepath}")
            return True
            
        except Exception as e:
            logger.error(f"保存文档失败 {doc.title}: {e}")
            return False
    
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
    
    def migrate(self):
        """执行迁移"""
        logger.info("开始迁移为知笔记...")
        
        # 查找数据目录
        if not self.find_user_data():
            return
        
        # 创建目标结构
        self.create_target_structure()
        
        # 连接数据库
        conn = self.connect_database()
        
        try:
            # 获取所有文档
            documents = self.get_all_documents(conn)
            self.stats['total_notes'] = len(documents)
            
            # 迁移每个文档
            for i, doc in enumerate(documents, 1):
                logger.info(f"处理文档 {i}/{len(documents)}: {doc.title}")
                
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
                
                # 处理附件
                if doc.attachment_count > 0:
                    attachments = self.get_document_attachments(conn, doc.guid)
                    self.stats['total_attachments'] += len(attachments)
                    
                    for att in attachments:
                        if self.copy_attachment(doc, att):
                            self.stats['migrated_attachments'] += 1
                        else:
                            self.stats['failed_attachments'] += 1
            
            # 保存元数据
            self.save_metadata(documents)
            
        finally:
            conn.close()
        
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