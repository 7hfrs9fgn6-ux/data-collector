#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书籍知识库主采集程序
职责：
  1. 从种子源自动发现书籍
  2. 调用各解析器采集详情
  3. 分类过滤和去重
  4. 支持断点续传
  5. 输出采集报告

使用方式：
  python scripts/collect_book_knowledge.py              # 完整采集
  python scripts/collect_book_knowledge.py --debug      # 调试模式
  python scripts/collect_book_knowledge.py --max 50     # 限制采集数量
"""

import os
import sys
import json
import time
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入各模块
from scripts.parse_wikipedia import WikipediaParser, extract_books_from_seed_sources
from scripts.parse_wikiquote import get_quotes_for_book
from scripts.parse_google_books import get_book_info_from_google
from scripts.parse_douban import get_douban_info
from scripts.category_filter import CategoryFilter, filter_books
from scripts.dedup_check import DedupChecker, deduplicate_books
from utils import save_json, load_json, get_timestamp

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
KNOWLEDGE_LIBRARY_DIR = "knowledge_library"
INDEX_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "books_index.jsonl")
CHECKPOINT_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "collection_checkpoint.json")
BOOK_DETAILS_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "book_details")


class BookCollector:
    """书籍采集器"""

    def __init__(self, max_books: int = 500, debug: bool = False):
        self.max_books = max_books
        self.debug = debug
        self.checkpoint = self._load_checkpoint()
        self.collected_books = []
        self.failed_books = []
        self.category_filter = CategoryFilter()

        # 确保目录存在
        os.makedirs(KNOWLEDGE_LIBRARY_DIR, exist_ok=True)
        os.makedirs(BOOK_DETAILS_DIR, exist_ok=True)

    def _load_checkpoint(self) -> Dict:
        """加载断点"""
        if os.path.exists(CHECKPOINT_FILE):
            data = load_json(CHECKPOINT_FILE)
            if data:
                logger.info(f"   📌 加载断点: 已采集 {len(data.get('collected', []))} 本")
                return data
        return {"collected": [], "failed": [], "total_processed": 0}

    def _save_checkpoint(self):
        """保存断点"""
        checkpoint = {
            "collected": [b.get('id', '') for b in self.collected_books],
            "failed": self.failed_books,
            "total_processed": len(self.collected_books) + len(self.failed_books),
            "updated_at": datetime.now().isoformat()
        }
        save_json(checkpoint, CHECKPOINT_FILE)
        logger.debug(f"   💾 断点已保存: {checkpoint['total_processed']} 本已处理")

    def collect(self) -> Dict[str, Any]:
        """
        执行采集
        返回: 采集结果
        """
        logger.info("=" * 60)
        logger.info("📚 书籍知识库采集启动")
        logger.info("=" * 60)

        # 1. 加载种子源配置
        seed_file = os.path.join(KNOWLEDGE_LIBRARY_DIR, "seed_sources.json")
        if not os.path.exists(seed_file):
            logger.error(f"❌ 种子源配置文件不存在: {seed_file}")
            return {"error": "seed_sources.json not found"}

        seed_config = load_json(seed_file)
        if not seed_config:
            logger.error("❌ 无法加载种子源配置")
            return {"error": "failed to load seed_sources.json"}

        # 2. 发现书籍
        logger.info("📖 阶段 1: 自动发现书籍...")
        candidates = extract_books_from_seed_sources(seed_config)
        logger.info(f"   📚 发现 {len(candidates)} 本候选书籍")

        # 3. 加载已有索引（用于去重）
        logger.info("📖 阶段 2: 去重检查...")
        deduper = DedupChecker(INDEX_FILE)

        # 4. 采集书籍详情
        logger.info("📖 阶段 3: 采集书籍详情...")
        new_books = []

        # 限制采集数量
        max_to_collect = min(self.max_books, len(candidates))
        candidates_to_process = candidates[:max_to_collect]

        for idx, candidate in enumerate(candidates_to_process):
            title = candidate.get('title', '')
            source_id = candidate.get('source_id', '')

            # 检查是否已处理
            if title in self.checkpoint.get('collected', []):
                logger.debug(f"   ⏭️ 跳过已处理: {title}")
                continue

            logger.info(f"   📖 [{idx+1}/{max_to_collect}] 采集: {title}")

            # 采集书籍详情
            book_data = self._collect_single_book(candidate)

            if book_data:
                # 检查是否重复
                is_dup, reason = deduper.is_duplicate(book_data)
                if is_dup:
                    logger.info(f"      ⏭️ 重复书籍: {title} ({reason})")
                    continue

                # 分类过滤
                categories = book_data.get('categories', [])
                if not self.category_filter.is_book_relevant(categories, title):
                    logger.info(f"      ⛔ 分类不匹配: {title}")
                    continue

                # 添加到结果
                new_books.append(book_data)
                deduper.add_to_index(book_data)
                self.collected_books.append(book_data)

                # 保存详情
                self._save_book_detail(book_data)

                logger.info(f"      ✅ 采集成功: {book_data.get('title')} "
                           f"(评分: {book_data.get('relevance_score', 0):.2f})")
            else:
                self.failed_books.append(title)
                logger.warning(f"      ❌ 采集失败: {title}")

            # 保存断点
            if idx % 5 == 0:
                self._save_checkpoint()

            # 延迟（避免请求过快）
            time.sleep(2)

        # 5. 保存索引
        logger.info("📖 阶段 4: 保存索引...")
        deduper.save_index(INDEX_FILE)

        # 6. 生成采集报告
        logger.info("📖 阶段 5: 生成采集报告...")
        report = self._generate_report(new_books)

        # 7. 打包
        logger.info("📦 阶段 6: 打包...")
        package = self._build_package(new_books, report)

        return package

    def _collect_single_book(self, candidate: Dict) -> Optional[Dict]:
        """
        采集单本书籍详情（多源融合）
        """
        title = candidate.get('title', '')
        url = candidate.get('url', '')
        source_id = candidate.get('source_id', '')

        result = {
            "id": None,
            "title": title,
            "title_cn": "",
            "authors": [],
            "authors_cn": [],
            "categories": [],
            "description": "",
            "description_cn": "",
            "quotes": [],
            "cover_url": "",
            "publisher": "",
            "publish_date": "",
            "rating": 0,
            "sources": [],
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        # 1. 维基百科详情
        wiki_parser = WikipediaParser()
        wiki_data = wiki_parser.get_book_details(title)

        if wiki_data:
            result["id"] = f"wiki_{wiki_data.get('page_id', '')}"
            result["wikipedia_id"] = wiki_data.get('page_id', '')
            result["title"] = wiki_data.get('title', title)
            result["categories"] = wiki_data.get('categories', [])
            result["description"] = wiki_data.get('description', '')
            result["cover_url"] = wiki_data.get('cover_url', '')
            result["url"] = wiki_data.get('url', '')
            result["sources"].append("wikipedia")
            logger.debug(f"      ✅ 维基百科: {wiki_data.get('title')}")

        # 2. 维基语录
        quotes = get_quotes_for_book(title)
        if quotes:
            result["quotes"] = quotes[:20]
            result["sources"].append("wikiquote")
            logger.debug(f"      ✅ 维基语录: {len(quotes)} 条")

        # 3. Google Books API
        google_data = get_book_info_from_google(title)
        if google_data:
            # 补充信息（不覆盖维基百科）
            if not result["description"] and google_data.get("description"):
                result["description"] = google_data["description"]
            if google_data.get("authors"):
                result["authors"] = google_data["authors"]
            if google_data.get("publisher"):
                result["publisher"] = google_data["publisher"]
            if google_data.get("publish_date"):
                result["publish_date"] = google_data["publish_date"]
            if google_data.get("categories"):
                # 合并分类
                for cat in google_data["categories"]:
                    if cat not in result["categories"]:
                        result["categories"].append(cat)
            if not result["cover_url"] and google_data.get("cover_url"):
                result["cover_url"] = google_data["cover_url"]
            result["google_books_id"] = google_data.get("google_books_id", '')
            result["sources"].append("google_books")
            logger.debug(f"      ✅ Google Books: {google_data.get('title')}")

        # 4. 豆瓣（中文信息）
        # 尝试用中文标题搜索（如果有）
        douban_data = get_douban_info(title)
        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", result.get("title_cn", ''))
            if douban_data.get("authors_cn"):
                result["authors_cn"] = douban_data["authors_cn"]
            if douban_data.get("description_cn"):
                result["description_cn"] = douban_data["description_cn"]
            if douban_data.get("rating"):
                result["rating"] = douban_data["rating"]
            if douban_data.get("publisher"):
                result["publisher"] = douban_data["publisher"]
            result["douban_id"] = douban_data.get("douban_id", '')
            result["sources"].append("douban")
            logger.debug(f"      ✅ 豆瓣: {douban_data.get('title_cn')}")

        # 如果没有任何来源采集到数据
        if not result["sources"]:
            return None

        # 生成 ID（如果没有）
        if not result.get("id"):
            import hashlib
            hash_str = f"{title}_{'|'.join(result.get('authors', []))}"
            result["id"] = f"book_{hashlib.md5(hash_str.encode()).hexdigest()[:16]}"

        # 清理分类
        result["categories"] = list(set(result["categories"]))

        return result

    def _save_book_detail(self, book: Dict):
        """保存书籍详情到独立文件"""
        book_id = book.get('id', '')
        if book_id:
            filepath = os.path.join(BOOK_DETAILS_DIR, f"{book_id}.json")
            save_json(book, filepath)

    def _generate_report(self, new_books: List[Dict]) -> Dict:
        """生成采集报告"""
        return {
            "total_candidates": len(new_books),
            "collected": len(self.collected_books),
            "failed": len(self.failed_books),
            "failed_titles": self.failed_books[:10],  # 只保留前10个
            "sources": {
                "wikipedia": sum(1 for b in self.collected_books if 'wikipedia' in b.get('sources', [])),
                "wikiquote": sum(1 for b in self.collected_books if 'wikiquote' in b.get('sources', [])),
                "google_books": sum(1 for b in self.collected_books if 'google_books' in b.get('sources', [])),
                "douban": sum(1 for b in self.collected_books if 'douban' in b.get('sources', [])),
            },
            "total_books": len(self.collected_books)
        }

    def _build_package(self, new_books: List[Dict], report: Dict) -> Dict:
        """构建数据包"""
        now = datetime.now()
        trade_date = now.strftime("%Y-%m-%d")

        package = {
            "book": "公开数据",
            "chapter": "book_knowledge",
            "version": "2.0",
            "generated_at": now.isoformat() + "+08:00",
            "trade_date": trade_date,
            "is_trading_day": False,  # 书籍采集不考虑交易日
            "dst_active": False,
            "content": {
                "total": len(new_books),
                "books": new_books,
                "summary": report
            },
            "metadata": {
                "source": "wikipedia + google_books + douban + wikiquote",
                "collected_at": now.isoformat(),
                "data_type": "book_knowledge"
            }
        }

        # 签名
        from utils import sign_data
        key = os.environ.get('SIGNING_KEY', '')
        if key:
            package["signature"] = sign_data(package, key)
            logger.info("   🔐 数据包已签名")

        return package


def main():
    parser = argparse.ArgumentParser(description='书籍知识库采集')
    parser.add_argument('--max', type=int, default=500, help='最大采集数量')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()

    collector = BookCollector(max_books=args.max, debug=args.debug)
    package = collector.collect()

    # 保存数据包
    if package and not package.get('error'):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"staging/book_knowledge_package_{timestamp}.json"
        os.makedirs("staging", exist_ok=True)
        save_json(package, filepath)
        logger.info(f"✅ 书籍知识库采集完成: {filepath}")
        logger.info(f"   📚 采集书籍: {package['content']['summary']['collected']} 本")
    else:
        logger.error("❌ 采集失败")

    return 0


if __name__ == "__main__":
    sys.exit(main())
