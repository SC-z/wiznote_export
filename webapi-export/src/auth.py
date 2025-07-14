#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
为知笔记认证模块
处理登录、Token管理等认证相关功能
基于官方API文档实现
"""

import os
import json
import time
import hashlib
import requests
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import logging
from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)


class WizNoteAuth:
    """为知笔记认证管理器"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.as_url = config['api']['as_url']  # Account Server URL
        self.username = config['auth']['username']
        self.password = config['auth']['password']
        self.token_file = config['auth']['token_file']
        self.save_token = config['auth']['save_token']
        
        # 认证相关信息
        self.token = None
        self.kb_guid = None  # 当前知识库GUID
        self.kb_server = None  # 当前知识库服务器地址
        self.user_guid = None
        self.token_expiry = None
        self.kb_list = []  # 所有知识库列表（个人+团队）
        
        # 加密密钥（实际使用时应该更安全地管理）
        self._cipher_suite = None
        if self.save_token:
            self._init_encryption()
    
    def _init_encryption(self):
        """初始化加密"""
        key_file = os.path.join(os.path.dirname(self.token_file), '.key')
        if os.path.exists(key_file):
            with open(key_file, 'rb') as f:
                key = f.read()
        else:
            key = Fernet.generate_key()
            os.makedirs(os.path.dirname(key_file), exist_ok=True)
            with open(key_file, 'wb') as f:
                f.write(key)
        self._cipher_suite = Fernet(key)
    
    def _load_saved_token(self) -> bool:
        """加载保存的Token"""
        if not self.save_token or not os.path.exists(self.token_file):
            return False
        
        try:
            with open(self.token_file, 'rb') as f:
                encrypted_data = f.read()
            
            decrypted_data = self._cipher_suite.decrypt(encrypted_data)
            token_data = json.loads(decrypted_data.decode())
            
            # 检查是否过期
            expiry = datetime.fromisoformat(token_data['expiry'])
            if expiry > datetime.now():
                self.token = token_data['token']
                self.kb_guid = token_data['kb_guid']
                self.kb_server = token_data['kb_server']
                self.user_guid = token_data.get('user_guid')
                self.token_expiry = expiry
                self.kb_list = token_data.get('kb_list', [])
                logger.info("使用保存的Token")
                return True
            else:
                logger.info("保存的Token已过期")
                return False
        except Exception as e:
            logger.error(f"加载Token失败: {e}")
            return False
    
    def _save_token(self):
        """保存Token到文件"""
        if not self.save_token or not self.token:
            return
        
        try:
            token_data = {
                'token': self.token,
                'kb_guid': self.kb_guid,
                'kb_server': self.kb_server,
                'user_guid': self.user_guid,
                'kb_list': self.kb_list,
                'expiry': self.token_expiry.isoformat()
            }
            
            encrypted_data = self._cipher_suite.encrypt(
                json.dumps(token_data).encode()
            )
            
            os.makedirs(os.path.dirname(self.token_file), exist_ok=True)
            with open(self.token_file, 'wb') as f:
                f.write(encrypted_data)
            
            logger.info("Token已保存")
        except Exception as e:
            logger.error(f"保存Token失败: {e}")
    
    def login(self) -> bool:
        """登录获取Token"""
        # 首先尝试使用保存的Token
        if self._load_saved_token():
            return True
        
        # 执行登录
        logger.info(f"正在登录: {self.username}")
        
        # 根据官方文档，登录接口在AS服务器
        login_url = f"{self.as_url}/as/user/login"
        
        # 准备登录数据
        login_data = {
            "userId": self.username,
            "password": self.password  # 官方API直接使用明文密码
        }
        
        try:
            response = requests.post(
                login_url,
                json=login_data,
                timeout=self.config['api']['timeout']
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('returnCode') == 200:
                    # 从响应中获取认证信息
                    auth_result = result['result']
                    
                    # 调试：打印完整响应
                    logger.debug(f"登录响应: {json.dumps(result, indent=2, ensure_ascii=False)}")
                    
                    # 检查是否有额外的团队信息
                    if 'bizUserList' in auth_result:
                        logger.info(f"发现团队信息: {len(auth_result['bizUserList'])} 个团队")
                        for biz_user in auth_result['bizUserList']:
                            self.kb_list.append({
                                'kbGuid': biz_user.get('kbGuid'),
                                'kbServer': biz_user.get('kbServer'),
                                'name': f"{biz_user.get('bizName', 'Unknown')} - 团队笔记",
                                'type': 'team',
                                'bizName': biz_user.get('bizName'),
                                'bizGuid': biz_user.get('bizGuid')
                            })
                    
                    self.token = auth_result['token']
                    self.kb_guid = auth_result['kbGuid']
                    self.kb_server = auth_result['kbServer']
                    self.user_guid = auth_result.get('userGuid', self.username)
                    self.token_expiry = datetime.now() + timedelta(hours=24)
                    
                    # 获取所有知识库列表
                    self._get_kb_list()
                    
                    # 保存Token
                    self._save_token()
                    
                    logger.info(f"登录成功，知识库服务器: {self.kb_server}")
                    return True
                else:
                    logger.error(f"登录失败: {result.get('returnMessage', 'Unknown error')}")
                    return False
            else:
                logger.error(f"登录请求失败: HTTP {response.status_code}")
                return False
                
        except requests.RequestException as e:
            logger.error(f"登录请求异常: {e}")
            return False
    
    def _get_kb_list(self):
        """获取所有知识库列表（个人+团队）"""
        try:
            # 添加个人知识库
            self.kb_list = [{
                'kbGuid': self.kb_guid,
                'kbServer': self.kb_server,
                'name': '个人笔记',
                'type': 'personal',
                'bizName': None,
                'bizGuid': None
            }]
            
            # 获取团队知识库列表
            # 根据文档，使用 /as/biz/user_kb_list API
            # 注意：此时登录已完成，可以使用token
            try:
                # 先获取所有biz（企业/团队）
                biz_url = f"{self.as_url}/as/api/biz/joined"
                headers = {
                    "X-Wiz-Token": self.token,
                    "Content-Type": "application/json",
                    "User-Agent": "WizNote-Team-Backup/1.0"
                }
                
                logger.debug(f"获取团队列表: {biz_url}")
                response = requests.get(
                    biz_url,
                    headers=headers,
                    timeout=self.config['api']['timeout']
                )
                
                logger.debug(f"团队列表响应: {response.status_code}")
                if response.status_code == 200:
                    biz_result = response.json()
                    if biz_result.get('returnCode') == 200:
                        biz_list = biz_result.get('result', [])
                        
                        # 对每个biz获取知识库
                        for biz in biz_list:
                            biz_guid = biz.get('bizGuid')
                            biz_name = biz.get('bizName', 'Unknown')
                            
                            # 获取该biz的知识库
                            kb_url = f"{self.as_url}/as/biz/user_kb_list?bizGuid={biz_guid}"
                            kb_response = requests.get(
                                kb_url,
                                headers=headers,  # 使用同样的headers
                                timeout=self.config['api']['timeout']
                            )
                            
                            if kb_response.status_code == 200:
                                kb_result = kb_response.json()
                                if kb_result.get('returnCode') == 200:
                                    kb_info = kb_result.get('result', {})
                                    if kb_info:
                                        self.kb_list.append({
                                            'kbGuid': kb_info.get('kbGuid'),
                                            'kbServer': kb_info.get('kbServer'),
                                            'name': f"{biz_name} - 团队笔记",
                                            'type': 'team',
                                            'bizName': biz_name,
                                            'bizGuid': biz_guid
                                        })
            except Exception as e:
                logger.warning(f"获取团队知识库失败: {e}")
            
            logger.info(f"获取到 {len(self.kb_list)} 个知识库")
        except Exception as e:
            logger.error(f"获取知识库列表失败: {e}")
    
    def refresh_token(self) -> bool:
        """刷新Token"""
        # 如果Token还有效，不需要刷新
        if self.is_token_valid():
            return True
        
        # 重新登录
        logger.info("Token已过期，重新登录")
        return self.login()
    
    def is_token_valid(self) -> bool:
        """检查Token是否有效"""
        if not self.token or not self.token_expiry:
            return False
        
        # 提前5分钟过期，避免边界情况
        return datetime.now() < self.token_expiry - timedelta(minutes=5)
    
    def get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        if not self.is_token_valid():
            self.refresh_token()
        
        return {
            "X-Wiz-Token": self.token,  # 根据官方文档使用X-Wiz-Token
            "Content-Type": "application/json",
            "User-Agent": "WizNote-Team-Backup/1.0"
        }
    
    def get_kb_info(self) -> Dict:
        """获取当前知识库信息"""
        return {
            'kb_guid': self.kb_guid,
            'kb_server': self.kb_server,
            'user_guid': self.user_guid
        }
    
    def get_kb_list(self) -> List[Dict]:
        """获取所有知识库列表"""
        return self.kb_list
    
    def switch_kb(self, kb_guid: str) -> bool:
        """切换到指定知识库"""
        for kb in self.kb_list:
            if kb['kbGuid'] == kb_guid:
                self.kb_guid = kb['kbGuid']
                self.kb_server = kb['kbServer']
                logger.info(f"切换到知识库: {kb['name']} ({kb_guid})")
                return True
        
        logger.error(f"未找到知识库: {kb_guid}")
        return False


if __name__ == "__main__":
    # 测试代码
    import sys
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    
    # 读取配置
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config', 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # 测试认证
    auth = WizNoteAuth(config)
    if auth.login():
        print(f"登录成功！")
        print(f"Token: {auth.token[:20]}...")
        print(f"当前知识库GUID: {auth.kb_guid}")
        print(f"当前知识库服务器: {auth.kb_server}")
        print(f"\n知识库列表:")
        for kb in auth.get_kb_list():
            print(f"  - {kb['name']} ({kb['type']}) - {kb['kbGuid']}")
    else:
        print("登录失败！")