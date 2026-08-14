#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（cn-funds-mcp 版）
通过 cn-funds-mcp MCP 服务获取北向资金数据
频率：每30分钟
"""

import sys
import os
import json
import subprocess
from datetime import datetime
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
    """北向资金采集器（cn-funds-mcp）"""

    def __init__(self):
        self.config = load_config()

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 通过 cn-funds-mcp 获取北向资金
        data = self._fetch_from_cn_funds_mcp()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cn-funds-mcp"
            logger.info(f"✅ 北向资金采集成功 (来源: cn-funds-mcp, {len(data)} 项)")
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

    def _fetch_from_cn_funds_mcp(self) -> List[Dict]:
        """通过 cn-funds-mcp 获取北向资金"""
        try:
            # 调用 cn-funds-mcp 的 get_northbound_capital 工具
            result = subprocess.run(
                ['npx', '-y', 'cn-funds-mcp', 'get_northbound_capital'],
                capture_output=True,
                text=True,
                timeout=30
            )

            if result.returncode != 0:
                logger.debug(f"cn-funds-mcp 返回错误: {result.stderr}")
                return []

            # 尝试解析 JSON
            try:
                data = json.loads(result.stdout)
            except json.JSONDecodeError:
                # 如果输出不是 JSON，可能是 MCP 协议的格式化输出
                logger.debug(f"cn-funds-mcp 输出不是 JSON: {result.stdout[:200]}")
                return []

            # 解析数据（根据 cn-funds-mcp 实际返回格式调整）
            items = []
            if isinstance(data, list):
                for item in data:
                    items.append({
                        "date": item.get('date', datetime.now().strftime("%Y-%m-%d")),
                        "沪股通": round(float(item.get('sh', 0)), 2),
                        "深股通": round(float(item.get('sz', 0)), 2),
                        "合计": round(float(item.get('total', 0)), 2)
                    })
            elif isinstance(data, dict):
                # 如果是单个对象
                items.append({
                    "date": data.get('date', datetime.now().strftime("%Y-%m-%d")),
                    "沪股通": round(float(data.get('sh', 0)), 2),
                    "深股通": round(float(data.get('sz', 0)), 2),
                    "合计": round(float(data.get('total', 0)), 2)
                })

            return items

        except subprocess.TimeoutExpired:
            logger.debug("cn-funds-mcp 调用超时")
            return []
        except FileNotFoundError:
            logger.debug("npx 未安装，请确保 Node.js 环境已配置")
            return []
        except Exception as e:
            logger.debug(f"cn-funds-mcp 调用异常: {e}")
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
