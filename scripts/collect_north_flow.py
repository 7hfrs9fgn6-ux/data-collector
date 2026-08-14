#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（使用 a-stock-data 库）
从东方财富数据中心获取沪深港通资金流向
频率：每30分钟
数据源：a-stock-data → 缓存
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
# 尝试导入 a-stock-data 库
# ============================================================
try:
    from a_stock_adapter import eastmoney_datacenter
    A_STOCK_AVAILABLE = True
    logger.info("✅ a-stock-data 已加载（通过 a_stock_adapter）")
except ImportError:
    try:
        from a_stock_data import eastmoney_datacenter
        A_STOCK_AVAILABLE = True
        logger.info("✅ a-stock-data 已加载（通过 a_stock_data）")
    except ImportError:
        A_STOCK_AVAILABLE = False
        logger.warning("⚠️ a-stock-data 不可用，将使用 requests 备选")


class NorthFlowCollector:
    """北向资金采集器（a-stock-data）"""

    def __init__(self):
        self.config = load_config()
        self.session = None
        if not A_STOCK_AVAILABLE:
            try:
                import requests
                self.session = requests.Session()
                self.session.headers.update({
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Referer": "https://data.eastmoney.com/",
                    "Accept": "application/json"
                })
                HAS_REQUESTS = True
            except ImportError:
                HAS_REQUESTS = False

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：使用 a-stock-data（优先）
        if A_STOCK_AVAILABLE:
            data = self._fetch_from_a_stock()
            if data:
                result["items"] = data
                result["total"] = len(data)
                result["source"] = "a-stock-data"
                logger.info(f"✅ 北向资金采集成功 (来源: a-stock-data, {len(data)} 项)")
                return result

        # 方法2：requests 备选
        data = self._fetch_from_requests()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "requests"
            logger.info(f"✅ 北向资金采集成功 (来源: requests, {len(data)} 项)")
            return result

        # 方法3：从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_from_a_stock(self) -> List[Dict]:
        """使用 a-stock-data 的 eastmoney_datacenter"""
        if not A_STOCK_AVAILABLE:
            return []

        try:
            # 使用 eastmoney_datacenter 查询北向资金
            data = eastmoney_datacenter(
                report_name="RPT_HSGT_DAILY",
                columns="TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
                page_size=2,
                sort_columns="TRADE_DATE",
                sort_types="-1"
            )

            if not data:
                logger.debug("东财数据中心返回空")
                return []

            items = []
            for row in data[:2]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "date": trade_date[:10] if trade_date else datetime.now().strftime("%Y-%m-%d"),
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"a-stock-data 采集异常: {e}")
            return []

    def _fetch_from_requests(self) -> List[Dict]:
        """requests 备选（当 a-stock-data 不可用时）"""
        if not hasattr(self, 'session') or self.session is None:
            return []

        try:
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "reportName": "RPT_HSGT_DAILY",
                "columns": "TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
                "pageNumber": "1",
                "pageSize": "2",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB"
            }

            resp = self.session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                logger.debug(f"东财数据中心 HTTP {resp.status_code}")
                return []

            data = resp.json()
            if data.get("code") != 0:
                return []

            rows = data.get("result", {}).get("data", [])
            if not rows:
                return []

            items = []
            for row in rows[:2]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "date": trade_date[:10] if trade_date else datetime.now().strftime("%Y-%m-%d"),
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"requests 东财采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_north_flow() -> Dict[str, Any]:
    collector = NorthFlowCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/north_flow_{timestamp}.json"
    save_json(result, filepath)

    if result["total"] > 0:
        save_json(result, "staging/north_flow_cache.json")

    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
