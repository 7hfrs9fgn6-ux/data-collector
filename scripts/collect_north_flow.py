#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（纯提取私密库函数）
直接从东方财富数据中心获取北向资金，无需 akshare 中间层
频率：每30分钟
数据源：东方财富数据中心 → 缓存
"""

import sys
import os
import json
import time
import random
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================
# ★ 从私密库 a_stock_adapter.py 提取的核心函数 ★
# ============================================================

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
DATACENTER_URL = "https://datacenter-web.eastmoney.com/api/data/v1/get"

# 东财防封：全局节流 + 会话复用
EM_SESSION = None
if HAS_REQUESTS:
    EM_SESSION = requests.Session()
    EM_SESSION.headers.update({"User-Agent": UA})
    try:
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        _em_adapter = HTTPAdapter(max_retries=Retry(
            total=2, connect=2, backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504], allowed_methods=["GET"]))
        EM_SESSION.mount("https://", _em_adapter)
        EM_SESSION.mount("http://", _em_adapter)
    except Exception:
        pass

EM_MIN_INTERVAL = 1.0
_em_last_call = [0.0]


def _safe_float(value, default=0.0):
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def em_get(url: str, params: dict = None, headers: dict = None,
           timeout: int = 15, **kwargs) -> Optional[requests.Response]:
    """东财统一请求入口：自动节流 + 复用session + 默认UA"""
    if not HAS_REQUESTS or EM_SESSION is None:
        return None
    wait = EM_MIN_INTERVAL - (time.time() - _em_last_call[0])
    if wait > 0:
        time.sleep(wait + random.uniform(0.1, 0.5))
    if headers is None:
        headers = {}
    headers.setdefault("User-Agent", UA)
    try:
        resp = EM_SESSION.get(url, params=params, headers=headers, timeout=timeout, **kwargs)
        return resp
    finally:
        _em_last_call[0] = time.time()


def eastmoney_datacenter(report_name: str, columns: str = "ALL",
                         filter_str: str = "", page_size: int = 50,
                         sort_columns: str = "", sort_types: str = "-1") -> list:
    """东财数据中心统一查询"""
    if not HAS_REQUESTS:
        return []
    params = {
        "reportName": report_name, "columns": columns,
        "filter": filter_str, "pageNumber": "1", "pageSize": str(page_size),
        "sortColumns": sort_columns, "sortTypes": sort_types,
        "source": "WEB", "client": "WEB",
    }
    try:
        r = em_get(DATACENTER_URL, params=params, timeout=15)
        if r is None:
            return []
        d = r.json()
        if d.get("result") and d["result"].get("data"):
            return d["result"]["data"]
    except Exception as e:
        logger.debug(f"东财数据中心查询失败 ({report_name}): {e}")
    return []


def eastmoney_north_flow_direct() -> Optional[Dict[str, float]]:
    """通过东方财富数据中心API获取北向资金当日净流入"""
    try:
        data = eastmoney_datacenter(
            report_name="RPT_HSGT_DAILY",
            columns="TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
            page_size=2,
            sort_columns="TRADE_DATE",
            sort_types="-1"
        )
        if data and len(data) > 0:
            latest = data[0]
            hgt = _safe_float(latest.get("HGT_NET_INFLOW", 0))
            sgt = _safe_float(latest.get("SGT_NET_INFLOW", 0))
            date = str(latest.get("TRADE_DATE", ""))[:10]
            if hgt != 0 or sgt != 0:
                return {"hgt": hgt, "sgt": sgt, "net": hgt + sgt, "date": date}
    except Exception as e:
        logger.debug(f"东财北向API失败: {e}")
    return None


# ============================================================
# 采集器主类
# ============================================================

class NorthFlowCollector:
    def __init__(self):
        self.config = load_config()
        self.today = datetime.now().strftime("%Y-%m-%d")

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 1. 直接使用私密库提取的函数
        data = self._fetch_private_style()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney_direct"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财数据中心, {len(data)} 项)")
            return result

        # 2. 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_private_style(self) -> List[Dict]:
        """使用从私密库提取的 eastmoney_north_flow_direct"""
        if not HAS_REQUESTS:
            return []

        # 重试一次
        for attempt in range(2):
            north_data = eastmoney_north_flow_direct()
            if north_data:
                hgt = north_data.get("hgt", 0)
                sgt = north_data.get("sgt", 0)
                date = north_data.get("date", self.today)
                if hgt == 0 and sgt == 0:
                    continue
                return [{
                    "date": date,
                    "沪股通": round(hgt, 2),
                    "深股通": round(sgt, 2),
                    "合计": round(hgt + sgt, 2)
                }]
            # 等待0.5秒后重试
            time.sleep(0.5)

        return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            # 检查缓存是否过期（60分钟内）
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_minutes = (datetime.now() - dt).total_seconds() / 60
                    if age_minutes > 60:
                        logger.debug("北向资金缓存已过期")
                        return []
                except:
                    pass
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
