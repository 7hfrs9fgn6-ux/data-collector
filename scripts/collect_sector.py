#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（a-stock-data 增强版）
使用 a-stock-data 的免费能力 + akshare 历史数据
采集：A股15个核心板块的52周回撤历史
频率：每小时
数据源：a-stock-data + akshare → 缓存
"""

import sys
import os
import time
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

# ============================================================
# ★ 动态导入 a-stock-data（如果可用）
# ============================================================
try:
    # 尝试从 data_adapter 导入（如果在私密库环境中）
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
    from data_adapter.a_stock_adapter import tencent_quote
    A_STOCK_AVAILABLE = True
    logger.info("✅ a-stock-data 已加载（从私密库适配器）")
except ImportError:
    try:
        # 尝试直接导入 a-stock-data
        from a_stock_adapter import tencent_quote
        A_STOCK_AVAILABLE = True
        logger.info("✅ a-stock-data 已加载（直接导入）")
    except ImportError:
        A_STOCK_AVAILABLE = False
        logger.warning("⚠️ a-stock-data 不可用，将使用 akshare 备选")


class SectorCollector:
    """板块52周回撤采集器（a-stock-data 增强版）"""

    # V系统15个核心板块及对应的申万指数代码
    SECTORS = [
        {"name": "电子", "code": "801080"},
        {"name": "计算机", "code": "801750"},
        {"name": "通信", "code": "801770"},
        {"name": "传媒", "code": "801760"},
        {"name": "医药生物", "code": "801150"},
        {"name": "食品饮料", "code": "801120"},
        {"name": "家用电器", "code": "801110"},
        {"name": "电力设备", "code": "801730"},
        {"name": "汽车", "code": "801880"},
        {"name": "国防军工", "code": "801740"},
        {"name": "银行", "code": "801780"},
        {"name": "非银金融", "code": "801790"},
        {"name": "公用事业", "code": "801160"},
        {"name": "煤炭", "code": "801950"},
        {"name": "石油石化", "code": "801960"},
    ]

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        # 方法1：使用 a-stock-data + akshare（最精确）
        data = self._fetch_with_a_stock()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "a-stock-data"
            logger.info(f"✅ 板块回撤采集成功 (来源: a-stock-data, {len(data)} 项)")
            return result

        # 方法2：纯 akshare（备选）
        data = self._fetch_from_akshare_sw()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 板块回撤采集成功 (来源: akshare, {len(data)} 项)")
            return result

        # 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 板块回撤采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有板块回撤数据源均失败")
        return result

    def _fetch_with_a_stock(self) -> List[Dict]:
        """使用 a-stock-data 获取板块数据"""
        if not A_STOCK_AVAILABLE:
            logger.debug("a-stock-data 不可用，跳过")
            return []

        try:
            import akshare as ak
            import pandas as pd

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 1. 从 a-stock-data 获取板块当前价
            # 构建板块对应的股票代码（使用板块权重股代替）
            sector_stock_map = {
                "电子": "002475",    # 立讯精密
                "计算机": "000977",  # 浪潮信息
                "通信": "600050",    # 中国联通
                "传媒": "300058",    # 蓝色光标
                "医药生物": "600196", # 复星医药
                "食品饮料": "600519", # 贵州茅台
                "家用电器": "000333", # 美的集团
                "电力设备": "300750", # 宁德时代
                "汽车": "002594",    # 比亚迪
                "国防军工": "600150", # 中国船舶
                "银行": "600036",    # 招商银行
                "非银金融": "600030", # 中信证券
                "公用事业": "600900", # 长江电力
                "煤炭": "601088",    # 中国神华
                "石油石化": "600028", # 中国石化
            }

            # 批量获取股票实时行情
            stock_codes = list(sector_stock_map.values())
            quotes = tencent_quote(stock_codes)

            if not quotes:
                logger.debug("a-stock-data tencent_quote 返回空")
                return []

            # 2. 获取申万行业指数的52周最高价
            # 使用 akshare 获取申万行业指数历史数据
            sw_index_df = ak.stock_zh_index_spot_em(symbol="申万行业指数")
            if sw_index_df is None or sw_index_df.empty:
                logger.debug("申万行业指数获取失败")
                return []

            # 创建名称到价格的映射
            sw_prices = {}
            name_col = None
            price_col = None
            for col in sw_index_df.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower():
                    price_col = col

            if name_col and price_col:
                for _, row in sw_index_df.iterrows():
                    name = str(row.get(name_col, ''))
                    price = self._safe_float(row.get(price_col))
                    sw_prices[name] = price

            # 3. 计算每个板块的回撤
            for sector in self.SECTORS:
                sector_name = sector["name"]
                stock_code = sector_stock_map.get(sector_name)

                # 获取当前价（优先从 a-stock-data）
                current_price = 0
                if stock_code and stock_code in quotes:
                    current_price = quotes[stock_code].get('price', 0)

                # 如果 a-stock-data 没有，尝试从申万行业指数获取
                if current_price <= 0:
                    # 在申万行业指数中查找
                    for sw_name, sw_price in sw_prices.items():
                        if sector_name in sw_name:
                            current_price = sw_price
                            break

                if current_price <= 0:
                    logger.debug(f"   {sector_name}: 无法获取当前价")
                    continue

                # 获取52周最高价（从历史数据）
                high_52w = current_price
                try:
                    # 获取该板块近一年历史数据
                    sw_code = sector["code"]
                    hist_df = ak.stock_zh_index_daily(symbol=sw_code)
                    if hist_df is not None and not hist_df.empty:
                        high_52w = hist_df['high'].max()
                        if high_52w is None or high_52w <= 0:
                            high_52w = current_price
                except Exception as e:
                    logger.debug(f"   {sector_name} 历史数据获取失败: {e}")

                # 计算回撤
                if high_52w > 0 and current_price > 0:
                    drawdown = ((high_52w - current_price) / high_52w * 100)
                else:
                    drawdown = 0

                items.append({
                    "sector": sector_name,
                    "code": sector["code"],
                    "price": round(current_price, 2),
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(high_52w, 2),
                    "date": today
                })

            return items

        except ImportError as e:
            logger.debug(f"a-stock-data 导入失败: {e}")
            return []
        except Exception as e:
            logger.debug(f"a-stock-data 采集异常: {e}")
            return []

    def _fetch_from_akshare_sw(self) -> List[Dict]:
        """备选方法：从 akshare 获取"""
        try:
            import akshare as ak

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 获取申万行业指数
            df = ak.stock_zh_index_spot_em(symbol="申万行业指数")
            if df is None or df.empty:
                return []

            # 列名识别
            name_col = None
            price_col = None
            for col in df.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower():
                    price_col = col

            if not name_col or not price_col:
                return []

            for sector in self.SECTORS:
                sector_name = sector["name"]
                matched = None

                for _, row in df.iterrows():
                    name = str(row.get(name_col, ''))
                    if sector_name in name:
                        matched = row
                        break

                if matched is None:
                    continue

                price = self._safe_float(matched.get(price_col))
                if price <= 0:
                    continue

                # 获取52周最高价
                high_52w = price
                try:
                    sw_code = sector["code"]
                    hist_df = ak.stock_zh_index_daily(symbol=sw_code)
                    if hist_df is not None and not hist_df.empty:
                        high_52w = hist_df['high'].max()
                        if high_52w is None or high_52w <= 0:
                            high_52w = price
                except:
                    pass

                drawdown = ((high_52w - price) / high_52w * 100) if high_52w > 0 else 0

                items.append({
                    "sector": sector_name,
                    "code": sector["code"],
                    "price": round(price, 2),
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(high_52w, 2),
                    "date": today
                })

            return items

        except Exception as e:
            logger.debug(f"akshare 申万采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []

    def _safe_float(self, value) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0


def collect_sector() -> Dict[str, Any]:
    collector = SectorCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/sector_{timestamp}.json"
    save_json(result, filepath)

    if result["total"] > 0:
        save_json(result, "staging/sector_cache.json")

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
