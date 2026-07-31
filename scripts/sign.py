#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据签名模块
对采集的数据进行 HMAC-SHA256 签名，防止篡改
"""

import os
import hmac
import hashlib
import json
from typing import Dict, Any, Optional
from datetime import datetime

from utils import load_json, save_json, get_timestamp


class DataSigner:
    """数据签名器"""

    def __init__(self, secret_key: Optional[str] = None):
        """
        初始化签名器

        Args:
            secret_key: 签名密钥，如果不提供则从环境变量读取
        """
        self.secret_key = secret_key or os.environ.get('SIGNING_KEY', '')
        self.algorithm = 'HMAC-SHA256'

    def sign(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        对数据添加签名

        Args:
            data: 待签名的数据字典

        Returns:
            Dict: 包含签名的数据
                {
                    "payload": {...},
                    "signature": "xxxxx",
                    "signed_at": "2026-07-31T10:00:00",
                    "algorithm": "HMAC-SHA256"
                }
        """
        if not self.secret_key:
            # 如果没有密钥，只做标记不签名
            data['_unsigned'] = True
            return data

        # 复制数据，移除可能存在的旧签名字段
        payload = {k: v for k, v in data.items()
                   if k not in ['signature', 'signed_at', 'algorithm']}

        # 排序键使序列化稳定
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False)

        # 计算 HMAC-SHA256 签名
        signature = hmac.new(
            self.secret_key.encode('utf-8'),
            content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        return {
            "payload": payload,
            "signature": signature,
            "signed_at": get_timestamp(),
            "algorithm": self.algorithm
        }

    def verify(self, signed_data: Dict[str, Any]) -> tuple:
        """
        验证数据签名

        Args:
            signed_data: 包含签名的数据

        Returns:
            (is_valid, message): 是否有效，以及消息
        """
        # 检查是否有签名字段
        if not self.secret_key:
            return False, "签名密钥未配置"

        if 'signature' not in signed_data:
            return False, "缺少签名字段"

        if 'payload' not in signed_data:
            return False, "缺少数据载荷"

        # 提取签名和数据
        signature = signed_data.get('signature', '')
        payload = signed_data.get('payload', {})

        # 重新计算签名
        content = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        expected = hmac.new(
            self.secret_key.encode('utf-8'),
            content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        # 比较签名
        if hmac.compare_digest(signature, expected):
            return True, "签名验证通过"
        else:
            return False, "签名验证失败"


def sign_data_file(input_file: str, output_file: str) -> bool:
    """
    对数据文件进行签名

    Args:
        input_file: 输入文件路径（JSON）
        output_file: 输出文件路径（JSON）

    Returns:
        bool: 是否成功
    """
    data = load_json(input_file)
    if not data:
        print(f"读取文件失败: {input_file}")
        return False

    signer = DataSigner()
    signed_data = signer.sign(data)

    return save_json(signed_data, output_file)


def sign_staging_files() -> Dict[str, Any]:
    """
    对暂存区所有未签名的文件进行签名

    Returns:
        Dict: 签名结果统计
    """
    import glob

    signer = DataSigner()
    results = {
        "total": 0,
        "signed": 0,
        "failed": 0,
        "skipped": 0,
        "details": []
    }

    # 查找 staging 目录下所有 JSON 文件
    files = glob.glob("staging/*.json")

    for filepath in files:
        # 跳过已签名的文件
        if '_signed' in filepath:
            results['skipped'] += 1
            continue

        data = load_json(filepath)
        if not data:
            results['failed'] += 1
            results['details'].append({"file": filepath, "status": "failed"})
            continue

        # 检查是否已经包含签名
        if 'signature' in data and 'payload' in data:
            # 验证现有签名是否有效
            valid, msg = signer.verify(data)
            if valid:
                results['skipped'] += 1
                results['details'].append({"file": filepath, "status": "already_signed"})
                continue

        # 进行签名
        signed_data = signer.sign(data)

        # 保存到新文件
        output_path = filepath.replace('.json', '_signed.json')
        if save_json(signed_data, output_path):
            results['signed'] += 1
            results['details'].append({"file": filepath, "status": "signed", "output": output_path})
        else:
            results['failed'] += 1
            results['details'].append({"file": filepath, "status": "failed"})

        results['total'] += 1

    return results


if __name__ == "__main__":
    # 对暂存区所有文件进行签名
    result = sign_staging_files()
    print(f"签名完成: 总计 {result['total']} 个文件, "
          f"签名 {result['signed']} 个, "
          f"跳过 {result['skipped']} 个, "
          f"失败 {result['failed']} 个")
