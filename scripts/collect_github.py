#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GitHub Trending 采集模块
采集 GitHub Trending 页面数据
"""

import re
import requests
from typing import List, Dict, Any, Optional
from datetime import datetime
from bs4 import BeautifulSoup

from utils import save_json, get_timestamp, truncate_text


class GitHubTrendingCollector:
    """GitHub Trending 采集器"""

    def __init__(self):
        self.base_url = "https://github.com/trending"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        })

    def collect(self, languages: Optional[List[str]] = None, max_items: int = 50) -> Dict[str, Any]:
        """
        采集 GitHub Trending 数据

        Args:
            languages: 编程语言列表，如 ["python", "javascript"]
            max_items: 最大采集数量

        Returns:
            Dict: {
                "timestamp": "2026-07-31T10:00:00",
                "source": "github_trending",
                "total": 25,
                "items": [...]
            }
        """
        all_items = []

        if languages:
            for lang in languages:
                items = self._fetch_trending(lang, max_items // len(languages))
                all_items.extend(items)
        else:
            all_items = self._fetch_trending(None, max_items)

        # 去重（按 repo 名称）
        seen = set()
        unique_items = []
        for item in all_items:
            key = f"{item.get('owner')}/{item.get('repo')}"
            if key not in seen:
                seen.add(key)
                unique_items.append(item)

        # 按热度（stars）排序
        unique_items.sort(key=lambda x: x.get('stars', 0), reverse=True)

        return {
            "timestamp": get_timestamp(),
            "source": "github_trending",
            "total": len(unique_items),
            "items": unique_items[:max_items]
        }

    def _fetch_trending(self, language: Optional[str] = None, limit: int = 25) -> List[Dict]:
        """获取单个语言的 Trending 列表"""
        url = self.base_url
        if language:
            url = f"{self.base_url}/{language}"

        try:
            resp = self.session.get(url, timeout=15)
            resp.raise_for_status()
            return self._parse_trending(resp.text, limit)
        except Exception as e:
            print(f"采集 GitHub Trending ({language}) 失败: {e}")
            return []

    def _parse_trending(self, html: str, limit: int) -> List[Dict]:
        """解析 Trending 页面"""
        soup = BeautifulSoup(html, 'html.parser')
        items = []

        # GitHub Trending 的每个仓库是一个 article 元素
        articles = soup.find_all('article', class_='Box-row')

        for article in articles[:limit]:
            try:
                # 仓库名称
                h2 = article.find('h2')
                if not h2:
                    continue
                a_tag = h2.find('a')
                if not a_tag:
                    continue

                # 提取 owner/repo
                href = a_tag.get('href', '')
                if href.startswith('/'):
                    href = href[1:]
                parts = href.split('/')
                if len(parts) >= 2:
                    owner = parts[0]
                    repo = parts[1]
                else:
                    continue

                # 描述
                desc_p = article.find('p', class_='col-9')
                description = desc_p.text.strip() if desc_p else ""

                # Star 数
                star_link = article.find('a', href=re.compile(r'\/starred$'))
                stars = 0
                if star_link:
                    star_text = star_link.text.strip()
                    stars = self._parse_count(star_text)

                # Fork 数
                fork_link = article.find('a', href=re.compile(r'\/fork$'))
                forks = 0
                if fork_link:
                    fork_text = fork_link.text.strip()
                    forks = self._parse_count(fork_text)

                # 语言
                lang_span = article.find('span', itemprop='programmingLanguage')
                language = lang_span.text.strip() if lang_span else ""

                items.append({
                    "id": f"{owner}/{repo}",
                    "owner": owner,
                    "repo": repo,
                    "url": f"https://github.com/{owner}/{repo}",
                    "description": truncate_text(description, 300),
                    "stars": stars,
                    "forks": forks,
                    "language": language,
                })
            except Exception as e:
                print(f"解析单个仓库失败: {e}")
                continue

        return items

    def _parse_count(self, text: str) -> int:
        """解析带单位的数字（如 1.2k → 1200）"""
        if not text:
            return 0
        text = text.strip().replace(',', '')
        if 'k' in text.lower():
            try:
                num = float(text.lower().replace('k', '').strip())
                return int(num * 1000)
            except ValueError:
                return 0
        try:
            return int(text)
        except ValueError:
            return 0


def collect_github_trending() -> Dict[str, Any]:
    """公开接口：采集 GitHub Trending"""
    collector = GitHubTrendingCollector()
    config = load_config() if load_config else {}

    languages = config.get('collect', {}).get('github', {}).get('languages', [])
    max_items = config.get('collect', {}).get('github', {}).get('max_items', 50)

    result = collector.collect(languages=languages, max_items=max_items)

    # 保存到暂存区
    save_json(result, f"staging/github_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    return result


if __name__ == "__main__":
    from utils import load_config
    data = collect_github_trending()
    print(f"采集完成: {data['total']} 个仓库")
