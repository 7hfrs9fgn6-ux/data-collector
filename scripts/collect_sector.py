#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（baostock 版）
使用 baostock 免费量化数据源，无需API Key，无需登录
采集：A股15个核心板块的52周回撤历史
频率：每小时
数据源：baostock → 缓存
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
# 尝试导入 baostock
# ============================================================
try:
    import baostock as bs
    BAOSTOCK_AVAILABLE = True
    logger.info("✅ baostock 已加载")
except ImportError:
    BAOSTOCK_AVAILABLE = False
    logger.warning("⚠️ baostock 未安装，将使用缓存或备选")


class SectorCollector:
    """板块52周回撤采集器（baostock）"""

    # 申万一级行业代码（baostock 使用）
    # 注意：baostock 行业代码格式为 "sw" + 行业代码
    SECTOR_CODES = [
        {"name": "电子", "code": "sw801080"},
        {"name": "计算机", "code": "sw801750"},
        {"name": "通信", "code": "sw801770"},
        {"name": "传媒", "code": "sw801760"},
        {"name": "医药生物", "code": "sw801150"},
        {"name": "食品饮料", "code": "sw801120"},
        {"name": "家用电器", "code": "sw801110"},
        {"name": "电力设备", "code": "sw801730"},
        {"name": "汽车", "code": "sw801880"},
        {"name": "国防军工", "code": "sw801740"},
        {"name": "银行", "code": "sw801780"},
        {"name": "非银金融", "code": "sw801790"},
        {"name": "公用事业", "code": "sw801160"},
        {"name": "煤炭", "code": "sw801950"},
        {"name": "石油石化", "code": "sw801960"},
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

        # 方法1：使用 baostock
        data = self._fetch_from_baostock()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "baostock"
            logger.info(f"✅ 板块回撤采集成功 (来源: baostock, {len(data)} 项)")
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

    def _fetch_from_baostock(self) -> List[Dict]:
        if not BAOSTOCK_AVAILABLE:
            return []

        try:
            # 登录 baostock（实际上无需登录，但 API 要求调用 login）
            lg = bs.login()
            if lg.error_code != '0':
                logger.debug(f"baostock 登录失败: {lg.error_msg}")
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 计算回撤起始日期（近250个交易日 ≈ 1年）
            end_date = datetime.now().strftime("%Y-%m-%d")
            start_date = (datetime.now() - timedelta(days=400)).strftime("%Y-%m-%d")

            for sector in self.SECTOR_CODES:
                sector_name = sector["name"]
                code = sector["code"]

                try:
                    # 获取该行业指数日线数据
                    rs = bs.query_history_k_data_plus(
                        code,
                        "date,close,high,low",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2"  # 不复权
                    )

                    if rs.error_code != '0':
                        logger.debug(f"   {sector_name} 历史数据查询失败: {rs.error_msg}")
                        continue

                    # 收集数据
                    data_list = []
                    while (rs.error_code == '0') and rs.next():
                        row = rs.get_row_data()
                        data_list.append({
                            "date": row[0],
                            "close": float(row[1]),
                            "high": float(row[2]),
                            "low": float(row[3]),
                        })

                    if not data_list:
                        logger.debug(f"   {sector_name}: 无历史数据")
                        continue

                    # 当前最新价（最后一条的收盘价）
                    current_price = data_list[-1]["close"]
                    # 52周最高价（近250个交易日最高）
                    max_high = max([d["high"] for d in data_list])

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

                except Exception as e:
                    logger.debug(f"   {sector_name} 采集异常: {e}")
                    continue

            # 登出
            bs.logout()

            return items

        except Exception as e:
            logger.debug(f"baostock 采集异常: {e}")
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

    if result["total"] > 0:
        save_json(result, "staging/sector_cache.json")

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
