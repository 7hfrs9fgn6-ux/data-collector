#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金历史采集模块（网页爬虫版）
从东方财富网页抓取北向资金数据
频率：每30分钟
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
    """北向资金采集器（网页爬虫版）"""

    def __init__(self):
        self.config = load_config()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://data.eastmoney.com/"
        })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：东方财富数据中心API（JSON接口）
        data = self._fetch_from_eastmoney_api()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney_api"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财API, {len(data)} 项)")
            return result

        # 方法2：新浪财经接口
        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"✅ 北向资金采集成功 (来源: 新浪, {len(data)} 项)")
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

    def _fetch_from_eastmoney_api(self) -> List[Dict]:
        """
        使用东方财富数据中心API
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
            resp = self.session.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                logger.debug(f"东财API返回: {resp.status_code}")
                return []

            data = resp.json()
            result_data = data.get("result", {}).get("data", [])
            if not result_data:
                logger.debug("东财API返回空数据")
                return []

            items = []
            for row in result_data[:3]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)
                if hgt == 0 and sgt == 0:
                    continue
                items.append({
                    "date": trade_date[:10] if trade_date else "",
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })
            return items

        except Exception as e:
            logger.debug(f"东财API采集异常: {e}")
            return []

    def _fetch_from_sina(self) -> List[Dict]:
        """
        从新浪财经获取北向资金
        """
        try:
            # 新浪北向资金接口
            url = "https://hq.sinajs.cn/list=hgt,sgt"
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                return []

            content = resp.text
            if not content:
                return []

            items = []
            # 解析沪股通和深股通
            for line in content.strip().split('\n'):
                if 'hgt' in line.lower() or 'sgt' in line.lower():
                    # 格式：var hq_str_hgt="..."
                    if '=' not in line or '"' not in line:
                        continue
                    parts = line.split('"')
                    if len(parts) < 2:
                        continue
                    data_str = parts[1]
                    fields = data_str.split('~')
                    if len(fields) < 5:
                        continue
                    # 字段：0:名称, 1:时间, 2:当前值, 3:涨跌, 4:涨跌幅
                    name = fields[0]
                    value = self._safe_float(fields[2])
                    if '沪股通' in name or 'hgt' in name.lower():
                        # 需要区分沪股通和深股通
                        pass

            # 如果失败，回退到缓存
            return []

        except Exception as e:
            logger.debug(f"新浪北向采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
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
    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
