#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Books API 解析器
职责：通过 Google Books API 获取书籍信息
API：https://www.googleapis.com/books/v1/volumes
配额：免费 1000 次/天
"""

import os
import time
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


class GoogleBooksParser:
    """Google Books API 解析器"""

    def __init__(self, api_key: str = None):
        self.api_key = api_key or os.environ.get('GOOGLE_BOOKS_API_KEY', '')
        self.base_url = "https://www.googleapis.com/books/v1/volumes"
        self.quota_used = 0
        self.quota_limit = 1000  # 免费版

    def search_by_title(self, title: str, author: str = None) -> Optional[Dict]:
        """
        通过书名和作者搜索书籍
        """
        if not self.api_key:
            logger.debug("   ⚠️ Google Books API Key 未设置，跳过")
            return None

        # 检查配额
        if self.quota_used >= self.quota_limit:
            logger.warning("   ⚠️ Google Books API 配额已用完")
            return None

        try:
            import requests

            # 构建查询
            query = f'intitle:"{title}"'
            if author:
                query += f'+inauthor:"{author}"'

            params = {
                "q": query,
                "key": self.api_key,
                "maxResults": 1,
                "fields": "items(id,volumeInfo(title,authors,description,imageLinks,publishedDate,publisher,categories,pageCount,language,ratingsCount,averageRating),selfLink)"
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            self.quota_used += 1

            if response.status_code != 200:
                logger.debug(f"   Google Books API 请求失败: {response.status_code}")
                return None

            data = response.json()
            items = data.get('items', [])

            if not items:
                # 尝试更宽松的搜索
                return self._search_loose(title, author)

            return self._parse_volume(items[0])

        except Exception as e:
            logger.debug(f"   Google Books API 异常: {e}")
            return None

    def _search_loose(self, title: str, author: str = None) -> Optional[Dict]:
        """宽松搜索"""
        try:
            import requests

            query = title
            if author:
                query += f' {author}'

            params = {
                "q": query,
                "key": self.api_key,
                "maxResults": 1,
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            self.quota_used += 1

            if response.status_code != 200:
                return None

            data = response.json()
            items = data.get('items', [])
            if items:
                return self._parse_volume(items[0])
            return None

        except Exception:
            return None

    def _parse_volume(self, volume: Dict) -> Dict:
        """解析卷信息"""
        volume_info = volume.get('volumeInfo', {})

        # 提取封面 URL
        image_links = volume_info.get('imageLinks', {})
        cover_url = image_links.get('thumbnail', '')

        # 提取分类
        categories = volume_info.get('categories', [])
        if isinstance(categories, str):
            categories = [categories]

        # 提取描述（清理 HTML）
        description = volume_info.get('description', '')
        if description:
            import re
            description = re.sub(r'<[^>]+>', ' ', description)
            description = re.sub(r'\s+', ' ', description).strip()

        return {
            "google_books_id": volume.get('id', ''),
            "title": volume_info.get('title', ''),
            "authors": volume_info.get('authors', []),
            "description": description[:3000] if description else '',
            "cover_url": cover_url,
            "publisher": volume_info.get('publisher', ''),
            "publish_date": volume_info.get('publishedDate', ''),
            "categories": categories,
            "page_count": volume_info.get('pageCount', 0),
            "language": volume_info.get('language', ''),
            "rating": volume_info.get('averageRating', 0),
            "ratings_count": volume_info.get('ratingsCount', 0),
            "source": "google_books"
        }

    def search_by_isbn(self, isbn: str) -> Optional[Dict]:
        """通过 ISBN 搜索"""
        if not self.api_key:
            return None

        try:
            import requests

            params = {
                "q": f"isbn:{isbn}",
                "key": self.api_key,
                "maxResults": 1,
            }

            response = requests.get(self.base_url, params=params, timeout=10)
            self.quota_used += 1

            if response.status_code != 200:
                return None

            data = response.json()
            items = data.get('items', [])
            if items:
                return self._parse_volume(items[0])
            return None

        except Exception as e:
            logger.debug(f"   ISBN 搜索失败: {e}")
            return None


def get_book_info_from_google(title: str, author: str = None) -> Optional[Dict]:
    """
    从 Google Books 获取书籍信息
    """
    parser = GoogleBooksParser()
    return parser.search_by_title(title, author)


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    info = get_book_info_from_google("The Intelligent Investor", "Benjamin Graham")
    if info:
        print(f"书名: {info.get('title')}")
        print(f"作者: {info.get('authors')}")
        print(f"描述: {info.get('description', '')[:100]}...")
