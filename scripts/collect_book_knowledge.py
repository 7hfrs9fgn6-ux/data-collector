#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书籍知识库主采集程序（优化版）
职责：
  1. 从种子源自动发现书籍
  2. 调用各解析器采集详情
  3. 分类过滤和去重
  4. 支持断点续传
  5. 输出采集报告

数据源：维基百科 + 豆瓣 + 维基语录

优化记录：
  - 2026-09-06：分类匹配宽松化（标题关键词 + 分类匹配双重判断）
  - 2026-09-06：采集失败时降级为基础条目
  - 2026-09-06：增加重试机制
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
from scripts.parse_douban import get_douban_info
from scripts.category_filter import CategoryFilter
from scripts.dedup_check import DedupChecker
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

# ★ 金融/投资关键词（用于标题匹配）
FINANCE_KEYWORDS = [
    'finance', 'invest', 'econom', 'market', 'trading', 'asset',
    'capital', 'credit', 'bank', 'money', 'wealth', 'portfolio',
    'stock', 'bond', 'fund', 'derivative', 'risk', 'decision',
    'cognitive', 'psycholog', 'behavior', 'strategy', 'management',
    'business', 'entrepreneur', 'leadership', 'corporate', 'valuation',
    'dividend', 'earnings', 'profit', 'margin', 'cash', 'debt',
    'equity', 'recession', 'inflation', 'interest', 'tax', 'insurance',
    'pension', 'retirement', 'budget', 'accounting', 'audit',
    'merger', 'acquisition', 'ipo', 'venture', 'private equity',
    'hedge', 'mutual fund', 'etf', 'index', 'quant', 'algorithm',
    'behavioral', 'monetary', 'fiscal', 'policy', 'trade', 'tariff',
    'currency', 'forex', 'gold', 'commodity', 'oil', 'energy',
    'real estate', 'property', 'mortgage', 'loan', 'saving',
    'financial', 'banking', 'investing', 'trading', 'wealthy'
]

# ★ 标题匹配关键词（简化版，用于快速判断）
TITLE_KEYWORDS = [
    'invest', 'finance', 'econom', 'market', 'trade', 'asset',
    'capital', 'credit', 'bank', 'money', 'wealth', 'portfolio',
    'stock', 'bond', 'fund', 'risk', 'decision', 'cognitive',
    'psycholog', 'behavior', 'strategy', 'management', 'business',
    'valuation', 'cash', 'debt', 'equity', 'inflation', 'tax',
    'accounting', 'merger', 'acquisition', 'venture', 'hedge',
    'monetary', 'fiscal', 'currency', 'gold', 'commodity',
    'real estate', 'mortgage', 'loan', 'financial', 'banking',
    'investing', 'trading', 'wealthy'
]


class BookCollector:
    """书籍采集器（优化版）"""

    def __init__(self, max_books: int = 500, debug: bool = False):
        self.max_books = max_books
        self.debug = debug
        self.checkpoint = self._load_checkpoint()
        self.collected_books = []
        self.failed_books = []
        self.category_filter = CategoryFilter()
        self.wiki_parser = WikipediaParser('en')

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

    def _is_finance_book_by_title(self, title: str) -> bool:
        """
        ★ 通过标题判断是否金融/投资类书籍（宽松匹配）
        """
        if not title:
            return False
        title_lower = title.lower()

        # 检查是否包含关键词
        for keyword in TITLE_KEYWORDS:
            if keyword in title_lower:
                return True

        return False

    def _collect_single_book(self, candidate: Dict) -> Optional[Dict]:
        """
        采集单本书籍详情（优化版）
        新增：降级机制、重试机制
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

        # ★ 1. 维基百科详情（带重试）
        wiki_data = None
        for retry in range(3):
            try:
                wiki_data = self.wiki_parser.get_book_details(title)
                if wiki_data:
                    break
                time.sleep(1)  # 重试延迟
            except Exception as e:
                logger.debug(f"      维基百科重试 {retry+1}: {e}")
                time.sleep(1)

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

        # ★ 2. 如果维基百科失败，尝试用 title 构造基础条目（降级）
        if not wiki_data:
            # 至少保留书名
            result["id"] = f"book_{hashlib.md5(title.encode()).hexdigest()[:16]}"
            result["title"] = title
            logger.debug(f"      ⚠️ 维基百科失败，使用基础条目: {title}")

        # ★ 3. 维基语录（如果维基百科有数据）
        if wiki_data:
            quotes = get_quotes_for_book(title)
            if quotes:
                result["quotes"] = quotes[:20]
                result["sources"].append("wikiquote")
                logger.debug(f"      ✅ 维基语录: {len(quotes)} 条")

        # ★ 4. 豆瓣（中文信息）
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

        # ★ 5. 分类过滤（双重判断）
        categories = result.get('categories', [])
        is_finance = False

        # 5a. 分类匹配
        is_finance = self.category_filter.is_book_relevant(categories, title)

        # 5b. ★ 如果分类不匹配，但标题匹配金融关键词，则通过
        if not is_finance and self._is_finance_book_by_title(title):
            is_finance = True
            logger.debug(f"      ✅ 标题关键词匹配: {title}")

        # 5c. ★ 如果仍然不匹配，但书名包含 "invest" 或 "finance"，也通过
        if not is_finance:
            title_lower = title.lower()
            if 'invest' in title_lower or 'finance' in title_lower or 'econom' in title_lower:
                is_finance = True
                logger.debug(f"      ✅ 书名核心词匹配: {title}")

        if not is_finance:
            logger.info(f"      ⛔ 分类不匹配: {title}")
            return None

        # 如果没有任何来源采集到数据（且不是基础条目）
        if not result["sources"] and not wiki_data:
            return None

        # 生成 ID（如果没有）
        if not result.get("id"):
            import hashlib
            hash_str = f"{title}_{'|'.join(result.get('authors', []))}"
            result["id"] = f"book_{hashlib.md5(hash_str.encode()).hexdigest()[:16]}"

        # 清理分类
        result["categories"] = list(set(result["categories"]))

        return result

    def collect(self) -> Dict[str, Any]:
        """执行采集"""
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

                # 添加到结果
                new_books.append(book_data)
                deduper.add_to_index(book_data)
                self.collected_books.append(book_data)

                # 保存详情
                self._save_book_detail(book_data)

                logger.info(f"      ✅ 采集成功: {book_data.get('title')}")
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
        report = self._generate_report()

        # 7. 打包
        logger.info("📦 阶段 6: 打包...")
        package = self._build_package(report)

        return package

    def _save_book_detail(self, book: Dict):
        """保存书籍详情到独立文件"""
        book_id = book.get('id', '')
        if book_id:
            filepath = os.path.join(BOOK_DETAILS_DIR, f"{book_id}.json")
            save_json(book, filepath)

    def _generate_report(self) -> Dict:
        """生成采集报告"""
        return {
            "collected": len(self.collected_books),
            "failed": len(self.failed_books),
            "failed_titles": self.failed_books[:20],
            "sources": {
                "wikipedia": sum(1 for b in self.collected_books if 'wikipedia' in b.get('sources', [])),
                "wikiquote": sum(1 for b in self.collected_books if 'wikiquote' in b.get('sources', [])),
                "douban": sum(1 for b in self.collected_books if 'douban' in b.get('sources', [])),
            },
            "total_books": len(self.collected_books)
        }

    def _build_package(self, report: Dict) -> Dict:
        """构建数据包"""
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
                "total": len(self.collected_books),
                "books": self.collected_books,
                "summary": report
            },
            "metadata": {
                "source": "wikipedia + douban + wikiquote",
                "collected_at": now.isoformat(),
                "data_type": "book_knowledge"
            }
        }

        from utils import sign_data
        key = os.environ.get('SIGNING_KEY', '')
        if key:
            package["signature"] = sign_data(package, key)
            logger.info("   🔐 数据包已签名")

        return package


def main():
    parser = argparse.ArgumentParser(description='书籍知识库采集')
    parser.add_argument('--max', type=int, default=300, help='最大采集数量')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()

    collector = BookCollector(max_books=args.max, debug=args.debug)
    package = collector.collect()

    if package and not package.get('error'):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"staging/book_knowledge_package_{timestamp}.json"
        os.makedirs("staging", exist_ok=True)
        save_json(package, filepath)
        logger.info(f"✅ 书籍知识库采集完成: {filepath}")
        logger.info(f"   📚 采集书籍: {package['content']['summary']['collected']} 本")
        logger.info(f"   ❌ 失败: {package['content']['summary']['failed']} 本")
        logger.info(f"   📊 数据源: 维基百科 + 豆瓣 + 维基语录")
    else:
        logger.error("❌ 采集失败")

    return 0


if __name__ == "__main__":
    import hashlib
    sys.exit(main())
