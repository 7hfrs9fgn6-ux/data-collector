#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 汇率数据采集模块
采集：美元/人民币、欧元/人民币、日元/人民币等
频率：每日1次
数据源：akshare → 新浪财经 → 缓存
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ForexCollector:
    """汇率数据采集器"""

    CURRENCIES = [
        {"name": "USD/CNY", "symbol": "美元/人民币"},
        {"name": "EUR/CNY", "symbol": "欧元/人民币"},
        {"name": "JPY/CNY", "symbol": "日元/人民币"},
        {"name": "GBP/CNY", "symbol": "英镑/人民币"},
    ]

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "forex",
            "total": 0,
            "items": []
        }

        data = self._fetch_from_akshare()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 汇率采集成功 (来源: akshare, {len(data)} 项)")
            return result

        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"✅ 汇率采集成功 (来源: 新浪, {len(data)} 项)")
            return result

        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 汇率采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有汇率数据源均失败")
        return result

    def _fetch_from_akshare(self) -> List[Dict]:
        try:
            import akshare as ak

            items = []

            # 获取人民币汇率
            try:
                df = ak.currency_rates()
                if df is not None and not df.empty:
                    today = datetime.now().strftime("%Y-%m-%d")
                    for _, row in df.iterrows():
                        currency = row.get('货币名称', '')
                        rate = row.get('最新价', 0)
                        if currency and rate:
                            items.append({
                                "currency": currency,
                                "rate": round(float(rate), 4),
                                "date": today
                            })
                    return items
            except Exception as e:
                logger.debug(f"currency_rates 采集失败: {e}")

            return items

        except ImportError:
            return []
        except Exception as e:
            logger.debug(f"akshare 汇率采集异常: {e}")
            return []

    def _fetch_from_sina(self) -> List[Dict]:
        try:
            import requests

            items = []
            # 新浪汇率接口
            symbols = ["fx_susdcny", "fx_seurcny", "fx_sjpycny", "fx_sgbpcny"]
            for symbol in symbols:
                try:
                    url = f"https://hq.sinajs.cn/list={symbol}"
                    headers = {
                        "User-Agent": "Mozilla/5.0",
                        "Referer": "https://finance.sina.com.cn/"
                    }
                    resp = requests.get(url, headers=headers, timeout=5)
                    if resp.status_code == 200:
                        content = resp.text
                        if content and "没有找到" not in content:
                            start = content.find('"')
                            end = content.rfind('"')
                            if start != -1 and end != -1:
                                parts = content[start+1:end].split(',')
                                if len(parts) >= 4:
                                    # 部分字段说明
                                    # 0: 货币名称, 1: 最新价, 2: 涨跌, 3: 涨跌幅
                                    price = float(parts[1])
                                    items.append({
                                        "currency": parts[0],
                                        "rate": round(price, 4),
                                        "date": datetime.now().strftime("%Y-%m-%d")
                                    })
                except Exception as e:
                    logger.debug(f"   {symbol} 采集失败: {e}")
                    continue

            return items

        except Exception as e:
            logger.debug(f"新浪汇率采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/forex_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_forex() -> Dict[str, Any]:
    collector = ForexCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/forex_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/forex_cache.json")

    logger.info(f"📊 汇率数据: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_forex()
    print(f"汇率采集完成: {data['total']} 项")
