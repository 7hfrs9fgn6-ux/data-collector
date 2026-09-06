#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股数据打包模块（独立版）
用途：从采集数据重新打包为统一格式
使用：python scripts/pack_hk_stock.py
"""

import sys
import os
import glob
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, sign_data

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STAGING_DIR = "staging"


def get_signing_key() -> str:
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


def build_package(indices_data: list) -> dict:
    """构建统一格式的港股数据包"""
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")
    is_trading_day = len(indices_data) > 0 and any(d.get('price', 0) > 0 for d in indices_data)
    dst_active = False  # 港股不实行夏令时

    # ★ 确保 indices_data 中每个项目都有必要字段
    cleaned_indices = []
    for item in indices_data:
        cleaned_item = {
            "name": item.get("name", "未知"),
            "symbol": item.get("symbol", ""),
            "price": item.get("price", 0),
            "change_pct": item.get("change_pct", 0),
            "volume": item.get("volume", 0),
            "date": item.get("date", trade_date),
            "source": item.get("source", "unknown"),
        }
        cleaned_indices.append(cleaned_item)

    package = {
        "book": "公开数据",
        "chapter": "hk_stock",
        "version": "2.0",
        "generated_at": now.isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": dst_active,
        "content": {
            "total": len(cleaned_indices),
            "indices": cleaned_indices,
        },
        "metadata": {
            "source": "yfinance + akshare",
            "collected_at": now.isoformat(),
            "data_type": "hk_stock",
        },
    }

    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    return package


def find_latest_raw() -> str:
    """找到最新的原始数据文件（排除 package 和 cache）"""
    pattern = os.path.join(STAGING_DIR, "hk_stock_[0-9]*.json")
    files = glob.glob(pattern)
    files = [f for f in files if 'package' not in f and 'cache' not in f]
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser(description='港股数据重新打包')
    parser.add_argument('--input', help='指定原始数据文件路径')
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

    raw_data = load_json(raw_file)
    if raw_data is None:
        logger.error("❌ 无法加载原始数据")
        return 1

    indices_data = raw_data.get('items', [])
    if not indices_data:
        logger.warning("⚠️ 原始数据中没有指数项，将生成空包")

    # 打包
    package = build_package(indices_data)

    # ★ 保存：先 data，再 filepath（与 utils.py 签名一致）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(STAGING_DIR, f"hk_stock_package_{timestamp}.json")

    os.makedirs(STAGING_DIR, exist_ok=True)
    save_json(package, filepath)

    logger.info(f"✅ 打包完成: {filepath}")

    # 打印摘要
    content = package.get('content', {})
    logger.info(f"   📊 指数数量: {content.get('total', 0)}")
    logger.info(f"   📅 trade_date: {package.get('trade_date')}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
