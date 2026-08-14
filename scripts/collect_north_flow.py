#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（新浪财经稳定版）
使用新浪财经 API 获取沪深港通资金流向
频率：每30分钟
数据源：新浪财经 → 缓存
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

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NorthFlowCollector:
    """北向资金采集器（新浪财经稳定版）"""

    def __init__(self):
        self.config = load_config()
        self.session = None
        if HAS_REQUESTS:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://finance.sina.com.cn/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive"
            })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：新浪财经（首选）
        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"✅ 北向资金采集成功 (来源: 新浪财经, {len(data)} 项)")
            return result

        # 方法2：东财API（备选）
        data = self._fetch_from_eastmoney()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财, {len(data)} 项)")
            return result

        # 方法3：akshare（备选）
        data = self._fetch_from_akshare()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 北向资金采集成功 (来源: akshare, {len(data)} 项)")
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

    def _fetch_from_sina(self) -> List[Dict]:
        """新浪财经北向资金接口"""
        if not HAS_REQUESTS or not self.session:
            return []

        try:
            # 新浪北向资金 API
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/GlobalService.getHSG"
            params = {
                "page": "1",
                "num": "5"
            }

            resp = self.session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                logger.debug(f"新浪北向 HTTP {resp.status_code}")
                return []

            data = resp.json()
            if not data:
                logger.debug("新浪北向返回空")
                return []

            items = []
            today = datetime.now().strftime("%Y-%m-%d")

            for row in data[:3]:
                date = row.get('date', today)
                # 新浪返回的数据字段
                hgt = row.get('hgt', 0)      # 沪股通
                sgt = row.get('sgt', 0)      # 深股通

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "date": date,
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt) + float(sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"新浪北向采集异常: {e}")
            return []

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """东方财富数据中心（备选）"""
        if not HAS_REQUESTS or not self.session:
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
                logger.debug(f"东财北向 HTTP {resp.status_code}")
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
            logger.debug(f"东财北向采集异常: {e}")
            return []

    def _fetch_from_akshare(self) -> List[Dict]:
        """akshare 备选"""
        try:
            import akshare as ak

            df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
            if df is not None and not df.empty:
                recent = df.tail(2)
                items = []
                for _, row in recent.iterrows():
                    value = row.get('value', 0) / 10000
                    if value == 0:
                        continue
                    items.append({
                        "date": row.get('date', datetime.now().strftime("%Y-%m-%d")),
                        "合计": round(float(value), 2)
                    })
                return items
            return []

        except ImportError:
            return []
        except Exception as e:
            logger.debug(f"akshare 北向采集异常: {e}")
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
