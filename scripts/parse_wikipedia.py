#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维基百科解析器（修正版）
职责：
  1. 通过 MediaWiki API 提取书籍列表（替代 HTML 抓取）
  2. 获取每本书的详情
  3. 返回标准化的书籍数据
★ 2026-09-06 修正：优先使用 MediaWiki API，避免 403 反爬
"""

import re
import time
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)


class WikipediaParser:
    """维基百科解析器（API 优先）"""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.api_url = f"https://{lang}.wikipedia.org/w/api.php"
        self.base_url = f"https://{lang}.wikipedia.org/wiki/"

    def extract_books_from_seed_url(self, url: str) -> List[Dict]:
        """
        从种子 URL 提取书籍列表
        ★ 优先使用 MediaWiki API
        ★ 仅在 API 失败时降级到 HTML 抓取
        """
        books = []

        # 判断 URL 类型
        if '/wiki/Category:' in url:
            # 分类页面 → 使用 API
            category = url.split('/wiki/Category:')[-1]
            # 处理 URL 编码
            category = unquote(category)
            books = self.get_books_from_category_api(category)
        elif '/wiki/List_of' in url:
            # 列表页面 → 尝试 API，失败则用 HTML
            # 列表页面无法直接用 API 获取完整列表，用 HTML 抓取
            books = self._extract_books_from_list_html(url)
        else:
            # 普通页面 → 提取单个条目
            title = url.split('/wiki/')[-1]
            title = unquote(title).replace('_', ' ')
            if title:
                books = [{"title": title, "url": url}]

        logger.info(f"   📚 从 {url} 提取 {len(books)} 本书")
        return books

    def get_books_from_category_api(self, category: str, max_books: int = 200) -> List[Dict]:
        """
        ★ MediaWiki API 获取分类下的书籍列表（推荐方式）
        """
        try:
            import requests

            # 第一次请求：获取分类成员
            params = {
                "action": "query",
                "format": "json",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmtype": "page",
                "cmlimit": max_books,
                "cmnamespace": 0,
            }

            response = requests.get(self.api_url, params=params, timeout=20, 
                                    headers={"User-Agent": "VSystem-DataCollector/1.0"})
            response.raise_for_status()
            data = response.json()

            books = []
            for item in data.get('query', {}).get('categorymembers', []):
                title = item.get('title', '')
                if title and not self._is_non_book(title):
                    books.append({
                        "title": title,
                        "url": self.base_url + title.replace(' ', '_'),
                        "source": "wikipedia_api"
                    })

            logger.info(f"   ✅ API 获取分类 '{category}' 成功: {len(books)} 本书")
            return books

        except Exception as e:
            logger.warning(f"   ⚠️ API 获取分类失败: {e}")
            return []

    def _extract_books_from_list_html(self, url: str) -> List[Dict]:
        """
        从列表页面 HTML 提取书籍（仅用于列表页面）
        """
        try:
            import requests
            from bs4 import BeautifulSoup

            response = requests.get(url, timeout=15,
                                   headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            books = []
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                title = link.get('title', '')

                if not href.startswith('/wiki/'):
                    continue
                if ':' in href:
                    continue
                if not title or len(title) < 2:
                    continue
                if self._is_non_book(title):
                    continue

                # 检查是否在列表正文区域
                parent = link.parent
                in_list = False
                while parent:
                    if parent.name in ['ul', 'ol', 'dl', 'table']:
                        in_list = True
                        break
                    parent = parent.parent

                if not in_list:
                    continue

                books.append({
                    "title": title,
                    "url": self.base_url + href.replace('/wiki/', ''),
                    "source": "wikipedia_list"
                })

            return books

        except Exception as e:
            logger.warning(f"   ⚠️ HTML 列表解析失败: {e}")
            return []

    def _is_non_book(self, title: str) -> bool:
        """判断是否非书籍条目"""
        non_book_patterns = [
            r'^List of',
            r'^Category:',
            r'^Template:',
            r'^Wikipedia:',
            r'^Help:',
            r'^Portal:',
            r'^(disambiguation|Disambiguation)',
            r'\(disambiguation\)',
            r'\(film\)',
            r'\(song\)',
            r'\(album\)',
            r'\(TV series\)',
        ]
        for pattern in non_book_patterns:
            if re.match(pattern, title, re.IGNORECASE):
                return True
        return False

    def get_book_details(self, title: str) -> Optional[Dict]:
        """
        使用 MediaWiki API 获取书籍详情
        """
        try:
            import requests

            params = {
                "action": "query",
                "format": "json",
                "titles": title,
                "prop": "extracts|pageimages|categories|info",
                "exintro": "true",
                "explaintext": "true",
                "exsentences": 10,
                "pithumbsize": 200,
                "cllimit": "max",
                "inprop": "url"
            }

            response = requests.get(self.api_url, params=params, timeout=15,
                                   headers={"User-Agent": "VSystem-DataCollector/1.0"})
            response.raise_for_status()
            data = response.json()

            pages = data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    continue

                categories = []
                for cat in page_data.get('categories', []):
                    cat_title = cat.get('title', '').replace('Category:', '')
                    if not cat_title.startswith('Wikipedia:') and not cat_title.startswith('Pages'):
                        categories.append(cat_title)

                extract = page_data.get('extract', '')

                result = {
                    "wikipedia_id": page_id,
                    "title": page_data.get('title', title),
                    "url": page_data.get('fullurl', ''),
                    "description": extract[:2000] if extract else '',
                    "categories": categories[:20],
                    "cover_url": page_data.get('thumbnail', {}).get('source', ''),
                    "page_id": page_id,
                }

                return result

            return None

        except Exception as e:
            logger.debug(f"   API 获取 {title} 详情失败: {e}")
            return None


def extract_books_from_seed_sources(seed_config: Dict) -> List[Dict]:
    """
    从种子源配置提取所有书籍
    ★ 优先使用 API，避免 403
    """
    all_books = []
    seen_titles = set()

    sources = seed_config.get('sources', [])

    for source in sources:
        if not source.get('enabled', True):
            continue

        url = source.get('url', '')
        source_id = source.get('id', '')
        source_type = source.get('type', 'wikipedia_category')

        logger.info(f"   📖 处理源: {source_id} (类型: {source_type})")

        # 根据类型选择提取方式
        parser = WikipediaParser('en' if source.get('language') == 'en' else 'zh')

        if source_type == 'wikipedia_category':
            # ★ 使用 API（推荐）
            category = url.split('/wiki/Category:')[-1]
            category = unquote(category)
            books = parser.get_books_from_category_api(category)
        elif source_type == 'wikipedia_list':
            # 列表页面 → 用 HTML 抓取（API 不支持）
            books = parser._extract_books_from_list_html(url)
        else:
            # 兜底
            books = parser.extract_books_from_seed_url(url)

        # 去重：按标题去重
        for book in books:
            title = book.get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                book['source_id'] = source_id
                all_books.append(book)

        time.sleep(1)  # 请求间隔

    logger.info(f"   📚 共发现 {len(all_books)} 本候选书籍")
    return all_books
