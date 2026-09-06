#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查重去重模块
职责：
  1. 维基百科 ID 精确匹配去重
  2. 书名+作者相似度匹配（阈值 90%）
  3. 跨语言版本识别（英文名 vs 中文名）
  4. 检查已有数据，避免重复采集
"""

import os
import json
import re
import logging
from typing import Dict, List, Optional, Set, Tuple
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class DedupChecker:
    """查重去重检查器"""

    def __init__(self, index_file: str = None):
        """
        初始化查重器
        index_file: 已有书籍索引文件路径
        """
        self.index_file = index_file
        self.existing_books = []
        self.existing_ids = set()
        self.existing_titles = set()
        self._load_index()

    def _load_index(self):
        """加载已有书籍索引"""
        if not self.index_file or not os.path.exists(self.index_file):
            logger.debug("   📂 没有已有索引文件，跳过加载")
            return

        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        book = json.loads(line)
                        self.existing_books.append(book)
                        if 'wikipedia_id' in book:
                            self.existing_ids.add(book['wikipedia_id'])
                        if 'title' in book:
                            self.existing_titles.add(book['title'].lower())
                        if 'title_cn' in book:
                            self.existing_titles.add(book['title_cn'].lower())
                    except json.JSONDecodeError:
                        continue

            logger.info(f"   📚 加载已有书籍: {len(self.existing_books)} 本")
        except Exception as e:
            logger.warning(f"   ⚠️ 加载索引失败: {e}")

    def is_duplicate(self, book: Dict) -> Tuple[bool, str]:
        """
        检查书籍是否重复
        返回: (是否重复, 重复原因)
        """
        title = book.get('title', '')
        title_cn = book.get('title_cn', '')
        authors = book.get('authors', [])
        wikipedia_id = book.get('wikipedia_id', '')

        # 1. 维基百科 ID 精确匹配
        if wikipedia_id and wikipedia_id in self.existing_ids:
            return True, f"维基百科 ID 匹配: {wikipedia_id}"

        # 2. 书名精确匹配（忽略大小写）
        if title and title.lower() in self.existing_titles:
            return True, f"书名精确匹配: {title}"

        if title_cn and title_cn.lower() in self.existing_titles:
            return True, f"中文书名匹配: {title_cn}"

        # 3. 书名相似度匹配（阈值 90%）
        for existing_book in self.existing_books:
            existing_title = existing_book.get('title', '')
            existing_title_cn = existing_book.get('title_cn', '')

            if title and existing_title:
                similarity = self._calculate_similarity(title, existing_title)
                if similarity >= 0.90:
                    return True, f"书名相似度匹配: {title} ≈ {existing_title} ({similarity:.2f})"

            if title_cn and existing_title_cn:
                similarity = self._calculate_similarity(title_cn, existing_title_cn)
                if similarity >= 0.90:
                    return True, f"中文书名相似度匹配: {title_cn} ≈ {existing_title_cn} ({similarity:.2f})"

        # 4. 作者匹配 + 书名部分匹配
        if authors:
            for author in authors:
                for existing_book in self.existing_books:
                    existing_authors = existing_book.get('authors', [])
                    for existing_author in existing_authors:
                        if self._calculate_similarity(author, existing_author) >= 0.85:
                            # 作者匹配后，检查书名是否部分匹配
                            existing_title = existing_book.get('title', '')
                            if title and existing_title:
                                if self._calculate_similarity(title, existing_title) >= 0.60:
                                    return True, f"作者匹配 + 书名部分匹配: {author} → {existing_title}"

        return False, ""

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """计算两个字符串的相似度"""
        if not str1 or not str2:
            return 0.0

        str1 = str1.lower().strip()
        str2 = str2.lower().strip()

        # 移除括号内容
        str1 = re.sub(r'\s*\([^)]*\)\s*', ' ', str1)
        str2 = re.sub(r'\s*\([^)]*\)\s*', ' ', str2)

        # 移除常见后缀
        str1 = re.sub(r'\s*(book|novel|series|the|a|an)$', '', str1)
        str2 = re.sub(r'\s*(book|novel|series|the|a|an)$', '', str2)

        return SequenceMatcher(None, str1, str2).ratio()

    def add_to_index(self, book: Dict):
        """将书籍添加到索引中"""
        self.existing_books.append(book)
        if 'wikipedia_id' in book:
            self.existing_ids.add(book['wikipedia_id'])
        if 'title' in book:
            self.existing_titles.add(book['title'].lower())
        if 'title_cn' in book:
            self.existing_titles.add(book['title_cn'].lower())

    def save_index(self, filepath: str):
        """保存索引"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            for book in self.existing_books:
                f.write(json.dumps(book, ensure_ascii=False) + '\n')
        logger.info(f"   💾 索引已保存: {filepath} ({len(self.existing_books)} 本)")

    def get_existing_count(self) -> int:
        """获取已有书籍数量"""
        return len(self.existing_books)


def deduplicate_books(
    candidates: List[Dict],
    index_file: str = "knowledge_library/books_index.jsonl"
) -> List[Dict]:
    """
    对候选书籍列表进行去重
    返回: 去重后的书籍列表
    """
    checker = DedupChecker(index_file)
    new_books = []

    for book in candidates:
        is_dup, reason = checker.is_duplicate(book)
        if is_dup:
            logger.debug(f"   ⏭️ 跳过重复: {book.get('title')} ({reason})")
        else:
            new_books.append(book)
            checker.add_to_index(book)

    logger.info(f"   📊 去重结果: {len(new_books)} 本新书, {len(candidates) - len(new_books)} 本重复")
    return new_books


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)

    # 测试数据
    test_books = [
        {"title": "The Intelligent Investor", "authors": ["Benjamin Graham"], "wikipedia_id": "12345"},
        {"title": "The Intelligent Investor", "authors": ["Benjamin Graham"], "wikipedia_id": "12346"},  # 重复
        {"title": "Security Analysis", "authors": ["Benjamin Graham"]},
    ]

    new_books = deduplicate_books(test_books, "test_index.jsonl")
    print(f"新书: {len(new_books)} 本")
    for book in new_books:
        print(f"  - {book.get('title')}")
