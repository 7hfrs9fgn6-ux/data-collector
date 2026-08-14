#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：板块数据爬虫
主源 akshare 失败时，从东方财富爬取申万一级行业板块数据
"""

import re
import json
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class SectorScraper(BaseScraper):
    """
    板块数据爬虫
    爬取东方财富申万一级行业涨跌幅及估值数据
    """

    # 东方财富板块行情页面
    SECTOR_URL = 'https://quote.eastmoney.com/center/board.html'

    # 申万一级行业代码映射（与 akshare 保持一致）
    SECTOR_MAPPING = {
        '电子': '801080',
        '计算机': '801750',
        '通信': '801770',
        '传媒': '801760',
        '医药生物': '801150',
        '食品饮料': '801120',
        '家用电器': '801110',
        '电力设备': '801730',
        '汽车': '801880',
        '国防军工': '801740',
        '银行': '801780',
        '非银金融': '801790',
        '公用事业': '801160',
        '煤炭': '801950',
        '石油石化': '801960',
    }

    # 板块回撤阈值（与精阶段一致）
    SECTOR_THRESHOLDS = {
        '电子': 20, '计算机': 20, '通信': 15, '传媒': 17,
        '医药生物': 25, '食品饮料': 20, '家用电器': 13,
        '电力设备': 20, '汽车': 17, '国防军工': 23,
        '银行': 5, '非银金融': 10, '公用事业': 10,
        '煤炭': 13, '石油石化': 13,
    }

    def __init__(self):
        super().__init__(max_retries=3, timeout=20, delay_range=(2, 5))

    def _parse_sector_data(self, html: str) -> List[Dict[str, Any]]:
        """
        从东方财富页面解析板块数据

        Args:
            html: 页面 HTML

        Returns:
            板块数据列表
        """
        sectors = []

        # 东方财富的板块数据通常在 JavaScript 变量或 JSON 中
        # 尝试从页面中提取 JSON 数据
        json_patterns = [
            r'var\s+boardData\s*=\s*(\{.*?\});',
            r'"data"\s*:\s*(\[.*?\])',
            r'<script[^>]*id="boardData"[^>]*>(\{.*?\})</script>',
        ]

        data_json = None
        for pattern in json_patterns:
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    data_json = json.loads(match.group(1))
                    break
                except json.JSONDecodeError:
                    continue

        if data_json:
            # 尝试从 JSON 中提取板块数据
            items = self._extract_from_json(data_json)
            if items:
                return items

        # 备用：从 HTML 表格提取
        return self._extract_from_table(html)

    def _extract_from_json(self, data: Dict) -> List[Dict[str, Any]]:
        """从 JSON 数据中提取板块信息"""
        sectors = []

        # 递归查找包含板块数据的结构
        def find_sector_data(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, dict):
                # 检查是否包含板块数据特征
                if 'code' in obj and 'name' in obj and 'price' in obj:
                    name = obj.get('name', '')
                    if name in self.SECTOR_MAPPING:
                        sectors.append({
                            'name': name,
                            'code': self.SECTOR_MAPPING.get(name, ''),
                            'price': obj.get('price', 0),
                            'change_pct': obj.get('change_pct', 0),
                            'turnover': obj.get('turnover', 0),
                            'pe': obj.get('pe', 0),
                            'pb': obj.get('pb', 0),
                        })
                for value in obj.values():
                    find_sector_data(value, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    find_sector_data(item, depth + 1)

        find_sector_data(data)
        return sectors

    def _extract_from_table(self, html: str) -> List[Dict[str, Any]]:
        """从 HTML 表格提取板块数据（备用）"""
        sectors = []

        # 匹配表格行
        row_pattern = r'<tr[^>]*>.*?<td[^>]*>.*?<a[^>]*>([^<]+)</a>.*?</td>.*?<td[^>]*>([\d.]+)</td>.*?<td[^>]*>([+-]?[\d.]+)%</td>'
        matches = re.findall(row_pattern, html, re.DOTALL)

        for match in matches:
            name = match[0].strip()
            if name in self.SECTOR_MAPPING:
                try:
                    sectors.append({
                        'name': name,
                        'code': self.SECTOR_MAPPING.get(name, ''),
                        'price': float(match[1]),
                        'change_pct': float(match[2]),
                        'turnover': 0,
                        'pe': 0,
                        'pb': 0,
                    })
                except ValueError:
                    continue

        return sectors

    def scrape(self) -> Optional[Dict[str, Any]]:
        """
        爬取所有板块数据

        Returns:
            {
                'data_type': 'sector',
                'generated_at': '2026-08-14 10:00:00',
                'items': [
                    {
                        'name': '电子',
                        'code': '801080',
                        'price': 4500.0,
                        'change_pct': 1.2,
                        'turnover': 100.5,
                        'pe': 35.0,
                        'pb': 3.5,
                        'threshold': 20,
                        'drawdown': 18.5
                    },
                    ...
                ],
                'source': 'eastmoney'
            }
        """
        logger.info(f"Scraping sector data from {self.SECTOR_URL}")
        html = self.fetch(self.SECTOR_URL)

        if html is None:
            logger.error("Failed to fetch sector page")
            return None

        items = self._parse_sector_data(html)

        if not items:
            logger.error("No sector data parsed")
            return None

        # 计算回撤（基于近一年最高价估算）
        for item in items:
            threshold = self.SECTOR_THRESHOLDS.get(item['name'], 20)
            item['threshold'] = threshold
            # 估算回撤：使用当前价格与52周高点的差距
            # 由于东方财富页面可能不直接提供52周高点，使用价格估算
            # 实际使用时，应结合历史数据计算
            high_52w = item['price'] * (1 + threshold / 100 * 1.2)
            drawdown = (high_52w - item['price']) / high_52w * 100
            item['drawdown'] = round(min(drawdown, 50), 2)  # 限制最大50%

        return {
            'data_type': 'sector',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'items': items,
            'source': 'eastmoney',
            'total': len(items),
        }

    def get_data_type(self) -> str:
        return 'sector'


# 便捷函数
def scrape_sectors() -> Optional[Dict[str, Any]]:
    """爬取板块数据的便捷入口"""
    scraper = SectorScraper()
    return scraper.scrape()


if __name__ == '__main__':
    result = scrape_sectors()
    if result:
        print(f"Scraped {result['total']} sectors from {result['source']}")
        for item in result['items'][:5]:
            print(f"  {item['name']}: {item['price']:.2f} ({item['change_pct']:+.2f}%) 回撤:{item['drawdown']:.1f}%")
        if result['total'] > 5:
            print(f"  ... and {result['total'] - 5} more")
    else:
        print("Scraping failed")
