#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维基百科解析器
职责：
  1. 从维基百科分类页面提取书籍列表
  2. 获取每本书的详情（简介、分类、封面）
  3. 返回标准化的书籍数据
"""

import re
import time
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote, unquote

logger = logging.getLogger(__name__)


class WikipediaParser:
    """维基百科解析器"""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.api_url = f"https://{lang}.wikipedia.org/w/api.php"
        self.base_url = f"https://{lang}.wikipedia.org/wiki/"

    def extract_books_from_page(self, url: str) -> List[Dict]:
        """
        从维基百科页面提取书籍列表
        支持：普通列表页面、分类页面
        """
        import requests
        from bs4 import BeautifulSoup

        books = []

        try:
            response = requests.get(url, timeout=15)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            # 判断页面类型
            if '/wiki/List_of' in url or 'List_of' in url:
                # 列表页面：提取列表中的书籍
                books = self._extract_from_list_page(soup)
            elif '/wiki/Category:' in url:
                # 分类页面：提取分类中的书籍
                books = self._extract_from_category_page(soup)
            else:
                # 普通页面：提取标题作为单本书
                title = self._extract_title(soup)
                if title:
                    books = [{"title": title, "url": url}]

            logger.info(f"   📚 从 {url} 提取 {len(books)} 本书")
            return books

        except Exception as e:
            logger.warning(f"   ⚠️ 解析页面失败 {url}: {e}")
            return []

    def _extract_from_list_page(self, soup) -> List[Dict]:
        """从列表页面提取书籍"""
        books = []

        # 查找所有链接
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            title = link.get('title', '')

            # 过滤：必须是维基百科内部链接
            if not href.startswith('/wiki/'):
                continue
            if ':' in href:  # 排除特殊页面
                continue
            if not title or len(title) < 2:
                continue

            # 排除非书籍条目
            if self._is_non_book(title):
                continue

            # 检查是否在列表的正文区域（避免导航链接）
            parent = link.parent
            is_in_list = False
            while parent:
                if parent.name in ['ul', 'ol', 'dl', 'table']:
                    is_in_list = True
                    break
                parent = parent.parent

            if not is_in_list:
                continue

            books.append({
                "title": title,
                "url": self.base_url + href.replace('/wiki/', ''),
                "source": "wikipedia_list"
            })

        return books

    def _extract_from_category_page(self, soup) -> List[Dict]:
        """从分类页面提取书籍"""
        books = []

        # 分类页面中的子分类和页面列表
        for link in soup.find_all('a', href=True):
            href = link.get('href', '')
            title = link.get('title', '')

            if not href.startswith('/wiki/'):
                continue
            if ':' in href:
                continue
            if not title or len(title) < 2:
                continue

            # 检查是否在分类内容区域
            parent = link.parent
            in_category = False
            while parent:
                if parent.get('id') in ['mw-pages', 'mw-subcategories']:
                    in_category = True
                    break
                parent = parent.parent

            if not in_category:
                continue

            if self._is_non_book(title):
                continue

            books.append({
                "title": title,
                "url": self.base_url + href.replace('/wiki/', ''),
                "source": "wikipedia_category"
            })

        return books

    def _extract_title(self, soup) -> Optional[str]:
        """从页面提取标题"""
        title_elem = soup.find('h1', {'id': 'firstHeading'})
        if title_elem:
            return title_elem.get_text().strip()
        return None

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

            response = requests.get(self.api_url, params=params, timeout=15)
            response.raise_for_status()
            data = response.json()

            pages = data.get('query', {}).get('pages', {})
            for page_id, page_data in pages.items():
                if page_id == "-1":
                    continue

                # 提取分类（过滤掉维基百科维护分类）
                categories = []
                for cat in page_data.get('categories', []):
                    cat_title = cat.get('title', '').replace('Category:', '')
                    # 排除维基百科内部分类
                    if not cat_title.startswith('Wikipedia:') and not cat_title.startswith('Pages'):
                        categories.append(cat_title)

                # 提取简介
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

    def get_books_from_category(self, category: str, max_books: int = 100) -> List[Dict]:
        """
        从维基百科分类获取书籍列表（API 方式）
        """
        try:
            import requests

            params = {
                "action": "query",
                "format": "json",
                "list": "categorymembers",
                "cmtitle": f"Category:{category}",
                "cmtype": "page",
                "cmlimit": max_books,
                "cmnamespace": 0,
            }

            response = requests.get(self.api_url, params=params, timeout=20)
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
            logger.debug(f"   API 获取分类 {category} 失败: {e}")
            return []


def extract_books_from_seed_sources(seed_config: Dict) -> List[Dict]:
    """
    从种子源配置提取所有书籍
    """
    all_books = []
    seen_titles = set()

    parser = WikipediaParser("en")
    zh_parser = WikipediaParser("zh")

    sources = seed_config.get('sources', [])

    for source in sources:
        if not source.get('enabled', True):
            continue

        url = source.get('url', '')
        source_id = source.get('id', '')

        logger.info(f"   📖 处理源: {source_id}")

        # 根据语言选择解析器
        lang = source.get('language', 'en')
        parser_inst = parser if lang == 'en' else zh_parser

        books = parser_inst.extract_books_from_page(url)

        for book in books:
            title = book.get('title', '')
            if title and title not in seen_titles:
                seen_titles.add(title)
                book['source_id'] = source_id
                all_books.append(book)

        time.sleep(1)  # 请求间隔

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
