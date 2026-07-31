#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ECC 仓库更新监控模块
采集 ECC 仓库的最新活动（commits、releases）
"""

import requests
from typing import List, Dict, Any, Optional
from datetime import datetime

from utils import save_json, get_timestamp, truncate_text


class ECCCollector:
    """ECC 仓库监控采集器"""

    def __init__(self):
        self.api_base = "https://api.github.com/repos"
        self.repo_path = "ecc-community/ecc"
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "data-collector/1.0",
            "Accept": "application/vnd.github.v3+json"
        })

    def collect(self, max_items: int = 20) -> Dict[str, Any]:
        """
        采集 ECC 仓库最新活动

        Args:
            max_items: 最大采集数量

        Returns:
            Dict: {
                "timestamp": "2026-07-31T10:00:00",
                "source": "ecc",
                "total": 15,
                "items": [...]
            }
        """
        all_items = []

        # 1. 获取最新 commits
        commits = self._fetch_commits(max_items)
        all_items.extend(commits)

        # 2. 获取最新 releases
        releases = self._fetch_releases(max_items // 2)
        all_items.extend(releases)

        # 按时间排序（最新的在前）
        all_items.sort(key=lambda x: x.get('date', ''), reverse=True)

        return {
            "timestamp": get_timestamp(),
            "source": "ecc",
            "total": len(all_items),
            "items": all_items[:max_items]
        }

    def _fetch_commits(self, limit: int = 20) -> List[Dict]:
        """获取最新的 commits"""
        url = f"{self.api_base}/{self.repo_path}/commits"
        params = {"per_page": limit}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_commits(data)
        except Exception as e:
            print(f"采集 ECC commits 失败: {e}")
            return []

    def _fetch_releases(self, limit: int = 10) -> List[Dict]:
        """获取最新的 releases"""
        url = f"{self.api_base}/{self.repo_path}/releases"
        params = {"per_page": limit}

        try:
            resp = self.session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return self._parse_releases(data)
        except Exception as e:
            print(f"采集 ECC releases 失败: {e}")
            return []

    def _parse_commits(self, commits: List[Dict]) -> List[Dict]:
        """解析 commits 数据"""
        items = []
        for commit in commits:
            try:
                author = commit.get('commit', {}).get('author', {})
                message = commit.get('commit', {}).get('message', '')
                sha = commit.get('sha', '')[:8]

                # 过滤掉 merge commits
                if message.startswith('Merge'):
                    continue

                items.append({
                    "type": "commit",
                    "id": sha,
                    "title": truncate_text(message.split('\n')[0], 100),
                    "description": truncate_text('\n'.join(message.split('\n')[1:]), 200),
                    "author": author.get('name', ''),
                    "date": author.get('date', ''),
                    "url": commit.get('html_url', ''),
                })
            except Exception:
                continue
        return items

    def _parse_releases(self, releases: List[Dict]) -> List[Dict]:
        """解析 releases 数据"""
        items = []
        for release in releases:
            try:
                items.append({
                    "type": "release",
                    "id": release.get('tag_name', ''),
                    "title": release.get('name', '') or release.get('tag_name', ''),
                    "description": truncate_text(release.get('body', ''), 200),
                    "author": release.get('author', {}).get('login', ''),
                    "date": release.get('published_at', ''),
                    "url": release.get('html_url', ''),
                    "is_prerelease": release.get('prerelease', False)
                })
            except Exception:
                continue
        return items


def collect_ecc_updates() -> Dict[str, Any]:
    """公开接口：采集 ECC 更新"""
    collector = ECCCollector()
    config = load_config() if load_config else {}

    max_items = config.get('collect', {}).get('ecc', {}).get('max_items', 20)

    result = collector.collect(max_items=max_items)

    # 保存到暂存区
    save_json(result, f"staging/ecc_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

    return result


if __name__ == "__main__":
    from utils import load_config
    data = collect_ecc_updates()
    print(f"ECC 采集完成: {data['total']} 条记录")
