#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 宏观数据采集模块
采集：GDP、CPI、PMI、社融等宏观经济指标
频率：每日1次
数据源：akshare → 网页爬虫（兜底）
★ 2026-08-14 新增：自动HMAC-SHA256签名 ★
"""

import sys
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, truncate_text, load_config, sign_data

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_signing_key() -> str:
    """从环境变量获取签名密钥"""
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


class MacroDataCollector:
    """宏观数据采集器"""

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2
        self.timeout = 15

    def collect(self) -> Dict[str, Any]:
        """
        采集宏观数据
        返回: {
            "timestamp": "...",
            "source": "macro",
            "total": 5,
            "items": [...],
            "signature": "..."  ← 自动添加
        }
        """
        result = {
            "timestamp": get_timestamp(),
            "source": "macro",
            "total": 0,
            "items": []
        }

        # 尝试多种数据源
        methods = [
            ("akshare", self._fetch_from_akshare),
            ("cache", self._fetch_from_cache),
        ]

        for source_name, fetch_func in methods:
            try:
                data = fetch_func()
                if data and len(data) > 0:
                    result["items"] = data
                    result["total"] = len(data)
                    result["source"] = source_name
                    logger.info(f"✅ 宏观数据采集成功 (来源: {source_name})")
                    break
            except Exception as e:
                logger.debug(f"   宏观数据源 {source_name} 失败: {e}")
                continue

        if result["total"] == 0:
            logger.warning("⚠️ 所有宏观数据源均失败，使用空数据")

        # ★ 自动添加签名 ★
        key = get_signing_key()
        if key:
            result['signature'] = sign_data(result, key)
            logger.debug(f"🔐 宏观数据已签名: {result['signature'][:16]}...")
        else:
            result['signature'] = None
            logger.warning("⚠️ 宏观数据未签名（SIGNING_KEY 未设置）")

        return result

    def _fetch_from_akshare(self) -> List[Dict]:
        """从 akshare 获取宏观数据"""
        try:
            import akshare as ak

            macro_data = []
            today = datetime.now().strftime("%Y-%m-%d")

            # 1. 中国 GDP 数据
            try:
                gdp = ak.macro_china_gdp()
                if gdp is not None and not gdp.empty:
                    latest = gdp.iloc[-1]
                    macro_data.append({
                        "indicator": "GDP",
                        "value": float(latest.get('value', 0)),
                        "quarter": latest.get('quarter', ''),
                        "unit": "万亿元",
                        "date": latest.get('date', today)
                    })
            except Exception as e:
                logger.debug(f"GDP 采集失败: {e}")

            # 2. 中国 CPI 数据
            try:
                cpi = ak.macro_china_cpi()
                if cpi is not None and not cpi.empty:
                    latest = cpi.iloc[-1]
                    macro_data.append({
                        "indicator": "CPI",
                        "value": float(latest.get('value', 0)),
                        "date": latest.get('date', today),
                        "unit": "%",
                        "change": "同比"
                    })
            except Exception as e:
                logger.debug(f"CPI 采集失败: {e}")

            # 3. 中国 PMI 数据
            try:
                pmi = ak.macro_china_pmi()
                if pmi is not None and not pmi.empty:
                    latest = pmi.iloc[-1]
                    macro_data.append({
                        "indicator": "PMI",
                        "value": float(latest.get('value', 0)),
                        "date": latest.get('date', today),
                        "unit": ""
                    })
            except Exception as e:
                logger.debug(f"PMI 采集失败: {e}")

            logger.info(f"   ✅ akshare 宏观: {len(macro_data)} 项")
            return macro_data

        except ImportError:
            logger.debug("akshare 未安装")
            return []

        except Exception as e:
            logger.debug(f"akshare 宏观采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载宏观数据"""
        cache_file = "staging/macro_cache.json"
        data = load_json(cache_file)
        if data:
            # 检查缓存是否有效（24小时内）
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_hours = (datetime.now() - dt).total_seconds() / 3600
                    if age_hours > 24:
                        logger.debug("宏观缓存已过期")
                        return []
                except:
                    pass
            return data.get('items', [])
        return []


def collect_macro() -> Dict[str, Any]:
    """公开接口：采集宏观数据"""
    collector = MacroDataCollector()
    result = collector.collect()

    # 保存到暂存区（已包含签名）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/macro_{timestamp}.json"
    save_json(result, filepath)

    # 同时保存缓存
    save_json(result, "staging/macro_cache.json")

    logger.info(f"📊 宏观数据: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    return result


if __name__ == "__main__":
    data = collect_macro()
    print(f"宏观数据采集完成: {data['total']} 项")
