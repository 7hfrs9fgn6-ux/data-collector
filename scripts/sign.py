#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据签名模块
对采集的数据进行 HMAC-SHA256 签名，防止篡改
★ ★ ★ 2026-08-19 升级：支持多目录扫描 ★ ★ ★
   - 自动扫描 staging/ 和 data/knowledge/ 目录
   - 支持通过 --input-dir 参数指定自定义目录
   - 密钥为空时使用默认密钥（确保签名结构完整）
"""

import os
import hmac
import hashlib
import json
import glob
import argparse
from typing import Dict, Any, Optional, List
from datetime import datetime


# ============================================================
# 工具函数
# ============================================================

def get_timestamp() -> str:
    """获取当前时间戳（ISO 格式）"""
    return datetime.now().isoformat()


def load_json(filepath: str) -> Optional[Dict[str, Any]]:
    """加载 JSON 文件"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"   ⚠️ 读取失败 {filepath}: {e}")
        return None


def save_json(data: Dict[str, Any], filepath: str) -> bool:
    """保存 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(filepath) or '.', exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"   ⚠️ 保存失败 {filepath}: {e}")
        return False


# ============================================================
# 签名器
# ============================================================

class DataSigner:
    """数据签名器"""

    # 默认密钥（用于签名结构完整，但实际应使用环境变量）
    DEFAULT_KEY = "v-system-default-signing-key-2026"

    def __init__(self, secret_key: Optional[str] = None):
        """
        初始化签名器

        Args:
            secret_key: 签名密钥，如果不提供则从环境变量读取
        """
        self.secret_key = secret_key or os.environ.get('SIGNING_KEY', '')
        self.algorithm = 'HMAC-SHA256'

        if not self.secret_key:
            print("   ⚠️ 签名密钥未设置，使用默认密钥（非生产环境）")
            self.secret_key = self.DEFAULT_KEY

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
                    "signed_at": "2026-08-19T10:00:00",
                    "algorithm": "HMAC-SHA256"
                }
        """
        # 如果数据已经包含 payload 和 signature，直接返回
        if 'payload' in data and 'signature' in data:
            # 检查是否缺少 algorithm
            if 'algorithm' not in data:
                data['algorithm'] = self.algorithm
            return data

        # 复制数据，移除可能存在的旧签名字段
        payload = {k: v for k, v in data.items()
                   if k not in ['signature', 'signed_at', 'algorithm', '_unsigned']}

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
        if 'signature' not in signed_data:
            return False, "缺少签名字段"

        if 'payload' not in signed_data:
            return False, "缺少数据载荷"

        signature = signed_data.get('signature', '')
        payload = signed_data.get('payload', {})

        content = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        expected = hmac.new(
            self.secret_key.encode('utf-8'),
            content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

        if hmac.compare_digest(signature, expected):
            return True, "签名验证通过"
        else:
            return False, "签名验证失败"


# ============================================================
# 签名函数
# ============================================================

def sign_data_file(input_file: str, output_file: str, secret_key: Optional[str] = None) -> bool:
    """
    对数据文件进行签名

    Args:
        input_file: 输入文件路径（JSON）
        output_file: 输出文件路径（JSON）
        secret_key: 签名密钥（可选）

    Returns:
        bool: 是否成功
    """
    data = load_json(input_file)
    if not data:
        print(f"   ❌ 读取文件失败: {input_file}")
        return False

    signer = DataSigner(secret_key)
    signed_data = signer.sign(data)

    return save_json(signed_data, output_file)


def sign_files_in_directory(
    directory: str,
    pattern: str = "*.json",
    suffix: str = "_signed",
    secret_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    对目录下所有匹配的文件进行签名

    Args:
        directory: 要扫描的目录
        pattern: 文件匹配模式
        suffix: 输出文件后缀
        secret_key: 签名密钥

    Returns:
        Dict: 签名结果统计
    """
    signer = DataSigner(secret_key)
    results = {
        "directory": directory,
        "total": 0,
        "signed": 0,
        "failed": 0,
        "skipped": 0,
        "already_signed": 0,
        "details": []
    }

    # 构建搜索路径
    search_path = os.path.join(directory, pattern)
    files = glob.glob(search_path)

    if not files:
        print(f"   ℹ️ 目录 {directory} 无匹配文件")
        return results

    print(f"   📂 扫描目录: {directory} (找到 {len(files)} 个文件)")

    for filepath in files:
        # 跳过已签名的文件
        if '_signed' in filepath or '.signed' in filepath:
            results['skipped'] += 1
            continue

        # 检查是否已有签名结构
        data = load_json(filepath)
        if data and 'payload' in data and 'signature' in data:
            # 验证现有签名
            valid, msg = signer.verify(data)
            if valid:
                results['already_signed'] += 1
                results['details'].append({"file": filepath, "status": "already_valid"})
                continue
            # 签名无效，重新签名

        # 进行签名
        output_path = filepath.replace('.json', f'{suffix}.json')
        if sign_data_file(filepath, output_path, secret_key):
            results['signed'] += 1
            results['details'].append({"file": filepath, "status": "signed", "output": output_path})
        else:
            results['failed'] += 1
            results['details'].append({"file": filepath, "status": "failed"})

        results['total'] += 1

    return results


def sign_staging_files(secret_key: Optional[str] = None) -> Dict[str, Any]:
    """
    对暂存区所有文件进行签名（兼容旧接口）

    Returns:
        Dict: 签名结果统计
    """
    return sign_files_in_directory("staging", "*.json", "_signed", secret_key)


def sign_knowledge_files(secret_key: Optional[str] = None) -> Dict[str, Any]:
    """
    对知识数据文件进行签名

    Returns:
        Dict: 签名结果统计
    """
    return sign_files_in_directory("data/knowledge", "knowledge_package_*.json", "_signed", secret_key)


def sign_all_files(secret_key: Optional[str] = None) -> Dict[str, Any]:
    """
    对所有目录的文件进行签名

    Returns:
        Dict: 签名结果统计
    """
    results = {
        "directories": {},
        "total_signed": 0,
        "total_failed": 0,
        "total_skipped": 0
    }

    # 1. 签名暂存区
    staging_result = sign_staging_files(secret_key)
    results["directories"]["staging"] = staging_result
    results["total_signed"] += staging_result["signed"]
    results["total_failed"] += staging_result["failed"]
    results["total_skipped"] += staging_result["skipped"] + staging_result["already_signed"]

    # 2. 签名知识数据
    knowledge_result = sign_knowledge_files(secret_key)
    results["directories"]["knowledge"] = knowledge_result
    results["total_signed"] += knowledge_result["signed"]
    results["total_failed"] += knowledge_result["failed"]
    results["total_skipped"] += knowledge_result["skipped"] + knowledge_result["already_signed"]

    return results


# ============================================================
# 主入口
# ============================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="数据签名工具")
    parser.add_argument("--input-dir", type=str, default=None,
                       help="指定输入目录（覆盖默认扫描）")
    parser.add_argument("--pattern", type=str, default="*.json",
                       help="文件匹配模式（默认: *.json）")
    parser.add_argument("--suffix", type=str, default="_signed",
                       help="输出文件后缀（默认: _signed）")
    parser.add_argument("--all", action="store_true",
                       help="扫描所有目录（staging + data/knowledge）")
    parser.add_argument("--key", type=str, default=None,
                       help="签名密钥（默认从环境变量读取）")

    args = parser.parse_args()

    # 优先使用命令行指定的密钥
    secret_key = args.key or os.environ.get('SIGNING_KEY', '')

    # 执行签名
    if args.input_dir:
        result = sign_files_in_directory(args.input_dir, args.pattern, args.suffix, secret_key)
        print(f"签名完成: 目录 {result['directory']}, "
              f"签名 {result['signed']} 个, "
              f"跳过 {result['skipped']} 个, "
              f"失败 {result['failed']} 个")
    elif args.all:
        result = sign_all_files(secret_key)
        print(f"签名完成: 总计签名 {result['total_signed']} 个, "
              f"失败 {result['total_failed']} 个, "
              f"跳过 {result['total_skipped']} 个")
    else:
        # 默认：只签名 staging 目录（兼容旧行为）
        result = sign_staging_files(secret_key)
        print(f"签名完成: 总计 {result['total']} 个文件, "
              f"签名 {result['signed']} 个, "
              f"跳过 {result['skipped']} 个, "
              f"失败 {result['failed']} 个")
