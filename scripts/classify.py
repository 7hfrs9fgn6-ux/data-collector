#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信息分级筛选模块（优化版）
将采集到的信息分为 L1/L2/L3 三个等级
"""

import re
from typing import Dict, List, Any, Optional
from datetime import datetime

from utils import save_json, get_timestamp, load_config


class InformationClassifier:
    """信息分级分类器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._load_keywords()
        self._load_thresholds()

    def _load_keywords(self):
        """加载关键词配置"""
        classification = self.config.get('classification', {})
        self.l1_keywords = classification.get('l1_keywords', [
            'trading', 'quant', 'backtest', 'factor', 'alpha',
            'signal', 'portfolio', 'risk', 'optimization',
            'parameter', 'weight', 'threshold', 'momentum',
            'reversal', 'arbitrage', 'volatility', 'correlation',
            'regime', 'stop loss', 'take profit', 'drawdown',
            'sharpe', 'calmar', 'sortino'
        ])
        self.l2_keywords = classification.get('l2_keywords', [
            'research', 'paper', 'discussion', 'blog', 'tutorial',
            'overview', 'news', 'guide', 'introduction', 'summary',
            'review', 'data', 'dataset', 'finance', 'economic'
        ])

    def _load_thresholds(self):
        """加载分级阈值"""
        thresholds = self.config.get('classification', {}).get('thresholds', {})
        self.l1_min_matches = thresholds.get('l1_min_matches', 2)
        self.l1_star_threshold = thresholds.get('l1_star_threshold', 500)
        self.l2_min_matches = thresholds.get('l2_min_matches', 2)

    def classify(self, items: List[Dict]) -> Dict[str, Any]:
        """
        对信息列表进行分级分类
        """
        l1_items = []
        l2_items = []
        l3_items = []

        for item in items:
            level, score, details = self._classify_single(item)
            item['v_score'] = round(score, 2)
            item['category'] = level
            item['match_details'] = details

            if level == 'L1':
                l1_items.append(item)
            elif level == 'L2':
                l2_items.append(item)
            else:
                l3_items.append(item)

        # 按评分排序
        l1_items.sort(key=lambda x: x.get('v_score', 0), reverse=True)
        l2_items.sort(key=lambda x: x.get('v_score', 0), reverse=True)
        l3_items.sort(key=lambda x: x.get('v_score', 0), reverse=True)

        result = {
            "timestamp": get_timestamp(),
            "total": len(items),
            "l1": l1_items,
            "l2": l2_items,
            "l3": l3_items,
            "stats": {
                "l1": len(l1_items),
                "l2": len(l2_items),
                "l3": len(l3_items)
            }
        }

        save_json(result, f"staging/classified_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
        return result

    def _classify_single(self, item: Dict) -> tuple:
        """
        对单条信息进行分级
        
        Returns:
            (level, score, details)
        """
        title = item.get('title', '')
        description = item.get('description', '') or ''
        repo_name = item.get('repo', '') or item.get('name', '')
        stars = item.get('stars', 0)
        topics = item.get('topics', [])

        # 构建搜索文本
        text = f"{repo_name} {title} {description} {' '.join(topics)}".lower()

        # 计算各等级匹配度
        l1_matches, l1_score = self._calculate_match_score(text, self.l1_keywords)
        l2_matches, l2_score = self._calculate_match_score(text, self.l2_keywords)

        details = {
            "l1_matches": l1_matches,
            "l2_matches": l2_matches,
            "stars": stars
        }

        # === L1 判定（高价值） ===
        # 条件A：命中 L1 关键词 ≥ 3 个
        # 条件B：命中 L1 关键词 ≥ 2 个 + stars > 500
        is_l1 = False
        score = 0

        if l1_matches >= 3:
            is_l1 = True
            score = min(10, 5 + l1_matches)
            details['reason'] = f'命中 {l1_matches} 个 L1 关键词'
        elif l1_matches >= 2 and stars > self.l1_star_threshold:
            is_l1 = True
            score = min(10, 4 + l1_matches + (stars / 1000))
            details['reason'] = f'命中 {l1_matches} 个 L1 关键词 + ⭐{stars}'

        if is_l1:
            return 'L1', min(10, score), details

        # === L2 判定（中等价值） ===
        if l2_matches >= self.l2_min_matches:
            score = min(8, 2 + l2_matches + (l1_matches * 0.5))
            details['reason'] = f'命中 {l2_matches} 个 L2 关键词'
            return 'L2', min(8, score), details

        # === L3 判定（参考素材） ===
        return 'L3', min(6, 1 + l1_matches * 0.5 + l2_matches * 0.3), details

    def _calculate_match_score(self, text: str, keywords: List[str]) -> tuple:
        """
        计算文本与关键词的匹配度
        
        Returns:
            (匹配数量, 评分)
        """
        matches = 0
        matched_words = []

        for keyword in keywords:
            keyword_lower = keyword.lower()
            if keyword_lower in text:
                # 检查是否是完整单词匹配
                patterns = [
                    f'\\b{re.escape(keyword_lower)}\\b',
                    f'\\b{re.escape(keyword_lower)}s\\b',
                    f'\\b{re.escape(keyword_lower)}ing\\b',
                    f'\\b{re.escape(keyword_lower)}ed\\b'
                ]
                for pattern in patterns:
                    if re.search(pattern, text):
                        if keyword_lower not in matched_words:
                            matches += 1
                            matched_words.append(keyword_lower)
                        break
                else:
                    # 部分匹配也算
                    if keyword_lower not in matched_words:
                        matches += 0.5
                        matched_words.append(keyword_lower)

        return min(len(keywords), matches), matches


def classify_items(items: List[Dict]) -> Dict[str, Any]:
    """公开接口：对信息列表进行分级分类"""
    config = load_config() if load_config else {}
    classifier = InformationClassifier(config)
    return classifier.classify(items)


def merge_and_classify(github_data: Dict, search_data: Dict) -> Dict[str, Any]:
    """
    合并多个数据源并进行分级分类
    """
    all_items = []

    if github_data and github_data.get('items'):
        for item in github_data['items']:
            item['source'] = 'github_trending'
            all_items.append(item)

    if search_data and search_data.get('items'):
        for item in search_data['items']:
            item['source'] = 'github_search'
            all_items.append(item)

    # 去重
    seen = set()
    unique_items = []
    for item in all_items:
        item_id = item.get('id', '')
        if item_id and item_id not in seen:
            seen.add(item_id)
            unique_items.append(item)
        elif not item_id:
            unique_items.append(item)

    return classify_items(unique_items)


if __name__ == "__main__":
    from utils import load_json
    import glob

    github_files = glob.glob("staging/github_*.json")
    search_files = glob.glob("staging/search_*.json")

    github_data = load_json(github_files[-1]) if github_files else None
    search_data = load_json(search_files[-1]) if search_files else None

    if github_data or search_data:
        result = merge_and_classify(github_data, search_data)
        print(f"分级完成: L1={result['stats']['l1']}, "
              f"L2={result['stats']['l2']}, "
              f"L3={result['stats']['l3']}")
    else:
        print("无测试数据")
