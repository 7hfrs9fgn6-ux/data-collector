#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
维基语录解析器
职责：从维基语录页面获取经典语录
"""

import re
import time
import logging
from typing import Dict, List, Optional, Any
from urllib.parse import quote

logger = logging.getLogger(__name__)


class WikiquoteParser:
    """维基语录解析器"""

    def __init__(self, lang: str = "en"):
        self.lang = lang
        self.base_url = f"https://{lang}.wikiquote.org/wiki/"

    def get_quotes(self, title: str) -> List[str]:
        """
        从维基语录页面获取经典语录
        支持：英文、中文维基语录
        """
        import requests
        from bs4 import BeautifulSoup

        try:
            # 构造维基语录 URL
            # 将书名转换为维基语录格式
            page_title = self._format_title(title)
            url = self.base_url + quote(page_title.replace(' ', '_'))

            response = requests.get(url, timeout=15)
            if response.status_code == 404:
                # 尝试中文维基语录
                if self.lang == 'en':
                    logger.debug(f"   📖 尝试中文维基语录: {title}")
                    zh_parser = WikiquoteParser('zh')
                    return zh_parser.get_quotes(title)
                return []

            response.raise_for_status()
            soup = BeautifulSoup(response.text, 'html.parser')

            quotes = []

            # 查找语录区块
            # 英文维基语录：通常使用 <ul> 或 <dl> 包含引文
            # 中文维基语录：通常使用 <dl> 包含引文

            if self.lang == 'en':
                quotes = self._extract_english_quotes(soup)
            else:
                quotes = self._extract_chinese_quotes(soup)

            # 清理和去重
            quotes = list(dict.fromkeys(quotes))  # 去重
            quotes = [q.strip() for q in quotes if q.strip() and len(q.strip()) > 10]

            if quotes:
                logger.debug(f"   📖 从维基语录获取 {len(quotes)} 条语录: {title}")
                return quotes[:20]  # 最多返回20条

            return []

        except Exception as e:
            logger.debug(f"   ⚠️ 维基语录获取失败 {title}: {e}")
            return []

    def _format_title(self, title: str) -> str:
        """格式化标题为维基语录页面名称"""
        # 移除括号内容
        title = re.sub(r'\s*\([^)]*\)\s*', ' ', title)
        # 处理常见的作者后缀
        title = re.sub(r'\s*(book|novel|series|film|movie)$', '', title, flags=re.IGNORECASE)
        return title.strip()

    def _extract_english_quotes(self, soup) -> List[str]:
        """提取英文维基语录"""
        quotes = []

        # 方法1：查找 <dl> 中的引文（常见格式）
        for dl in soup.find_all('dl'):
            for dt in dl.find_all('dt'):
                text = dt.get_text().strip()
                if text and len(text) > 15:
                    quotes.append(text)
            for dd in dl.find_all('dd'):
                text = dd.get_text().strip()
                if text and len(text) > 15:
                    quotes.append(text)

        # 方法2：查找 <ul> 中的引文
        for ul in soup.find_all('ul'):
            for li in ul.find_all('li'):
                text = li.get_text().strip()
                if text and len(text) > 15:
                    # 检查是否包含引号
                    if '"' in text or "'" in text or '“' in text or '”' in text:
                        quotes.append(text)

        # 方法3：查找引文区块
        for div in soup.find_all(['div', 'blockquote']):
            if 'quote' in str(div.get('class', [])).lower():
                text = div.get_text().strip()
                if text and len(text) > 20:
                    quotes.append(text)

        # 过滤掉非语录内容
        filtered = []
        for q in quotes:
            # 保留包含引号或较长内容的语录
            if any(c in q for c in ['"', "'", '“', '”', '—', '–']):
                filtered.append(q)
            elif len(q) > 40:
                filtered.append(q)

        return filtered

    def _extract_chinese_quotes(self, soup) -> List[str]:
        """提取中文维基语录"""
        quotes = []

        # 中文维基语录格式：通常使用 <dl> 中的 <dd>
        for dl in soup.find_all('dl'):
            for dd in dl.find_all('dd'):
                text = dd.get_text().strip()
                if text and len(text) > 10:
                    # 检查是否包含中文引号
                    if '“' in text or '”' in text or '「' in text or '」' in text or '‘' in text:
                        quotes.append(text)
                    elif len(text) > 20:
                        quotes.append(text)

        # 查找 <blockquote>
        for blockquote in soup.find_all('blockquote'):
            text = blockquote.get_text().strip()
            if text and len(text) > 10:
                quotes.append(text)

        return quotes


def get_quotes_for_book(title: str, authors: List[str] = None) -> List[str]:
    """
    为书籍获取语录（尝试多种策略）
    """
    all_quotes = []

    # 策略1：直接使用书名
    parser = WikiquoteParser('en')
    quotes = parser.get_quotes(title)
    if quotes:
        all_quotes.extend(quotes)

    # 策略2：如果书名包含作者，尝试用作者名查找
    if authors and len(all_quotes) < 3:
        for author in authors[:2]:
            author_quotes = parser.get_quotes(author)
            if author_quotes:
                all_quotes.extend(author_quotes[:3])

    # 策略3：尝试中文维基语录
    if len(all_quotes) < 3:
        zh_parser = WikiquoteParser('zh')
        zh_quotes = zh_parser.get_quotes(title)
        if zh_quotes:
            all_quotes.extend(zh_quotes)

    # 去重并限制数量
    all_quotes = list(dict.fromkeys(all_quotes))
    return all_quotes[:20]


if __name__ == "__main__":
    # 测试
    logging.basicConfig(level=logging.INFO)
    quotes = get_quotes_for_book("The Intelligent Investor")
    print(f"获取到 {len(quotes)} 条语录:")
    for q in quotes[:5]:
        print(f"  - {q[:80]}...")
