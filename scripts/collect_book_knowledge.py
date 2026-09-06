#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
书籍知识库主采集程序（V5：双通道采集）
职责：
  1. 从种子源自动发现书籍
  2. ★ 双通道采集：书籍（ISBN/Infobox book）+ 知识条目（理论/概念/人物/术语）
  3. 分类过滤和去重
  4. 支持断点续传
  5. 输出采集报告

数据源：维基百科 + 豆瓣 + 维基语录

策略说明：
  - 标题匹配金融关键词 → 进入采集流程
  - 有 ISBN/Infobox book → 作为"书籍"采集
  - 无 ISBN 但属于金融/经济/行为领域 → 作为"知识条目"采集
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

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入各模块
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

# 配置
KNOWLEDGE_LIBRARY_DIR = "knowledge_library"
BOOK_INDEX_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "books_index.jsonl")
ENTRY_INDEX_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "knowledge_entries_index.jsonl")
CHECKPOINT_FILE = os.path.join(KNOWLEDGE_LIBRARY_DIR, "collection_checkpoint.json")
BOOK_DETAILS_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "book_details")
ENTRY_DETAILS_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "knowledge_entries")


class BookCollector:
    """书籍/知识条目采集器（双通道）"""

    def __init__(self, max_items: int = 500, debug: bool = False):
        self.max_items = max_items
        self.debug = debug
        self.checkpoint = self._load_checkpoint()
        self.collected_books = []
        self.collected_entries = []
        self.failed_items = []
        self.category_filter = CategoryFilter()
        self.wiki_parser = WikipediaParser('en')

        # 确保目录存在
        os.makedirs(KNOWLEDGE_LIBRARY_DIR, exist_ok=True)
        os.makedirs(BOOK_DETAILS_DIR, exist_ok=True)
        os.makedirs(ENTRY_DETAILS_DIR, exist_ok=True)

    def _load_checkpoint(self) -> Dict:
        """加载断点"""
        if os.path.exists(CHECKPOINT_FILE):
            data = load_json(CHECKPOINT_FILE)
            if data:
                logger.info(f"   📌 加载断点: 已处理 {len(data.get('collected_titles', []))} 个条目")
                return data
        return {"collected_titles": [], "failed_titles": [], "total_processed": 0}

    def _save_checkpoint(self):
        """保存断点"""
        checkpoint = {
            "collected_titles": [b.get('title', '') for b in self.collected_books] +
                                [e.get('title', '') for e in self.collected_entries],
            "failed_titles": self.failed_items,
            "total_processed": len(self.collected_books) + len(self.collected_entries) + len(self.failed_items),
            "updated_at": datetime.now().isoformat()
        }
        save_json(checkpoint, CHECKPOINT_FILE)
        logger.debug(f"   💾 断点已保存: {checkpoint['total_processed']} 个已处理")

    def _is_book(self, wiki_data: Dict) -> bool:
        """
        判断维基百科条目是否为一本书
        判断依据：有 ISBN 或 Infobox book
        """
        if not wiki_data:
            return False

        # 检查 ISBN
        if wiki_data.get('isbn'):
            return True

        # 检查是否有书籍信息框
        infobox = wiki_data.get('infobox', '')
        if infobox and 'Infobox book' in str(infobox):
            return True

        # 检查分类中是否包含 "books"
        categories = wiki_data.get('categories', [])
        for cat in categories:
            cat_lower = cat.lower()
            if 'book' in cat_lower or 'novel' in cat_lower:
                return True

        return False

    def _build_book_result(self, wiki_data: Dict, title: str, quotes: List[str] = None, douban_data: Dict = None) -> Dict:
        """构建书籍结果"""
        result = {
            "id": f"wiki_{wiki_data.get('page_id', hashlib.md5(title.encode()).hexdigest()[:16])}",
            "wikipedia_id": wiki_data.get('page_id', ''),
            "title": wiki_data.get('title', title),
            "title_cn": "",
            "authors": [],
            "authors_cn": [],
            "categories": wiki_data.get('categories', []),
            "description": wiki_data.get('description', ''),
            "description_cn": "",
            "quotes": quotes or [],
            "cover_url": wiki_data.get('cover_url', ''),
            "url": wiki_data.get('url', ''),
            "publisher": "",
            "publish_date": "",
            "rating": 0,
            "sources": ["wikipedia"],
            "type": "book",
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        # 补充豆瓣信息
        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", result.get("title_cn", ''))
            result["authors_cn"] = douban_data.get("authors_cn", [])
            result["description_cn"] = douban_data.get("description_cn", '')
            result["rating"] = douban_data.get("rating", 0)
            result["publisher"] = douban_data.get("publisher", '')
            result["douban_id"] = douban_data.get("douban_id", '')
            result["sources"].append("douban")

        return result

    def _build_knowledge_entry(self, wiki_data: Dict, title: str, douban_data: Dict = None) -> Dict:
        """构建知识条目结果（理论/概念/人物/术语等）"""
        # 推断条目类型
        entry_type = self.category_filter.infer_entry_type(title, wiki_data)

        result = {
            "id": f"entry_{hashlib.md5(title.encode()).hexdigest()[:16]}",
            "type": entry_type,
            "title": title,
            "title_cn": "",
            "categories": wiki_data.get('categories', []) if wiki_data else [],
            "description": wiki_data.get('description', '') if wiki_data else '',
            "description_cn": "",
            "url": wiki_data.get('url', '') if wiki_data else '',
            "cover_url": wiki_data.get('cover_url', '') if wiki_data else '',
            "related_people": [],
            "related_concepts": [],
            "sources": ["wikipedia_entry"],
            "collected_at": datetime.now().isoformat(),
            "status": "active"
        }

        # 补充豆瓣信息
        if douban_data:
            result["title_cn"] = douban_data.get("title_cn", result.get("title_cn", ''))
            result["description_cn"] = douban_data.get("description_cn", '')
            result["sources"].append("douban")

        return result

    def _collect_single_item(self, candidate: Dict) -> Optional[Dict]:
        """
        采集单个条目（双通道）
        ★ 逻辑：
          1. 标题匹配金融关键词 → 继续
          2. 尝试维基百科 API
          3. 判断是否为"书籍" → 走书籍通道
          4. 否则 → 走知识条目通道
        """
        title = candidate.get('title', '')
        url = candidate.get('url', '')

        # ★ 1. 检查是否金融相关
        if not self.category_filter.is_finance_title(title):
            logger.debug(f"      ⛔ 非金融: {title}")
            return None

        # ★ 2. 尝试维基百科 API（带重试）
        wiki_data = None
        for retry in range(3):
            try:
                wiki_data = self.wiki_parser.get_book_details(title)
                if wiki_data:
                    break
                time.sleep(1)
            except Exception as e:
                logger.debug(f"      维基百科重试 {retry+1}: {e}")
                time.sleep(1)

        # ★ 3. 获取维基语录（如果是书籍）
        quotes = []
        if wiki_data and self._is_book(wiki_data):
            quotes = get_quotes_for_book(title)
            if quotes:
                logger.debug(f"      ✅ 维基语录: {len(quotes)} 条")

        # ★ 4. 获取豆瓣信息
        douban_data = get_douban_info(title)

        # ★ 5. 判断类型并构建结果
        if wiki_data and self._is_book(wiki_data):
            # 书籍通道
            result = self._build_book_result(wiki_data, title, quotes, douban_data)
            logger.debug(f"      📚 书籍: {result.get('title')}")
            return result
        elif self.category_filter.is_finance_title(title):
            # 知识条目通道（即使没有 wiki_data 也保留基础信息）
            result = self._build_knowledge_entry(wiki_data, title, douban_data)
            logger.debug(f"      🧠 知识条目 [{result.get('type')}]: {result.get('title')}")
            return result

        # 都不匹配
        return None

    def collect(self) -> Dict[str, Any]:
        """执行采集"""
        logger.info("=" * 60)
        logger.info("📚 书籍/知识库采集启动（双通道）")
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
        logger.info(f"   📚 发现 {len(candidates)} 个候选条目")

        # 3. 加载已有索引（用于去重）
        logger.info("📖 阶段 2: 去重检查...")
        book_deduper = DedupChecker(BOOK_INDEX_FILE)
        entry_deduper = DedupChecker(ENTRY_INDEX_FILE)

        # 4. 采集条目详情
        logger.info("📖 阶段 3: 采集条目详情（双通道）...")

        # 限制采集数量
        max_to_collect = min(self.max_items, len(candidates))
        candidates_to_process = candidates[:max_to_collect]

        new_books = []
        new_entries = []

        for idx, candidate in enumerate(candidates_to_process):
            title = candidate.get('title', '')

            # 检查是否已处理
            if title in self.checkpoint.get('collected_titles', []):
                logger.debug(f"   ⏭️ 跳过已处理: {title}")
                continue

            logger.info(f"   📖 [{idx+1}/{max_to_collect}] 采集: {title}")

            # 采集条目
            item_data = self._collect_single_item(candidate)

            if item_data:
                item_type = item_data.get('type', 'unknown')

                if item_type == 'book':
                    # 检查书籍重复
                    is_dup, reason = book_deduper.is_duplicate(item_data)
                    if is_dup:
                        logger.info(f"      ⏭️ 重复书籍: {title} ({reason})")
                        continue

                    new_books.append(item_data)
                    book_deduper.add_to_index(item_data)
                    self.collected_books.append(item_data)
                    self._save_book_detail(item_data)
                    logger.info(f"      ✅ 书籍采集成功: {item_data.get('title')}")

                else:
                    # 知识条目
                    is_dup, reason = entry_deduper.is_duplicate(item_data)
                    if is_dup:
                        logger.info(f"      ⏭️ 重复知识条目: {title} ({reason})")
                        continue

                    new_entries.append(item_data)
                    entry_deduper.add_to_index(item_data)
                    self.collected_entries.append(item_data)
                    self._save_entry_detail(item_data)
                    logger.info(f"      🧠 知识条目采集成功: [{item_data.get('type')}] {item_data.get('title')}")

            else:
                self.failed_items.append(title)
                logger.warning(f"      ❌ 采集失败: {title}")

            # 保存断点
            if idx % 5 == 0:
                self._save_checkpoint()

            # 延迟（避免请求过快）
            time.sleep(1.5)

        # 5. 保存索引
        logger.info("📖 阶段 4: 保存索引...")
        book_deduper.save_index(BOOK_INDEX_FILE)
        entry_deduper.save_index(ENTRY_INDEX_FILE)

        # 6. 生成采集报告
        logger.info("📖 阶段 5: 生成采集报告...")
        report = self._generate_report()

        # 7. 打包
        logger.info("📦 阶段 6: 打包...")
        package = self._build_package(report)

        return package

    def _save_book_detail(self, book: Dict):
        """保存书籍详情"""
        book_id = book.get('id', '')
        if book_id:
            filepath = os.path.join(BOOK_DETAILS_DIR, f"{book_id}.json")
            save_json(book, filepath)

    def _save_entry_detail(self, entry: Dict):
        """保存知识条目详情"""
        entry_id = entry.get('id', '')
        if entry_id:
            filepath = os.path.join(ENTRY_DETAILS_DIR, f"{entry_id}.json")
            save_json(entry, filepath)

    def _generate_report(self) -> Dict:
        """生成采集报告"""
        return {
            "books_collected": len(self.collected_books),
            "entries_collected": len(self.collected_entries),
            "failed": len(self.failed_items),
            "failed_titles": self.failed_items[:20],
            "entry_types": {
                "theory": sum(1 for e in self.collected_entries if e.get('type') == 'theory'),
                "concept": sum(1 for e in self.collected_entries if e.get('type') == 'concept'),
                "person": sum(1 for e in self.collected_entries if e.get('type') == 'person'),
                "term": sum(1 for e in self.collected_entries if e.get('type') == 'term'),
                "bias": sum(1 for e in self.collected_entries if e.get('type') == 'bias'),
                "effect": sum(1 for e in self.collected_entries if e.get('type') == 'effect'),
                "model": sum(1 for e in self.collected_entries if e.get('type') == 'model'),
            },
            "total_collected": len(self.collected_books) + len(self.collected_entries)
        }

    def _build_package(self, report: Dict) -> Dict:
        """构建数据包"""
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
    parser = argparse.ArgumentParser(description='书籍/知识库采集（双通道）')
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
        logger.info(f"      ├── 理论: {summary.get('entry_types', {}).get('theory', 0)}")
        logger.info(f"      ├── 概念: {summary.get('entry_types', {}).get('concept', 0)}")
        logger.info(f"      ├── 人物: {summary.get('entry_types', {}).get('person', 0)}")
        logger.info(f"      ├── 术语: {summary.get('entry_types', {}).get('term', 0)}")
        logger.info(f"      ├── 偏差: {summary.get('entry_types', {}).get('bias', 0)}")
        logger.info(f"      ├── 效应: {summary.get('entry_types', {}).get('effect', 0)}")
        logger.info(f"      └── 模型: {summary.get('entry_types', {}).get('model', 0)}")
        logger.info(f"   ❌ 失败: {summary.get('failed', 0)} 个")
        logger.info(f"   📦 输出: {filepath}")
        logger.info("=" * 60)
    else:
        logger.error("❌ 采集失败")

    return 0


if __name__ == "__main__":
    sys.exit(main())
