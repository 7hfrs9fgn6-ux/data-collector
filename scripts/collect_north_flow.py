#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金采集模块（三源轮询版）
使用三个数据源轮询，确保采集成功率
频率：每30分钟
数据源：东财数据中心 → 新浪财经 → 缓存
"""

import sys
import os
import re
import json
import requests
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


class NorthFlowCollector:
    """北向资金采集器（三源轮询版）"""

    def __init__(self):
        self.config = load_config()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 数据源1：东方财富数据中心 API
        logger.info("   🔍 尝试东财数据中心 API...")
        data = self._fetch_from_eastmoney()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney"
            logger.info(f"   ✅ 北向资金采集成功 (来源: 东财, {len(data)} 项)")
            return result

        # 数据源2：新浪财经
        logger.info("   🔍 尝试新浪财经数据源...")
        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"   ✅ 北向资金采集成功 (来源: 新浪, {len(data)} 项)")
            return result

        # 数据源3：从缓存加载
        logger.info("   📂 尝试从缓存加载...")
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"   ✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """
        东方财富数据中心 API
        使用 RPT_HSGT_DAILY 报表
        """
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
            headers = {
                "Referer": "https://data.eastmoney.com/",
                "Host": "datacenter-web.eastmoney.com",
                "Origin": "https://data.eastmoney.com"
            }
            resp = self.session.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                logger.debug(f"   东财API返回: {resp.status_code}")
                return []

            data = resp.json()
            result_data = data.get("result", {}).get("data", [])
            if not result_data:
                logger.debug("   东财API返回空数据")
                return []

            items = []
            for row in result_data[:3]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)
                if abs(hgt) > 500 or abs(sgt) > 500:
                    continue
                if hgt == 0 and sgt == 0:
                    continue
                items.append({
                    "date": trade_date[:10] if trade_date else "",
                    "hgt": round(float(hgt), 2),
                    "sgt": round(float(sgt), 2),
                    "total": round(float(hgt + sgt), 2)
                })
            return items

        except Exception as e:
            logger.debug(f"   东财API采集异常: {e}")
            return []

    def _fetch_from_sina(self) -> List[Dict]:
        """
        新浪财经北向资金接口
        """
        try:
            # 新浪北向资金接口
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getBkInfo"
            params = {
                "page": "1",
                "num": "20",
                "sort": "change",
                "asc": "0",
                "node": "hsgt"
            }
            headers = {
                "Referer": "https://finance.sina.com.cn/",
                "Host": "vip.stock.finance.sina.com.cn"
            }
            resp = self.session.get(url, params=params, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []

            # 新浪返回的是JSON数组
            data = resp.json()
            if not data:
                return []

            items = []
            for item in data[:3]:
                name = item.get("name", "")
                if "北向" in name or "沪深港通" in name:
                    items.append({
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "name": name,
                        "value": round(float(item.get("price", 0)), 2),
                        "change": round(float(item.get("change", 0)), 2)
                    })

            # 如果没找到北向数据，尝试另一个接口
            if not items:
                return self._fetch_from_sina_alt()

            return items

        except Exception as e:
            logger.debug(f"   新浪采集异常: {e}")
            return []

    def _fetch_from_sina_alt(self) -> List[Dict]:
        """
        新浪财经北向资金备选接口
        """
        try:
            url = "https://hq.sinajs.cn/list=hgt,sgt"
            headers = {
                "Referer": "https://finance.sina.com.cn/",
                "Host": "hq.sinajs.cn"
            }
            resp = self.session.get(url, headers=headers, timeout=10)
            if resp.status_code != 200:
                return []

            content = resp.text
            if not content:
                return []

            items = []
            today = datetime.now().strftime("%Y-%m-%d")

            for line in content.strip().split('\n'):
                if 'hgt' not in line.lower() and 'sgt' not in line.lower():
                    continue
                if '=' not in line or '"' not in line:
                    continue
                parts = line.split('"')
                if len(parts) < 2:
                    continue
                data_str = parts[1]
                fields = data_str.split('~')
                if len(fields) < 5:
                    continue
                name = fields[0]
                value = self._safe_float(fields[2])
                if "沪股通" in name:
                    items.append({
                        "date": today,
                        "type": "沪股通",
                        "value": round(value / 10000, 2) if value > 1000 else round(value, 2)
                    })
                elif "深股通" in name:
                    items.append({
                        "date": today,
                        "type": "深股通",
                        "value": round(value / 10000, 2) if value > 1000 else round(value, 2)
                    })

            return items

        except Exception as e:
            logger.debug(f"   新浪备选采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            cache_items = data.get('items', [])
            if cache_items:
                logger.info(f"   📂 加载缓存: {len(cache_items)} 项")
            return cache_items
        return []

    def _safe_float(self, value) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0


def collect_north_flow() -> Dict[str, Any]:
    collector = NorthFlowCollector()
    result = collector.collect()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/north_flow_{timestamp}.json"
    save_json(result, filepath)
    
    if result["total"] > 0:
        save_json(result, "staging/north_flow_cache.json")
        logger.info(f"✅ 北向缓存已更新: {result['total']} 项")
    else:
        logger.warning("⚠️ 北向采集失败，缓存保持不变")

    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
