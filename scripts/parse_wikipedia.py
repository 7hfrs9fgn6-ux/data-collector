#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维基百科解析器（V3：HTML优先 + API降级）
职责：
  1. 网页抓取分类页面获取书籍列表（主方式）
  2. API 作为降级备用
  3. 获取每本书的详情
  4. 返回标准化的书籍数据
★ 2026-09-06 修正：HTML抓取优先，避免API限流
"""

import re
import time
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)


class WikipediaParser:
    """维基百科解析器（HTML优先 + API降级）"""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.api_url = f"https://{lang}.wikipedia.org/w/api.php"
        self.base_url = f"https://{lang}.wikipedia.org/wiki/"

    # ============================================================
    # ★ 主入口：获取分类下的书籍列表（HTML优先）
    # ============================================================

    def get_books_from_category(self, category: str, max_books: int = 300) -> List[Dict]:
        """
        获取分类下的书籍列表
        ★ HTML优先（获取完整列表），API作为降级
        """
        # 1. 尝试 HTML 抓取（主方式）
        books = self._get_books_from_category_html(category)
        if books:
            logger.info(f"   ✅ HTML 获取分类 '{category}' 成功: {len(books)} 本书")
            return books[:max_books]

        # 2. HTML 失败 → 降级到 API
        logger.debug(f"   ⚠️ HTML 获取分类 '{category}' 失败，降级到 API...")
        time.sleep(1)  # 降级前等待
        books = self._get_books_from_category_api(category, max_books)
        if books:
            logger.info(f"   ✅ API 获取分类 '{category}' 成功: {len(books)} 本书")
            return books

        logger.warning(f"   ⚠️ 分类 '{category}' 所有方式均失败")
        return []

    # ============================================================
    # ★ HTML 抓取分类页面（主方式）
    # ============================================================

    def _get_books_from_category_html(self, category: str) -> List[Dict]:
        """
        从 HTML 页面解析分类下的书籍列表
        """
        try:
            import requests
            from bs4 import BeautifulSoup

            url = f"https://{self.lang}.wikipedia.org/wiki/Category:{category.replace(' ', '_')}"
            logger.debug(f"   🌐 HTML 请求: {url}")

            response = requests.get(
                url,
                timeout=15,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                }
            )

            if response.status_code != 200:
                logger.debug(f"   HTML 请求失败: {response.status_code}")
                return []

            soup = BeautifulSoup(response.text, 'html.parser')

            books = []
            # 分类页面中的条目在 <div class="mw-category"> 中
            category_div = soup.find('div', {'class': 'mw-category'})
            if not category_div:
                # 尝试其他可能的容器
                category_div = soup.find('div', {'id': 'mw-pages'})

            if category_div:
                # 查找所有链接
                for link in category_div.find_all('a', href=True):
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

                    books.append({
                        "title": title,
                        "url": self.base_url + href.replace('/wiki/', ''),
                        "source": "wikipedia_html"
                    })

            # 如果没有找到 mw-category，尝试查找所有带链接的条目
            if not books:
                # 查找所有 <li> 中的链接
                for li in soup.find_all('li'):
                    link = li.find('a', href=True)
                    if link:
                        href = link.get('href', '')
                        title = link.get('title', '')
                        if href.startswith('/wiki/') and not ':' in href:
                            if title and not self._is_non_book(title):
                                books.append({
                                    "title": title,
                                    "url": self.base_url + href.replace('/wiki/', ''),
                                    "source": "wikipedia_html"
                                })

            return books

        except Exception as e:
            logger.debug(f"   HTML 抓取失败: {e}")
            return []

    # ============================================================
    # ★ API 获取分类（降级方式）
    # ============================================================

    def _get_books_from_category_api(self, category: str, max_books: int = 200) -> List[Dict]:
        """
        MediaWiki API 获取分类下的书籍列表（降级方式）
        """
        try:
            import requests

            params = {
                "action": "query",
                "format": "json",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmtype": "page",
                "cmlimit": min(max_books, 200),
                "cmnamespace": 0,
            }

            response = requests.get(
                self.api_url,
                params=params,
                timeout=20,
                headers={"User-Agent": "VSystem-DataCollector/1.0"}
            )
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

            return books

        except Exception as e:
            if '429' in str(e):
                logger.warning(f"   ⚠️ API 限流，等待 5 秒后重试...")
                time.sleep(5)
                # 重试一次
                return self._get_books_from_category_api(category, max_books)
            logger.debug(f"   API 获取分类失败: {e}")
            return []

    # ============================================================
    # 提取书籍列表（从任意 URL）
    # ============================================================

    def extract_books_from_url(self, url: str, source_type: str = 'category') -> List[Dict]:
        """
        从 URL 提取书籍列表（兼容旧接口）
        """
        if '/wiki/Category:' in url:
            category = url.split('/wiki/Category:')[-1]
            category = unquote(category)
            return self.get_books_from_category(category)
        else:
            # 列表页面
            return self._extract_books_from_list_html(url)

    def _extract_books_from_list_html(self, url: str) -> List[Dict]:
        """从列表页面 HTML 提取书籍"""
        try:
            import requests
            from bs4 import BeautifulSoup

            response = requests.get(
                url,
                timeout=15,
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
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

    # ============================================================
    # 辅助方法
    # ============================================================

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

            response = requests.get(
                self.api_url,
                params=params,
                timeout=15,
                headers={"User-Agent": "VSystem-DataCollector/1.0"}
            )
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


# ============================================================
# 兼容旧接口
# ============================================================

def extract_books_from_seed_sources(seed_config: Dict) -> List[Dict]:
    """
    从种子源配置提取所有书籍
    ★ 根据 type 字段选择采集方式
    """
    all_books = []
    seen_titles = set()

    sources = seed_config.get('sources', [])

    # ★ 分类之间的延迟
    delay_between_sources = 3

    for idx, source in enumerate(sources):
        if not source.get('enabled', True):
            continue

        url = source.get('url', '')
        source_id = source.get('id', '')
        source_type = source.get('type', 'wikipedia_category')
        lang = source.get('language', 'en')

        logger.info(f"   📖 处理源: {source_id} (类型: {source_type})")

        parser = WikipediaParser(lang)

        if source_type == 'wikipedia_category':
            # ★ 使用 HTML 优先 + API 降级
            category = url.split('/wiki/Category:')[-1]
            category = unquote(category)
            books = parser.get_books_from_category(category)
        else:
            # 列表页面
            books = parser.extract_books_from_url(url)

        # 去重
        for book in books:
            title = book.get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                book['source_id'] = source_id
                all_books.append(book)

        # ★ 每个分类之间延迟 3 秒
        if idx < len(sources) - 1:
            logger.debug(f"   ⏱️ 等待 {delay_between_sources} 秒后继续...")
            time.sleep(delay_between_sources)

    logger.info(f"   📚 共发现 {len(all_books)} 本候选书籍")
    return all_books


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    parser = WikipediaParser()
    books = parser.get_books_from_category("Finance_books", 20)
    print(f"发现 {len(books)} 本书:")
    for book in books[:5]:
        print(f"  - {book['title']}")
