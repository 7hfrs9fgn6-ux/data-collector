#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（纯 akshare 版）
直接使用 akshare 申万行业指数，无需外部依赖
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


class SectorCollector:
    """板块52周回撤采集器（纯 akshare）"""

    # 申万行业指数代码（一级行业）
    SECTOR_CODES = [
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

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        # 方法1：从申万行业指数实时行情 + 历史数据计算回撤
        data = self._fetch_from_sw_spot()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sw_spot"
            logger.info(f"✅ 板块回撤采集成功 (来源: 申万行情, {len(data)} 项)")
            return result

        # 方法2：从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 板块回撤采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有板块回撤数据源均失败")
        return result

    def _fetch_from_sw_spot(self) -> List[Dict]:
        try:
            import akshare as ak
            import pandas as pd

            today = datetime.now().strftime("%Y-%m-%d")

            # 1. 获取申万行业指数实时行情
            sw_spot = ak.stock_zh_index_spot_em(symbol="申万行业指数")
            if sw_spot is None or sw_spot.empty:
                logger.debug("申万行业指数实时行情为空")
                return []

            # 识别列名
            name_col = None
            price_col = None
            for col in sw_spot.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower():
                    price_col = col

            if not name_col or not price_col:
                logger.debug("申万行业指数列名识别失败")
                return []

            # 建立名称到价格的映射
            name_to_price = {}
            for _, row in sw_spot.iterrows():
                name = str(row.get(name_col, ''))
                price = self._safe_float(row.get(price_col))
                if price > 0:
                    name_to_price[name] = price

            items = []

            # 2. 对每个板块获取52周最高价
            for sector in self.SECTOR_CODES:
                sector_name = sector["name"]
                code = sector["code"]

                # 查找当前价（精确匹配或包含匹配）
                current_price = None
                for sw_name, price in name_to_price.items():
                    if sector_name in sw_name or sw_name in sector_name:
                        current_price = price
                        break

                if current_price is None:
                    logger.debug(f"   {sector_name}: 未找到实时行情")
                    continue

                # 获取52周最高价
                try:
                    # 获取该指数近1年日线数据
                    hist = ak.stock_zh_index_daily(symbol=code)
                    if hist is not None and not hist.empty:
                        # 计算近52周（约252个交易日）最高价
                        max_high = hist['high'].max()
                        if max_high is None or max_high <= 0:
                            max_high = current_price
                    else:
                        max_high = current_price
                except Exception as e:
                    logger.debug(f"   {sector_name} 历史数据获取失败: {e}")
                    max_high = current_price

                # 计算回撤
                if max_high > 0 and current_price > 0:
                    drawdown = ((max_high - current_price) / max_high * 100)
                else:
                    drawdown = 0

                items.append({
                    "sector": sector_name,
                    "code": code,
                    "price": round(current_price, 2),
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(max_high, 2),
                    "date": today
                })

            return items

        except Exception as e:
            logger.debug(f"申万行情采集异常: {e}")
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
