#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金历史采集模块（修复版）
基于私密库 a_stock_adapter.py 的 eastmoney_datacenter 已验证逻辑
采集：沪股通、深股通当日净流入（从东财数据中心获取）
频率：每30分钟
数据源：东方财富数据中心 → akshare → 缓存
"""

import sys
import os
import time
import random
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

# 尝试导入东财请求模块（如果不存在则使用简单请求）
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NorthFlowCollector:
    """北向资金历史采集器（基于东财数据中心）"""

    def __init__(self):
        self.config = load_config()
        self.session = requests.Session() if HAS_REQUESTS else None
        if self.session:
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

        # 方法1：东方财富数据中心API（私密库已验证）
        data = self._fetch_from_eastmoney()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney"
            logger.info(f"✅ 北向资金采集成功 (来源: 东财数据中心, {len(data)} 项)")
            return result

        # 方法2：akshare 备选
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

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """
        通过东方财富数据中心获取北向资金数据
        基于私密库 a_stock_adapter.py 的 eastmoney_datacenter 逻辑
        """
        try:
            # 东财数据中心API
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

            if not self.session:
                return []

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
                hgt = row.get("HGT_NET_INFLOW", 0)  # 沪股通净流入（亿元）
                sgt = row.get("SGT_NET_INFLOW", 0)  # 深股通净流入（亿元）

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "type": "北向资金",
                    "date": trade_date[:10] if trade_date else datetime.now().strftime("%Y-%m-%d"),
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })

            # 如果获取成功，添加当日总览数据
            if items and len(items) > 0:
                latest = items[0]
                # 添加今日总览（与最新一条相同）
                pass

            return items

        except Exception as e:
            logger.debug(f"东财数据中心采集异常: {e}")
            return []

    def _fetch_from_akshare(self) -> List[Dict]:
        """备用方法：从 akshare 获取北向资金"""
        try:
            import akshare as ak

            items = []

            # 尝试获取北向资金数据
            try:
                # 使用 stock_hsgt_north_net_flow_in_em（东财接口）
                df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
                if df is not None and not df.empty:
                    recent = df.tail(5)
                    for _, row in recent.iterrows():
                        items.append({
                            "type": "北向资金",
                            "date": row.get('date', ''),
                            "沪股通": round(float(row.get('value', 0)) / 10000, 2),
                            "深股通": 0,
                            "合计": round(float(row.get('value', 0)) / 10000, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"akshare 北向接口失败: {e}")

            # 尝试获取沪深股通数据
            try:
                # 获取沪股通
                hgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
                # 获取深股通
                sgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="深股通")

                if hgt_df is not None and not hgt_df.empty and sgt_df is not None and not sgt_df.empty:
                    hgt_recent = hgt_df.tail(5)
                    sgt_recent = sgt_df.tail(5)

                    # 按日期合并
                    hgt_dict = {row.get('date', ''): row for _, row in hgt_recent.iterrows()}
                    sgt_dict = {row.get('date', ''): row for _, row in sgt_recent.iterrows()}

                    all_dates = set(hgt_dict.keys()) | set(sgt_dict.keys())
                    for date in sorted(all_dates, reverse=True)[:3]:
                        hgt_row = hgt_dict.get(date)
                        sgt_row = sgt_dict.get(date)
                        hgt_val = float(hgt_row.get('value', 0)) / 10000 if hgt_row else 0
                        sgt_val = float(sgt_row.get('value', 0)) / 10000 if sgt_row else 0
                        items.append({
                            "type": "北向资金",
                            "date": date,
                            "沪股通": round(hgt_val, 2),
                            "深股通": round(sgt_val, 2),
                            "合计": round(hgt_val + sgt_val, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"akshare 沪深股通接口失败: {e}")

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 北向资金采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
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
