#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块V2.0
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
    # ★ 匹配关键词优先级从高到低
    AK_TARGETS = [
        {"symbol": "HSTECH", "name": "恒生科技指数", "keywords": ["恒生科技", "科技指数", "HSTECH", "HSIT"]},
    ]

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
        """
        专门从 akshare 采集恒生科技指数
        ★ V2.0：增强匹配逻辑，支持多种名称变体
        """
        try:
            import akshare as ak

            target = self.AK_TARGETS[0]  # HSTECH
            target_symbol = target["symbol"]
            target_name = target["name"]
            keywords = target["keywords"]

            # ----- 方法1：stock_hk_index_daily（日线数据）-----
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
                            logger.debug(f"   stock_hk_index_daily({target_symbol}) 成功")
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
                logger.debug(f"   stock_hk_index_daily({target_symbol}) 失败: {e}")

            # ----- 方法2：stock_hk_index_spot（指数实时行情）-----
            try:
                df = ak.stock_hk_index_spot(symbol=target_symbol)
                if df is not None and not df.empty:
                    row = df.iloc[0]
                    # 尝试多种列名获取价格
                    price = 0
                    for col_name in ['最新价', 'price', '现价', '价']:
                        if col_name in df.columns:
                            price = float(row.get(col_name, 0))
                            if price > 0:
                                break
                    if price == 0:
                        # 尝试第一列数值
                        for col in df.columns:
                            if df[col].dtype in ['float64', 'int64']:
                                price = float(row.get(col, 0))
                                if price > 0:
                                    break

                    change_pct = 0
                    for col_name in ['涨跌幅', 'change_pct', 'change']:
                        if col_name in df.columns:
                            try:
                                change_pct = float(row.get(col_name, 0))
                            except (ValueError, TypeError):
                                pass
                            break

                    if price > 0:
                        logger.debug(f"   stock_hk_index_spot({target_symbol}) 成功")
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
                logger.debug(f"   stock_hk_index_spot({target_symbol}) 失败: {e}")

            # ----- 方法3：stock_hk_spot（全市场实时行情中匹配）-----
            try:
                df = ak.stock_hk_spot()
                if df is not None and not df.empty:
                    logger.debug(f"   stock_hk_spot 获取到 {len(df)} 条数据")

                    # 先打印前 5 条的名称，便于调试
                    name_col = None
                    price_col = None
                    for col in df.columns:
                        if 'name' in col.lower() or '名称' in col:
                            name_col = col
                            break
                    if name_col is None:
                        for col in df.columns:
                            if '名' in col:
                                name_col = col
                                break

                    if name_col:
                        sample_names = []
                        for _, row in df.head(5).iterrows():
                            sample_names.append(str(row.get(name_col, '')))
                        logger.debug(f"   数据中前5条名称: {sample_names}")

                    # 价格列
                    for col in df.columns:
                        if 'price' in col.lower() or '现价' in col or '最新价' in col:
                            price_col = col
                            break
                    if price_col is None:
                        for col in df.columns:
                            if '价' in col:
                                price_col = col
                                break

                    if name_col and price_col:
                        # 尝试所有匹配关键词
                        matched_row = None
                        matched_keyword = None

                        for _, row in df.iterrows():
                            name = str(row.get(name_col, '')).strip()
                            if not name:
                                continue

                            # 检查是否匹配任何关键词
                            for keyword in keywords:
                                if keyword.lower() in name.lower():
                                    matched_row = row
                                    matched_keyword = keyword
                                    break
                            if matched_row is not None:
                                break

                        if matched_row is not None:
                            price = float(matched_row.get(price_col, 0))
                            if price > 0:
                                logger.debug(f"   stock_hk_spot 匹配成功 (关键词: {matched_keyword})")
                                return [{
                                    "name": target_name,
                                    "symbol": target_symbol,
                                    "price": round(price, 2),
                                    "change_pct": 0,
                                    "volume": 0,
                                    "date": datetime.now().strftime("%Y-%m-%d"),
                                    "source": "akshare_spot"
                                }]
                        else:
                            # 打印所有名称样本，帮助调试
                            all_names = []
                            for _, row in df.head(30).iterrows():
                                all_names.append(str(row.get(name_col, '')))
                            logger.debug(f"   前30条名称样本: {all_names[:10]}")
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

    # ★ 修复：save_json 签名是 (data, filepath)，不是 (filepath, data)
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
