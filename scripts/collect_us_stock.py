#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 美股指数采集模块
采集：道琼斯、纳斯达克、标普500 日线数据
频率：每日1次（美股收盘后）
数据源：yfinance → pandas_datareader → 缓存
★ 2026-08-14 新增：自动HMAC-SHA256签名 ★
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config, sign_data

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_signing_key() -> str:
    """从环境变量获取签名密钥"""
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


class USStockCollector:
    """美股指数采集器"""

    INDICES = {
        "^DJI": "道琼斯",
        "^IXIC": "纳斯达克",
        "^GSPC": "标普500",
    }

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        """
        采集美股指数数据
        返回: {
            "timestamp": "...",
            "source": "us_stock",
            "total": 3,
            "items": [...],
            "signature": "..."  ← 自动添加
        }
        """
        result = {
            "timestamp": get_timestamp(),
            "source": "us_stock",
            "total": 0,
            "items": []
        }

        # 尝试 yfinance
        data = self._fetch_from_yfinance()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "yfinance"
            logger.info(f"✅ 美股指数采集成功 (来源: yfinance, {len(data)} 项)")
            key = get_signing_key()
            if key:
                result['signature'] = sign_data(result, key)
            else:
                result['signature'] = None
            return result

        # 尝试 pandas_datareader
        data = self._fetch_from_datareader()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "datareader"
            logger.info(f"✅ 美股指数采集成功 (来源: datareader, {len(data)} 项)")
            key = get_signing_key()
            if key:
                result['signature'] = sign_data(result, key)
            else:
                result['signature'] = None
            return result

        # 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 美股指数采集成功 (来源: 缓存, {len(data)} 项)")
            # 缓存数据可能已包含签名

        logger.warning("⚠️ 所有美股指数数据源均失败")
        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
        try:
            import yfinance as yf

            items = []
            for symbol, name in self.INDICES.items():
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="5d")
                    if hist.empty:
                        continue

                    latest = hist.iloc[-1]
                    price = float(latest['Close'])
                    if price <= 0:
                        continue

                    change_pct = 0
                    if len(hist) >= 2:
                        prev_close = float(hist.iloc[-2]['Close'])
                        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    items.append({
                        "name": name,
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": int(latest.get('Volume', 0)),
                        "date": latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, 'strftime') else datetime.now().strftime("%Y-%m-%d")
                    })
                except Exception as e:
                    logger.debug(f"   {name}({symbol}) 获取失败: {e}")
                    continue

            return items

        except ImportError:
            logger.debug("yfinance 未安装")
            return []
        except Exception as e:
            logger.debug(f"yfinance 美股采集异常: {e}")
            return []

    def _fetch_from_datareader(self) -> List[Dict]:
        try:
            import pandas_datareader as pdr
            from pandas_datareader import data as web
            import pandas as pd

            items = []
            end = datetime.now()
            start = end - timedelta(days=5)

            for symbol, name in self.INDICES.items():
                try:
                    df = web.DataReader(symbol, 'yahoo', start, end)
                    if df.empty:
                        continue

                    latest = df.iloc[-1]
                    price = float(latest['Close'])
                    if price <= 0:
                        continue

                    change_pct = 0
                    if len(df) >= 2:
                        prev_close = float(df.iloc[-2]['Close'])
                        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0

                    items.append({
                        "name": name,
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": int(latest.get('Volume', 0)),
                        "date": latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, 'strftime') else datetime.now().strftime("%Y-%m-%d")
                    })
                except Exception as e:
                    logger.debug(f"   {name}({symbol}) datareader 失败: {e}")
                    continue

            return items

        except ImportError:
            logger.debug("pandas_datareader 未安装")
            return []
        except Exception as e:
            logger.debug(f"datareader 美股采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/us_stock_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_us_stock() -> Dict[str, Any]:
    collector = USStockCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/us_stock_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/us_stock_cache.json")

    logger.info(f"📊 美股指数: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    return result


if __name__ == "__main__":
    data = collect_us_stock()
    print(f"美股指数采集完成: {data['total']} 项")
