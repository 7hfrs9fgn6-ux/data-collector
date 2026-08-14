#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（修复版）
采集：A股15个核心板块的52周回撤历史
频率：每小时
数据源：akshare (stock_zh_index_spot_em) → 缓存
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
    """板块52周回撤采集器（修复版）"""

    # V系统15个核心板块名称（用于匹配申万行业指数）
    SECTOR_NAMES = [
        "电子", "计算机", "通信", "传媒", "医药生物",
        "食品饮料", "家用电器", "电力设备", "汽车", "国防军工",
        "银行", "非银金融", "公用事业", "煤炭", "石油石化"
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

        # 尝试 akshare（使用 stock_zh_index_spot_em 获取行业板块行情）
        data = self._fetch_from_akshare_spot()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare_spot"
            logger.info(f"✅ 板块回撤采集成功 (来源: akshare_spot, {len(data)} 项)")
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

    def _fetch_from_akshare_spot(self) -> List[Dict]:
        """通过 stock_zh_index_spot_em 获取行业板块行情并计算回撤"""
        try:
            import akshare as ak

            # 获取所有行业板块行情（包含52周最高/最低）
            df = ak.stock_zh_index_spot_em(symbol="行业板块")
            if df is None or df.empty:
                logger.debug("行业板块行情获取失败")
                return []

            items = []
            today = datetime.now().strftime("%Y-%m-%d")

            for sector_name in self.SECTOR_NAMES:
                # 在数据中查找匹配的行
                matched = df[df['名称'].str.contains(sector_name, na=False)]
                if matched.empty:
                    logger.debug(f"未找到板块: {sector_name}")
                    continue

                row = matched.iloc[0]
                current_price = float(row.get('最新价', 0))
                high_52w = float(row.get('52周最高', 0))
                low_52w = float(row.get('52周最低', 0))

                if high_52w <= 0 or current_price <= 0:
                    continue

                drawdown = ((high_52w - current_price) / high_52w * 100) if high_52w > 0 else 0

                items.append({
                    "sector": sector_name,
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(high_52w, 2),
                    "low_52w": round(low_52w, 2),
                    "current_price": round(current_price, 2),
                    "date": today
                })

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 板块回撤采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_sector() -> Dict[str, Any]:
    collector = SectorCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/sector_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/sector_cache.json")

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
