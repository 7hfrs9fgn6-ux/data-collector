#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块（公开库）- 调试版
用于排查恒生科技指数名称匹配问题
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
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


class HKStockCollector:
    """港股指数采集器"""

    YF_INDICES = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
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

        # 1. 从 yfinance 采集
        yf_data = self._fetch_from_yfinance()
        if yf_data:
            result["items"].extend(yf_data)

        # 2. 从 akshare 采集恒生科技
        ak_data = self._fetch_hstech_from_akshare()
        if ak_data:
            result["items"].extend(ak_data)
            logger.info(f"   ✅ 恒生科技指数: {ak_data[0].get('price', 0)} [akshare]")
        else:
            logger.warning("   ⚠️ 恒生科技指数: akshare 采集失败")

        # 3. 尝试从缓存恢复
        if len(result["items"]) < 3:
            cache_tech = self._fetch_hstech_from_cache()
            if cache_tech:
                result["items"].extend(cache_tech)
                logger.info(f"   ✅ 恒生科技指数: {cache_tech[0].get('price', 0)} [缓存恢复]")

        result["total"] = len(result["items"])

        key = get_signing_key()
        if key and result["total"] > 0:
            result['signature'] = sign_data(result, key)
        else:
            result['signature'] = None

        logger.info(f"✅ 港股指数采集成功: {result['total']} 项")
        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
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
        except Exception as e:
            logger.debug(f"yfinance 港股采集异常: {e}")
            return []

    def _fetch_hstech_from_akshare(self) -> List[Dict]:
        """从 akshare 采集恒生科技指数 - 带完整调试输出"""
        try:
            import akshare as ak

            target_symbol = "HSTECH"
            target_name = "恒生科技指数"

            # ★★★ 调试模式：打印所有指数名称 ★★★
            logger.info("=" * 60)
            logger.info("🔍 调试模式：打印 stock_hk_spot() 所有数据")
            logger.info("=" * 60)

            try:
                df = ak.stock_hk_spot()
                if df is not None and not df.empty:
                    logger.info(f"   📊 数据行数: {len(df)}")
                    logger.info(f"   📋 列名: {df.columns.tolist()}")

                    # 找名称列
                    name_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'name' in col_lower or '名称' in col:
                            name_col = col
                            break
                    if name_col is None:
                        logger.warning("   ⚠️ 未找到名称列")
                    else:
                        logger.info(f"   🏷️ 名称列: {name_col}")
                        logger.info("   📝 所有指数名称:")
                        for idx, row in df.iterrows():
                            name = str(row.get(name_col, '')).strip()
                            # ★ 打印所有包含 "恒生" 或 "科技" 或 "HSTECH" 的名称
                            if '恒生' in name or '科技' in name or 'HSTECH' in name.upper() or 'TECH' in name.upper():
                                logger.info(f"      ★★★ {idx}: {name} ★★★")
                            else:
                                logger.info(f"      {idx}: {name}")
                        logger.info("=" * 60)
                        logger.info("🔍 调试结束，开始匹配...")
                        logger.info("=" * 60)

                        # ★ 现在尝试更宽松的匹配
                        for _, row in df.iterrows():
                            name = str(row.get(name_col, '')).strip()
                            # 匹配包含 "恒生科技" 或 "HSTECH" 或 "Tech" 且包含 "恒生" 的
                            if ('恒生科技' in name or 'HSTECH' in name.upper() or 
                                ('恒生' in name and ('科技' in name or 'TECH' in name.upper()))):
                                # 找价格列
                                price_col = None
                                for col in df.columns:
                                    if 'price' in col.lower() or '现价' in col or '最新价' in col:
                                        price_col = col
                                        break
                                if price_col is None:
                                    for col in df.columns:
                                        if df[col].dtype in ['float64', 'int64']:
                                            price_col = col
                                            break
                                if price_col:
                                    price = float(row.get(price_col, 0))
                                    if price > 0:
                                        logger.info(f"   ✅ 匹配成功: {name} ({price})")
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
                logger.error(f"   ❌ stock_hk_spot 失败: {e}")

            # 如果上面的调试没有匹配到，使用原来逻辑
            logger.warning("   ⚠️ 调试匹配未找到，尝试备用方法...")

            # 方法2：stock_hk_index_daily
            try:
                df = ak.stock_hk_index_daily(symbol=target_symbol)
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
                            logger.info(f"   ✅ stock_hk_index_daily 成功: {price}")
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
                logger.debug(f"   stock_hk_index_daily 失败: {e}")

            return []

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.error(f"   ❌ akshare 恒生科技采集异常: {e}")
            return []

    def _fetch_hstech_from_cache(self) -> List[Dict]:
        cache_file = "staging/hk_stock_cache.json"
        data = load_json(cache_file)
        if data:
            items = data.get('items', [])
            for item in items:
                if '恒生科技' in item.get('name', '') or 'HSTECH' in item.get('symbol', ''):
                    return [item]
        return []


def collect_hk_stock() -> Dict[str, Any]:
    collector = HKStockCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/hk_stock_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/hk_stock_cache.json")

    logger.info(f"📊 港股指数: {result['total']} 项")
    return result


def main():
    logger.info("=" * 60)
    logger.info("🇭🇰 港股指数采集启动 (调试版)")
    logger.info("=" * 60)

    data = collect_hk_stock()

    logger.info("=" * 60)
    logger.info("✅ 港股指数采集完成")
    logger.info(f"   🇭🇰 指数数量: {data['total']}")
    logger.info("=" * 60)

    return 0 if data['total'] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
