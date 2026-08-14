#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（akshare 申万行业指数版）
直接使用 akshare 获取申万行业指数的 52周最高/最低价
无需 baostock，无需额外依赖
频率：每小时
数据源：akshare（申万行业指数）→ 缓存
"""

import sys
import os
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
    """板块52周回撤采集器（akshare 申万行业指数）"""

    # 申万一级行业名称列表
    SECTOR_NAMES = [
        "电子", "计算机", "通信", "传媒", "医药生物",
        "食品饮料", "家用电器", "电力设备", "汽车", "国防军工",
        "银行", "非银金融", "公用事业", "煤炭", "石油石化"
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

        # 方法1：从 akshare 申万行业指数获取
        data = self._fetch_from_sw_index()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sw_index"
            logger.info(f"✅ 板块回撤采集成功 (来源: 申万行业指数, {len(data)} 项)")
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

    def _fetch_from_sw_index(self) -> List[Dict]:
        try:
            import akshare as ak
            import pandas as pd

            today = datetime.now().strftime("%Y-%m-%d")

            # 获取申万行业指数（包含52周最高/最低）
            df = ak.stock_zh_index_spot_em(symbol="申万行业指数")

            if df is None or df.empty:
                logger.debug("申万行业指数数据为空")
                return []

            logger.debug(f"申万行业指数列名: {list(df.columns)}")

            # 列名识别
            name_col = None
            price_col = None
            high_col = None
            low_col = None

            for col in df.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower():
                    price_col = col
                if '最高' in col or 'high' in col.lower() or '52周最高' in col:
                    high_col = col
                if '最低' in col or 'low' in col.lower() or '52周最低' in col:
                    low_col = col

            if not name_col or not price_col:
                logger.debug("列名识别失败")
                return []

            # 查找52周最高/最低列的备选名称
            if not high_col:
                for col in df.columns:
                    if '52周' in col and ('最高' in col or '高' in col):
                        high_col = col
                        break
            if not low_col:
                for col in df.columns:
                    if '52周' in col and ('最低' in col or '低' in col):
                        low_col = col
                        break

            items = []

            for sector_name in self.SECTOR_NAMES:
                matched = None
                for _, row in df.iterrows():
                    name = str(row.get(name_col, ''))
                    # 申万行业指数名称格式如 "电子(申万)" 或 "电子"
                    if sector_name in name and ('申万' in name or 'sw' in name.lower()):
                        matched = row
                        break

                if matched is None:
                    # 更宽泛匹配
                    for _, row in df.iterrows():
                        name = str(row.get(name_col, ''))
                        if sector_name in name:
                            matched = row
                            break

                if matched is None:
                    logger.debug(f"未匹配到板块: {sector_name}")
                    continue

                current_price = self._safe_float(matched.get(price_col))
                if current_price <= 0:
                    continue

                # 获取52周最高价
                high_52w = current_price
                if high_col:
                    high_52w = self._safe_float(matched.get(high_col))
                if high_52w <= 0:
                    high_52w = current_price

                # 获取52周最低价（仅用于记录）
                low_52w = current_price
                if low_col:
                    low_52w = self._safe_float(matched.get(low_col))

                # 计算回撤
                if high_52w > 0 and current_price > 0:
                    drawdown = ((high_52w - current_price) / high_52w * 100)
                else:
                    drawdown = 0

                items.append({
                    "sector": sector_name,
                    "price": round(current_price, 2),
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(high_52w, 2),
                    "low_52w": round(low_52w, 2),
                    "date": today
                })

            return items

        except Exception as e:
            logger.debug(f"申万行业指数采集异常: {e}")
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
