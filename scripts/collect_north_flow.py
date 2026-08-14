#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金历史采集模块（修复版）
采集：沪股通、深股通历史累计净流入
频率：每30分钟
数据源：akshare (em/sina) → 缓存
"""

import sys
import os
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
    """北向资金历史采集器（修复版）"""

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 尝试多个 akshare 接口
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

    def _fetch_from_akshare(self) -> List[Dict]:
        try:
            import akshare as ak

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 方法1: 使用 stock_hsgt_north_net_flow_in_em（东方财富）
            try:
                df_em = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
                if df_em is not None and not df_em.empty:
                    recent = df_em.tail(30)
                    for _, row in recent.iterrows():
                        items.append({
                            "type": "沪股通",
                            "date": row.get('date', ''),
                            "value": round(float(row.get('value', 0)) / 10000, 2),
                            "cumulative": round(float(row.get('cumulative', 0)) / 10000, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"沪股通(em)采集失败: {e}")

            # 方法2: 使用 stock_hsgt_north_net_flow_in_sina（新浪）
            try:
                df_sina = ak.stock_hsgt_north_net_flow_in_sina(symbol="沪股通")
                if df_sina is not None and not df_sina.empty:
                    recent = df_sina.tail(30)
                    for _, row in recent.iterrows():
                        items.append({
                            "type": "沪股通",
                            "date": row.get('date', ''),
                            "value": round(float(row.get('value', 0)) / 10000, 2),
                            "cumulative": round(float(row.get('cumulative', 0)) / 10000, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"沪股通(sina)采集失败: {e}")

            # 如果以上都失败，尝试直接从 history 接口获取
            try:
                df_hist = ak.stock_hsgt_hist(symbol="沪股通")
                if df_hist is not None and not df_hist.empty:
                    recent = df_hist.tail(30)
                    for _, row in recent.iterrows():
                        items.append({
                            "type": "沪股通",
                            "date": row.get('date', ''),
                            "value": round(float(row.get('net_inflow', 0)), 2),
                            "cumulative": round(float(row.get('cumulative', 0)), 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"沪股通(hist)采集失败: {e}")

            return []

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
            return data.get('items', [])
        return []


def collect_north_flow() -> Dict[str, Any]:
    collector = NorthFlowCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/north_flow_{timestamp}.json"
    save_json(result, filepath)
    save_json(result, "staging/north_flow_cache.json")

    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
