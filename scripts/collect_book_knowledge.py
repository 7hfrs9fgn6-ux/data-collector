#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书籍知识库主采集程序（V10：基于特征的书籍/知识条目分类）
核心原则：明确特征 → 按优先级判定
  1. 先判定是否为"书"（硬特征+软特征）
  2. 再判定是否为"知识条目"（理论/概念/人物/术语/偏差/效应/模型）
  3. 最后默认为"概念"
"""

import os
import sys
import json
import time
import argparse
import logging
import hashlib
from datetime import datetime
from typing import Dict, List, Optional, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.parse_wikipedia import WikipediaParser, extract_books_from_seed_sources
from scripts.parse_wikiquote import get_quotes_for_book
from scripts.parse_douban import get_douban_info
from scripts.category_filter import CategoryFilter
from scripts.dedup_check import DedupChecker
from utils import save_json, load_json

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

KNOWLEDGE_LIBRARY_DIR = "knowledge_library"
BOOK_INDEX_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "books_index.jsonl")
ENTRY_INDEX_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "knowledge_entries_index.jsonl")
CHECKPOINT_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "collection_checkpoint.json")
BOOK_DETAILS_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "book_details")
ENTRY_DETAILS_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "knowledge_entries")


class BookCollector:
    """书籍/知识条目采集器（V10：基于特征的分类）"""

    def __init__(self, max_items: int = 500, debug: bool = False):
        self.max_items = max_items
        self.debug = debug
        self.checkpoint = self._load_checkpoint()
        self.collected_books = []
        self.collected_entries = []
        self.failed_items = []
        self.category_filter = CategoryFilter()
        self.wiki_parser = WikipediaParser('en')
        self._page_exists_cache = {}

        os.makedirs(KNOWLEDGE_LIBRARY_DIR, exist_ok=True)
        os.makedirs(BOOK_DETAILS_DIR, exist_ok=True)
        os.makedirs(ENTRY_DETAILS_DIR, exist_ok=True)

    def _load_checkpoint(self) -> Dict:
        if os.path.exists(CHECKPOINT_FILE):
            data = load_json(CHECKPOINT_FILE)
            if data:
                logger.info(f"   📌 加载断点: 已处理 {len(data.get('collected_titles', []))} 个条目")
                return data
        return {"collected_titles": [], "failed_titles": [], "total_processed": 0}

    def _save_checkpoint(self):
        checkpoint = {
            "collected_titles": [b.get('title', '') for b in self.collected_books] +
                                [e.get('title', '') for e in self.collected_entries],
            "failed_titles": self.failed_items,
            "total_processed": len(self.collected_books) + len(self.collected_entries) + len(self.failed_items),
            "updated_at": datetime.now().isoformat()
        }
        save_json(checkpoint, CHECKPOINT_FILE)

    # ============================================================
    # ★ 页面存在性预检测
    # ============================================================

    def _page_exists(self, title: str) -> bool:
        if title in self._page_exists_cache:
            return self._page_exists_cache[title]

        try:
            import requests
            params = {
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "info",
            }
            response = requests.get(
                self.wiki_parser.api_url,
                params=params,
                timeout=5,
                headers={"User-Agent": "VSystem-DataCollector/1.0"}
            )
            data = response.json()
            pages = data.get('query', {}).get('pages', {})
            for page_id in pages:
                if page_id != "-1":
                    self._page_exists_cache[title] = True
                    return True
            self._page_exists_cache[title] = False
            return False
        except Exception:
            self._page_exists_cache[title] = True
            return True

    # ============================================================
    # ★ 核心：基于特征的分类（V10 核心）
    # ============================================================

    def _classify_entry(self, wiki_data: Dict, title: str) -> str:
        """
        基于特征判定条目类型
        优先级：书 > 知识条目 > 概念
        """
        if not wiki_data:
            return 'none'

        title_lower = title.lower()
        categories = wiki_data.get('categories', [])
        cat_text = ' '.join(categories).lower()

        # ============================================================
        # 第1步：判定是否为「书」（硬特征 + 软特征）
        # ============================================================

        # 1a. 硬特征：ISBN
        if wiki_data.get('isbn'):
            return 'book'

        # 1b. 硬特征：Infobox book
        infobox = wiki_data.get('infobox', '')
        if infobox and 'Infobox book' in str(infobox):
            return 'book'

        # 1c. 硬特征：有作者字段
        if wiki_data.get('authors'):
            return 'book'

        # 1d. 硬特征：有出版社字段
        if wiki_data.get('publisher'):
            return 'book'

        # 1e. 软特征：标题后缀
        if '(book)' in title_lower or '(novel)' in title_lower or '(memoir)' in title_lower:
            return 'book'

        # 1f. 软特征：分类中包含 "book"
        if 'book' in cat_text:
            return 'book'

        # 1g. 软特征：分类中包含 "novel"
        if 'novel' in cat_text:
            return 'book'

        # ============================================================
        # 第2步：判定是否为「知识条目」
        # ============================================================

        # 2a. 理论
        if 'theory' in title_lower or 'theory' in cat_text:
            return 'theory'

        # 2b. 效应
        if 'effect' in title_lower or 'effect' in cat_text:
            return 'effect'

        # 2c. 偏差
        if 'bias' in title_lower or 'bias' in cat_text:
            return 'bias'

        # 2d. 模型
        if 'model' in title_lower or 'model' in cat_text:
            return 'model'

        # 2e. 人物
        if any(k in cat_text for k in ['people', 'economists', 'biography']):
            return 'person'
        if any(k in title_lower for k in ['buffett', 'munger', 'graham', 'kahneman', 'tversky', 'thaler', 'shiller']):
            return 'person'

        # 2f. 术语
        if any(k in title_lower for k in ['trap', 'rally', 'correction', 'sell-off', 'spread']):
            return 'term'
        if 'term' in cat_text or 'definition' in cat_text:
            return 'term'

        # ============================================================
        # 第3步：默认
        # ============================================================

        return 'concept'

    # ============================================================
    # ★ 构建结果
    # ============================================================

    def _build_book_result(self, wiki_data: Dict, title: str, quotes: List[str] = None, douban_data: Dict = None) -> Dict:
        """构建书籍结果"""
        result = {
            "id": f"wiki_{wiki_data.get('page_id', hashlib.md5(title.encode()).hexdigest()[:16])}",
            "wikipedia_id": wiki_data.get('page_id', ''),
            "title": wiki_data.get('title', title),
            "title_cn": "",
            "authors": wiki_data.get('authors', []),
            "authors_cn": [],
            "categories": wiki_data.get('categories', []),
            "description": wiki_data.get('description', ''),
            "description_cn": "",
            "quotes": quotes or [],
            "cover_url": wiki_data.get('cover_url', ''),
            "url": wiki_data.get('url', ''),
            "publisher": wiki_data.get('publisher', ''),
            "publish_date": "",
            "rating": 0,
            "sources": ["wikipedia"],
            "type": "book",
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", result.get("title_cn", ''))
            result["authors_cn"] = douban_data.get("authors_cn", [])
            result["description_cn"] = douban_data.get("description_cn", '')
            result["rating"] = douban_data.get("rating", 0)
            result["publisher"] = douban_data.get("publisher", result.get("publisher", ''))
            result["douban_id"] = douban_data.get("douban_id", '')
            result["sources"].append("douban")

        return result

    def _build_entry_result(self, wiki_data: Dict, title: str, entry_type: str, douban_data: Dict = None) -> Dict:
        """构建知识条目结果"""
        result = {
            "id": f"entry_{hashlib.md5(title.encode()).hexdigest()[:16]}",
            "type": entry_type,
            "title": wiki_data.get('title', title) if wiki_data else title,
            "title_cn": "",
            "categories": wiki_data.get('categories', []) if wiki_data else [],
            "description": wiki_data.get('description', '') if wiki_data else '',
            "description_cn": "",
            "url": wiki_data.get('url', '') if wiki_data else '',
            "cover_url": wiki_data.get('cover_url', '') if wiki_data else '',
            "sources": ["wikipedia"] if wiki_data else ["wikipedia_fallback"],
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", result.get("title_cn", ''))
            result["description_cn"] = douban_data.get("description_cn", '')
            result["sources"].append("douban")

        return result

    def _build_minimal_result(self, title: str, douban_data: Dict = None) -> Dict:
        """构建最小结果（无 wiki_data 时使用）"""
        # 根据标题推断类型
        title_lower = title.lower()
        if any(k in title_lower for k in ['theory']):
            entry_type = 'theory'
        elif any(k in title_lower for k in ['bias']):
            entry_type = 'bias'
        elif any(k in title_lower for k in ['effect']):
            entry_type = 'effect'
        elif any(k in title_lower for k in ['model']):
            entry_type = 'model'
        elif any(k in title_lower for k in ['trap', 'rally', 'correction']):
            entry_type = 'term'
        elif any(k in title_lower for k in ['buffett', 'munger', 'graham', 'kahneman', 'tversky', 'thaler', 'shiller']):
            entry_type = 'person'
        else:
            entry_type = 'concept'

        result = {
            "id": f"entry_{hashlib.md5(title.encode()).hexdigest()[:16]}",
            "type": entry_type,
            "title": title,
            "title_cn": "",
            "categories": [],
            "description": "",
            "description_cn": "",
            "url": "",
            "cover_url": "",
            "sources": ["wikipedia_fallback"],
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", '')
            result["description_cn"] = douban_data.get("description_cn", '')
            result["sources"].append("douban")

        return result

    # ============================================================
    # ★ 核心采集逻辑
    # ============================================================

    def _collect_single_item(self, candidate: Dict) -> Optional[Dict]:
        """采集单个条目（V10：基于特征分类）"""
        title = candidate.get('title', '')

        if not self.category_filter.is_finance_title(title):
            return None

        # ★ 预检测：页面是否存在
        if not self._page_exists(title):
            return None

        # ★ 获取 wiki_data
        wiki_data = None
        for retry in range(3):
            try:
                wiki_data = self.wiki_parser.get_book_details(title)
                if wiki_data:
                    break
                time.sleep(1)
            except Exception:
                time.sleep(1)

        # ★ 获取豆瓣信息
        douban_data = get_douban_info(title)

        # ★ 获取语录（如果有 wiki_data）
        quotes = []
        if wiki_data:
            quotes = get_quotes_for_book(title)

        # ★ 分类（核心：基于特征）
        if wiki_data:
            entry_type = self._classify_entry(wiki_data, title)
        else:
            entry_type = 'concept'

        # ★ 构建结果
        if entry_type == 'book':
            if wiki_data:
                result = self._build_book_result(wiki_data, title, quotes, douban_data)
            else:
                # 即使没有 wiki_data，但标题明显是书，也保留
                result = self._build_minimal_result(title, douban_data)
                result['type'] = 'book'
            return result
        else:
            if wiki_data:
                result = self._build_entry_result(wiki_data, title, entry_type, douban_data)
            else:
                result = self._build_minimal_result(title, douban_data)
            return result

    # ============================================================
    # 主流程
    # ============================================================

    def collect(self) -> Dict[str, Any]:
        logger.info("=" * 60)
        logger.info("📚 书籍/知识库采集启动（V10：基于特征分类）")
        logger.info("=" * 60)

        seed_file = os.path.join(KNOWLEDGE_LIBRARY_DIR, "seed_sources.json")
        if not os.path.exists(seed_file):
            logger.error(f"❌ 种子源配置文件不存在: {seed_file}")
            return {"error": "seed_sources.json not found"}

        seed_config = load_json(seed_file)
        if not seed_config:
            logger.error("❌ 无法加载种子源配置")
            return {"error": "failed to load seed_sources.json"}

        logger.info("📖 阶段 1: 自动发现书籍...")
        candidates = extract_books_from_seed_sources(seed_config)
        logger.info(f"   📚 发现 {len(candidates)} 个候选条目")

        logger.info("📖 阶段 2: 去重检查...")
        book_deduper = DedupChecker(BOOK_INDEX_FILE)
        entry_deduper = DedupChecker(ENTRY_INDEX_FILE)

        logger.info("📖 阶段 3: 采集条目详情...")

        max_to_collect = min(self.max_items, len(candidates))
        candidates_to_process = candidates[:max_to_collect]

        for idx, candidate in enumerate(candidates_to_process):
            title = candidate.get('title', '')

            if title in self.checkpoint.get('collected_titles', []):
                logger.debug(f"   ⏭️ 跳过已处理: {title}")
                continue

            logger.info(f"   📖 [{idx+1}/{max_to_collect}] 采集: {title}")

            item_data = self._collect_single_item(candidate)

            if item_data:
                entry_type = item_data.get('type', 'concept')

                if entry_type == 'book':
                    is_dup, reason = book_deduper.is_duplicate(item_data)
                    if is_dup:
                        logger.info(f"      ⏭️ 重复书籍: {title} ({reason})")
                        continue

                    self.collected_books.append(item_data)
                    book_deduper.add_to_index(item_data)
                    self._save_book_detail(item_data)
                    logger.info(f"      ✅ 书籍采集成功: {item_data.get('title')}")

                else:
                    is_dup, reason = entry_deduper.is_duplicate(item_data)
                    if is_dup:
                        logger.info(f"      ⏭️ 重复知识条目: {title} ({reason})")
                        continue

                    self.collected_entries.append(item_data)
                    entry_deduper.add_to_index(item_data)
                    self._save_entry_detail(item_data)
                    logger.info(f"      🧠 知识条目采集成功: [{entry_type}] {item_data.get('title')}")

            else:
                self.failed_items.append(title)
                logger.warning(f"      ❌ 采集失败: {title}")

            if idx % 5 == 0:
                self._save_checkpoint()

            time.sleep(1.2)

        logger.info("📖 阶段 4: 保存索引...")
        book_deduper.save_index(BOOK_INDEX_FILE)
        entry_deduper.save_index(ENTRY_INDEX_FILE)

        logger.info("📖 阶段 5: 生成采集报告...")
        report = self._generate_report()

        logger.info("📦 阶段 6: 打包...")
        package = self._build_package(report)

        return package

    def _save_book_detail(self, book: Dict):
        book_id = book.get('id', '')
        if book_id:
            filepath = os.path.join(BOOK_DETAILS_DIR, f"{book_id}.json")
            save_json(book, filepath)

    def _save_entry_detail(self, entry: Dict):
        entry_id = entry.get('id', '')
        if entry_id:
            filepath = os.path.join(ENTRY_DETAILS_DIR, f"{entry_id}.json")
            save_json(entry, filepath)

    def _generate_report(self) -> Dict:
        entry_types = {}
        for e in self.collected_entries:
            t = e.get('type', 'concept')
            entry_types[t] = entry_types.get(t, 0) + 1

        return {
            "books_collected": len(self.collected_books),
            "entries_collected": len(self.collected_entries),
            "failed": len(self.failed_items),
            "failed_titles": self.failed_items[:20],
            "entry_types": entry_types,
            "total_collected": len(self.collected_books) + len(self.collected_entries)
        }

    def _build_package(self, report: Dict) -> Dict:
        now = datetime.now()
        trade_date = now.strftime("%Y-%m-%d")

        package = {
            "book": "公开数据",
            "chapter": "book_knowledge",
            "version": "3.0",
            "generated_at": now.isoformat() + "+08:00",
            "trade_date": trade_date,
            "is_trading_day": False,
            "dst_active": False,
            "content": {
                "books": self.collected_books,
                "knowledge_entries": self.collected_entries,
                "summary": report
            },
            "metadata": {
                "source": "wikipedia + douban + wikiquote",
                "collected_at": now.isoformat(),
                "data_type": "book_knowledge",
                "version": "3.0"
            }
        }

        from utils import sign_data
        key = os.environ.get('SIGNING_KEY', '')
        if key:
            package["signature"] = sign_data(package, key)
            logger.info("   🔐 数据包已签名")

        return package


def main():
    parser = argparse.ArgumentParser(description='书籍/知识库采集（V10：基于特征分类）')
    parser.add_argument('--max', type=int, default=300, help='最大采集数量')
    parser.add_argument('--debug', action='store_true', help='调试模式')
    args = parser.parse_args()

    collector = BookCollector(max_items=args.max, debug=args.debug)
    package = collector.collect()

    if package and not package.get('error'):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = f"staging/book_knowledge_package_{timestamp}.json"
        os.makedirs("staging", exist_ok=True)
        save_json(package, filepath)

        summary = package.get('content', {}).get('summary', {})
        logger.info("=" * 60)
        logger.info("✅ 书籍/知识库采集完成")
        logger.info(f"   📚 书籍: {summary.get('books_collected', 0)} 本")
        logger.info(f"   🧠 知识条目: {summary.get('entries_collected', 0)} 条")
        for t, count in summary.get('entry_types', {}).items():
            logger.info(f"      ├── {t}: {count}")
        logger.info(f"   ❌ 失败: {summary.get('failed', 0)} 个")
        logger.info(f"   📦 输出: {filepath}")
        logger.info("=" * 60)
    else:
        logger.error("❌ 采集失败")

    return 0


if __name__ == "__main__":
    sys.exit(main())
