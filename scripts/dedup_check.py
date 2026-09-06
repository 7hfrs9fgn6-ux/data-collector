#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查重去重模块（增强版 V2）
职责：
  1. 维基百科 ID 精确匹配去重
  2. 书名+作者相似度匹配（阈值 85%）
  3. 跨语言版本识别（英文名 vs 中文名）
  4. ★ 知识条目语义相似度去重（针对 concept/theory/model）
  5. ★ 自动合并重复条目（保留信息最完整的版本）
  6. 检查已有数据，避免重复采集
"""

import os
import json
import re
import logging
from typing import Dict, List, Optional, Set, Tuple, Any
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


class DedupChecker:
    """查重去重检查器（增强版 V2）"""

    # ★ 相似度阈值
    TITLE_SIMILARITY_THRESHOLD = 0.85
    AUTHOR_SIMILARITY_THRESHOLD = 0.80
    ENTRY_SIMILARITY_THRESHOLD = 0.80

    def __init__(self, index_file: str = None, entry_index_file: str = None):
        """
        初始化查重器
        index_file: 已有书籍索引文件路径
        entry_index_file: 已有知识条目索引文件路径
        """
        self.index_file = index_file
        self.entry_index_file = entry_index_file
        self.existing_books = []
        self.existing_entries = []
        self.existing_ids = set()
        self.existing_titles = set()
        self.existing_title_hashes = set()
        self._load_index()

    def _load_index(self):
        """加载已有索引"""
        # 加载书籍索引
        if self.index_file and os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            book = json.loads(line)
                            self.existing_books.append(book)
                            self._add_to_sets(book)
                        except json.JSONDecodeError:
                            continue
                logger.debug(f"   📚 加载已有书籍: {len(self.existing_books)} 本")
            except Exception as e:
                logger.warning(f"   ⚠️ 加载书籍索引失败: {e}")

        # 加载知识条目索引
        if self.entry_index_file and os.path.exists(self.entry_index_file):
            try:
                with open(self.entry_index_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            self.existing_entries.append(entry)
                            self._add_to_sets(entry)
                        except json.JSONDecodeError:
                            continue
                logger.debug(f"   🧠 加载已有知识条目: {len(self.existing_entries)} 条")
            except Exception as e:
                logger.warning(f"   ⚠️ 加载知识条目索引失败: {e}")

        logger.info(f"   📊 共加载 {len(self.existing_books)} 本书 + {len(self.existing_entries)} 条知识条目")

    def _add_to_sets(self, item: Dict):
        """将条目添加到集合中"""
        # ID 集合
        if 'id' in item:
            self.existing_ids.add(item['id'])
        if 'wikipedia_id' in item and item['wikipedia_id']:
            self.existing_ids.add(item['wikipedia_id'])
        if 'douban_id' in item and item['douban_id']:
            self.existing_ids.add(item['douban_id'])

        # 标题集合（去括号、去空格）
        title = item.get('title', '')
        if title:
            normalized_title = self._normalize_title(title)
            self.existing_titles.add(normalized_title)
            self.existing_title_hashes.add(hash(normalized_title))

        title_cn = item.get('title_cn', '')
        if title_cn:
            normalized_cn = self._normalize_title(title_cn)
            self.existing_titles.add(normalized_cn)
            self.existing_title_hashes.add(hash(normalized_cn))

    def _normalize_title(self, title: str) -> str:
        """标准化标题（用于比较）"""
        if not title:
            return ''
        # 转小写
        title = title.lower()
        # 移除括号内容
        title = re.sub(r'\s*\([^)]*\)\s*', ' ', title)
        # 移除常见后缀
        title = re.sub(r'\s*(book|novel|series|the|a|an|volume|part|edition)$', '', title)
        # 移除多余空格
        title = re.sub(r'\s+', ' ', title).strip()
        return title

    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """计算两个字符串的相似度"""
        if not str1 or not str2:
            return 0.0
        return SequenceMatcher(None, self._normalize_title(str1), self._normalize_title(str2)).ratio()

    def _get_key_authors(self, authors: List[str]) -> Set[str]:
        """提取关键作者（去除常见中间名）"""
        if not authors:
            return set()
        result = set()
        for author in authors:
            # 取第一个和最后一个词
            parts = author.strip().split()
            if parts:
                result.add(parts[-1].lower())  # 姓氏
                if len(parts) >= 2:
                    result.add(parts[0].lower())  # 名字
                # 完整名字
                result.add(author.lower())
        return result

    # ============================================================
    # ★ 核心方法：判断是否重复
    # ============================================================

    def is_duplicate(self, item: Dict, check_existing: List[Dict] = None) -> Tuple[bool, str]:
        """
        检查条目是否重复
        返回: (是否重复, 重复原因)
        """
        title = item.get('title', '')
        title_cn = item.get('title_cn', '')
        authors = item.get('authors', [])
        wikipedia_id = item.get('wikipedia_id', '')
        entry_type = item.get('type', 'concept')

        # 获取要检查的已有条目列表
        existing = check_existing if check_existing is not None else self.existing_books + self.existing_entries

        # ★ 1. 维基百科 ID 精确匹配
        if wikipedia_id:
            for existing_item in existing:
                if existing_item.get('wikipedia_id') == wikipedia_id:
                    return True, f"维基百科 ID 匹配: {wikipedia_id}"

        # ★ 2. 标题精确匹配（标准化后）
        normalized_title = self._normalize_title(title)
        normalized_cn = self._normalize_title(title_cn) if title_cn else ''

        for existing_item in existing:
            existing_title = existing_item.get('title', '')
            existing_cn = existing_item.get('title_cn', '')

            if normalized_title and self._normalize_title(existing_title) == normalized_title:
                return True, f"标题精确匹配: {title}"

            if normalized_cn and self._normalize_title(existing_cn) == normalized_cn:
                return True, f"中文标题匹配: {title_cn}"

        # ★ 3. 标题相似度匹配（阈值 85%）
        for existing_item in existing:
            existing_title = existing_item.get('title', '')
            existing_cn = existing_item.get('title_cn', '')

            if title and existing_title:
                similarity = self._calculate_similarity(title, existing_title)
                if similarity >= self.TITLE_SIMILARITY_THRESHOLD:
                    return True, f"标题相似度匹配: {title} ≈ {existing_title} ({similarity:.2f})"

            if title_cn and existing_cn:
                similarity = self._calculate_similarity(title_cn, existing_cn)
                if similarity >= self.TITLE_SIMILARITY_THRESHOLD:
                    return True, f"中文标题相似度: {title_cn} ≈ {existing_cn} ({similarity:.2f})"

        # ★ 4. 作者匹配 + 书名部分匹配
        if authors:
            key_authors = self._get_key_authors(authors)
            for existing_item in existing:
                existing_authors = existing_item.get('authors', [])
                if not existing_authors:
                    continue

                existing_key_authors = self._get_key_authors(existing_authors)
                if key_authors.intersection(existing_key_authors):
                    # 作者匹配后，检查书名是否部分匹配
                    existing_title = existing_item.get('title', '')
                    if title and existing_title:
                        if self._calculate_similarity(title, existing_title) >= 0.60:
                            return True, f"作者匹配 + 书名部分: {authors[0]} → {existing_title}"

        # ★ 5. 知识条目语义去重（针对 concept/theory/model）
        if entry_type in ['concept', 'theory', 'model']:
            for existing_item in existing:
                existing_type = existing_item.get('type', '')
                if existing_type not in ['concept', 'theory', 'model']:
                    continue
                existing_title = existing_item.get('title', '')
                if title and existing_title:
                    # 检查是否属于同一主题
                    similarity = self._calculate_similarity(title, existing_title)
                    # 更宽松的阈值（概念可能有不同表述）
                    if similarity >= self.ENTRY_SIMILARITY_THRESHOLD:
                        return True, f"知识条目相似: {title} ≈ {existing_title} ({similarity:.2f})"

        return False, ""

    # ============================================================
    # ★ 新增：智能合并重复条目
    # ============================================================

    def merge_entries(self, entries: List[Dict]) -> List[Dict]:
        """
        合并重复的知识条目（保留信息最完整的版本）
        """
        if len(entries) <= 1:
            return entries

        # 按信息完整度排序（保留最完整的）
        def completeness_score(entry: Dict) -> int:
            score = 0
            if entry.get('description'):
                score += 3
            if entry.get('description_cn'):
                score += 2
            if entry.get('categories'):
                score += 1
            if entry.get('url'):
                score += 1
            if entry.get('cover_url'):
                score += 1
            if entry.get('quotes'):
                score += 2
            return score

        # 按标题分组
        groups = {}
        for entry in entries:
            title = self._normalize_title(entry.get('title', ''))
            if not title:
                continue
            # 找最近的组
            found = False
            for key in list(groups.keys()):
                if self._calculate_similarity(title, key) >= self.ENTRY_SIMILARITY_THRESHOLD:
                    groups[key].append(entry)
                    found = True
                    break
            if not found:
                groups[title] = [entry]

        # 合并每组
        merged = []
        for group_key, group_entries in groups.items():
            if len(group_entries) == 1:
                merged.append(group_entries[0])
            else:
                # 选择最完整的，然后补充其他条目的信息
                best = max(group_entries, key=completeness_score)
                # 合并来源
                sources = set(best.get('sources', []))
                for entry in group_entries:
                    sources.update(entry.get('sources', []))
                best['sources'] = list(sources)

                # 合并分类
                categories = set(best.get('categories', []))
                for entry in group_entries:
                    categories.update(entry.get('categories', []))
                best['categories'] = list(categories)

                # 保留最长的描述
                for entry in group_entries:
                    if entry.get('description') and len(entry['description']) > len(best.get('description', '')):
                        best['description'] = entry['description']
                    if entry.get('description_cn') and len(entry['description_cn']) > len(best.get('description_cn', '')):
                        best['description_cn'] = entry['description_cn']

                merged.append(best)
                logger.debug(f"   🔗 合并重复条目: {group_key} ({len(group_entries)} 个)")

        return merged

    def add_to_index(self, item: Dict):
        """将条目添加到索引中"""
        self.existing_books.append(item)
        self._add_to_sets(item)

    def save_index(self, filepath: str):
        """保存索引"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            for book in self.existing_books:
                f.write(json.dumps(book, ensure_ascii=False) + '\n')
        logger.info(f"   💾 索引已保存: {filepath} ({len(self.existing_books)} 本)")

    def save_entry_index(self, filepath: str):
        """保存知识条目索引"""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        # 先去重合并
        merged = self.merge_entries(self.existing_entries)
        with open(filepath, 'w', encoding='utf-8') as f:
            for entry in merged:
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        logger.info(f"   💾 知识条目索引已保存: {filepath} ({len(merged)} 条, 去重前 {len(self.existing_entries)} 条)")


def deduplicate_books(
    candidates: List[Dict],
    index_file: str = "knowledge_library/books_index.jsonl"
) -> List[Dict]:
    """
    对候选书籍列表进行去重
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


def deduplicate_entries(
    candidates: List[Dict],
    entry_index_file: str = "knowledge_library/knowledge_entries_index.jsonl"
) -> List[Dict]:
    """
    对候选知识条目进行去重和合并
    """
    checker = DedupChecker(entry_index_file=entry_index_file)
    new_entries = []

    for entry in candidates:
        is_dup, reason = checker.is_duplicate(entry)
        if is_dup:
            logger.debug(f"   ⏭️ 跳过重复知识条目: {entry.get('title')} ({reason})")
        else:
            new_entries.append(entry)
            checker.existing_entries.append(entry)
            checker._add_to_sets(entry)

    # 合并最终结果
    merged = checker.merge_entries(new_entries)
    logger.info(f"   📊 知识条目去重结果: {len(merged)} 条 (去重前 {len(candidates)} 条)")
    return merged


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    test_entries = [
        {"title": "Behavioral economics", "type": "theory", "description": "Behavioral economics study..."},
        {"title": "Behavioral Economics", "type": "concept", "description": "Behavioral economics is..."},
        {"title": "Financial economics", "type": "concept", "description": "Financial economics..."},
    ]
    checker = DedupChecker()
    merged = checker.merge_entries(test_entries)
    print(f"合并后: {len(merged)} 条")
    for entry in merged:
        print(f"  - {entry.get('title')} ({entry.get('type')})")
