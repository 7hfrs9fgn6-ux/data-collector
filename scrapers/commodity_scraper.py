#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：大宗商品爬虫（新浪财经版）
主源 yfinance 失败时，从新浪财经期货接口获取大宗商品价格
数据源：新浪财经 hq.sinajs.cn（对 GitHub Actions 云 IP 友好）
"""

import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

import requests

from .base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class CommodityScraper(BaseScraper):
    """
    大宗商品爬虫（新浪财经版）
    爬取原油(CL)、黄金(GC)、铜(HG)、白银(SI)、布伦特原油(BZ) 实时价格
    数据源：新浪财经期货接口 hq.sinajs.cn
    """

    # 新浪财经期货符号 → (yfinance符号, 显示名称)
    SINA_FUTURES = {
        'fut_IS_SC': ('CL=F', 'WTI原油'),
        'fut_IS_AU': ('GC=F', '黄金'),
        'fut_IS_HG': ('HG=F', '铜'),
        'fut_IS_SI': ('SI=F', '白银'),
        'fut_IS_BZ': ('BZ=F', '布伦特原油'),
    }

    SINA_URL = 'https://hq.sinajs.cn/list='

    def __init__(self):
        super().__init__(max_retries=2, timeout=10, delay_range=(0.5, 1.5))
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
            'Accept': 'text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _fetch_sina_data(self, symbols: List[str]) -> Optional[str]:
        if not symbols:
            return None

        url = self.SINA_URL + ','.join(symbols)
        self._random_delay()

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.encoding = 'gbk'
            response.raise_for_status()

            if not response.text or len(response.text.strip()) < 20:
                logger.warning("⚠️ 新浪接口返回空数据（可能非交易时段）")
                return None

            logger.info("✅ 新浪财经接口请求成功")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 新浪财经接口请求失败: {e}")
            return None

    def _parse_sina_response(self, raw_data: str) -> List[Dict[str, Any]]:
        """
        解析新浪财经返回的期货数据

        字段顺序（共12个字段）:
            0: 名称, 1: 最新价, 2: 涨跌额, 3: 涨跌幅%, 4: 今开, 5: 最高, 6: 最低, 7: 昨收, 8: 成交量, 9: 持仓量, 10: 日期, 11: 时间
        """
        items = []

        if not raw_data:
            return items

        lines = raw_data.strip().split('\n')

        for line in lines:
            if not line.strip():
                continue

            match = re.search(r'hq_str_([^=]+)="([^"]+)"', line)
            if not match:
                continue

            symbol = match.group(1)
            content = match.group(2)

            if not content:
                continue

            parts = content.split(',')

            if len(parts) < 12:
                continue

            name = parts[0].strip()
            price_str = parts[1].strip()
            change_pct_str = parts[3].strip().replace('%', '')

            if not name or not price_str:
                continue

            try:
                price = float(price_str)
                change_pct = float(change_pct_str) if change_pct_str else 0.0

                yf_symbol, display_name = self.SINA_FUTURES.get(symbol, (symbol, name))

                items.append({
                    'name': display_name,
                    'symbol': yf_symbol,
                    'price': round(price, 2),
                    'change_pct': round(change_pct, 2),
                })
                logger.debug(f"  ✅ {display_name}: ${price} ({change_pct:+.2f}%)")
            except (ValueError, TypeError):
                continue

        return items

    def scrape(self) -> Dict[str, Any]:
        """
        爬取所有大宗商品数据
        返回：始终返回字典，即使无数据也返回空列表
        """
        # 1️⃣ 尝试新浪财经接口
        symbols = list(self.SINA_FUTURES.keys())
        raw_data = self._fetch_sina_data(symbols)

        if raw_data:
            items = self._parse_sina_response(raw_data)
            if items:
                logger.info(f"✅ 大宗商品爬虫成功: {len(items)} 项 (来源: sina_finance)")
                return {
                    'data_type': 'commodity',
                    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'items': items,
                    'source': 'sina_finance',
                    'total': len(items),
                }
            else:
                logger.warning("⚠️ 新浪数据解析为空（可能非交易时段）")

        # 2️⃣ 尝试 akshare（备选）
        logger.info("🔄 尝试 akshare 备选")
        items = self._fetch_from_akshare_fallback()
        if items:
            logger.info(f"✅ 大宗商品爬虫成功: {len(items)} 项 (来源: akshare)")
            return {
                'data_type': 'commodity',
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'items': items,
                'source': 'akshare',
                'total': len(items),
            }

        # 3️⃣ 所有源均无数据，返回空结果（让调用方走缓存）
        logger.warning("⚠️ 所有大宗商品数据源均返回空（可能非交易时段），返回空列表")
        return {
            'data_type': 'commodity',
            'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'items': [],
            'source': 'no_data',
            'total': 0,
        }

    def _fetch_from_akshare_fallback(self) -> List[Dict[str, Any]]:
        try:
            import akshare as ak
            items = []

            for symbol, (yf_sym, name) in [
                ('SC', 'CL=F', 'WTI原油'),
                ('AU', 'GC=F', '黄金'),
                ('CU', 'HG=F', '铜'),
            ]:
                try:
                    data = ak.futures_main_sina(symbol=symbol)
                    if data is not None and not data.empty:
                        latest = data.iloc[-1]
                        items.append({
                            'name': name,
                            'symbol': yf_sym,
                            'price': round(float(latest.get('price', 0)), 2),
                            'change_pct': round(float(latest.get('change_pct', 0)), 2),
                        })
                except Exception:
                    continue
            return items
        except ImportError:
            return []
        except Exception:
            return []

    def get_data_type(self) -> str:
        return 'commodity'


def scrape_commodities() -> Dict[str, Any]:
    """便捷入口"""
    scraper = CommodityScraper()
    return scraper.scrape()


if __name__ == '__main__':
    result = scrape_commodities()
    if result['total'] > 0:
        print(f"✅ 爬取成功: {result['total']} 项商品 (来源: {result['source']})")
        for item in result['items']:
            print(f"  {item['name']}: ${item['price']} ({item['change_pct']:+.2f}%)")
    else:
        print("ℹ️ 爬取返回空数据（可能非交易时段），这是正常现象")
