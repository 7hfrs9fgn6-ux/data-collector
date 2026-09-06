#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
欧洲指数采集模块（公开库）
采集：德国DAX、英国富时100、法国CAC40
频率：每日 01:00（欧洲收盘后）
数据源：yfinance（支持所有主要欧洲指数）
"""

import sys
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config, sign_data

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_signing_key() -> str:
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


class EUStockCollector:
    """欧洲指数采集器"""

    # ★ yfinance 支持的欧洲指数
    INDICES = {
        "^GDAXI": "德国DAX",
        "^FTSE": "英国富时100",
        "^FCHI": "法国CAC40",
    }

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "eu_stock",
            "total": 0,
            "items": []
        }

        # 从 yfinance 采集
        data = self._fetch_from_yfinance()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "yfinance"
            logger.info(f"✅ 欧洲指数采集成功 (来源: yfinance, {len(data)} 项)")
        else:
            # 尝试从缓存恢复
            cache_data = self._fetch_from_cache()
            if cache_data:
                result["items"] = cache_data
                result["total"] = len(cache_data)
                result["source"] = "cache"
                logger.info(f"✅ 欧洲指数从缓存恢复: {len(cache_data)} 项")
            else:
                logger.warning("⚠️ 所有欧洲指数数据源均失败")

        # 签名
        key = get_signing_key()
        if key and result["total"] > 0:
            result['signature'] = sign_data(result, key)
        else:
            result['signature'] = None

        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
        """使用 yfinance 采集欧洲指数"""
        try:
            import yfinance as yf

            items = []
            for symbol, name in self.INDICES.items():
                try:
                    ticker = yf.Ticker(symbol)
                    hist = ticker.history(period="5d")
                    if hist.empty:
                        logger.debug(f"   {name}({symbol}) yfinance 无数据")
                        continue

                    latest = hist.iloc[-1]
                    price = float(latest['Close'])
                    if price <= 0:
                        logger.debug(f"   {name}({symbol}) 价格无效: {price}")
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
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "source": "yfinance"
                    })
                    logger.info(f"   ✅ {name}: {price} ({change_pct:+.2f}%)")
                except Exception as e:
                    logger.debug(f"   {name}({symbol}) yfinance 异常: {e}")
                    continue

            return items

        except ImportError:
            logger.debug("yfinance 未安装")
            return []
        except Exception as e:
            logger.debug(f"yfinance 欧洲采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载"""
        cache_file = "staging/eu_stock_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_eu_stock() -> Dict[str, Any]:
    collector = EUStockCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_json(result, f"staging/eu_stock_{timestamp}.json")
    save_json(result, "staging/eu_stock_cache.json")

    logger.info(f"📊 欧洲指数: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    return result


def main():
    logger.info("=" * 60)
    logger.info("🇪🇺 欧洲指数采集启动")
    logger.info("=" * 60)

    data = collect_eu_stock()

    logger.info("=" * 60)
    logger.info("✅ 欧洲指数采集完成")
    logger.info(f"   🇪🇺 指数数量: {data['total']}")
    logger.info(f"   📦 数据源: {data.get('source', 'unknown')}")
    logger.info("=" * 60)

    return 0 if data['total'] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
