#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 大宗商品采集模块
采集：原油、黄金、铜等大宗商品价格
频率：每小时
数据源：yfinance → akshare → 缓存
"""

import sys
import os
from datetime import datetime
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CommodityCollector:
    """大宗商品采集器"""

    COMMODITIES = [
        ("CL=F", "WTI原油"),
        ("GC=F", "黄金"),
        ("HG=F", "铜"),
        ("SI=F", "白银"),
        ("BZ=F", "布伦特原油"),
    ]

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2
        self.timeout = 15

    def collect(self) -> Dict[str, Any]:
        """采集大宗商品数据"""
        result = {
            "timestamp": get_timestamp(),
            "source": "commodity",
            "total": 0,
            "items": []
        }

        # 1️⃣ 尝试 yfinance（主源）
        data = self._fetch_from_yfinance()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "yfinance"
            logger.info(f"✅ 大宗商品采集成功 (来源: yfinance, {len(data)} 项)")
            return result

        # 2️⃣ 尝试 akshare（备源）
        data = self._fetch_from_akshare()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 大宗商品采集成功 (来源: akshare, {len(data)} 项)")
            return result

        # 3️⃣ 从缓存加载（兜底）
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 大宗商品采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有大宗商品数据源均失败")
        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
        """从 yfinance 获取大宗商品数据"""
        try:
            import yfinance as yf

            items = []
            for symbol, name in self.COMMODITIES:
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="1d")
                    if hist.empty:
                        continue

                    latest = hist.iloc[-1]
                    price = float(latest['Close'])
                    if price <= 0:
                        continue

                    if len(hist) >= 2:
                        prev_close = float(hist.iloc[-2]['Close'])
                        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                    else:
                        change_pct = 0

                    items.append({
                        "name": name,
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                except Exception as e:
                    logger.debug(f"   {name}({symbol}) 获取失败: {e}")
                    continue

            return items

        except ImportError:
            logger.debug("yfinance 未安装")
            return []
        except Exception as e:
            logger.debug(f"yfinance 采集异常: {e}")
            return []

    def _fetch_from_akshare(self) -> List[Dict]:
        """从 akshare 获取大宗商品数据"""
        try:
            import akshare as ak
            items = []

            for symbol, name in [("SC", "SC原油"), ("AU", "黄金")]:
                try:
                    data = ak.futures_main_sina(symbol=symbol)
                    if data is not None and not data.empty:
                        latest = data.iloc[-1]
                        items.append({
                            "name": name,
                            "symbol": symbol,
                            "price": round(float(latest.get('price', 0)), 2),
                            "change_pct": round(float(latest.get('change_pct', 0)), 2),
                            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        })
                except Exception as e:
                    logger.debug(f"{name}采集失败: {e}")

            return items

        except ImportError:
            return []
        except Exception as e:
            logger.debug(f"akshare 大宗商品采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载大宗商品数据"""
        cache_file = "staging/commodity_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_commodity() -> Dict[str, Any]:
    """公开接口：采集大宗商品数据"""
    collector = CommodityCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/commodity_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/commodity_cache.json")

    logger.info(f"📊 大宗商品: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_commodity()
    print(f"大宗商品采集完成: {data['total']} 项")
