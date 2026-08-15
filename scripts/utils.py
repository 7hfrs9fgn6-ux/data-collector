#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 通用工具函数
"""

import json
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional


def load_config(config_path: str = "config.yaml") -> Dict:
    """加载配置文件"""
    import yaml
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def save_json(data: Any, filepath: str) -> bool:
    """保存JSON文件"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存失败: {e}")
        return False


def load_json(filepath: str) -> Optional[Any]:
    """加载JSON文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def generate_fingerprint(text: str) -> str:
    """生成内容指纹（用于去重）"""
    return hashlib.md5(text.encode('utf-8')).hexdigest()


def sign_data(data: Dict, secret_key: str) -> str:
    """
    使用 HMAC-SHA256 对数据进行签名
    """
    content = json.dumps(data, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        secret_key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def verify_signature(data: Dict, signature: str, secret_key: str) -> bool:
    """验证数据签名"""
    expected = sign_data(data, secret_key)
    return hmac.compare_digest(expected, signature)


def is_expired(timestamp: str, ttl_hours: int = 24) -> bool:
    """检查时间戳是否过期"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return (datetime.now().astimezone() - dt).total_seconds() > ttl_hours * 3600
    except Exception:
        return True


def get_timestamp() -> str:
    """获取当前时间戳（ISO格式）"""
    return datetime.now().isoformat()


def safe_get(data: Dict, keys: List[str], default=None):
    """安全获取嵌套字典的值"""
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key)
        if data is None:
            return default
    return data


def truncate_text(text: str, max_length: int = 500) -> str:
    """截断文本"""
    if len(text) <= max_length:
        return text
    return text[:max_length] + "..."
