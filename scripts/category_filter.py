#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类过滤模块（优化版 V3）
策略：标题优先 → 分类辅助 → 降级保留
"""

import re
import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class CategoryFilter:
    """分类过滤器（V3：标题优先）"""

    # ★ 标题优先关键词（匹配即通过）
    TITLE_KEYWORDS = [
        # 金融与投资
        'invest', 'finance', 'econom', 'market', 'trade', 'asset',
        'capital', 'credit', 'bank', 'money', 'wealth', 'portfolio',
        'stock', 'bond', 'fund', 'risk', 'valuation', 'cash', 'debt',
        'equity', 'inflation', 'tax', 'accounting', 'merger', 'acquisition',
        'venture', 'hedge', 'monetary', 'fiscal', 'currency', 'gold',
        'commodity', 'real estate', 'mortgage', 'loan', 'financial',
        'banking', 'investing', 'trading', 'wealthy',
        
        # 金融书籍常见词
        'street', 'gate', 'paper', 'lenders', 'capitalism',
        'rich', 'poor', 'babylon', 'smartest', 'snowball',
        'millionaire', 'billionaire', 'profit', 'margin', 'insurance',
        'pension', 'retirement', 'budget', 'audit', 'corporate',
        'dividend', 'earnings', 'recession', 'interest', 'tariff',
        'forex', 'oil', 'energy', 'property', 'saving',
        'value', 'growth', 'income', 'expense', 'liability',
        'buffett', 'soros', 'munger', 'graham', 'investor', 'trader',
        
        # ★ 行为金融学
        'prospect', 'mental accounting', 'money illusion', 'herd',
        'overconfidence', 'loss aversion', 'framing', 'cognitive',
        'behavioral', 'heuristic', 'bias', 'fallacy', 'psycholog',
        'decision', 'judgment', 'uncertainty',
        
        # ★ 货币/比特币/加密货币
        'bitcoin', 'cryptocurrency', 'monetary', 'gold standard',
        'fiat', 'digital currency', 'blockchain',
        
        # ★ 保险/风险
        'insurance', 'actuarial', 'risk management', 'underwriting',
        
        # ★ 经济学经典
        'treatise', 'principles of', 'inquiry into', 'wealth of nations',
        'capital', 'economics of', 'theory of', 'political economy',
        
        # ★ 企业管理/商业
        'management', 'leadership', 'strategy', 'entrepreneur',
        'corporate', 'business', 'startup', 'venture',
        'organizational', 'organisational',
        
        # ★ 其他
        'breakout', 'nations', 'global', 'crisis', 'recovery',
        'bubble', 'crash', 'regulation', 'deregulation',
        'banking', 'lender', 'borrower', 'credit', 'debt',
        'interest rate', 'yield', 'dividend', 'buyback',
        'shareholder', 'stakeholder', 'governance',
        'trust', 'antitrust', 'monopoly', 'competition',
        'welfare', 'poverty', 'inequality', 'distribution',
        'growth', 'productivity', 'employment', 'unemployment',
        'trade war', 'tariff war', 'sanction', 'embargo',
        'stimulus', 'bailout', 'quantitative easing', 'taper',
        'inflation targeting', 'independence', 'central bank',
        'fed', 'federal reserve', 'ecb', 'boj', 'boe',
        'imf', 'world bank', 'wto', 'oecd', 'g20',
        'emerging market', 'frontier market', 'developed market',
        'bull', 'bear', 'correction', 'rally', 'sell-off',
    ]

    # ★ 分类匹配关键词（辅助，仅当标题不匹配时使用）
    CATEGORY_KEYWORDS = [
        'finance', 'investing', 'investment', 'economics', 'business',
        'management', 'accounting', 'banking', 'insurance', 'risk',
        'valuation', 'monetary', 'fiscal', 'trade', 'market',
        'capital', 'asset', 'fund', 'corporate', 'entrepreneur',
        'behavioral', 'cognitive', 'psychology',
        'strategy', 'leadership', 'organizational',
    ]

    EXCLUDED_KEYWORDS = [
        'fiction', 'novel', 'science fiction', 'fantasy',
        'mystery', 'thriller', 'romance', 'horror',
        'poetry', 'drama', 'theater', 'play',
        'children', 'juvenile', 'young adult',
        'cookbook', 'cooking', 'food',
        'self help', 'spirituality', 'religion', 'bible', 'quran',
        'health', 'fitness', 'diet', 'travel', 'guide', 'tour',
        'craft', 'hobby', 'diy', 'art', 'music', 'photography',
        'sports', 'exercise', 'gym', 'language', 'dictionary', 'grammar'
    ]

    def __init__(self):
        self.title_keywords = self.TITLE_KEYWORDS
        self.category_keywords = self.CATEGORY_KEYWORDS
        self.excluded_keywords = self.EXCLUDED_KEYWORDS

    def is_book_relevant(self, categories: List[str], title: str = '') -> bool:
        """
        ★ 判断书籍是否相关（V3：标题优先）
        1. 标题匹配关键词 → 直接通过（跳过分类检查）
        2. 标题不匹配 → 检查分类
        3. 分类匹配 → 通过
        4. 都不匹配 → 拒绝
        """
        # ★ 1. 标题优先匹配
        if self._check_title(title):
            return True

        # 2. 分类匹配（辅助）
        if not categories:
            return False

        cat_text = ' '.join(categories).lower()
        
        # 检查排除关键词
        for excluded in self.excluded_keywords:
            if excluded in cat_text:
                return False

        # 检查分类关键词（宽松匹配）
        for keyword in self.category_keywords:
            if keyword in cat_text:
                return True

        return False

    def _check_title(self, title: str) -> bool:
        """标题匹配关键词"""
        if not title:
            return False

        title_lower = title.lower()

        # 逐词匹配
        for keyword in self.title_keywords:
            if keyword in title_lower:
                return True

        return False

    def is_finance_title(self, title: str) -> bool:
        """公开方法：判断标题是否为金融相关（供采集器使用）"""
        return self._check_title(title)

    def get_relevance_score(self, categories: List[str], title: str = '') -> float:
        """计算相关性得分（0-1）"""
        # 标题匹配 → 高分
        if self._check_title(title):
            return 0.95

        if not categories:
            return 0.0

        cat_text = ' '.join(categories).lower()
        match_count = 0
        for keyword in self.category_keywords:
            if keyword in cat_text:
                match_count += 1

        return min(1.0, match_count / 3)


def filter_books(books: List[Dict]) -> List[Dict]:
    """批量过滤书籍"""
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
        # 应该通过（标题匹配）
        ("The Bitcoin Standard", [], True),
        ("Prospect Theory", [], True),
        ("The Armchair Economist", [], True),
        ("Money Illusion", [], True),
        # 应该通过（分类匹配）
        ("Some Book", ["Finance"], True),
        ("Some Book", ["Economics"], True),
        ("Some Book", ["Business"], True),
        # 应该拒绝
        ("Some Book", ["Fiction"], False),
        ("Some Book", ["Science Fiction"], False),
    ]

    for title, categories, expected in test_cases:
        result = filter_engine.is_book_relevant(categories, title)
        print(f"{title} ({categories}) → {result} (期望: {expected})")
