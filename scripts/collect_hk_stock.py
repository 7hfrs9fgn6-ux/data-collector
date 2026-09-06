#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块（公开库）- 精简版
采集：恒生指数、恒生国企指数、恒生科技指数
数据源：
  - 恒生指数、国企指数：yfinance（可靠）
  - 恒生科技指数：akshare（可能不支持），失败时从缓存恢复
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


class HKStockCollector:
    """港股指数采集器"""

    # ★ yfinance 支持的指数（恒生科技不支持）
    YF_INDICES = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
    }

    # ★ 需要从 akshare 尝试的指数（可能不支持）
    AK_INDICES = {
        "HSTECH": "恒生科技指数",
    }

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "hk_stock",
            "total": 0,
            "items": []
        }

        # 1. 从 yfinance 采集（恒生指数、国企指数）
        yf_data = self._fetch_from_yfinance()
        if yf_data:
            result["items"].extend(yf_data)
            logger.info(f"   ✅ yfinance 采集成功: {len(yf_data)} 项")

        # 2. 从 akshare 尝试恒生科技（可能失败）
        ak_data = self._fetch_hstech_from_akshare()
        if ak_data:
            result["items"].extend(ak_data)
            logger.info(f"   ✅ 恒生科技指数: 采集成功 [akshare]")
        else:
            # ★ 恒生科技采集失败 → 尝试从缓存恢复
            cache_tech = self._fetch_hstech_from_cache()
            if cache_tech:
                result["items"].extend(cache_tech)
                logger.info(f"   ✅ 恒生科技指数: 从缓存恢复")
            else:
                logger.warning("   ⚠️ 恒生科技指数: 所有数据源均不可用")

        # 3. 如果全部失败，尝试从完整缓存恢复
        if len(result["items"]) == 0:
            cache_data = self._fetch_from_cache()
            if cache_data:
                result["items"] = cache_data
                logger.info(f"   ✅ 全部指数从缓存恢复: {len(cache_data)} 项")

        result["total"] = len(result["items"])

        # 4. 签名
        key = get_signing_key()
        if key and result["total"] > 0:
            result['signature'] = sign_data(result, key)
        else:
            result['signature'] = None

        if result["total"] > 0:
            logger.info(f"✅ 港股指数采集成功: {result['total']} 项")
        else:
            logger.warning("⚠️ 所有港股指数采集失败")

        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
        """使用 yfinance 采集（恒生指数、国企指数）"""
        try:
            import yfinance as yf
            items = []
            for symbol, name in self.YF_INDICES.items():
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
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "source": "yfinance"
                    })
                    logger.info(f"   ✅ {name}: {price} ({change_pct:+.2f}%)")
                except Exception as e:
                    logger.debug(f"   {name} yfinance 失败: {e}")
                    continue
            return items
        except Exception as e:
            logger.debug(f"yfinance 异常: {e}")
            return []

    def _fetch_hstech_from_akshare(self) -> List[Dict]:
        """从 akshare 尝试恒生科技指数（精简版，不打印海量数据）"""
        try:
            import akshare as ak

            symbol = "HSTECH"
            name = "恒生科技指数"

            # ★ 只试指数专用接口，不走个股列表
            # 方法1：stock_hk_index_daily
            try:
                df = ak.stock_hk_index_daily(symbol=symbol)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    close_col = None
                    for col in df.columns:
                        if 'close' in col.lower() or '收盘' in col:
                            close_col = col
                            break
                    if close_col is None:
                        for col in df.columns:
                            if df[col].dtype in ['float64', 'int64']:
                                close_col = col
                                break
                    if close_col:
                        price = float(latest.get(close_col, 0))
                        if price > 0:
                            return [{
                                "name": name,
                                "symbol": symbol,
                                "price": round(price, 2),
                                "change_pct": 0,
                                "volume": 0,
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "source": "akshare_daily"
                            }]
            except Exception as e:
                logger.debug(f"   stock_hk_index_daily 失败: {e}")

            # 方法2：stock_hk_index_spot
            try:
                df = ak.stock_hk_index_spot(symbol=symbol)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    price = float(row.get('最新价', 0)) or float(row.get('price', 0))
                    if price > 0:
                        return [{
                            "name": name,
                            "symbol": symbol,
                            "price": round(price, 2),
                            "change_pct": float(row.get('涨跌幅', 0)),
                            "volume": 0,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "akshare_spot"
                        }]
            except Exception as e:
                logger.debug(f"   stock_hk_index_spot 失败: {e}")

            # ★ 方法3：index_hist_hk（备选）
            try:
                df = ak.index_hist_hk(symbol=symbol)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    close_col = None
                    for col in df.columns:
                        if 'close' in col.lower() or '收盘' in col:
                            close_col = col
                            break
                    if close_col:
                        price = float(latest.get(close_col, 0))
                        if price > 0:
                            return [{
                                "name": name,
                                "symbol": symbol,
                                "price": round(price, 2),
                                "change_pct": 0,
                                "volume": 0,
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "source": "akshare_hist"
                            }]
            except Exception as e:
                logger.debug(f"   index_hist_hk 失败: {e}")

            return []

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 异常: {e}")
            return []

    def _fetch_hstech_from_cache(self) -> List[Dict]:
        """从缓存恢复恒生科技指数"""
        cache_file = "staging/hk_stock_cache.json"
        data = load_json(cache_file)
        if data:
            for item in data.get('items', []):
                if '恒生科技' in item.get('name', ''):
                    return [item]
        return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存恢复全部"""
        cache_file = "staging/hk_stock_cache.json"
        data = load_json(cache_file)
        return data.get('items', []) if data else []


def collect_hk_stock() -> Dict[str, Any]:
    collector = HKStockCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    save_json(result, f"staging/hk_stock_{timestamp}.json")
    save_json(result, "staging/hk_stock_cache.json")

    logger.info(f"📊 港股指数: {result['total']} 项")
    return result


def main():
    logger.info("=" * 60)
    logger.info("🇭🇰 港股指数采集启动")
    logger.info("=" * 60)

    data = collect_hk_stock()

    logger.info("=" * 60)
    logger.info("✅ 港股指数采集完成")
    logger.info(f"   🇭🇰 指数数量: {data['total']}")
    logger.info("=" * 60)

    return 0 if data['total'] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
