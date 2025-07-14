#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记API客户端
基于官方API文档实现
"""

import os
import json
import time
import requests
from typing import Dict, List, Optional, Generator
from functools import wraps
import logging
from tenacity import retry, stop_after_attempt, wait_exponential
from urllib.parse import quote

logger = logging.getLogger(__name__)


def rate_limit(calls_per_second: int = 10):
    """限流装饰器"""
    def decorator(func):
        last_called = [0.0]
        min_interval = 1.0 / calls_per_second
        
        @wraps(func)
        def wrapper(*args, **kwargs):
            elapsed = time.time() - last_called[0]
            left_to_wait = min_interval - elapsed
            if left_to_wait > 0:
                time.sleep(left_to_wait)
            result = func(*args, **kwargs)
            last_called[0] = time.time()
            return result
        return wrapper
    return decorator


class WizNoteAPIClient:
    """为知笔记API客户端"""
    
    def __init__(self, auth, config: Dict):
        self.auth = auth
        self.config = config
        self.timeout = config['api']['timeout']
        self.rate_limit_per_second = config['api']['rate_limit_per_second']
        
        # 从认证信息获取知识库信息
        kb_info = auth.get_kb_info()
        self.kb_guid = kb_info['kb_guid']
        self.kb_server = kb_info['kb_server']
        
        # 应用限流到所有API方法
        self._apply_rate_limit()
    
    def _apply_rate_limit(self):
        """应用限流到所有API方法"""
        for attr_name in dir(self):
            attr = getattr(self, attr_name)
            if callable(attr) and not attr_name.startswith('_') and attr_name != 'request':
                setattr(self, attr_name, rate_limit(self.rate_limit_per_second)(attr))
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10)
    )
    def request(self, method: str, endpoint: str, **kwargs) -> requests.Response:
        """统一的请求方法，带重试机制"""
        # 构建完整URL
        if endpoint.startswith('/'):
            url = f"{self.kb_server}{endpoint}"
        else:
            url = endpoint
            
        headers = self.auth.get_headers()
        
        if 'headers' in kwargs:
            headers.update(kwargs['headers'])
            kwargs.pop('headers')
        
        logger.debug(f"{method} {url}")
        
        response = requests.request(
            method,
            url,
            headers=headers,
            timeout=self.timeout,
            **kwargs
        )
        
        # 检查响应
        if response.status_code == 401:
            # Token过期，刷新后重试
            logger.info("Token过期，刷新中...")
            self.auth.refresh_token()
            headers = self.auth.get_headers()
            response = requests.request(
                method,
                url,
                headers=headers,
                timeout=self.timeout,
                **kwargs
            )
        
        response.raise_for_status()
        return response
    
    def get_all_folders(self) -> List[Dict]:
        """获取所有文件夹
        
        官方API: GET /ks/category/all/:kbGuid
        """
        response = self.request('GET', f'/ks/category/all/{self.kb_guid}')
        
        if response.status_code == 200:
            try:
                result = response.json()
                if isinstance(result, list):
                    logger.info(f"获取到 {len(result)} 个文件夹")
                    return result
                elif isinstance(result, dict) and result.get('returnCode') == 200:
                    folders = result.get('result', [])
                    logger.info(f"获取到 {len(folders)} 个文件夹")
                    return folders
            except Exception as e:
                logger.error(f"解析文件夹响应失败: {e}")
        
        return []
    
    def get_notes_in_folder(self, folder_path: str = "/", 
                           start: int = 0, count: int = 100,
                           order_by: str = "modified",
                           ascending: str = "desc") -> Dict:
        """获取文件夹中的笔记列表
        
        官方API: GET /ks/note/list/category/:kbGuid
        参数:
        - category: 文件夹路径
        - start: 分页起始
        - count: 每页数量
        - orderBy: 排序字段 (title/created/modified)
        - ascending: 排序方向 (asc/desc)
        - withAbstract: 是否包含摘要
        """
        params = {
            "category": folder_path,
            "start": start,
            "count": count,
            "orderBy": order_by,
            "ascending": ascending,
            "withAbstract": "true"
        }
        
        response = self.request('GET', f'/ks/note/list/category/{self.kb_guid}', params=params)
        
        if response.status_code == 200:
            try:
                result = response.json()
                # 返回格式可能是直接的数组或包含returnCode的对象
                if isinstance(result, list):
                    return {
                        'notes': result,
                        'total': len(result)
                    }
                elif isinstance(result, dict):
                    if result.get('returnCode') == 200:
                        notes = result.get('result', [])
                        return {
                            'notes': notes,
                            'total': result.get('total', len(notes))
                        }
                    else:
                        logger.error(f"获取笔记列表失败: {result.get('returnMessage')}")
            except Exception as e:
                logger.error(f"解析笔记列表响应失败: {e}")
        
        return {'notes': [], 'total': 0}
    
    def get_all_notes_in_folder(self, folder_path: str = "/") -> Generator[Dict, None, None]:
        """获取文件夹中的所有笔记（自动分页）"""
        start = 0
        count = 100
        
        while True:
            result = self.get_notes_in_folder(folder_path, start, count)
            notes = result['notes']
            
            if not notes:
                break
            
            for note in notes:
                yield note
            
            start += len(notes)
            
            # 如果返回的笔记数少于请求数，说明已经到最后一页
            if len(notes) < count:
                break
    
    def get_note_info(self, doc_guid: str) -> Optional[Dict]:
        """获取笔记信息
        
        官方API: GET /ks/note/view/:kbGuid/:docGuid/
        """
        try:
            response = self.request('GET', f'/ks/note/view/{self.kb_guid}/{doc_guid}/')
            
            if response.status_code == 200:
                # 检查响应内容
                content_type = response.headers.get('content-type', '')
                
                if 'application/json' in content_type:
                    try:
                        result = response.json()
                        if isinstance(result, dict):
                            if result.get('returnCode') == 200:
                                return result.get('result')
                            else:
                                logger.error(f"获取笔记信息失败: {result.get('returnMessage')}")
                        else:
                            # 可能直接返回笔记信息
                            return result
                    except Exception as e:
                        logger.error(f"解析笔记信息响应失败: {e}")
                else:
                    # 可能是HTML内容
                    logger.debug(f"获取到非JSON响应，内容类型: {content_type}")
                    return None
        except Exception as e:
            logger.error(f"获取笔记信息异常: {e}")
        
        return None
    
    def download_note(self, doc_guid: str, download_info: bool = True, 
                     download_data: bool = True) -> Optional[Dict]:
        """下载笔记内容
        
        官方API: GET /ks/note/download/:kbGuid/:docGuid
        参数:
        - downloadInfo: 是否下载笔记信息
        - downloadData: 是否下载笔记数据
        """
        params = {
            "downloadInfo": 1 if download_info else 0,
            "downloadData": 1 if download_data else 0
        }
        
        response = self.request('GET', f'/ks/note/download/{self.kb_guid}/{doc_guid}', params=params)
        
        if response.status_code == 200:
            # 检查响应类型
            content_type = response.headers.get('content-type', '')
            
            if 'application/json' in content_type:
                # JSON响应，包含笔记信息和内容
                try:
                    result = response.json()
                    if isinstance(result, dict) and result.get('returnCode') == 200:
                        return result.get('result')
                    return result
                except Exception as e:
                    logger.error(f"解析笔记下载响应失败: {e}")
            else:
                # 可能是HTML内容
                return {
                    'html': response.text,
                    'guid': doc_guid
                }
        
        return None
    
    def get_note_html(self, doc_guid: str) -> Optional[str]:
        """获取笔记的HTML内容"""
        note_data = self.download_note(doc_guid, download_info=False, download_data=True)
        
        if note_data:
            if isinstance(note_data, dict):
                return note_data.get('html', '')
            elif isinstance(note_data, str):
                return note_data
        
        return None
    
    def get_attachments(self, doc_guid: str) -> List[Dict]:
        """获取笔记的附件列表
        
        注意：官方API文档中没有明确的获取附件列表接口
        可能需要从笔记内容中解析或使用其他方式
        """
        # 尝试从笔记信息中获取附件
        note_info = self.get_note_info(doc_guid)
        if note_info and 'attachments' in note_info:
            return note_info['attachments']
        
        return []
    
    def download_attachment(self, doc_guid: str, att_guid: str) -> Optional[bytes]:
        """下载附件
        
        官方API: GET /ks/attachment/download/:kbGuid/:docGuid/:attGuid
        """
        response = self.request(
            'GET', 
            f'/ks/attachment/download/{self.kb_guid}/{doc_guid}/{att_guid}',
            stream=True
        )
        
        if response.status_code == 200:
            # 流式下载大文件
            chunks = []
            for chunk in response.iter_content(chunk_size=self.config['download']['chunk_size']):
                if chunk:
                    chunks.append(chunk)
            return b''.join(chunks)
        else:
            logger.error(f"下载附件失败: HTTP {response.status_code}")
            return None
    
    def create_folder(self, parent_folder: str, folder_name: str) -> bool:
        """创建文件夹
        
        官方API: POST /ks/category/create/:kbGuid
        """
        data = {
            "parent": parent_folder,
            "name": folder_name
        }
        
        response = self.request('POST', f'/ks/category/create/{self.kb_guid}', json=data)
        
        if response.status_code == 200:
            result = response.json()
            if result.get('returnCode') == 200:
                logger.info(f"创建文件夹成功: {parent_folder}/{folder_name}")
                return True
            else:
                logger.error(f"创建文件夹失败: {result.get('returnMessage')}")
        
        return False


if __name__ == "__main__":
    # 测试代码
    import sys
    from auth import WizNoteAuth
    
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # 读取配置
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # 设置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 测试API客户端
    auth = WizNoteAuth(config)
    if auth.login():
        client = WizNoteAPIClient(auth, config)
        
        # 获取文件夹
        print("\n测试获取文件夹...")
        folders = client.get_all_folders()
        if folders:
            print(f"获取到 {len(folders)} 个文件夹")
            # 检查数据格式
            if folders:
                print(f"第一个文件夹数据类型: {type(folders[0])}")
                if isinstance(folders[0], str):
                    print(f"文件夹列表 (前5个): {folders[:5]}")
                else:
                    print(f"文件夹列表 (前5个): {[f.get('name', str(f)) for f in folders[:5]]}")
                
                # 获取根目录的笔记
                print(f"\n获取根目录中的笔记...")
                notes_result = client.get_notes_in_folder("/", count=5)
                notes = notes_result['notes']
                if notes:
                    print(f"找到 {len(notes)} 个笔记")
                    for note in notes[:3]:
                        print(f"  - {note.get('title', 'Untitled')}")
    else:
        print("登录失败！")