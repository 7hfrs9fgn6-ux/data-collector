#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股数据打包模块（独立版）
用途：从 raw 数据重新打包，无需重新采集
使用：python scripts/pack_hk_stock.py --input staging/hk_stock_raw_*.json
"""

import os
import sys
import json
import argparse
import hmac
import hashlib
import logging
from datetime import datetime

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")
SIGNING_KEY = os.environ.get('SIGNING_KEY', '')


def get_signing_key() -> str:
    global SIGNING_KEY
    if not SIGNING_KEY:
        SIGNING_KEY = os.environ.get('SIGNING_KEY', '')
    return SIGNING_KEY


def sign_data(data: dict, key: str) -> str:
    if not key:
        return ""
    sign_data_content = {k: v for k, v in data.items() 
                         if k not in ['signature', 'signature_metadata']}
    content = json.dumps(sign_data_content, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


def load_raw(filepath: str) -> list:
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def repack(indices_data: list) -> dict:
    """重新打包"""
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")
    is_trading_day = len(indices_data) > 0 and any(d.get('price', 0) > 0 for d in indices_data)

    package = {
        "book": "公开数据",
        "chapter": "hk_stock",
        "version": "2.0",
        "generated_at": now.isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": False,
        "content": {
            "total": len(indices_data),
            "indices": indices_data,
        },
        "metadata": {
            "source": "akshare",
            "repacked_at": now.isoformat(),
            "data_type": "hk_stock",
        },
    }

    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
    else:
        package["signature"] = None

    return package


def save_package(package: dict) -> str:
    os.makedirs(STAGING_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"hk_stock_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)
    return filepath


def find_latest_raw() -> str:
    """找到最新的原始数据文件"""
    import glob
    pattern = os.path.join(STAGING_DIR, "hk_stock_raw_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser(description='港股数据重新打包')
    parser.add_argument('--input', help='指定 raw 文件路径')
    args = parser.parse_args()

    logger.info("📦 港股数据重新打包")

    if args.input:
        raw_file = args.input
    else:
        raw_file = find_latest_raw()

    if not raw_file or not os.path.exists(raw_file):
        logger.error(f"❌ 文件不存在: {raw_file}")
        return 1

    logger.info(f"   📂 原始数据: {raw_file}")
    raw_data = load_raw(raw_file)

    package = repack(raw_data)
    filepath = save_package(package)

    logger.info(f"✅ 打包完成: {filepath}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
