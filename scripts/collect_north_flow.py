#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金历史采集模块（a-stock-data 增强版）
直接复用 a-stock-adapter 的 eastmoney_datacenter 逻辑
采集：沪股通、深股通当日净流入
频率：每30分钟
数据源：东方财富数据中心 → 缓存
"""

import sys
import os
import time
import json
import hashlib
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
# ★ 导入 a-stock-data 的 em_get 和 eastmoney_datacenter
# ============================================================
try:
    # 尝试从私密库导入
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '..'))
    from data_adapter.a_stock_adapter import eastmoney_datacenter
    A_STOCK_AVAILABLE = True
    logger.info("✅ a-stock-data 已加载（从私密库适配器）")
except ImportError:
    try:
        from a_stock_adapter import eastmoney_datacenter
        A_STOCK_AVAILABLE = True
        logger.info("✅ a-stock-data 已加载（直接导入）")
    except ImportError:
        # 如果 a-stock-data 不可用，使用简单的 requests 实现
        A_STOCK_AVAILABLE = False
        logger.warning("⚠️ a-stock-data 不可用，将使用 requests 备选")
        try:
            import requests
            HAS_REQUESTS = True
        except ImportError:
            HAS_REQUESTS = False


class NorthFlowCollector:
    """北向资金采集器（a-stock-data 增强版）"""

    def __init__(self):
        self.config = load_config()
        self.session = None
        if not A_STOCK_AVAILABLE and HAS_REQUESTS:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：使用 a-stock-data eastmoney_datacenter
        data = self._fetch_from_eastmoney_direct()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney_direct"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财数据中心, {len(data)} 项)")
            return result

        # 方法2：使用 requests 备选
        data = self._fetch_from_eastmoney_requests()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney_requests"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财Requests, {len(data)} 项)")
            return result

        # 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_from_eastmoney_direct(self) -> List[Dict]:
        """使用 a-stock-data 的 eastmoney_datacenter"""
        if not A_STOCK_AVAILABLE:
            logger.debug("a-stock-data 不可用，跳过")
            return []

        try:
            # 使用 eastmoney_datacenter 查询北向资金
            data = eastmoney_datacenter(
                report_name="RPT_HSGT_DAILY",
                columns="TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
                page_size=3,
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
                    "type": "北向资金",
                    "date": trade_date[:10] if trade_date else datetime.now().strftime("%Y-%m-%d"),
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"eastmoney_datacenter 采集异常: {e}")
            return []

    def _fetch_from_eastmoney_requests(self) -> List[Dict]:
        """使用 requests 直接调用东财API（备选）"""
        if not HAS_REQUESTS or not self.session:
            return []

        try:
            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "reportName": "RPT_HSGT_DAILY",
                "columns": "TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
                "pageNumber": "1",
                "pageSize": "3",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB"
            }

            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                logger.debug(f"东财数据中心返回: {resp.status_code}")
                return []

            data = resp.json()
            result_data = data.get("result", {}).get("data", [])

            if not result_data:
                return []

            items = []
            for row in result_data[:2]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "type": "北向资金",
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
