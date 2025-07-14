#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
转换器模块
负责将HTML内容转换为Markdown格式
"""

import os
import re
import logging
import html2text
from typing import Dict, List, Tuple, Optional
from bs4 import BeautifulSoup
import base64
from pathlib import Path

logger = logging.getLogger(__name__)


class HTMLToMarkdownConverter:
    """HTML到Markdown转换器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.extract_images = config['format']['extract_images']
        self.add_metadata = config['format']['add_metadata']
        
        # 配置html2text
        self.h2t = html2text.HTML2Text()
        self.h2t.body_width = 0  # 不自动换行
        self.h2t.protect_links = True  # 保护链接
        self.h2t.unicode_snob = True  # 使用Unicode
        self.h2t.images_to_alt = False  # 保留图片链接
        self.h2t.single_line_break = True  # 单行换行
    
    def convert(self, html_content: str, note_info: Dict, 
                resources: List[str]) -> Tuple[str, List[Dict]]:
        """转换HTML到Markdown
        
        Args:
            html_content: HTML内容
            note_info: 笔记信息
            resources: 资源列表
            
        Returns:
            (markdown_content, updated_resources)
        """
        try:
            # 预处理HTML
            processed_html, extracted_resources = self._preprocess_html(
                html_content, 
                resources
            )
            
            # 转换为Markdown
            markdown_content = self.h2t.handle(processed_html)
            
            # 后处理Markdown
            markdown_content = self._postprocess_markdown(markdown_content)
            
            # 添加元数据
            if self.add_metadata:
                markdown_content = self._add_metadata(markdown_content, note_info)
            
            return markdown_content, extracted_resources
            
        except Exception as e:
            logger.error(f"转换失败: {e}")
            # 返回原始内容的简单转换
            return f"# {note_info.get('title', 'Untitled')}\n\n转换失败，以下为原始HTML：\n\n```html\n{html_content}\n```", []
    
    def _preprocess_html(self, html_content: str, 
                        resources: List[str]) -> Tuple[str, List[Dict]]:
        """预处理HTML内容"""
        soup = BeautifulSoup(html_content, 'html.parser')
        extracted_resources = []
        
        # 处理图片
        if self.extract_images:
            for img in soup.find_all('img'):
                src = img.get('src', '')
                
                # 处理base64图片
                if src.startswith('data:image'):
                    resource_info = self._extract_base64_image(src)
                    if resource_info:
                        img['src'] = f"./assets/{resource_info['filename']}"
                        extracted_resources.append(resource_info)
                
                # 处理本地图片路径
                elif src.startswith('index_files/') or 'resources/' in src:
                    filename = os.path.basename(src)
                    img['src'] = f"./assets/{filename}"
                    
                    # 检查是否在资源列表中
                    if filename in resources:
                        extracted_resources.append({
                            'filename': filename,
                            'type': 'resource',
                            'original_src': src
                        })
        
        # 处理代码块
        for pre in soup.find_all('pre'):
            # 检查是否有代码语言标记
            code = pre.find('code')
            if code:
                # 获取语言类型
                lang_class = code.get('class', [])
                language = ''
                for cls in lang_class:
                    if cls.startswith('language-'):
                        language = cls.replace('language-', '')
                        break
                
                # 替换为Markdown代码块格式
                code_text = code.get_text()
                new_pre = soup.new_tag('pre')
                new_pre.string = f"```{language}\n{code_text}\n```"
                pre.replace_with(new_pre)
        
        # 处理表格
        for table in soup.find_all('table'):
            # 确保表格有正确的结构
            if not table.find('thead'):
                # 如果没有thead，尝试从第一行创建
                first_row = table.find('tr')
                if first_row:
                    thead = soup.new_tag('thead')
                    first_row.wrap(thead)
        
        # 清理多余的样式和属性
        for tag in soup.find_all(True):
            # 保留的属性
            keep_attrs = ['href', 'src', 'alt', 'title']
            attrs = dict(tag.attrs)
            for attr in attrs:
                if attr not in keep_attrs:
                    del tag[attr]
        
        return str(soup), extracted_resources
    
    def _extract_base64_image(self, data_uri: str) -> Optional[Dict]:
        """提取base64编码的图片"""
        try:
            # 解析data URI
            match = re.match(r'data:image/(\w+);base64,(.+)', data_uri)
            if not match:
                return None
            
            image_type = match.group(1)
            base64_data = match.group(2)
            
            # 解码base64
            image_data = base64.b64decode(base64_data)
            
            # 生成文件名
            import hashlib
            hash_md5 = hashlib.md5(image_data).hexdigest()[:8]
            filename = f"image_{hash_md5}.{image_type}"
            
            return {
                'filename': filename,
                'type': 'base64',
                'data': image_data,
                'image_type': image_type
            }
            
        except Exception as e:
            logger.error(f"提取base64图片失败: {e}")
            return None
    
    def _postprocess_markdown(self, markdown_content: str) -> str:
        """后处理Markdown内容"""
        # 清理多余的空行
        markdown_content = re.sub(r'\n{3,}', '\n\n', markdown_content)
        
        # 修复代码块格式
        markdown_content = re.sub(r'```\n\n', '```\n', markdown_content)
        markdown_content = re.sub(r'\n\n```', '\n```', markdown_content)
        
        # 清理行首行尾空格
        lines = markdown_content.split('\n')
        lines = [line.rstrip() for line in lines]
        markdown_content = '\n'.join(lines)
        
        # 确保文件末尾有换行
        if not markdown_content.endswith('\n'):
            markdown_content += '\n'
        
        return markdown_content
    
    def _add_metadata(self, markdown_content: str, note_info: Dict) -> str:
        """添加YAML前置元数据"""
        metadata = []
        metadata.append("---")
        metadata.append(f"title: {note_info.get('title', 'Untitled')}")
        
        if note_info.get('created'):
            metadata.append(f"created: {note_info['created']}")
        
        if note_info.get('modified'):
            metadata.append(f"modified: {note_info['modified']}")
        
        if note_info.get('tags'):
            tags = note_info['tags']
            if isinstance(tags, list):
                metadata.append(f"tags: [{', '.join(tags)}]")
            else:
                metadata.append(f"tags: [{tags}]")
        
        if note_info.get('author'):
            metadata.append(f"author: {note_info['author']}")
        
        metadata.append("---")
        metadata.append("")
        
        return '\n'.join(metadata) + markdown_content
    
    def convert_batch(self, notes: List[Dict]) -> List[Dict]:
        """批量转换笔记"""
        results = []
        
        for note in notes:
            try:
                html_content = note.get('html_content', '')
                note_info = note.get('info', {})
                resources = note.get('resources', [])
                
                markdown_content, extracted_resources = self.convert(
                    html_content,
                    note_info,
                    resources
                )
                
                results.append({
                    'guid': note_info.get('guid'),
                    'markdown_content': markdown_content,
                    'extracted_resources': extracted_resources,
                    'success': True
                })
                
            except Exception as e:
                logger.error(f"批量转换失败 {note.get('title')}: {e}")
                results.append({
                    'guid': note.get('guid'),
                    'error': str(e),
                    'success': False
                })
        
        return results


class DirectMarkdownHandler:
    """处理已经是Markdown格式的笔记"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.add_metadata = config['format']['add_metadata']
    
    def process(self, markdown_content: str, note_info: Dict) -> str:
        """处理Markdown内容"""
        # 清理内容
        markdown_content = self._clean_markdown(markdown_content)
        
        # 添加元数据
        if self.add_metadata:
            markdown_content = self._add_metadata(markdown_content, note_info)
        
        return markdown_content
    
    def _clean_markdown(self, content: str) -> str:
        """清理Markdown内容"""
        # 移除可能的HTML标签
        content = re.sub(r'<[^>]+>', '', content)
        
        # 清理多余的空行
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        # 确保代码块格式正确
        content = re.sub(r'```\s*\n\s*```', '```\n```', content)
        
        return content.strip() + '\n'
    
    def _add_metadata(self, markdown_content: str, note_info: Dict) -> str:
        """添加YAML前置元数据"""
        # 检查是否已有元数据
        if markdown_content.startswith('---\n'):
            # 已有元数据，不重复添加
            return markdown_content
        
        metadata = []
        metadata.append("---")
        metadata.append(f"title: {note_info.get('title', 'Untitled')}")
        
        if note_info.get('created'):
            metadata.append(f"created: {note_info['created']}")
        
        if note_info.get('modified'):
            metadata.append(f"modified: {note_info['modified']}")
        
        if note_info.get('tags'):
            tags = note_info['tags']
            if isinstance(tags, list):
                metadata.append(f"tags: [{', '.join(tags)}]")
            else:
                metadata.append(f"tags: [{tags}]")
        
        metadata.append("---")
        metadata.append("")
        
        return '\n'.join(metadata) + markdown_content


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 测试配置
    test_config = {
        'format': {
            'extract_images': True,
            'add_metadata': True
        }
    }
    
    # 创建转换器
    converter = HTMLToMarkdownConverter(test_config)
    
    # 测试HTML
    test_html = """
    <h1>测试笔记</h1>
    <p>这是一个<strong>测试</strong>段落。</p>
    <ul>
        <li>列表项1</li>
        <li>列表项2</li>
    </ul>
    <pre><code class="language-python">
def hello():
    print("Hello, World!")
    </code></pre>
    <img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" alt="测试图片">
    """
    
    test_note_info = {
        'title': '测试笔记',
        'created': '2024-01-01T10:00:00',
        'modified': '2024-01-01T11:00:00',
        'tags': ['测试', 'demo']
    }
    
    # 转换
    markdown, resources = converter.convert(test_html, test_note_info, [])
    
    print("转换结果:")
    print(markdown)
    print(f"\n提取的资源: {resources}")