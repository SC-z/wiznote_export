#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
下载器模块
负责协调笔记、附件和资源的下载
基于官方API重新实现
"""

import os
import logging
from typing import Dict, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
import time
import re

logger = logging.getLogger(__name__)


class NoteDownloader:
    """笔记下载器"""
    
    def __init__(self, api_client, storage, converter=None):
        self.api_client = api_client
        self.storage = storage
        self.converter = converter
        self.config = api_client.config
        self.max_workers = self.config['download']['max_concurrent']
        self.kb_name = "Personal"  # 默认知识库名称
        
        # 统计信息
        self.stats = {
            'total_notes': 0,
            'downloaded_notes': 0,
            'failed_notes': 0,
            'skipped_notes': 0,
            'total_attachments': 0,
            'downloaded_attachments': 0,
            'failed_attachments': 0,
            'total_size': 0,
            'start_time': None,
            'end_time': None
        }
        
        # 失败记录
        self.failed_items = []
    
    def set_kb_name(self, kb_name: str):
        """设置知识库名称"""
        self.kb_name = kb_name
    
    def download_all(self, folders_filter: Optional[List[str]] = None):
        """下载所有笔记"""
        self.stats['start_time'] = time.time()
        
        logger.info("开始备份笔记...")
        
        # 获取所有文件夹
        all_folders = self.api_client.get_all_folders()
        
        if not all_folders:
            logger.warning("未找到任何文件夹")
            return
        
        # 应用文件夹过滤
        if folders_filter:
            folders_to_process = [f for f in all_folders if f in folders_filter]
        else:
            # 排除指定的文件夹
            exclude_folders = self.config['sync']['exclude_folders']
            if exclude_folders:
                folders_to_process = [f for f in all_folders if not any(f.startswith(ex) for ex in exclude_folders)]
            else:
                folders_to_process = all_folders
        
        logger.info(f"准备处理 {len(folders_to_process)} 个文件夹")
        
        # 处理每个文件夹
        for folder_path in folders_to_process:
            self._download_folder(folder_path)
        
        self.stats['end_time'] = time.time()
        
        # 保存索引和同步状态
        self.storage.save_index()
        
        sync_state = self.storage.get_sync_state()
        sync_state['last_sync'] = time.time()
        self.storage.save_sync_state(sync_state)
        
        # 打印统计信息
        self._print_statistics()
    
    def _download_folder(self, folder_path: str):
        """下载文件夹中的所有笔记"""
        # 从路径中提取文件夹名称
        folder_name = folder_path.strip('/').split('/')[-1] if folder_path != '/' else 'Root'
        logger.info(f"处理文件夹: {folder_path} ({folder_name})")
        
        # 获取笔记列表
        notes = list(self.api_client.get_all_notes_in_folder(folder_path))
        
        if not notes:
            logger.info(f"文件夹 {folder_path} 中没有笔记")
            return
        
        logger.info(f"文件夹 {folder_path} 中有 {len(notes)} 个笔记")
        self.stats['total_notes'] += len(notes)
        
        # 过滤需要下载的笔记
        notes_to_download = []
        for note in notes:
            if self.config['sync']['incremental']:
                # 增量同步模式，检查笔记是否需要更新
                note_guid = note.get('docGuid', note.get('guid', ''))
                modified_time = note.get('dataModified', note.get('modified', ''))
                
                if not self.storage.is_note_modified(note_guid, modified_time):
                    logger.debug(f"跳过未修改的笔记: {note.get('title', 'Untitled')}")
                    self.stats['skipped_notes'] += 1
                    continue
            notes_to_download.append(note)
        
        if not notes_to_download:
            logger.info(f"文件夹 {folder_path} 中没有需要下载的笔记")
            return
        
        # 使用进度条
        with tqdm(total=len(notes_to_download), desc=f"下载 {folder_name}") as pbar:
            # 并发下载
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_note = {
                    executor.submit(
                        self._download_note,
                        folder_path,
                        note
                    ): note
                    for note in notes_to_download
                }
                
                for future in as_completed(future_to_note):
                    note = future_to_note[future]
                    try:
                        success = future.result()
                        if success:
                            self.stats['downloaded_notes'] += 1
                        else:
                            self.stats['failed_notes'] += 1
                    except Exception as e:
                        logger.error(f"下载笔记失败 {note.get('title', 'Untitled')}: {e}")
                        self.stats['failed_notes'] += 1
                        self.failed_items.append({
                            'type': 'note',
                            'title': note.get('title', 'Untitled'),
                            'guid': note.get('docGuid', note.get('guid', '')),
                            'error': str(e)
                        })
                    finally:
                        pbar.update(1)
    
    def _download_note(self, folder_path: str, note_info: Dict) -> bool:
        """下载单个笔记及其附件"""
        try:
            note_guid = note_info.get('docGuid', note_info.get('guid', ''))
            note_title = note_info.get('title', 'Untitled')
            
            logger.debug(f"处理笔记: {note_title}, GUID: {note_guid}")
            logger.debug(f"笔记信息: {note_info}")
            
            # 获取笔记完整信息
            full_note_info = self.api_client.get_note_info(note_guid)
            if full_note_info:
                note_info.update(full_note_info)
                
            # 标准化笔记信息中的关键字段
            if 'docGuid' not in note_info and 'guid' in note_info:
                note_info['docGuid'] = note_info['guid']
            if 'guid' not in note_info and 'docGuid' in note_info:
                note_info['guid'] = note_info['docGuid']
            if 'dataModified' not in note_info and 'modified' in note_info:
                note_info['dataModified'] = note_info['modified']
            if 'modified' not in note_info and 'dataModified' in note_info:
                note_info['modified'] = note_info['dataModified']
            
            # 下载笔记内容
            note_data = self.api_client.download_note(note_guid)
            if not note_data:
                logger.error(f"无法下载笔记内容: {note_title}")
                return False
            
            # 获取HTML内容
            html_content = note_data.get('html', '')
            if not html_content:
                # 尝试单独获取HTML
                html_content = self.api_client.get_note_html(note_guid)
                if not html_content:
                    logger.error(f"无法获取笔记HTML: {note_title}")
                    return False
            
            # 提取资源（图片等）
            resources = self._extract_resources_from_html(html_content)
            
            # 转换内容
            if self.converter and self.config['format']['convert_to_markdown']:
                # 转换为Markdown
                markdown_content, extracted_resources = self.converter.convert(
                    html_content,
                    note_info,
                    resources
                )
                
                # 保存笔记
                note_path = self.storage.save_note(
                    self.kb_name,  # 使用当前知识库名称
                    folder_path,
                    note_info,
                    markdown_content,
                    'md'
                )
                
                # 处理提取的资源（如base64图片）
                if note_path and extracted_resources:
                    for resource in extracted_resources:
                        if resource.get('type') == 'base64' and resource.get('data'):
                            self.storage.save_resource(
                                note_path,
                                resource['filename'],
                                resource['data']
                            )
            else:
                # 保存原始HTML
                note_path = self.storage.save_note(
                    self.kb_name,  # 使用当前知识库名称
                    folder_path,
                    note_info,
                    html_content,
                    'html'
                )
            
            if not note_path:
                return False
            
            # 下载附件
            attachments = self.api_client.get_attachments(note_guid)
            if attachments and self.config['download']['download_attachments']:
                self.stats['total_attachments'] += len(attachments)
                self._download_attachments(note_guid, note_path, attachments)
            
            # 下载资源（图片）- 从HTML中提取的
            if resources and self.config['format']['extract_images']:
                self._download_resources(note_guid, note_path, resources)
            
            return True
            
        except Exception as e:
            logger.error(f"下载笔记异常 {note_info.get('title', 'Untitled')}: {e}")
            return False
    
    def _extract_resources_from_html(self, html_content: str) -> List[str]:
        """从HTML中提取资源链接"""
        resources = []
        
        # 匹配图片标签
        img_pattern = r'<img[^>]+src="([^"]+)"'
        for match in re.finditer(img_pattern, html_content):
            src = match.group(1)
            # 检查是否是内部资源（不是http/https/data:开头的）
            if not src.startswith(('http://', 'https://', 'data:')):
                # 可能是相对路径的资源
                resource_name = os.path.basename(src)
                if resource_name and resource_name not in resources:
                    resources.append(resource_name)
        
        return resources
    
    def _download_attachments(self, note_guid: str, note_path, attachments: List[Dict]):
        """下载笔记的附件"""
        for attachment in attachments:
            try:
                att_guid = attachment.get('guid', '')
                att_name = attachment.get('name', 'attachment')
                
                if not att_guid:
                    continue
                
                # 下载附件内容
                content = self.api_client.download_attachment(note_guid, att_guid)
                
                if content:
                    # 保存附件
                    self.storage.save_attachment(
                        note_path,
                        att_name,
                        content
                    )
                    self.stats['downloaded_attachments'] += 1
                    self.stats['total_size'] += len(content)
                else:
                    self.stats['failed_attachments'] += 1
                    
            except Exception as e:
                logger.error(f"下载附件失败 {attachment.get('name', 'attachment')}: {e}")
                self.stats['failed_attachments'] += 1
                self.failed_items.append({
                    'type': 'attachment',
                    'name': attachment.get('name', 'attachment'),
                    'note_guid': note_guid,
                    'error': str(e)
                })
    
    def _download_resources(self, note_guid: str, note_path, resources: List[str]):
        """下载笔记的资源（图片等）
        
        注意：官方API可能没有专门的资源下载接口，
        这些资源可能已经包含在HTML中或需要特殊处理
        """
        # 这里暂时只记录日志，因为资源可能已经在HTML中
        if resources:
            logger.debug(f"笔记 {note_guid} 包含 {len(resources)} 个资源引用")
    
    def _print_statistics(self):
        """打印下载统计信息"""
        duration = self.stats['end_time'] - self.stats['start_time']
        
        print("\n" + "=" * 50)
        print("备份完成！")
        print("=" * 50)
        print(f"总耗时: {duration:.2f} 秒")
        print(f"处理笔记: {self.stats['total_notes']}")
        print(f"下载笔记: {self.stats['downloaded_notes']}")
        print(f"跳过笔记: {self.stats['skipped_notes']}")
        print(f"失败笔记: {self.stats['failed_notes']}")
        
        if self.stats['total_attachments'] > 0:
            print(f"下载附件: {self.stats['downloaded_attachments']} / {self.stats['total_attachments']}")
            print(f"失败附件: {self.stats['failed_attachments']}")
        
        print(f"总大小: {self.stats['total_size'] / 1024 / 1024:.2f} MB")
        
        if self.failed_items:
            print(f"\n失败项目 ({len(self.failed_items)} 个):")
            for item in self.failed_items[:10]:  # 只显示前10个
                print(f"  - [{item['type']}] {item.get('title', item.get('name'))}: {item['error']}")
            
            if len(self.failed_items) > 10:
                print(f"  ... 还有 {len(self.failed_items) - 10} 个失败项目")
        
        # 存储统计信息
        storage_stats = self.storage.get_statistics()
        print(f"\n存储统计:")
        print(f"  总笔记数: {storage_stats['total_notes']}")
        print(f"  总文件数: {storage_stats['total_files']}")
        print(f"  存储大小: {storage_stats['total_size_mb']} MB")