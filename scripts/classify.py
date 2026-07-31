#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
信息分级筛选模块
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

    def _load_keywords(self):
        """加载关键词配置"""
        classification = self.config.get('classification', {})
        self.l1_keywords = classification.get('l1_keywords', [
            'parameter', 'weight', 'threshold', 'optimization',
            'improvement', 'tuning', 'adjustment', 'factor'
        ])
        self.l2_keywords = classification.get('l2_keywords', [
            'strategy', 'signal', 'analysis', 'factor',
            'model', 'indicator', 'backtest'
        ])
        self.l3_keywords = classification.get('l3_keywords', [
            'research', 'paper', 'discussion', 'trend',
            'news', 'blog', 'tutorial', 'overview'
        ])

    def classify(self, items: List[Dict]) -> Dict[str, Any]:
        """
        对信息列表进行分级分类

        Args:
            items: 信息列表，每条信息包含 title, description, source 等字段

        Returns:
            Dict: {
                "timestamp": "2026-07-31T10:00:00",
                "total": 50,
                "l1": [...],  # 高价值信号
                "l2": [...],  # 中等价值线索
                "l3": [...],  # 参考素材
                "stats": {"l1": 5, "l2": 15, "l3": 30}
            }
        """
        l1_items = []
        l2_items = []
        l3_items = []

        for item in items:
            level, score = self._classify_single(item)
            item['v_score'] = score
            item['category'] = level

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

        # 保存分级结果
        save_json(result, f"staging/classified_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        return result

    def _classify_single(self, item: Dict) -> tuple:
        """
        对单条信息进行分级

        Returns:
            (level, score): 等级和评分
        """
        title = item.get('title', '')
        description = item.get('description', '')
        item_type = item.get('type', '')
        source = item.get('source', '')

        # 构建搜索文本
        text = f"{title} {description} {item_type} {source}".lower()

        # 计算各等级匹配度
        l1_score = self._calculate_match_score(text, self.l1_keywords)
        l2_score = self._calculate_match_score(text, self.l2_keywords)
        l3_score = self._calculate_match_score(text, self.l3_keywords)

        # 判断等级
        if l1_score >= 3:
            return 'L1', min(10, 5 + l1_score)
        elif l2_score >= 2:
            return 'L2', min(8, 3 + l2_score)
        elif l3_score >= 1:
            return 'L3', min(6, 1 + l3_score)
        else:
            return 'L3', 0.5

    def _calculate_match_score(self, text: str, keywords: List[str]) -> float:
        """计算文本与关键词的匹配度"""
        score = 0
        text_words = set(re.findall(r'\w+', text))

        for keyword in keywords:
            if keyword.lower() in text:
                score += 1
            # 检查单词边界匹配
            if f" {keyword.lower()} " in f" {text} ":
                score += 0.5

        # 检查组合关键词
        if len(keywords) > 3:
            combinations = [f"{keywords[i]}_{keywords[j]}" for i in range(len(keywords))
                          for j in range(i+1, len(keywords))]
            for combo in combinations:
                if combo in text:
                    score += 1

        return score


def classify_items(items: List[Dict]) -> Dict[str, Any]:
    """公开接口：对信息列表进行分级分类"""
    config = load_config() if load_config else {}
    classifier = InformationClassifier(config)
    return classifier.classify(items)


def merge_and_classify(github_data: Dict, ecc_data: Dict) -> Dict[str, Any]:
    """
    合并多个数据源并进行分级分类
    """
    all_items = []

    # 提取 GitHub 数据
    if github_data and github_data.get('items'):
        for item in github_data['items']:
            item['source'] = 'github_trending'
            all_items.append(item)

    # 提取 ECC 数据
    if ecc_data and ecc_data.get('items'):
        for item in ecc_data['items']:
            item['source'] = 'ecc'
            all_items.append(item)

    # 去重（按 id）
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

    # 测试：加载已有的采集数据
    import glob
    github_files = glob.glob("staging/github_*.json")
    ecc_files = glob.glob("staging/ecc_*.json")

    github_data = load_json(github_files[-1]) if github_files else None
    ecc_data = load_json(ecc_files[-1]) if ecc_files else None

    if github_data or ecc_data:
        result = merge_and_classify(github_data, ecc_data)
        print(f"分级完成: L1={result['stats']['l1']}, "
              f"L2={result['stats']['l2']}, "
              f"L3={result['stats']['l3']}")
    else:
        print("无测试数据")
