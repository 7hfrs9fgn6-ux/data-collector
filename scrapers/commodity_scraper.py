#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：大宗商品爬虫（新浪财经版）
主源 yfinance 失败时，从新浪财经期货接口获取大宗商品价格
数据源：新浪财经 hq.sinajs.cn（对 GitHub Actions 云 IP 友好）
备选：akshare（新浪接口失败时的第二层降级）
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

    # 新浪财经接口 URL
    SINA_URL = 'https://hq.sinajs.cn/list='

    def __init__(self):
        # 新浪接口不需要复杂的 UA 轮换和延迟，但保留超时
        super().__init__(max_retries=2, timeout=10, delay_range=(0.5, 1.5))
        # 新浪接口需要特定的 Referer
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Referer': 'https://finance.sina.com.cn/',
            'Accept': 'text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
        }

    def _fetch_sina_data(self, symbols: List[str]) -> Optional[str]:
        """
        从新浪财经获取期货数据

        Args:
            symbols: 新浪期货符号列表

        Returns:
            原始响应文本，失败返回 None
        """
        if not symbols:
            return None

        url = self.SINA_URL + ','.join(symbols)

        # 随机延迟
        self._random_delay()

        try:
            response = requests.get(
                url,
                headers=self.headers,
                timeout=self.timeout,
            )
            response.encoding = 'gbk'  # 新浪财经使用 GBK 编码
            response.raise_for_status()
            logger.info(f"✅ 新浪财经接口请求成功: {len(symbols)} 个符号")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 新浪财经接口请求失败: {e}")
            return None

    def _parse_sina_response(self, raw_data: str) -> List[Dict[str, Any]]:
        """
        解析新浪财经返回的期货数据

        返回格式示例:
            var hq_str_fut_IS_SC="原油,77.50,78.20,76.80,77.00,76.50,2026-08-14,06:30:00,123456";
            var hq_str_fut_IS_AU="黄金,1920.00,1915.00,1925.00,1918.00,1910.00,2026-08-14,06:30:00,78901";

        字段顺序: 名称, 最新价, 昨收, 今开, 最高, 最低, 日期, 时间, 成交量
        """
        items = []

        if not raw_data:
            return items

        # 按行拆分
        lines = raw_data.strip().split('\n')

        for line in lines:
            if not line.strip():
                continue

            # 提取变量名和内容
            # 格式: var hq_str_fut_IS_SC="...";
            match = re.search(r'hq_str_([^=]+)="([^"]+)"', line)
            if not match:
                continue

            symbol = match.group(1)  # 如 'fut_IS_SC'
            content = match.group(2)

            # 如果内容为空，跳过
            if not content:
                continue

            # 按逗号分割字段
            parts = content.split(',')

            # 至少需要 9 个字段
            if len(parts) < 9:
                continue

            # 字段映射（新浪期货接口返回格式）
            # 索引: 0=名称, 1=最新价, 2=昨收, 3=今开, 4=最高, 5=最低, 6=日期, 7=时间, 8=成交量
            name = parts[0].strip()
            price_str = parts[1].strip()
            prev_close_str = parts[2].strip()

            try:
                price = float(price_str)
                prev_close = float(prev_close_str) if prev_close_str else price

                # 计算涨跌幅
                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                # 映射到 yfinance 符号和标准化名称
                yf_symbol, display_name = self.SINA_FUTURES.get(symbol, (symbol, name))

                items.append({
                    'name': display_name,
                    'symbol': yf_symbol,
                    'price': round(price, 2),
                    'change_pct': round(change_pct, 2),
                })

                logger.debug(f"  {display_name}: ${price} ({change_pct:+.2f}%)")

            except (ValueError, TypeError) as e:
                logger.debug(f"解析 {name} 数据失败: {e}")
                continue

        return items

    def _fetch_from_akshare_fallback(self) -> List[Dict[str, Any]]:
        """
        当新浪接口失败时，使用 akshare 作为备选
        """
        try:
            import akshare as ak
            items = []

            # 获取原油
            try:
                oil = ak.futures_main_sina(symbol="SC")
                if oil is not None and not oil.empty:
                    latest = oil.iloc[-1]
                    items.append({
                        'name': 'WTI原油',
                        'symbol': 'CL=F',
                        'price': round(float(latest.get('price', 0)), 2),
                        'change_pct': round(float(latest.get('change_pct', 0)), 2),
                    })
            except Exception as e:
                logger.debug(f"akshare 原油采集失败: {e}")

            # 获取黄金
            try:
                gold = ak.futures_main_sina(symbol="AU")
                if gold is not None and not gold.empty:
                    latest = gold.iloc[-1]
                    items.append({
                        'name': '黄金',
                        'symbol': 'GC=F',
                        'price': round(float(latest.get('price', 0)), 2),
                        'change_pct': round(float(latest.get('change_pct', 0)), 2),
                    })
            except Exception as e:
                logger.debug(f"akshare 黄金采集失败: {e}")

            # 获取铜
            try:
                copper = ak.futures_main_sina(symbol="CU")
                if copper is not None and not copper.empty:
                    latest = copper.iloc[-1]
                    items.append({
                        'name': '铜',
                        'symbol': 'HG=F',
                        'price': round(float(latest.get('price', 0)), 2),
                        'change_pct': round(float(latest.get('change_pct', 0)), 2),
                    })
            except Exception as e:
                logger.debug(f"akshare 铜采集失败: {e}")

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 备选采集异常: {e}")
            return []

    def scrape(self) -> Optional[Dict[str, Any]]:
        """
        爬取所有大宗商品数据

        返回格式:
            {
                'data_type': 'commodity',
                'generated_at': '2026-08-14 10:00:00',
                'items': [
                    {'name': 'WTI原油', 'symbol': 'CL=F', 'price': 78.5, 'change_pct': 1.2},
                    ...
                ],
                'source': 'sina_finance' 或 'akshare'
                'total': n
            }
        """
        # 1️⃣ 尝试新浪财经接口（主）
        symbols = list(self.SINA_FUTURES.keys())
        raw_data = self._fetch_sina_data(symbols)

        if raw_data:
            items = self._parse_sina_response(raw_data)
            if items:
                return {
                    'data_type': 'commodity',
                    'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'items': items,
                    'source': 'sina_finance',
                    'total': len(items),
                }

        # 2️⃣ 尝试 akshare（备选）
        logger.info("🔄 新浪接口无数据，尝试 akshare 备选")
        items = self._fetch_from_akshare_fallback()
        if items:
            return {
                'data_type': 'commodity',
                'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'items': items,
                'source': 'akshare',
                'total': len(items),
            }

        logger.error("❌ 所有大宗商品数据源（新浪/akshare）均失败")
        return None

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
        print(f"✅ 爬取成功: {result['total']} 项商品 (来源: {result['source']})")
        for item in result['items']:
            print(f"  {item['name']}: ${item['price']} ({item['change_pct']:+.2f}%)")
    else:
        print("❌ 爬取失败")
