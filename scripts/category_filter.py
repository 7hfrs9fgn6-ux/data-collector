#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类过滤模块（优化版 V2）
职责：
  1. 根据白名单过滤书籍
  2. 多源验证分类匹配度
  3. ★ 标题优先策略：标题匹配则跳过分类过滤
  4. ★ 宽松匹配模式：分类匹配更灵活
"""

import re
import logging
from typing import Dict, List, Set, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)


class CategoryFilter:
    """分类过滤器（优化版）"""

    # ★ 扩展白名单（增加细化分类）
    ALLOWED_CATEGORIES = {
        # 金融与投资
        'finance', 'investing', 'investment', 'financial_markets',
        'asset_pricing', 'risk_management', 'portfolio_management',
        'value_investing', 'quantitative_finance', 'derivatives',
        'corporate_finance', 'behavioral_finance', 'financial_economics',
        'personal finance', 'wealth management', 'asset management',
        'money management', 'financial planning', 'retirement planning',
        'financial literacy', 'financial independence',

        # 经济学
        'economics', 'macroeconomics', 'microeconomics',
        'econometrics', 'political_economy', 'economic_history',
        'behavioral_economics', 'development_economics',
        'monetary economics', 'international economics',

        # 商业与管理
        'business', 'management', 'strategy', 'leadership',
        'organizational_behavior', 'decision_theory', 'game_theory',
        'entrepreneurship', 'corporate governance', 'business history',
        'operations management', 'supply chain', 'marketing',

        # 心理学与思维
        'psychology', 'cognitive_science', 'cognitive_psychology',
        'mental_models', 'decision_making', 'thinking',
        'behavioral science', 'human behavior',

        # 历史与传记
        'financial_history', 'business_history', 'economic_history',
        'biography', 'autobiography', 'memoir',

        # 数据与量化
        'statistics', 'data_science', 'machine_learning',
        'operations_research', 'mathematics', 'quantitative_analysis',

        # 会计与法律
        'accounting', 'financial_law', 'commercial_law',
        'tax', 'auditing',

        # ★ 新增细化分类
        'corporate', 'business strategy', 'business management',
        'philosophy', 'philosophy of economics', 'philosophy of finance',
        'investor psychology', 'market psychology', 'trading psychology',
        'financial crisis', 'economic crisis', 'banking',
        'public finance', 'fiscal policy', 'monetary policy',
        'global economy', 'international trade', 'development finance',
        'venture capital', 'private equity', 'hedge funds',
        'mutual funds', 'etf', 'index funds', 'passive investing',
        'active investing', 'technical analysis', 'fundamental analysis',
        'real estate investing', 'property investing',
    }

    # ★ 标题优先关键词（匹配即通过）
    TITLE_PRIORITY_KEYWORDS = [
        'invest', 'finance', 'econom', 'market', 'trade', 'asset',
        'capital', 'credit', 'bank', 'money', 'wealth', 'portfolio',
        'stock', 'bond', 'fund', 'risk', 'decision', 'behavior',
        'psycholog', 'strategy', 'management', 'business', 'valuation',
        'cash', 'debt', 'equity', 'inflation', 'tax', 'accounting',
        'merger', 'acquisition', 'venture', 'hedge', 'monetary',
        'fiscal', 'currency', 'gold', 'commodity', 'real estate',
        'mortgage', 'loan', 'financial', 'banking', 'investing',
        'trading', 'wealthy', 'street', 'gate', 'paper', 'lenders',
        'capitalism', 'rich', 'poor', 'babylon', 'smartest', 'snowball',
        'millionaire', 'billionaire', 'profit', 'margin', 'insurance',
        'pension', 'retirement', 'budget', 'audit', 'corporate',
        'dividend', 'earnings', 'recession', 'interest', 'tariff',
        'forex', 'oil', 'energy', 'property', 'saving',
        'value', 'growth', 'income', 'expense', 'liability',
        'net worth', 'stock market', 'bond market', 'buffett',
        'soros', 'munger', 'graham', 'investor', 'trader'
    ]

    # 排除关键词
    EXCLUDED_KEYWORDS = {
        'fiction', 'novel', 'science_fiction', 'fantasy',
        'mystery', 'thriller', 'romance', 'horror',
        'poetry', 'drama', 'theater', 'play',
        'children', 'juvenile', 'young_adult',
        'cookbook', 'cooking', 'food',
        'self_help', 'spirituality', 'religion', 'bible', 'quran',
        'health', 'fitness', 'diet', 'travel', 'guide', 'tour',
        'craft', 'hobby', 'diy', 'art', 'music', 'photography',
        'sports', 'exercise', 'gym', 'language', 'dictionary', 'grammar'
    }

    def __init__(self):
        self.allowed_categories = self.ALLOWED_CATEGORIES
        self.excluded_keywords = self.EXCLUDED_KEYWORDS
        self.title_keywords = self.TITLE_PRIORITY_KEYWORDS

    def is_book_relevant(self, categories: List[str], title: str = '') -> bool:
        """
        判断书籍是否相关
        ★ 优化：标题优先匹配 → 通过
        ★ 优化：宽松分类匹配
        """
        if not categories:
            # 没有分类时，依赖标题判断
            return self._check_title(title)

        # ★ 1. 标题优先匹配（匹配则直接通过，不检查分类）
        if self._check_title(title):
            return True

        # ★ 2. 宽松分类匹配
        for cat in categories:
            cat_lower = cat.lower()

            # 检查排除关键词
            for excluded in self.excluded_keywords:
                if excluded in cat_lower:
                    return False

            # ★ 检查白名单匹配（双向匹配）
            for allowed in self.allowed_categories:
                # 方式1：分类包含白名单词
                if allowed in cat_lower:
                    return True
                # 方式2：白名单词包含分类（处理 "Personal finance" 这类）
                if cat_lower in allowed:
                    return True

        return False

    def _check_title(self, title: str) -> bool:
        """通过标题判断是否相关"""
        if not title:
            return False

        title_lower = title.lower()

        # ★ 检查标题关键词
        for keyword in self.title_keywords:
            if keyword in title_lower:
                return True

        return False

    def get_relevance_score(self, categories: List[str], title: str = '') -> float:
        """计算相关性得分 (0-1)"""
        # 标题匹配优先
        if self._check_title(title):
            return 0.9

        if not categories:
            return 0.0

        match_count = 0
        for cat in categories:
            cat_lower = cat.lower()
            for allowed in self.allowed_categories:
                if allowed in cat_lower or cat_lower in allowed:
                    match_count += 1
                    break

        return match_count / len(categories) if categories else 0.0

    def multi_source_validate(self, source_results: Dict[str, Any]) -> Dict[str, Any]:
        """多源验证：从不同来源验证分类一致性"""
        all_categories = []
        source_names = []

        wiki_categories = source_results.get('wikipedia', {}).get('categories', [])
        if wiki_categories:
            all_categories.extend(wiki_categories)
            source_names.append('wikipedia')

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

        category_counts = Counter(all_categories)
        relevance_score = self.get_relevance_score(all_categories)

        is_valid = relevance_score >= 0.3 or len(source_names) >= 2

        return {
            'valid': is_valid,
            'score': relevance_score,
            'sources': source_names,
            'categories': all_categories,
            'category_counts': dict(category_counts),
            'source_coverage': len(source_names) / 2,
            'reason': f"匹配度 {relevance_score:.2f}, 来源 {len(source_names)}/2"
        }


def filter_books(books: List[Dict]) -> List[Dict]:
    """批量过滤书籍（优化版）"""
    filter_engine = CategoryFilter()
    filtered = []

    for book in books:
        categories = book.get('categories', [])
        title = book.get('title', '')

        if filter_engine.is_book_relevant(categories, title):
            book['relevance_score'] = filter_engine.get_relevance_score(categories, title)
            filtered.append(book)
        else:
            logger.debug(f"   ⛔ 过滤: {title}")

    logger.info(f"   📊 过滤后保留 {len(filtered)}/{len(books)} 本书")
    return filtered


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    filter_engine = CategoryFilter()

    test_cases = [
        # 应该通过（即使分类不匹配，标题也匹配）
        (["Personal finance"], "Barbarians at the Gate", True),
        (["Business"], "Beating the Street", True),
        (["Philosophy"], "Antifragile", True),
        (["Biography"], "The Snowball", True),
        # 应该排除
        (["Fiction"], "Harry Potter", False),
        (["Science Fiction"], "Dune", False),
    ]

    for categories, title, expected in test_cases:
        result = filter_engine.is_book_relevant(categories, title)
        print(f"{title} ({categories}) → {result} (期望: {expected})")
