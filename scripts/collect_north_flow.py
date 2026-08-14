#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（hhxg-market 风格）
零依赖，仅使用 Python 标准库 + requests
数据来源：恢恢量化公开 API
频率：每30分钟
"""

import sys
import os
import json
import urllib.request
import urllib.error
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
    """北向资金采集器（纯标准库，零依赖）"""

    # 恢恢量化北向资金 API（公开免费，无需 Key）
    NORTHBOUND_API = "https://hhxg.top/api/northbound"

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：恢恢量化 API（推荐）
        data = self._fetch_from_hhxg()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "hhxg"
            logger.info(f"✅ 北向资金采集成功 (来源: 恢恢量化, {len(data)} 项)")
            return result

        # 方法2：从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_from_hhxg(self) -> List[Dict]:
        """
        从恢恢量化 API 获取北向资金数据
        完全免费，无需 API Key，无需安装任何包
        """
        try:
            req = urllib.request.Request(
                self.NORTHBOUND_API,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "application/json"
                }
            )

            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status != 200:
                    logger.debug(f"恢恢量化 API HTTP {resp.status}")
                    return []

                data = json.loads(resp.read().decode('utf-8'))

                # 解析返回数据
                # 预期格式: {"code": 0, "data": {"northbound": [...], "southbound": [...]}}
                if data.get('code') != 0:
                    logger.debug(f"恢恢量化 API 返回错误: {data.get('msg')}")
                    return []

                api_data = data.get('data', {})
                northbound = api_data.get('northbound', [])

                if not northbound:
                    logger.debug("恢恢量化 API 返回空数据")
                    return []

                items = []
                for item in northbound[:7]:  # 最近7天
                    items.append({
                        "date": item.get('date', ''),
                        "沪股通": round(float(item.get('sh', 0)), 2),
                        "深股通": round(float(item.get('sz', 0)), 2),
                        "合计": round(float(item.get('total', 0)), 2)
                    })

                return items

        except urllib.error.URLError as e:
            logger.debug(f"恢恢量化 API 网络错误: {e}")
            return []
        except json.JSONDecodeError as e:
            logger.debug(f"恢恢量化 API JSON 解析失败: {e}")
            return []
        except Exception as e:
            logger.debug(f"恢恢量化 API 异常: {e}")
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
