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

    # 新浪财经接口 URL
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
        """从新浪财经获取期货数据"""
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

            # 检查是否返回了有效数据（非空）
            if not response.text or len(response.text.strip()) < 20:
                logger.warning("⚠️ 新浪接口返回空数据")
                return None

            logger.info(f"✅ 新浪财经接口请求成功: {len(symbols)} 个符号")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ 新浪财经接口请求失败: {e}")
            return None

    def _parse_sina_response(self, raw_data: str) -> List[Dict[str, Any]]:
        """
        解析新浪财经返回的期货数据

        真实返回格式:
            var hq_str_fut_IS_SC="原油,77.50,0.30,0.39%,77.20,78.00,76.80,77.20,123456,78901,2026-08-14,06:30:00";
            var hq_str_fut_IS_AU="黄金,1920.00,-5.00,-0.26%,1915.00,1925.00,1910.00,1925.00,45678,23456,2026-08-14,06:30:00";

        字段顺序（共12个字段）:
            0: 名称
            1: 最新价
            2: 涨跌额
            3: 涨跌幅%
            4: 今开
            5: 最高
            6: 最低
            7: 昨收
            8: 成交量
            9: 持仓量
            10: 日期
            11: 时间
        """
        items = []

        if not raw_data:
            return items

        lines = raw_data.strip().split('\n')

        for line in lines:
            if not line.strip():
                continue

            # 提取变量名和内容
            match = re.search(r'hq_str_([^=]+)="([^"]+)"', line)
            if not match:
                continue

            symbol = match.group(1)  # 如 'fut_IS_SC'
            content = match.group(2)

            if not content:
                continue

            parts = content.split(',')

            # 新浪期货接口固定返回12个字段
            if len(parts) < 12:
                logger.debug(f"字段数不足: {len(parts)}, 期望12, 内容: {content[:100]}")
                continue

            # 字段映射（真实顺序）
            # 索引: 0=名称, 1=最新价, 2=涨跌额, 3=涨跌幅%, 4=今开, 5=最高, 6=最低, 7=昨收, 8=成交量, 9=持仓量, 10=日期, 11=时间
            name = parts[0].strip()
            price_str = parts[1].strip()
            change_pct_str = parts[3].strip().replace('%', '')

            if not name or not price_str:
                logger.debug(f"名称或价格为空: name='{name}', price='{price_str}'")
                continue

            try:
                price = float(price_str)

                # 解析涨跌幅
                if change_pct_str:
                    change_pct = float(change_pct_str)
                else:
                    change_pct = 0.0

                # 映射到 yfinance 符号和标准化名称
                yf_symbol, display_name = self.SINA_FUTURES.get(symbol, (symbol, name))

                items.append({
                    'name': display_name,
                    'symbol': yf_symbol,
                    'price': round(price, 2),
                    'change_pct': round(change_pct, 2),
                })

                logger.debug(f"  ✅ {display_name}: ${price} ({change_pct:+.2f}%)")

            except (ValueError, TypeError) as e:
                logger.debug(f"解析 {name} 数据失败: {e}, price_str='{price_str}'")
                continue

        return items

    def scrape(self) -> Optional[Dict[str, Any]]:
        """爬取所有大宗商品数据"""
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
                # 解析失败，打印原始数据前200字符以便调试
                logger.warning(f"⚠️ 新浪数据解析失败，原始数据前200字符: {raw_data[:200]}")

        # 2️⃣ 尝试 akshare（备选）
        logger.info("🔄 新浪接口无数据，尝试 akshare 备选")
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

        logger.error("❌ 所有大宗商品数据源（新浪/akshare）均失败")
        return None

    def _fetch_from_akshare_fallback(self) -> List[Dict[str, Any]]:
        """akshare 备选降级"""
        try:
            import akshare as ak
            items = []

            # 原油
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
                logger.debug(f"akshare 原油失败: {e}")

            # 黄金
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
                logger.debug(f"akshare 黄金失败: {e}")

            # 铜
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
                logger.debug(f"akshare 铜失败: {e}")

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 备选异常: {e}")
            return []

    def get_data_type(self) -> str:
        return 'commodity'


# 便捷函数
def scrape_commodities() -> Optional[Dict[str, Any]]:
    """爬取大宗商品数据的便捷入口"""
    scraper = CommodityScraper()
    return scraper.scrape()


if __name__ == '__main__':
    result = scrape_commodities()
    if result:
        print(f"✅ 爬取成功: {result['total']} 项商品 (来源: {result['source']})")
        for item in result['items']:
            print(f"  {item['name']}: ${item['price']} ({item['change_pct']:+.2f}%)")
    else:
        print("❌ 爬取失败")
