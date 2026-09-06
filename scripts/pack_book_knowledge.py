#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书籍知识库打包模块（独立版）
用途：从已采集的书籍知识库数据重新打包
使用：python scripts/pack_book_knowledge.py
"""

import sys
import os
import json
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
KNOWLEDGE_LIBRARY_DIR = "knowledge_library"


def get_signing_key() -> str:
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


def load_books_from_index(index_file: str) -> list:
    """从索引文件加载书籍列表"""
    books = []
    if not os.path.exists(index_file):
        logger.warning(f"⚠️ 索引文件不存在: {index_file}")
        return books

    with open(index_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                books.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    return books


def build_package(books: list) -> dict:
    """构建统一格式的书籍知识库数据包"""
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")

    package = {
        "book": "公开数据",
        "chapter": "book_knowledge",
        "version": "2.0",
        "generated_at": now.isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": False,
        "dst_active": False,
        "content": {
            "total": len(books),
            "books": books,
            "summary": {
                "total_books": len(books),
                "collected": len(books),
                "failed": 0
            }
        },
        "metadata": {
            "source": "wikipedia + google_books + douban + wikiquote",
            "repacked_at": now.isoformat(),
            "data_type": "book_knowledge"
        }
    }

    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    return package


def find_latest_collection() -> str:
    """找到最新的采集文件"""
    pattern = os.path.join(STAGING_DIR, "book_knowledge_package_*.json")
    files = glob.glob(pattern)
    if not files:
        return None
    return max(files, key=os.path.getmtime)


def main():
    parser = argparse.ArgumentParser(description='书籍知识库重新打包')
    parser.add_argument('--input', help='指定书籍索引文件路径', default=None)
    parser.add_argument('--output', help='指定输出文件路径')
    args = parser.parse_args()

    logger.info("📦 书籍知识库重新打包")

    # 加载书籍数据
    if args.input:
        books = load_books_from_index(args.input)
        logger.info(f"   📂 从文件加载: {len(books)} 本书")
    else:
        # 从索引加载
        index_file = os.path.join(KNOWLEDGE_LIBRARY_DIR, "books_index.jsonl")
        books = load_books_from_index(index_file)
        logger.info(f"   📂 从索引加载: {len(books)} 本书")

        # 如果索引为空，尝试从最新的采集包加载
        if not books:
            latest_package = find_latest_collection()
            if latest_package:
                data = load_json(latest_package)
                if data:
                    books = data.get('content', {}).get('books', [])
                    logger.info(f"   📂 从采集包加载: {len(books)} 本书")

    if not books:
        logger.warning("⚠️ 没有找到书籍数据")
        return 1

    # 打包
    package = build_package(books)

    # 保存
    os.makedirs(STAGING_DIR, exist_ok=True)
    if args.output:
        filepath = args.output
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(STAGING_DIR, f"book_knowledge_package_{timestamp}.json")

    save_json(package, filepath)

    logger.info(f"✅ 打包完成: {filepath}")
    logger.info(f"   📊 书籍数量: {package['content']['total']}")
    logger.info(f"   📅 trade_date: {package.get('trade_date')}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
