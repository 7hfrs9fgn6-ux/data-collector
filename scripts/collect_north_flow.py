#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（cn-funds-mcp 版）
通过 cn-funds-mcp MCP 服务获取北向资金数据
无需 API Key，完全免费
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
            # --yes 自动确认安装，避免交互
            result = subprocess.run(
                ['npx', '--yes', 'cn-funds-mcp', 'get_northbound_capital'],
                capture_output=True,
                text=True,
                timeout=60
            )

            if result.returncode != 0:
                logger.debug(f"cn-funds-mcp 返回错误码: {result.returncode}")
                logger.debug(f"stderr: {result.stderr[:200]}")
                return []

            # 尝试解析 JSON
            output = result.stdout.strip()
            if not output:
                logger.debug("cn-funds-mcp 输出为空")
                return []

            # 尝试解析 JSON（MCP 可能输出多行）
            data = None
            try:
                # 尝试直接解析
                data = json.loads(output)
            except json.JSONDecodeError:
                # 可能是多行 JSON 或多个 JSON 对象
                # 尝试找到第一个有效的 JSON 对象
                lines = output.split('\n')
                for line in lines:
                    line = line.strip()
                    if line.startswith('{') and line.endswith('}'):
                        try:
                            data = json.loads(line)
                            break
                        except:
                            continue

            if data is None:
                logger.debug(f"cn-funds-mcp 输出无法解析: {output[:200]}")
                return []

            # 解析数据（根据 cn-funds-mcp 实际返回格式调整）
            items = []
            if isinstance(data, list):
                for item in data:
                    if not isinstance(item, dict):
                        continue
                    items.append({
                        "date": item.get('date', datetime.now().strftime("%Y-%m-%d")),
                        "沪股通": round(float(item.get('sh', item.get('沪股通', 0))), 2),
                        "深股通": round(float(item.get('sz', item.get('深股通', 0))), 2),
                        "合计": round(float(item.get('total', item.get('合计', 0))), 2)
                    })
            elif isinstance(data, dict):
                # 检查是否包含数据列表
                if 'data' in data and isinstance(data['data'], list):
                    for item in data['data']:
                        items.append({
                            "date": item.get('date', datetime.now().strftime("%Y-%m-%d")),
                            "沪股通": round(float(item.get('sh', item.get('沪股通', 0))), 2),
                            "深股通": round(float(item.get('sz', item.get('深股通', 0))), 2),
                            "合计": round(float(item.get('total', item.get('合计', 0))), 2)
                        })
                else:
                    # 单个对象
                    items.append({
                        "date": data.get('date', datetime.now().strftime("%Y-%m-%d")),
                        "沪股通": round(float(data.get('sh', data.get('沪股通', 0))), 2),
                        "深股通": round(float(data.get('sz', data.get('深股通', 0))), 2),
                        "合计": round(float(data.get('total', data.get('合计', 0))), 2)
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
            # 检查缓存是否过期（30分钟内）
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
