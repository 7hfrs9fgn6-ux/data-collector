#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块
采集：A股15个核心板块的52周回撤历史
频率：每小时
数据源：akshare → 东方财富爬虫 → 缓存
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
    """板块52周回撤采集器"""

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

        # 尝试 akshare
        data = self._fetch_from_akshare()
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

    def _fetch_from_akshare(self) -> List[Dict]:
        try:
            import akshare as ak

            items = []
            # 获取申万行业指数
            df = ak.stock_zh_index_spot_em(symbol="申万行业指数")

            if df is None or df.empty:
                logger.debug("申万行业指数获取失败")
                return []

            # 获取52周最高价和当前价
            today = datetime.now().strftime("%Y-%m-%d")

            for sector in self.SECTORS:
                try:
                    # 获取该板块近一年的数据
                    code = sector["code"]
                    # 使用申万指数代码获取历史数据
                    # 注意：申万指数代码可能为6位，需要适配
                    index_code = code
                    if not index_code.startswith("8"):
                        # 申万指数通常以8开头
                        pass

                    sector_df = ak.stock_zh_index_daily(symbol=index_code)
                    if sector_df is None or sector_df.empty:
                        continue

                    # 计算52周最高价
                    high_52w = sector_df['high'].max()
                    # 当前价
                    latest = sector_df.iloc[-1]
                    current_price = latest['close']

                    # 计算回撤
                    drawdown = ((high_52w - current_price) / high_52w * 100) if high_52w > 0 else 0

                    items.append({
                        "sector": sector["name"],
                        "code": code,
                        "drawdown": round(drawdown, 2),
                        "high_52w": round(high_52w, 2),
                        "current_price": round(current_price, 2),
                        "date": today
                    })
                except Exception as e:
                    logger.debug(f"   {sector['name']} 回撤计算失败: {e}")
                    continue

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
