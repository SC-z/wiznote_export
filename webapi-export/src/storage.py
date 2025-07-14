#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
本地存储管理模块
负责文件的保存、组织和元数据管理
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, List
import logging
import re

logger = logging.getLogger(__name__)


class LocalStorage:
    """本地存储管理器"""
    
    def __init__(self, base_path: str, preserve_structure: bool = True):
        self.base_path = Path(base_path)
        self.preserve_structure = preserve_structure
        self.metadata_dir = self.base_path / '_metadata'
        
        # 创建基础目录
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(exist_ok=True)
        
        # 笔记索引
        self.note_index = {}
        self.load_index()
    
    def load_index(self):
        """加载笔记索引"""
        index_file = self.metadata_dir / 'index.json'
        if index_file.exists():
            try:
                with open(index_file, 'r', encoding='utf-8') as f:
                    self.note_index = json.load(f)
                logger.info(f"加载了 {len(self.note_index)} 条索引记录")
            except Exception as e:
                logger.error(f"加载索引失败: {e}")
                self.note_index = {}
    
    def save_index(self):
        """保存笔记索引"""
        index_file = self.metadata_dir / 'index.json'
        try:
            with open(index_file, 'w', encoding='utf-8') as f:
                json.dump(self.note_index, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存索引失败: {e}")
    
    def sanitize_filename(self, filename: str) -> str:
        """清理文件名，移除非法字符"""
        # Windows文件名非法字符
        illegal_chars = '<>:"|?*\r\n\t'
        for char in illegal_chars:
            filename = filename.replace(char, '_')
        
        # 移除前后空格和点
        filename = filename.strip(' .')
        
        # 限制长度
        name, ext = os.path.splitext(filename)
        if len(name) > 200:
            name = name[:200]
        
        return name + ext
    
    def get_team_path(self, team_name: str) -> Path:
        """获取团队目录路径"""
        safe_name = self.sanitize_filename(team_name)
        return self.base_path / safe_name
    
    def get_note_path(self, team_name: str, folder_path: str, 
                      note_title: str, note_guid: str) -> Path:
        """获取笔记文件路径"""
        team_path = self.get_team_path(team_name)
        
        if self.preserve_structure and folder_path:
            # 保持原始文件夹结构
            folder_parts = [self.sanitize_filename(part) 
                          for part in folder_path.strip('/').split('/') 
                          if part]
            note_dir = team_path / Path(*folder_parts)
        else:
            # 扁平化存储
            note_dir = team_path
        
        # 创建目录
        note_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名
        safe_title = self.sanitize_filename(note_title)
        filename = f"{safe_title}.md"
        
        # 处理重名
        file_path = note_dir / filename
        if file_path.exists():
            # 检查是否是同一个笔记
            existing_guid = self.get_note_guid_by_path(str(file_path))
            if existing_guid != note_guid:
                # 不同笔记，添加GUID后缀
                name, ext = os.path.splitext(filename)
                filename = f"{name}_{note_guid[:8]}{ext}"
                file_path = note_dir / filename
        
        return file_path
    
    def get_note_guid_by_path(self, file_path: str) -> Optional[str]:
        """根据文件路径获取笔记GUID"""
        for guid, info in self.note_index.items():
            if info.get('file_path') == file_path:
                return guid
        return None
    
    def save_note(self, team_name: str, folder_path: str, note: Dict, 
                  content: str, format: str = 'md') -> Optional[Path]:
        """保存笔记内容"""
        try:
            # 获取文件路径
            file_path = self.get_note_path(
                team_name, 
                folder_path,
                note['title'],
                note['guid']
            )
            
            # 保存内容
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            
            # 更新索引
            self.note_index[note['guid']] = {
                'title': note['title'],
                'file_path': str(file_path),
                'team': team_name,
                'folder': folder_path,
                'created': note.get('created'),
                'modified': note.get('modified'),
                'tags': note.get('tags', []),
                'format': format,
                'saved_at': datetime.now().isoformat()
            }
            
            logger.info(f"保存笔记: {file_path}")
            return file_path
            
        except Exception as e:
            logger.error(f"保存笔记失败 {note['title']}: {e}")
            return None
    
    def get_attachment_dir(self, note_path: Path) -> Path:
        """获取笔记的附件目录"""
        note_dir = note_path.parent
        return note_dir / 'assets'
    
    def save_attachment(self, note_path: Path, attachment_name: str, 
                       content: bytes) -> Optional[Path]:
        """保存附件"""
        try:
            # 创建附件目录
            attachment_dir = self.get_attachment_dir(note_path)
            attachment_dir.mkdir(exist_ok=True)
            
            # 清理文件名
            safe_name = self.sanitize_filename(attachment_name)
            attachment_path = attachment_dir / safe_name
            
            # 处理重名
            if attachment_path.exists():
                name, ext = os.path.splitext(safe_name)
                counter = 1
                while attachment_path.exists():
                    attachment_path = attachment_dir / f"{name}_{counter}{ext}"
                    counter += 1
            
            # 保存文件
            with open(attachment_path, 'wb') as f:
                f.write(content)
            
            logger.info(f"保存附件: {attachment_path}")
            return attachment_path
            
        except Exception as e:
            logger.error(f"保存附件失败 {attachment_name}: {e}")
            return None
    
    def save_resource(self, note_path: Path, resource_name: str, 
                     content: bytes) -> Optional[Path]:
        """保存资源（图片等）"""
        # 资源也保存在assets目录
        return self.save_attachment(note_path, resource_name, content)
    
    def get_sync_state(self) -> Dict:
        """获取同步状态"""
        sync_file = self.metadata_dir / 'sync_state.json'
        if sync_file.exists():
            try:
                with open(sync_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"加载同步状态失败: {e}")
        
        return {
            'last_sync': None,
            'synced_teams': {},
            'failed_notes': []
        }
    
    def save_sync_state(self, state: Dict):
        """保存同步状态"""
        sync_file = self.metadata_dir / 'sync_state.json'
        try:
            with open(sync_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存同步状态失败: {e}")
    
    def is_note_modified(self, note_guid: str, modified_time: str) -> bool:
        """检查笔记是否被修改"""
        if note_guid not in self.note_index:
            return True  # 新笔记
        
        saved_info = self.note_index[note_guid]
        saved_modified = saved_info.get('modified')
        
        if not saved_modified:
            return True
        
        # 比较修改时间
        return modified_time > saved_modified
    
    def get_statistics(self) -> Dict:
        """获取存储统计信息"""
        total_notes = len(self.note_index)
        teams = {}
        
        for note_info in self.note_index.values():
            team = note_info['team']
            if team not in teams:
                teams[team] = 0
            teams[team] += 1
        
        # 计算存储大小
        total_size = 0
        file_count = 0
        for path in self.base_path.rglob('*'):
            if path.is_file():
                total_size += path.stat().st_size
                file_count += 1
        
        return {
            'total_notes': total_notes,
            'teams': teams,
            'total_files': file_count,
            'total_size': total_size,
            'total_size_mb': round(total_size / 1024 / 1024, 2)
        }
    
    def cleanup_empty_dirs(self):
        """清理空目录"""
        for dirpath, dirnames, filenames in os.walk(self.base_path, topdown=False):
            if not dirnames and not filenames and dirpath != str(self.base_path):
                try:
                    os.rmdir(dirpath)
                    logger.debug(f"删除空目录: {dirpath}")
                except Exception as e:
                    logger.error(f"删除目录失败 {dirpath}: {e}")
    
    def __del__(self):
        """析构时保存索引"""
        self.save_index()


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 创建存储管理器
    storage = LocalStorage("./test_output")
    
    # 测试保存笔记
    test_note = {
        'guid': 'test-guid-123',
        'title': '测试笔记',
        'created': '2024-01-01T10:00:00',
        'modified': '2024-01-01T11:00:00',
        'tags': ['测试', 'demo']
    }
    
    content = "# 测试笔记\n\n这是一个测试内容。"
    
    note_path = storage.save_note(
        team_name="测试团队",
        folder_path="/测试文件夹/子文件夹",
        note=test_note,
        content=content
    )
    
    if note_path:
        print(f"笔记保存成功: {note_path}")
        
        # 测试保存附件
        test_attachment = b"This is a test attachment content."
        att_path = storage.save_attachment(
            note_path,
            "测试附件.txt",
            test_attachment
        )
        
        if att_path:
            print(f"附件保存成功: {att_path}")
    
    # 显示统计信息
    stats = storage.get_statistics()
    print(f"存储统计: {stats}")