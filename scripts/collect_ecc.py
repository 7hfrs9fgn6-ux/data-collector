#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub 搜索采集模块
采集与量化、金融相关的 GitHub 项目（作为 ECC 的替代数据源）
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from utils import save_json, get_timestamp, truncate_text, load_config


class GitHubSearchCollector:
    """GitHub 搜索采集器"""

    def __init__(self):
        self.api_base = "https://api.github.com/search/repositories"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "data-collector/1.0",
            "Accept": "application/vnd.github.v3+json"
        })

    def collect(self, queries: Optional[List[str]] = None, max_items: int = 30) -> Dict[str, Any]:
        """
        采集 GitHub 搜索数据

        Args:
            queries: 搜索关键词列表
            max_items: 最大采集数量

        Returns:
            Dict: {
                "timestamp": "2026-07-31T10:00:00",
                "source": "github_search",
                "total": 15,
                "items": [...]
            }
        """
        if queries is None:
            queries = [
                "quantitative trading",
                "stock analysis",
                "factor model",
                "backtesting",
                "alpha factor"
            ]

        all_items = []
        per_query_limit = max(5, max_items // len(queries) + 1)

        for query in queries:
            items = self._search_repositories(query, per_query_limit)
            all_items.extend(items)

        # 去重（按 repo 名称）
        seen = set()
        unique_items = []
        for item in all_items:
            key = f"{item.get('owner')}/{item.get('repo')}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        # 按 stars 排序
        unique_items.sort(key=lambda x: x.get('stars', 0), reverse=True)

        return {
            "timestamp": get_timestamp(),
            "source": "github_search",
            "total": len(unique_items),
            "items": unique_items[:max_items]
        }

    def _search_repositories(self, query: str, limit: int = 5) -> List[Dict]:
        """执行搜索"""
        params = {
            "q": query,
            "sort": "stars",
            "order": "desc",
            "per_page": limit
        }

        try:
            resp = self.session.get(self.api_base, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_search_results(data, query)
        except Exception as e:
            print(f"搜索 '{query}' 失败: {e}")
            return []

    def _parse_search_results(self, data: Dict, query: str) -> List[Dict]:
        """解析搜索结果"""
        items = []
        repo_data = data.get('items', [])

        for repo in repo_data:
            try:
                # 过滤掉明显不相关的项目
                name = repo.get('name', '')
                description = repo.get('description', '') or ''
                full_name = repo.get('full_name', '')

                # 计算相关性评分（基于关键词匹配）
                relevance_score = self._calculate_relevance(
                    name, description, query
                )

                # 只保留有一定相关性的项目
                if relevance_score < 0.1:
                    continue

                items.append({
                    "id": full_name,
                    "owner": repo.get('owner', {}).get('login', ''),
                    "repo": name,
                    "url": repo.get('html_url', ''),
                    "description": truncate_text(description, 300),
                    "stars": repo.get('stargazers_count', 0),
                    "forks": repo.get('forks_count', 0),
                    "language": repo.get('language', ''),
                    "topics": repo.get('topics', []),
                    "search_query": query,
                    "relevance_score": round(relevance_score, 2)
                })
            except Exception as e:
                print(f"解析仓库失败: {e}")
                continue

        return items

    def _calculate_relevance(self, name: str, description: str, query: str) -> float:
        """计算相关性评分（0-1）"""
        text = f"{name} {description}".lower()
        query_words = query.lower().split()

        matches = 0
        for word in query_words:
            if word in text:
                matches += 1

        # 基础评分
        if matches == 0:
            return 0.0
        base_score = matches / len(query_words)

        # 额外关键词加分
        extra_keywords = ['quant', 'finance', 'trading', 'backtest', 'factor', 'alpha']
        extra_score = 0
        for kw in extra_keywords:
            if kw in text:
                extra_score += 0.1

        return min(1.0, base_score + extra_score)


def collect_github_search() -> Dict[str, Any]:
    """公开接口：采集 GitHub 搜索数据"""
    collector = GitHubSearchCollector()
    config = load_config() if load_config else {}

    queries = config.get('collect', {}).get('github_search', {}).get('queries', [])
    max_items = config.get('collect', {}).get('github_search', {}).get('max_items', 30)

    result = collector.collect(queries=queries, max_items=max_items)

    # 保存到暂存区
    save_json(result, f"staging/search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    return result


if __name__ == "__main__":
    from utils import load_config
    data = collect_github_search()
    print(f"搜索采集完成: {data['total']} 个项目")
