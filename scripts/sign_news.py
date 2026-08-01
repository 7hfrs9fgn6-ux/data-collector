#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻签名脚本
使用 HMAC-SHA256 对数据包进行签名
"""

import os
import sys
import json
import hashlib
import hmac
import glob
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_signing_key() -> str:
    """获取签名密钥（从环境变量）"""
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，使用默认测试密钥")
        # 测试用默认密钥（生产环境必须配置）
        return "test-key-do-not-use-in-production"
    return key


def sign_package(data: dict, key: str) -> str:
    """对数据包进行HMAC-SHA256签名"""
    # 排除signature字段本身，计算其余内容的签名
    sign_data = data.copy()
    sign_data.pop('signature', None)

    # 序列化为JSON字符串（排序保证一致性）
    json_str = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)

    # 计算HMAC
    signature = hmac.new(
        key.encode('utf-8'),
        json_str.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    return signature


def main():
    logger.info("=" * 50)
    logger.info("🔐 data-collector 新闻签名启动")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    staging_dir = "staging"
    key = get_signing_key()

    # 查找最新的打包文件
    package_files = glob.glob(os.path.join(staging_dir, "news_package_*.json"))

    if not package_files:
        logger.warning("⚠️ 未找到打包文件")
        # 尝试查找其他可签名文件
        filtered_files = glob.glob(os.path.join(staging_dir, "filtered_news_*.json"))
        if filtered_files:
            filtered_files.sort(key=os.path.getmtime, reverse=True)
            package_files = [filtered_files[0]]
            logger.info(f"📂 使用筛选文件替代: {package_files[0]}")

    if not package_files:
        logger.error("❌ 未找到可签名的文件")
        sys.exit(1)

    package_files.sort(key=os.path.getmtime, reverse=True)
    latest_file = package_files[0]

    logger.info(f"📂 签名文件: {latest_file}")

    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 计算签名
    signature = sign_package(data, key)

    # 注入签名
    data['signature'] = signature

    # 添加签名元数据
    data['signature_metadata'] = {
        'algorithm': 'HMAC-SHA256',
        'timestamp': datetime.now().isoformat(),
        'key_version': 'v1'
    }

    # 保存签名后的文件（覆盖原文件或另存）
    if 'news_package' in latest_file:
        output_file = latest_file
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = os.path.join(staging_dir, f"news_package_signed_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 签名文件: {output_file}")
    logger.info(f"🔐 签名: {signature[:16]}...")
    logger.info("=" * 50)
    logger.info("✅ 签名完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
