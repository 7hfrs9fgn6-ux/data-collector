#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块
采集：恒生指数、恒生科技指数、国企指数
频率：每日 17:00（港股 16:00 收盘后）
数据源：yfinance → akshare → 缓存

★ 参照 collect_us_stock.py 设计模式

★ 使用方式：
  python scripts/collect_hk_stock.py              # 采集全部指数

★ 输出文件：
  staging/hk_stock_{timestamp}.json          # 采集数据（含签名）
  staging/hk_stock_package_{timestamp}.json  # 打包后的统一格式数据包
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

    # 港股指数 yfinance 代码
    INDICES = {
        "^HSI": "恒生指数",
        "^HSCE": "恒生国企指数",
        "^HSTECH": "恒生科技指数",
    }

    # akshare 备用代码（如果 yfinance 失败）
    AK_INDICES = {
        "HSI": "恒生指数",
        "HSCEI": "恒生国企指数",
        "HSTECH": "恒生科技指数",
    }

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        """
        采集港股指数数据
        返回: {
            "timestamp": "...",
            "source": "hk_stock",
            "total": 0,
            "items": [...],
            "signature": "..."
        }
        """
        result = {
            "timestamp": get_timestamp(),
            "source": "hk_stock",
            "total": 0,
            "items": []
        }

        # 尝试 yfinance（主源，与美股一致）
        data = self._fetch_from_yfinance()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "yfinance"
            logger.info(f"✅ 港股指数采集成功 (来源: yfinance, {len(data)} 项)")
            key = get_signing_key()
            if key:
                result['signature'] = sign_data(result, key)
            else:
                result['signature'] = None
            return result

        # 尝试 akshare（降级）
        data = self._fetch_from_akshare()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 港股指数采集成功 (来源: akshare, {len(data)} 项)")
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
            logger.info(f"✅ 港股指数采集成功 (来源: 缓存, {len(data)} 项)")

        if result["total"] == 0:
            logger.warning("⚠️ 所有港股指数数据源均失败")

        return result

    def _fetch_from_yfinance(self) -> List[Dict]:
        """
        使用 yfinance 采集港股指数（主源）
        """
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

    def _fetch_from_akshare(self) -> List[Dict]:
        """
        使用 akshare 采集港股指数（降级源）
        """
        try:
            import akshare as ak

            items = []
            
            # 方法1：stock_hk_spot（港股实时行情）
            try:
                df = ak.stock_hk_spot()
                if df is not None and not df.empty:
                    # 检测列名
                    name_col = None
                    price_col = None
                    change_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'name' in col_lower or '名称' in col:
                            name_col = col
                        if 'price' in col_lower or '现价' in col or '最新价' in col:
                            price_col = col
                        if 'change' in col_lower and 'pct' in col_lower or '涨跌幅' in col:
                            change_col = col
                    
                    if name_col is None:
                        # 尝试找包含中文名的列
                        for col in df.columns:
                            if '名' in col:
                                name_col = col
                                break
                    if price_col is None:
                        for col in df.columns:
                            if '价' in col:
                                price_col = col
                                break

                    if name_col and price_col:
                        for _, row in df.iterrows():
                            name = str(row.get(name_col, '')).strip()
                            # 匹配我们需要的指数
                            matched = None
                            for ak_symbol, ak_name in self.AK_INDICES.items():
                                if ak_name in name or name in ak_name:
                                    matched = (ak_symbol, ak_name)
                                    break
                            if not matched:
                                continue
                            
                            price = float(row.get(price_col, 0))
                            change_pct = 0
                            if change_col:
                                try:
                                    change_pct = float(row.get(change_col, 0))
                                except (ValueError, TypeError):
                                    pass
                            
                            if price > 0:
                                items.append({
                                    "name": matched[1],
                                    "symbol": matched[0],
                                    "price": round(price, 2),
                                    "change_pct": round(change_pct, 2),
                                    "volume": 0,
                                    "date": datetime.now().strftime("%Y-%m-%d"),
                                    "source": "akshare_spot"
                                })
                                logger.info(f"   ✅ {matched[1]}: {price} ({change_pct:+.2f}%) [akshare]")
                        
                        if items:
                            return items
            except Exception as e:
                logger.debug(f"   akshare stock_hk_spot 失败: {e}")

            # 方法2：stock_hk_index_spot（港股指数行情）
            try:
                for symbol, name in self.AK_INDICES.items():
                    try:
                        df = ak.stock_hk_index_spot(symbol=symbol)
                        if df is not None and not df.empty:
                            row = df.iloc[0]
                            price = float(row.get('最新价', 0)) or float(row.get('price', 0)) or float(row.iloc[0] if len(row) > 0 else 0)
                            change_pct = float(row.get('涨跌幅', 0)) or float(row.get('change_pct', 0))
                            if price > 0:
                                items.append({
                                    "name": name,
                                    "symbol": symbol,
                                    "price": round(price, 2),
                                    "change_pct": round(change_pct, 2),
                                    "volume": 0,
                                    "date": datetime.now().strftime("%Y-%m-%d"),
                                    "source": "akshare_index_spot"
                                })
                                logger.info(f"   ✅ {name}: {price} ({change_pct:+.2f}%) [akshare_index]")
                    except Exception as e:
                        logger.debug(f"   {name} stock_hk_index_spot 失败: {e}")
                if items:
                    return items
            except Exception as e:
                logger.debug(f"   akshare stock_hk_index_spot 整体失败: {e}")

            # 方法3：stock_hk_index_daily（港股指数日线）
            try:
                for symbol, name in self.AK_INDICES.items():
                    try:
                        df = ak.stock_hk_index_daily(symbol=symbol)
                        if df is not None and not df.empty:
                            latest = df.iloc[-1]
                            # 检测列名
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
                                    items.append({
                                        "name": name,
                                        "symbol": symbol,
                                        "price": round(price, 2),
                                        "change_pct": 0,
                                        "volume": 0,
                                        "date": datetime.now().strftime("%Y-%m-%d"),
                                        "source": "akshare_daily"
                                    })
                                    logger.info(f"   ✅ {name}: {price} [akshare_daily]")
                    except Exception as e:
                        logger.debug(f"   {name} stock_hk_index_daily 失败: {e}")
                if items:
                    return items
            except Exception as e:
                logger.debug(f"   akshare stock_hk_index_daily 整体失败: {e}")

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 港股采集异常: {e}")
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
    save_json(result, filepath)
    save_json(result, "staging/hk_stock_cache.json")

    logger.info(f"📊 港股指数: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    return result


def main():
    """主函数"""
    logger.info("=" * 60)
    logger.info("🇭🇰 港股指数采集启动")
    logger.info("=" * 60)

    data = collect_hk_stock()

    logger.info("=" * 60)
    logger.info("✅ 港股指数采集完成")
    logger.info(f"   🇭🇰 指数数量: {data['total']}")
    logger.info(f"   📦 数据源: {data.get('source', 'unknown')}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if data.get('signature') else '⚠️ 未签名'}")
    logger.info("=" * 60)

    return 0 if data['total'] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
