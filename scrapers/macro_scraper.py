#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：宏观数据爬虫
主源 akshare 失败时，从国家统计局/新浪财经爬取宏观数据
"""

import re
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class MacroScraper(BaseScraper):
    """
    宏观数据爬虫
    爬取 CPI、PMI、社融等关键宏观指标
    """

    # 宏观数据源 URL
    MACRO_SOURCES = {
        # 新浪财经宏观数据中心
        'cpi': 'https://finance.sina.com.cn/mac/cpi.shtml',
        'pmi': 'https://finance.sina.com.cn/mac/pmi.shtml',
        'm2': 'https://finance.sina.com.cn/mac/m2.shtml',
    }

    # 备用：国家统计局数据查询页面
    NBS_URL = 'https://data.stats.gov.cn/easyquery.htm'

    def __init__(self):
        super().__init__(max_retries=3, timeout=20, delay_range=(2, 5))

    def _extract_table_data(self, html: str, indicator: str) -> Optional[float]:
        """
        从新浪宏观页面提取指标数据

        Args:
            html: 页面 HTML
            indicator: 指标名称

        Returns:
            指标值，失败返回 None
        """
        # 新浪宏观页面的数据通常在表格或特定结构中
        patterns = [
            # 匹配 "CPI: 2.1%" 或 "CPI 2.1%"
            rf'{indicator}\s*[:：]?\s*([\d.]+)%',
            rf'{indicator}\s*数据\s*[:：]?\s*([\d.]+)',
            # 匹配 JSON 格式数据
            r'"value":\s*([\d.]+)',
            r'"data":\s*([\d.]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue

        # 尝试从表格中提取
        table_pattern = r'<table[^>]*>.*?<td[^>]*>.*?%s.*?</td>.*?<td[^>]*>([\d.]+)' % indicator
        match = re.search(table_pattern, html, re.IGNORECASE | re.DOTALL)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass

        return None

    def scrape(self) -> Optional[Dict[str, Any]]:
        """
        爬取宏观数据

        Returns:
            {
                'data_type': 'macro',
                'generated_at': '2026-08-14 10:00:00',
                'items': [
                    {'indicator': 'cpi', 'value': 2.1, 'unit': '%'},
                    ...
                ],
                'source': 'sina_finance'
            }
        """
        items = []

        for indicator, url in self.MACRO_SOURCES.items():
            logger.info(f"Scraping macro indicator: {indicator} from {url}")
            html = self.fetch(url)

            if html is None:
                logger.warning(f"Failed to fetch {indicator}, skipping")
                continue

            value = self._extract_table_data(html, indicator.upper())

            if value is None:
                logger.warning(f"Failed to extract value for {indicator}")
                continue

            items.append({
                'indicator': indicator,
                'value': value,
                'unit': '%' if indicator in ['cpi', 'pmi'] else '万亿元',
                'date': datetime.now().strftime('%Y-%m'),
            })

        # 如果新浪数据不足，尝试从国家统计局获取
        if len(items) < 2:
            logger.info("Attempting to fetch from NBS as fallback")
            nbs_data = self._fetch_from_nbs()
            if nbs_data:
                items.extend(nbs_data)

        if not items:
            logger.error("No macro data scraped")
            return None

        return {
            'data_type': 'macro',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'items': items,
            'source': 'sina_finance',
            'total': len(items),
        }

    def _fetch_from_nbs(self) -> List[Dict[str, Any]]:
        """
        从国家统计局爬取数据（备用）

        Returns:
            宏观数据列表
        """
        # 国家统计局需要构建特定的查询参数
        # 这里提供框架，实际使用时需要根据具体接口调整
        params = {
            'm': 'QueryData',
            'dbcode': 'hgnd',
            'rowcode': 'zb',
            'colcode': 'sj',
            'wds': '[]',
            'dfwds': '[{"wdcode":"zb","valuecode":"A01"}]',
        }

        html = self.fetch(self.NBS_URL, params=params)
        if html is None:
            return []

        # 尝试解析 JSON 响应
        try:
            # 国家统计局返回的是 JSONP 格式
            json_match = re.search(r'\((\{.*\})\)', html)
            if json_match:
                data = json.loads(json_match.group(1))
                # 解析数据...
                # 这里仅做示例，实际需要根据返回结构解析
                return []
        except json.JSONDecodeError:
            pass

        return []

    def get_data_type(self) -> str:
        return 'macro'


# 便捷函数
def scrape_macro() -> Optional[Dict[str, Any]]:
    """爬取宏观数据的便捷入口"""
    scraper = MacroScraper()
    return scraper.scrape()


if __name__ == '__main__':
    result = scrape_macro()
    if result:
        print(f"Scraped {result['total']} macro indicators from {result['source']}")
        for item in result['items']:
            print(f"  {item['indicator']}: {item['value']}{item['unit']}")
    else:
        print("Scraping failed")
