#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块
采集：恒生指数、恒生国企指数、恒生科技指数
频率：每日 17:00（港股 16:00 收盘后）
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


class HKStockCollector:
    """港股指数采集器"""

    # ★ yfinance 支持的港股指数（恒生科技不支持）
    YF_INDICES = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
    }

    # ★ 需要从 akshare 采集的指数（yfinance 不支持）
    AK_ONLY_INDICES = {
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

        # 2. 从 akshare 采集恒生科技（yfinance 不支持）
        ak_data = self._fetch_hstech_from_akshare()
        if ak_data:
            result["items"].extend(ak_data)
            logger.info(f"   ✅ 恒生科技指数: {ak_data[0].get('price', 0)} [akshare]")
        else:
            logger.warning("   ⚠️ 恒生科技指数: akshare 采集失败")

        # 3. 如果全部失败，尝试从缓存恢复
        if len(result["items"]) == 0:
            cache_data = self._fetch_from_cache()
            if cache_data:
                result["items"] = cache_data
                result["source"] = "cache"
                logger.info(f"✅ 港股指数从缓存恢复: {len(result['items'])} 项")

        result["total"] = len(result["items"])

        # 4. 签名
        key = get_signing_key()
        if key and result["total"] > 0:
            result['signature'] = sign_data(result, key)
            logger.info(f"   🔐 数据包已签名")
        else:
            result['signature'] = None
            if result["total"] == 0:
                logger.warning("⚠️ 无数据可签名")

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

                    date_str = latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, 'strftime') else datetime.now().strftime("%Y-%m-%d")

                    items.append({
                        "name": name,
                        "symbol": symbol,
                        "price": round(price, 2),
                        "change_pct": round(change_pct, 2),
                        "volume": int(latest.get('Volume', 0)),
                        "date": date_str,
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
            logger.debug(f"yfinance 港股采集异常: {e}")
            return []

    def _fetch_hstech_from_akshare(self) -> List[Dict]:
        """专门从 akshare 采集恒生科技指数"""
        try:
            import akshare as ak

            target_symbol = "HSTECH"
            target_name = "恒生科技指数"

            # 方法1：stock_hk_index_daily
            try:
                df = ak.stock_hk_index_daily(symbol=target_symbol)
                if df is not None and not df.empty:
                    latest = df.iloc[-1]
                    # 找收盘价列
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
                                "name": target_name,
                                "symbol": target_symbol,
                                "price": round(price, 2),
                                "change_pct": 0,
                                "volume": 0,
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "source": "akshare_daily"
                            }]
            except Exception as e:
                logger.debug(f"   stock_hk_index_daily(HSTECH) 失败: {e}")

            # 方法2：stock_hk_index_spot
            try:
                df = ak.stock_hk_index_spot(symbol=target_symbol)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    price = float(row.get('最新价', 0)) or float(row.get('price', 0)) or float(row.iloc[0] if len(row) > 0 else 0)
                    change_pct = float(row.get('涨跌幅', 0)) or float(row.get('change_pct', 0))
                    if price > 0:
                        return [{
                            "name": target_name,
                            "symbol": target_symbol,
                            "price": round(price, 2),
                            "change_pct": round(change_pct, 2),
                            "volume": 0,
                            "date": datetime.now().strftime("%Y-%m-%d"),
                            "source": "akshare_index_spot"
                        }]
            except Exception as e:
                logger.debug(f"   stock_hk_index_spot(HSTECH) 失败: {e}")

            # 方法3：stock_hk_spot（全市场实时行情中匹配）
            try:
                df = ak.stock_hk_spot()
                if df is not None and not df.empty:
                    name_col = None
                    price_col = None
                    for col in df.columns:
                        if 'name' in col.lower() or '名称' in col:
                            name_col = col
                        if 'price' in col.lower() or '现价' in col:
                            price_col = col
                    if name_col and price_col:
                        for _, row in df.iterrows():
                            name = str(row.get(name_col, '')).strip()
                            if '恒生科技' in name or 'HSTECH' in name:
                                price = float(row.get(price_col, 0))
                                if price > 0:
                                    return [{
                                        "name": target_name,
                                        "symbol": target_symbol,
                                        "price": round(price, 2),
                                        "change_pct": 0,
                                        "volume": 0,
                                        "date": datetime.now().strftime("%Y-%m-%d"),
                                        "source": "akshare_spot"
                                    }]
            except Exception as e:
                logger.debug(f"   stock_hk_spot 匹配失败: {e}")

            return []

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 恒生科技采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载"""
        cache_file = "staging/hk_stock_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_hk_stock() -> Dict[str, Any]:
    collector = HKStockCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/hk_stock_{timestamp}.json"
    save_json(filepath, result)
    save_json("staging/hk_stock_cache.json", result)

    logger.info(f"📊 港股指数: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    return result


def main():
    logger.info("=" * 60)
    logger.info("🇭🇰 港股指数采集启动")
    logger.info("=" * 60)

    data = collect_hk_stock()

    logger.info("=" * 60)
    logger.info("✅ 港股指数采集完成")
    logger.info(f"   🇭🇰 指数数量: {data['total']}")
    logger.info(f"   📦 数据源: {data.get('source', 'mixed')}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if data.get('signature') else '⚠️ 未签名'}")
    logger.info("=" * 60)

    return 0 if data['total'] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
