#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：大宗商品爬虫
主源 yfinance 失败时，从 investing.com 爬取大宗商品价格
"""

import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class CommodityScraper(BaseScraper):
    """
    大宗商品爬虫
    爬取 investing.com 的原油(CL)、黄金(GC)、铜(HG) 实时价格
    """

    # investing.com 商品页面 URL
    COMMODITY_URLS = {
        'crude_oil': 'https://www.investing.com/commodities/crude-oil',
        'gold': 'https://www.investing.com/commodities/gold',
        'copper': 'https://www.investing.com/commodities/copper',
    }

    # 商品代码映射（与 yfinance 保持一致）
    COMMODITY_CODES = {
        'crude_oil': 'CL=F',
        'gold': 'GC=F',
        'copper': 'HG=F',
    }

    def __init__(self):
        super().__init__(max_retries=3, timeout=15, delay_range=(2, 4))

    def _extract_price(self, html: str) -> Optional[float]:
        """
        从 investing.com 页面提取最新价格

        Args:
            html: 页面 HTML

        Returns:
            价格浮点数，失败返回 None
        """
        # investing.com 的价格通常在 data-test="instrument-price-last" 属性中
        # 或包含在特定的 CSS 类中
        patterns = [
            r'data-test="instrument-price-last"[^>]*>([\d,]+\.?\d*)',
            r'<span[^>]*class="[^"]*text-2xl[^"]*"[^>]*>([\d,]+\.?\d*)',
            r'<span[^>]*id="last_last"[^>]*>([\d,]+\.?\d*)',
            r'"last":\s*([\d.]+)',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                price_str = match.group(1).replace(',', '')
                try:
                    return float(price_str)
                except ValueError:
                    continue
        return None

    def _extract_change(self, html: str) -> Optional[float]:
        """
        提取涨跌幅（%）

        Args:
            html: 页面 HTML

        Returns:
            涨跌幅百分比，失败返回 None
        """
        patterns = [
            r'data-test="instrument-price-change"[^>]*>([+-]?[\d.]+)%',
            r'<span[^>]*class="[^"]*change[^"]*"[^>]*>([+-]?[\d.]+)%',
        ]

        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                try:
                    return float(match.group(1))
                except ValueError:
                    continue
        return None

    def scrape(self) -> Optional[Dict[str, Any]]:
        """
        爬取所有大宗商品数据

        Returns:
            {
                'data_type': 'commodity',
                'generated_at': '2026-08-14 10:00:00',
                'items': [
                    {'symbol': 'CL=F', 'name': 'crude_oil', 'price': 78.5, 'change_pct': 1.2},
                    ...
                ],
                'source': 'investing.com'
            }
        """
        items = []

        for name, url in self.COMMODITY_URLS.items():
            logger.info(f"Scraping commodity: {name} from {url}")
            html = self.fetch(url)

            if html is None:
                logger.warning(f"Failed to fetch {name}, skipping")
                continue

            price = self._extract_price(html)
            change = self._extract_change(html)

            if price is None:
                logger.warning(f"Failed to extract price for {name}")
                continue

            items.append({
                'symbol': self.COMMODITY_CODES.get(name, name),
                'name': name,
                'price': price,
                'change_pct': change if change is not None else 0.0,
            })

        if not items:
            logger.error("No commodity data scraped")
            return None

        return {
            'data_type': 'commodity',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'items': items,
            'source': 'investing.com',
            'total': len(items),
        }

    def get_data_type(self) -> str:
        return 'commodity'


# 便捷函数：供 collect_commodity.py 调用
def scrape_commodities() -> Optional[Dict[str, Any]]:
    """爬取大宗商品数据的便捷入口"""
    scraper = CommodityScraper()
    return scraper.scrape()


if __name__ == '__main__':
    # 测试运行
    result = scrape_commodities()
    if result:
        print(f"Scraped {result['total']} commodities from {result['source']}")
        for item in result['items']:
            print(f"  {item['name']}: ${item['price']} ({item['change_pct']:+.2f}%)")
    else:
        print("Scraping failed")
