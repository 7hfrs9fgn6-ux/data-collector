#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块（公开库）
采集：恒生指数、恒生国企指数、恒生科技指数
频率：每日 17:00（港股 16:00 收盘后）
数据源：
  - 恒生指数、国企指数：yfinance → akshare → 缓存
  - 恒生科技指数：akshare（yfinance 不支持该指数）
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
            # ★ 恒生科技采集失败时，尝试从缓存恢复
            cache_tech = self._fetch_hstech_from_cache()
            if cache_tech:
                result["items"].extend(cache_tech)
                logger.info(f"   ✅ 恒生科技指数: {cache_tech[0].get('price', 0)} [缓存恢复]")
            else:
                logger.warning("   ⚠️ 恒生科技指数: 所有数据源均失败")

        # 3. 如果全部失败，尝试从完整缓存恢复
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
        """
        专门从 akshare 采集恒生科技指数
        ★ 2026-09-06：改进匹配逻辑，增加多种名称变体匹配
        """
        try:
            import akshare as ak

            target_symbol = "HSTECH"
            target_name = "恒生科技指数"

            # ★ 名称变体列表（用于匹配）
            name_variants = [
                "恒生科技指数",
                "恒生科技",
                "HSTECH",
                "Hang Seng Tech",
                "HS Tech",
                "科技指数",
                "Tech Index",
            ]

            # 方法1：stock_hk_index_daily
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
                    # 尝试多种列名
                    price = 0
                    for col in ['最新价', 'price', '现价', '收盘价', 'close']:
                        if col in row:
                            try:
                                price = float(row[col])
                                if price > 0:
                                    break
                            except (ValueError, TypeError):
                                continue
                    if price <= 0:
                        # 尝试取第一列数值
                        for col in df.columns:
                            try:
                                val = float(row[col])
                                if val > 0 and col not in ['涨跌幅', 'change', 'change_pct']:
                                    price = val
                                    break
                            except (ValueError, TypeError):
                                continue
                    change_pct = 0
                    for col in ['涨跌幅', 'change_pct', 'change']:
                        if col in row:
                            try:
                                change_pct = float(row[col])
                                break
                            except (ValueError, TypeError):
                                continue
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
                    # ★ 检测列名
                    name_col = None
                    price_col = None
                    change_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'name' in col_lower or '名称' in col or '代码' in col:
                            name_col = col
                        if 'price' in col_lower or '现价' in col or '最新价' in col:
                            price_col = col
                        if 'change' in col_lower and 'pct' in col_lower or '涨跌幅' in col:
                            change_col = col

                    # ★ 如果找不到价格列，尝试取第一列数值
                    if price_col is None:
                        for col in df.columns:
                            if df[col].dtype in ['float64', 'int64']:
                                price_col = col
                                break

                    if name_col is None:
                        logger.debug("   stock_hk_spot: 未找到名称列")
                        return []
                    if price_col is None:
                        logger.debug("   stock_hk_spot: 未找到价格列")
                        return []

                    # ★ 遍历数据，匹配恒生科技
                    for _, row in df.iterrows():
                        name = str(row.get(name_col, '')).strip()
                        # 检查是否匹配任一名称变体
                        matched = False
                        for variant in name_variants:
                            if variant.lower() in name.lower() or name.lower() in variant.lower():
                                matched = True
                                break
                        if not matched:
                            continue

                        price = 0
                        try:
                            price = float(row.get(price_col, 0))
                        except (ValueError, TypeError):
                            continue

                        change_pct = 0
                        if change_col:
                            try:
                                change_pct = float(row.get(change_col, 0))
                            except (ValueError, TypeError):
                                pass

                        if price > 0:
                            logger.info(f"   ✅ 从 stock_hk_spot 匹配到: {name} ({price})")
                            return [{
                                "name": target_name,
                                "symbol": target_symbol,
                                "price": round(price, 2),
                                "change_pct": round(change_pct, 2),
                                "volume": 0,
                                "date": datetime.now().strftime("%Y-%m-%d"),
                                "source": "akshare_spot"
                            }]

                    # ★ 如果没找到，打印前5条数据帮助调试（仅调试模式）
                    logger.debug("   stock_hk_spot: 未匹配到恒生科技指数，前5条数据:")
                    for idx, (_, row) in enumerate(df.head(5).iterrows()):
                        if name_col:
                            logger.debug(f"      {idx+1}. {row.get(name_col, 'N/A')}")
            except Exception as e:
                logger.debug(f"   stock_hk_spot 匹配失败: {e}")

            return []

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 恒生科技采集异常: {e}")
            return []

    def _fetch_hstech_from_cache(self) -> List[Dict]:
        """从缓存恢复恒生科技指数"""
        cache_file = "staging/hk_stock_cache.json"
        data = load_json(cache_file)
        if data:
            items = data.get('items', [])
            for item in items:
                if '恒生科技' in item.get('name', '') or 'HSTECH' in item.get('symbol', ''):
                    return [item]
        return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载全部"""
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
    save_json(result, filepath)
    save_json(result, "staging/hk_stock_cache.json")

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
