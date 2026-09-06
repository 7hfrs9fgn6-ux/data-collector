#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分类过滤模块（V5：完整关键词覆盖 + 标题优先）
策略：标题优先 → 分类辅助 → 知识条目识别
★ 覆盖领域：金融、行为金融、加密货币、经济学、商业、行业、人物、市场术语
"""

import logging
from typing import Dict, List, Any

logger = logging.getLogger(__name__)


class CategoryFilter:
    """分类过滤器（V5：完整关键词覆盖）"""

    # ============================================================
    # ★ 标题优先关键词（完整版，按领域分类）
    # ============================================================

    TITLE_KEYWORDS = [
        # ---------- 1. 金融与投资核心 ----------
        'invest', 'finance', 'financial', 'investing', 'investment',
        'market', 'trading', 'trader', 'asset', 'capital', 'credit',
        'bank', 'banking', 'money', 'wealth', 'wealthy', 'portfolio',
        'stock', 'bond', 'fund', 'risk', 'valuation', 'cash', 'debt',
        'equity', 'inflation', 'deflation', 'tax', 'accounting',
        'audit', 'merger', 'acquisition', 'venture', 'hedge',
        'monetary', 'fiscal', 'currency', 'forex', 'gold', 'silver',
        'commodity', 'oil', 'energy', 'real estate', 'property',
        'mortgage', 'loan', 'saving', 'savings', 'interest', 'dividend',
        'earnings', 'profit', 'margin', 'yield', 'recession',
        'recovery', 'crisis', 'bubble', 'crash', 'regulation',
        'deregulation', 'lender', 'borrower', 'credit', 'debt',
        'buyback', 'shareholder', 'stakeholder', 'governance',
        'trust', 'antitrust', 'monopoly', 'competition', 'welfare',
        'poverty', 'inequality', 'distribution', 'growth', 'productivity',
        'employment', 'unemployment', 'trade', 'tariff', 'sanction',
        'embargo', 'stimulus', 'bailout', 'quantitative easing',
        'taper', 'inflation targeting', 'central bank',
        'federal reserve', 'fed', 'ecb', 'boj', 'boe', 'imf',
        'world bank', 'wto', 'oecd', 'g20', 'emerging market',
        'frontier market', 'developed market', 'bull', 'bear',
        'correction', 'rally', 'sell-off', 'private equity',
        'venture capital', 'angel investing', 'seed funding',
        'series a', 'series b', 'ipo', 'secondary market',
        'underwriting', 'syndicate', 'spac', 'warrants',
        'options', 'futures', 'swaps', 'derivatives', 'structured products',
        'securitization', 'mbs', 'abs', 'cdo', 'collateralized',
        'tranche', 'credit default', 'arbitrage', 'straddle',
        'strangle', 'butterfly', 'collar', 'protective put',
        'covered call', 'leap', 'etf', 'mutual fund', 'index fund',
        'passive investing', 'active investing', 'factor investing',
        'smart beta', 'esg', 'esg investing', 'impact investing',
        'sri', 'divestment', 'asset management', 'wealth management',
        'money management', 'financial planning', 'retirement planning',
        'financial literacy', 'financial independence', 'financial advisor',
        'financial analyst', 'portfolio manager', 'hedge fund',
        'mutual funds', 'etfs', 'dividend investing', 'growth investing',
        'value investing', 'value investment', 'growth stock',
        'income investing', 'quantitative investing', 'quant',
        'algorithmic trading', 'high frequency trading', 'market making',
        'liquidity', 'volatility', 'beta', 'alpha', 'sharpe ratio',
        'sortino ratio', 'calmar ratio', 'drawdown', 'maximum drawdown',
        'monte carlo', 'stress testing', 'scenario analysis', 'var',
        'expected shortfall', 'risk adjusted', 'risk management',

        # ---------- 2. 行为金融学 & 心理学 ----------
        'prospect', 'prospect theory', 'mental accounting', 'money illusion',
        'herd', 'herd behavior', 'overconfidence', 'loss aversion',
        'framing', 'framing effect', 'cognitive', 'cognitive bias',
        'heuristic', 'fallacy', 'behavioral economics',
        'behavioral finance', 'disposition effect', 'endowment effect',
        'status quo bias', 'sunk cost', 'anchoring', 'confirmation bias',
        'availability bias', 'representativeness', 'recency bias',
        'hindsight bias', 'overreaction', 'underreaction', 'momentum',
        'mean reversion', 'gambler fallacy', 'hot hand fallacy',
        'planning fallacy', 'optimism bias', 'pessimism bias',
        'self serving bias', 'attribution bias', 'cognitive dissonance',
        'choice architecture', 'nudge', 'default effect', 'salience',
        'priming', 'psychology', 'psychological',

        # ---------- 3. 货币 & 加密货币 ----------
        'bitcoin', 'cryptocurrency', 'digital currency', 'blockchain',
        'decentralized', 'ledger', 'crypto', 'stablecoin',
        'central bank digital currency', 'cbdc', 'tokenization',
        'smart contract', 'distributed ledger', 'fiat money',
        'gold standard',

        # ---------- 4. 经济学经典 & 理论 ----------
        'treatise', 'principles of', 'inquiry into', 'wealth of nations',
        'political economy', 'capital', 'economics of', 'theory of',
        'general theory', 'employment interest and money',
        'socialism', 'capitalism', 'communism', 'marxism', 'keynesian',
        'neoclassical', 'monetarism', 'austrian economics',
        'chicago school', 'institutional economics',
        'development economics', 'labor economics', 'public finance',
        'international economics', 'environmental economics',
        'urban economics', 'regional economics', 'experimental economics',
        'econometrics', 'game theory', 'supply side', 'demand side',
        'trickle down', 'economic growth', 'economic development',

        # ---------- 5. 商业 & 管理 ----------
        'management', 'leadership', 'strategy', 'entrepreneur',
        'entrepreneurship', 'corporate', 'governance', 'organizational',
        'organisational', 'operations', 'supply chain', 'logistics',
        'marketing', 'brand', 'consumer', 'retail', 'e-commerce',
        'innovation', 'disruption', 'competitive advantage',
        'differentiation', 'cost leadership', 'quality management',
        'service excellence', 'organizational culture', 'values',
        'mission statement', 'vision statement', 'stakeholder management',
        'sustainability', 'csr', 'triple bottom line',
        'circular economy', 'sharing economy', 'gig economy',
        'platform business', 'network effect', 'scale', 'growth hacking',
        'agile', 'lean', 'six sigma', 'kaizen', 'continuous improvement',
        'digital transformation', 'automation', 'business intelligence',
        'data analytics', 'forecasting', 'budgeting', 'p&l',
        'roi', 'kpi', 'metric', 'dashboard', 'balanced scorecard',
        'swot', 'pestel', 'porter', 'five forces', 'value chain',
        'core competency', 'blue ocean', 'red ocean', 'disruptive innovation',
        'sustaining innovation', 'business model', 'business plan',
        'feasibility study', 'market research', 'competitive analysis',

        # ---------- 6. 行业 ----------
        'banking', 'insurance', 'insurtech', 'actuarial', 'underwriting',
        'claims', 'risk assessment', 'actuarial science',
        'real estate', 'property', 'construction', 'development',
        'energy', 'oil', 'gas', 'renewable energy', 'solar', 'wind',
        'nuclear', 'technology', 'software', 'hardware', 'semiconductor',
        'chip', 'pharmaceutical', 'biotech', 'healthcare', 'medical',
        'hospital', 'retail', 'consumer', 'food', 'beverage', 'restaurant',
        'hospitality', 'travel', 'tourism', 'aviation', 'airline',
        'shipping', 'logistics', 'automotive', 'ev', 'autonomous vehicle',
        'mobility', 'transportation', 'telecom', '5g', 'fiber optic',
        'broadband', 'internet', 'web', 'cloud', 'saas', 'paas', 'iaas',
        'cybersecurity', 'fintech', 'proptech', 'healthtech', 'edtech',
        'agritech', 'cleantech', 'space', 'aerospace', 'defense',
        'military', 'government', 'public sector', 'nonprofit',
        'ngo', 'foundation', 'think tank', 'academic', 'university',

        # ---------- 7. 书籍 & 出版 ----------
        'book', 'books', 'bibliography', 'literature', 'reading list',
        'recommended reading', 'must read', 'classic', 'modern classic',
        'bestseller', 'new york times', 'wall street journal',

        # ---------- 8. 人物 & 传记 ----------
        'buffett', 'munger', 'graham', 'keynes', 'hayek', 'friedman',
        'kahneman', 'tversky', 'thaler', 'shiller', 'taleb', 'marks',
        'dalio', 'lynch', 'bogle', 'fisher', 'templeton', 'soros',
        'gates', 'jobs', 'musk', 'bezos', 'greenspan', 'bernanke',
        'yellen', 'powell', 'draghi', 'lagarde', 'carney', 'kuroda',
        'rajan', 'krugman', 'stiglitz', 'sen', 'deaton', 'piketty',
        'atkinson', 'saez', 'zucman', 'acemoglu', 'robinson',
        'banerjee', 'duflo', 'kremer', 'arrow', 'solow', 'romer',
        'lucas', 'prescott', 'kydland', 'fama', 'french',
        'shleifer', 'vishny', 'jensen', 'meckling', 'carhart',
        'asness', 'ilmanen', 'pedersen', 'ang', 'bouchaud',
        'sornette', 'mandelbrot', 'ariely', 'sunstein', 'mullainathan',
        'shafir', 'bertrand', 'karlan', 'zinman', 'morduch',
        'rutherford', 'collins', 'yunus', 'sachs', 'easterly',
        'collier', 'rodrik', 'hausmann', 'hidalgo', 'fujita',
        'venables', 'helpman', 'grossman', 'melitz', 'antras',
        'aghion', 'howitt', 'jones', 'weil', 'barro', 'mankiw',
        'north', 'williamson', 'ostrom', 'coase', 'alchian',
        'demsetz', 'klein', 'crawford', 'hart', 'moore',
        'holmstrom', 'milgrom', 'roberts', 'kreps', 'wilson',
        'spence', 'akerlof', 'roth', 'shapley', 'myerson',
        'maskin', 'hurwicz', 'mckenzie', 'samuelson', 'hicks',
        'hansen', 'sargent', 'sims', 'stock', 'watson',
        'hamilton', 'greene', 'wooldridge', 'angrist', 'imbens',
        'card', 'krueger', 'ashenfelter', 'heckman', 'mcfadden',
        'amemiya', 'white', 'newey', 'ljungqvist', 'stokey',
        'cooley', 'king', 'plosser', 'rebelo', 'hall',

        # ---------- 9. 市场术语 & 概念 ----------
        'bull trap', 'bear trap', 'dead cat bounce', 'pump and dump',
        'short squeeze', 'gamma squeeze', 'squeeze', 'margin call',
        'stop loss', 'take profit', 'limit order', 'market order',
        'spread', 'bid ask', 'liquidity trap', 'liquidity crisis',
        'credit crunch', 'credit bubble', 'debt trap', 'debt crisis',
        'sovereign debt', 'euro crisis', 'asian financial crisis',
        'dot com bubble', 'subprime mortgage', 'subprime crisis',
    ]

    # ---------- 分类匹配关键词（辅助，仅当标题不匹配时使用） ----------
    CATEGORY_KEYWORDS = [
        'finance', 'investing', 'investment', 'economics', 'business',
        'management', 'accounting', 'banking', 'insurance', 'risk',
        'valuation', 'monetary', 'fiscal', 'trade', 'market',
        'capital', 'asset', 'fund', 'corporate', 'entrepreneur',
        'behavioral', 'cognitive', 'psychology',
        'strategy', 'leadership', 'organizational',
        'theory', 'concept', 'principle', 'model',
        'person', 'biography', 'economist',
        'term', 'definition', 'glossary',
    ]

    # ---------- 排除关键词 ----------
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
        # 去重保持顺序
        self.title_keywords = self._deduplicate(self.TITLE_KEYWORDS)
        self.category_keywords = self._deduplicate(self.CATEGORY_KEYWORDS)
        self.excluded_keywords = self._deduplicate(self.EXCLUDED_KEYWORDS)

    def _deduplicate(self, items: list) -> list:
        """去重保持顺序"""
        seen = set()
        result = []
        for item in items:
            if item not in seen:
                seen.add(item)
                result.append(item)
        return result

    def is_book_relevant(self, categories: List[str], title: str = '') -> bool:
        """
        判断书籍/条目是否相关
        ★ 策略：标题优先匹配 → 通过
                标题不匹配 → 分类匹配
                都不匹配 → 拒绝
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

        # 检查分类关键词
        for keyword in self.category_keywords:
            if keyword in cat_text:
                return True

        return False

    def _check_title(self, title: str) -> bool:
        """标题匹配关键词"""
        if not title:
            return False

        title_lower = title.lower()

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

    def infer_entry_type(self, title: str, wiki_data: Dict = None) -> str:
        """
        推断知识条目类型
        返回: theory / concept / person / term / bias / effect / model / book
        """
        if not title:
            return 'concept'

        title_lower = title.lower()
        categories = []
        if wiki_data:
            categories = wiki_data.get('categories', [])

        cat_text = ' '.join(categories).lower() if categories else ''

        # 1. 书籍类型判断
        if wiki_data:
            if wiki_data.get('isbn') or 'Infobox book' in str(wiki_data.get('infobox', '')):
                return 'book'

        # 2. 理论
        if 'theory' in title_lower or 'theory' in cat_text:
            return 'theory'

        # 3. 效应
        if 'effect' in title_lower or 'effect' in cat_text:
            return 'effect'

        # 4. 偏差
        if 'bias' in title_lower or 'bias' in cat_text:
            return 'bias'

        # 5. 模型
        if 'model' in title_lower or 'model' in cat_text:
            return 'model'

        # 6. 人物
        if 'economist' in cat_text or 'people' in cat_text or 'biography' in cat_text:
            return 'person'
        if any(k in title_lower for k in ['biography', 'memoir', 'autobiography']):
            return 'person'
        if any(k in title_lower for k in [
            'buffett', 'munger', 'graham', 'keynes', 'hayek', 'friedman',
            'kahneman', 'tversky', 'thaler', 'shiller', 'taleb', 'marks',
            'dalio', 'lynch', 'bogle', 'fisher', 'templeton', 'soros',
            'gates', 'jobs', 'musk', 'bezos'
        ]):
            return 'person'

        # 7. 术语
        if any(k in title_lower for k in [
            'trap', 'rally', 'correction', 'sell-off', 'spread',
            'margin', 'stop loss', 'take profit', 'leverage'
        ]):
            return 'term'

        # 8. 概念（默认）
        if any(k in title_lower for k in [
            'behavior', 'cognitive', 'mental', 'psychology',
            'concept', 'principle', 'idea', 'framework'
        ]):
            return 'concept'

        return 'concept'


def filter_books(books: List[Dict]) -> List[Dict]:
    """批量过滤书籍（供采集器使用）"""
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
