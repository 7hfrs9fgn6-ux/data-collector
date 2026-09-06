#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
豆瓣解析器
职责：通过豆瓣 API 获取中文书籍信息
注意：豆瓣 API 有严格的反爬机制，需要谨慎使用
"""

import time
import json
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


class DoubanParser:
    """豆瓣解析器"""

    def __init__(self):
        self.base_url = "https://book.douban.com/subject/"
        self.api_url = "https://book.douban.com/j/subject_abstract"
        self.session = None
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
        ]

    def _get_session(self):
        """获取会话（带User-Agent）"""
        if self.session is None:
            import requests
            from requests.adapters import HTTPAdapter
            from urllib3.util.retry import Retry

            self.session = requests.Session()
            self.session.headers.update({
                'User-Agent': self.user_agents[0],
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
                'Accept-Encoding': 'gzip, deflate, br',
                'Connection': 'keep-alive',
            })

            # 重试策略
            retry = Retry(total=2, backoff_factor=0.5)
            adapter = HTTPAdapter(max_retries=retry)
            self.session.mount('http://', adapter)
            self.session.mount('https://', adapter)

        return self.session

    def search_by_title(self, title: str) -> Optional[Dict]:
        """
        通过书名搜索豆瓣图书
        """
        try:
            # 使用豆瓣搜索 API
            import requests

            search_url = "https://book.douban.com/subject_search"
            params = {
                "search_text": title
            }

            session = self._get_session()
            response = session.get(search_url, params=params, timeout=10)

            if response.status_code != 200:
                logger.debug(f"   豆瓣搜索失败: {response.status_code}")
                return None

            # 解析 HTML 提取图书信息
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # 查找第一个搜索结果
            result_item = soup.find('li', class_='subject-item')
            if not result_item:
                return None

            # 提取信息
            title_elem = result_item.find('h2').find('a')
            if not title_elem:
                return None

            book_title = title_elem.get_text().strip()
            book_url = title_elem.get('href', '')

            # 提取豆瓣 ID
            douban_id = None
            if book_url:
                import re
                match = re.search(r'/subject/(\d+)/', book_url)
                if match:
                    douban_id = match.group(1)

            # 提取作者
            author_elem = result_item.find('div', class_='pub')
            author = ''
            if author_elem:
                author_text = author_elem.get_text().strip()
                # 提取作者信息
                import re
                match = re.search(r'([^/]+)/', author_text)
                if match:
                    author = match.group(1).strip()

            # 提取评分
            rating_elem = result_item.find('span', class_='rating_nums')
            rating = 0
            if rating_elem:
                try:
                    rating = float(rating_elem.get_text().strip())
                except ValueError:
                    pass

            # 提取简介
            desc_elem = result_item.find('p')
            description = ''
            if desc_elem:
                description = desc_elem.get_text().strip()

            if not book_title or not douban_id:
                return None

            return {
                "douban_id": douban_id,
                "title_cn": book_title,
                "authors_cn": [author] if author else [],
                "description_cn": description[:1000] if description else '',
                "rating": rating,
                "url": book_url,
                "source": "douban"
            }

        except Exception as e:
            logger.debug(f"   豆瓣搜索异常: {e}")
            return None

    def get_by_id(self, douban_id: str) -> Optional[Dict]:
        """
        通过豆瓣 ID 获取图书详情
        """
        try:
            import requests

            # 豆瓣 API（非官方）
            api_url = f"https://book.douban.com/subject/{douban_id}/"

            session = self._get_session()
            response = session.get(api_url, timeout=10)

            if response.status_code != 200:
                return None

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')

            # 提取书名
            title_elem = soup.find('span', {'property': 'v:itemreviewed'})
            title_cn = title_elem.get_text().strip() if title_elem else ''

            # 提取作者
            author_elem = soup.find('a', {'rel': 'v:url'})
            authors_cn = []
            if author_elem:
                authors_cn.append(author_elem.get_text().strip())

            # 提取评分
            rating_elem = soup.find('strong', {'property': 'v:average'})
            rating = 0
            if rating_elem:
                try:
                    rating = float(rating_elem.get_text().strip())
                except ValueError:
                    pass

            # 提取简介
            desc_elem = soup.find('span', {'property': 'v:summary'})
            description_cn = ''
            if desc_elem:
                description_cn = desc_elem.get_text().strip()

            # 提取出版社
            pub_info = soup.find('div', id='info')
            publisher = ''
            if pub_info:
                for line in pub_info.get_text().split('\n'):
                    if '出版社' in line or '出版社:' in line:
                        publisher = line.replace('出版社', '').replace(':', '').strip()
                        break

            if not title_cn:
                return None

            return {
                "douban_id": douban_id,
                "title_cn": title_cn,
                "authors_cn": authors_cn,
                "description_cn": description_cn[:1500] if description_cn else '',
                "rating": rating,
                "publisher": publisher,
                "source": "douban_detail"
            }

        except Exception as e:
            logger.debug(f"   豆瓣详情获取失败 {douban_id}: {e}")
            return None


def get_douban_info(title: str) -> Optional[Dict]:
    """
    从豆瓣获取书籍信息
    """
    parser = DoubanParser()
    return parser.search_by_title(title)


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    info = get_douban_info("聪明的投资者")
    if info:
        print(f"中文书名: {info.get('title_cn')}")
        print(f"豆瓣评分: {info.get('rating')}")
