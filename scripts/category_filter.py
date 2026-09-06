#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类过滤模块
职责：
  1. 根据白名单过滤书籍
  2. 多源验证分类匹配度
  3. 过滤掉不相关的书籍
"""

import re
import logging
from typing import Dict, List, Set, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)


class CategoryFilter:
    """分类过滤器"""

    # 允许的类别白名单
    ALLOWED_CATEGORIES = {
        # 金融与投资
        'finance', 'investing', 'investment', 'financial_markets',
        'asset_pricing', 'risk_management', 'portfolio_management',
        'value_investing', 'quantitative_finance', 'derivatives',
        'corporate_finance', 'behavioral_finance', 'financial_economics',

        # 经济学
        'economics', 'macroeconomics', 'microeconomics',
        'econometrics', 'political_economy', 'economic_history',
        'behavioral_economics', 'development_economics',

        # 商业与管理
        'business', 'management', 'strategy', 'leadership',
        'organizational_behavior', 'decision_theory', 'game_theory',

        # 心理学与思维
        'psychology', 'cognitive_science', 'cognitive_psychology',
        'mental_models', 'decision_making', 'thinking',

        # 历史与传记
        'financial_history', 'business_history', 'economic_history',
        'biography', 'autobiography',

        # 数据与量化
        'statistics', 'data_science', 'machine_learning',
        'operations_research', 'mathematics',

        # 会计与法律
        'accounting', 'financial_law', 'commercial_law',

        # 中国相关
        'economics_china', 'financial_china', 'business_china',
    }

    # 排除的关键词
    EXCLUDED_KEYWORDS = {
        'fiction', 'novel', 'science_fiction', 'fantasy',
        'mystery', 'thriller', 'romance', 'horror',
        'poetry', 'drama', 'theater', 'play',
        'children', 'juvenile', 'young_adult',
        'cookbook', 'cooking', 'food',
        'self_help', 'self-help', 'spirituality',
        'religion', 'bible', 'quran',
        'health', 'fitness', 'diet',
        'travel', 'guide', 'tour',
        'craft', 'hobby', 'diy',
        'art', 'music', 'photography',
        'sports', 'exercise', 'gym',
        'language', 'dictionary', 'grammar',
    }

    def __init__(self):
        self.allowed_categories = self.ALLOWED_CATEGORIES
        self.excluded_keywords = self.EXCLUDED_KEYWORDS

    def is_book_relevant(self, categories: List[str], title: str = '') -> bool:
        """
        判断书籍是否相关
        - 至少有一个分类匹配白名单
        - 不包含排除关键词
        """
        if not categories:
            # 如果没有分类，通过标题判断
            return self._check_title(title)

        # 检查排除关键词
        for cat in categories:
            cat_lower = cat.lower()
            for excluded in self.excluded_keywords:
                if excluded in cat_lower:
                    logger.debug(f"   ⛔ 排除: {cat}")
                    return False

        # 检查白名单匹配
        for cat in categories:
            cat_lower = cat.lower()
            for allowed in self.allowed_categories:
                if allowed in cat_lower or cat_lower in allowed:
                    return True

        # 如果分类都不匹配，检查标题
        return self._check_title(title)

    def _check_title(self, title: str) -> bool:
        """通过标题判断是否相关"""
        if not title:
            return False

        title_lower = title.lower()

        # 检查排除关键词
        for excluded in self.excluded_keywords:
            if excluded in title_lower:
                return False

        # 检查白名单关键词
        allowed_keywords = {
            'invest', 'finance', 'econom', 'business', 'management',
            'market', 'trading', 'asset', 'capital', 'credit',
            'bank', 'money', 'wealth', 'portfolio', 'stock',
            'bond', 'fund', 'derivative', 'risk', 'decision',
            'cognitive', 'psycholog', 'behavior', 'strategy',
        }

        for keyword in allowed_keywords:
            if keyword in title_lower:
                return True

        return False

    def get_relevance_score(self, categories: List[str]) -> float:
        """
        计算相关性得分 (0-1)
        得分越高越相关
        """
        if not categories:
            return 0.0

        match_count = 0
        total_categories = len(categories)

        for cat in categories:
            cat_lower = cat.lower()
            for allowed in self.allowed_categories:
                if allowed in cat_lower:
                    match_count += 1
                    break

        return match_count / total_categories if total_categories > 0 else 0.0

    def multi_source_validate(
        self,
        source_results: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        多源验证：从不同来源验证分类一致性
        """
        # 收集各来源的分类
        all_categories = []
        source_names = []

        # 维基百科分类
        wiki_categories = source_results.get('wikipedia', {}).get('categories', [])
        if wiki_categories:
            all_categories.extend(wiki_categories)
            source_names.append('wikipedia')

        # Google Books 分类
        gbooks_categories = source_results.get('google_books', {}).get('categories', [])
        if gbooks_categories:
            all_categories.extend(gbooks_categories)
            source_names.append('google_books')

        # 豆瓣分类（如果有）
        douban_categories = source_results.get('douban', {}).get('categories', [])
        if douban_categories:
            all_categories.extend(douban_categories)
            source_names.append('douban')

        if not all_categories:
            return {
                'valid': False,
                'score': 0.0,
                'sources': source_names,
                'categories': [],
                'reason': '没有可用分类'
            }

        # 统计分类频率
        category_counts = Counter(all_categories)

        # 计算综合得分
        relevance_score = self.get_relevance_score(all_categories)
        source_coverage = len(source_names) / 3  # 最多3个来源

        # 如果有多个来源且至少一个来源匹配，验证通过
        is_valid = relevance_score >= 0.4 or (len(source_names) >= 2 and relevance_score >= 0.2)

        return {
            'valid': is_valid,
            'score': relevance_score,
            'sources': source_names,
            'categories': all_categories,
            'category_counts': dict(category_counts),
            'source_coverage': source_coverage,
            'reason': f"匹配度 {relevance_score:.2f}, 来源 {len(source_names)}/3"
        }


def filter_books(books: List[Dict]) -> List[Dict]:
    """
    批量过滤书籍
    返回过滤后的书籍列表
    """
    filter_engine = CategoryFilter()
    filtered = []

    for book in books:
        categories = book.get('categories', [])
        title = book.get('title', '')

        if filter_engine.is_book_relevant(categories, title):
            # 添加相关性得分
            book['relevance_score'] = filter_engine.get_relevance_score(categories)
            filtered.append(book)
        else:
            logger.debug(f"   ⛔ 过滤: {title}")

    logger.info(f"   📊 过滤后保留 {len(filtered)}/{len(books)} 本书")
    return filtered


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    filter_engine = CategoryFilter()

    test_cases = [
        (["Finance", "Investing", "Economics"], True),
        (["Fiction", "Novel"], False),
        (["Science Fiction", "Fantasy"], False),
        (["Business", "Management"], True),
    ]

    for categories, expected in test_cases:
        result = filter_engine.is_book_relevant(categories)
        print(f"{categories} → {result} (期望: {expected})")
