#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 板块52周回撤采集模块
从申万行业指数获取各板块52周回撤数据
频率：每小时
数据源：akshare（申万行业指数）→ 缓存
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


# ============================================================
# 板块配置（申万一级行业）
# 来源：real_adapter.py 的 AK_CODE_MAP
# ============================================================
SECTOR_CODES = [
    {"name": "电子", "code": "801080"},
    {"name": "计算机", "code": "801750"},
    {"name": "通信", "code": "801770"},
    {"name": "传媒", "code": "801760"},
    {"name": "医药生物", "code": "801150"},
    {"name": "食品饮料", "code": "801120"},
    {"name": "家用电器", "code": "801110"},
    {"name": "电力设备", "code": "801730"},
    {"name": "汽车", "code": "801880"},
    {"name": "国防军工", "code": "801740"},
    {"name": "银行", "code": "801780"},
    {"name": "非银金融", "code": "801790"},
    {"name": "公用事业", "code": "801160"},
    {"name": "煤炭", "code": "801950"},
    {"name": "石油石化", "code": "801960"},
]


class SectorCollector:
    """板块52周回撤采集器（基于 real_adapter.py 的 AKShare 逻辑）"""

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2
        self.timeout = 6

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        data = self._fetch_all_sectors()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare_sw"
            logger.info(f"✅ 板块回撤采集成功 (来源: 申万行业指数, {len(data)} 项)")
            return result

        # 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 板块回撤采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有板块回撤数据源均失败")
        return result

    def _fetch_all_sectors(self) -> List[Dict]:
        """并发获取所有板块数据（基于 real_adapter.py 的并发逻辑）"""
        try:
            import akshare as ak
            from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

            MAX_WORKERS = 8
            TIMEOUT = 10
            results = [None] * len(SECTOR_CODES)

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                future_to_idx = {
                    executor.submit(self._fetch_single_sector, sector["name"], sector["code"]): idx
                    for idx, sector in enumerate(SECTOR_CODES)
                }

                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        results[idx] = future.result(timeout=TIMEOUT)
                    except FuturesTimeoutError:
                        sector_name = SECTOR_CODES[idx]["name"]
                        logger.debug(f"⏰ {sector_name} 获取超时")
                    except Exception as e:
                        sector_name = SECTOR_CODES[idx]["name"]
                        logger.debug(f"❌ {sector_name} 获取异常: {e}")

            # 过滤成功的结果
            return [r for r in results if r is not None]

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"申万行业指数采集异常: {e}")
            return []

    def _fetch_single_sector(self, name: str, code: str) -> Optional[Dict]:
        """获取单个板块数据（基于 real_adapter.py 的 _fetch_single_sector_akshare）"""
        max_retries = 2

        for attempt in range(max_retries):
            try:
                import akshare as ak
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(ak.index_hist_sw, symbol=code)
                    try:
                        df = future.result(timeout=6)
                    except FuturesTimeoutError:
                        logger.debug(f"{name} AKShare 超时 (6s)")
                        continue

                if df is None or df.empty:
                    logger.debug(f"{name} 返回空数据")
                    continue

                # 列名识别
                high_col = None
                close_col = None
                for col in df.columns:
                    if '高' in col or 'high' in col.lower():
                        high_col = col
                    if '收' in col or 'close' in col.lower():
                        close_col = col

                if high_col is None or close_col is None:
                    logger.debug(f"{name} 列名识别失败")
                    continue

                high_52w = float(df[high_col].max())
                current = float(df[close_col].iloc[-1])

                if high_52w <= 0:
                    logger.debug(f"{name} 52周高点异常: {high_52w}")
                    continue

                drawdown = round((high_52w - current) / high_52w * 100, 1)

                return {
                    "sector": name,
                    "code": code,
                    "price": round(current, 2),
                    "high_52w": round(high_52w, 2),
                    "drawdown": drawdown,
                    "date": datetime.now().strftime("%Y-%m-%d")
                }

            except Exception as e:
                logger.debug(f"{name} 尝试 {attempt+1}/{max_retries} 失败: {e}")
                if attempt < max_retries - 1:
                    time.sleep(0.3 * (attempt + 1))

        return None

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_sector() -> Dict[str, Any]:
    collector = SectorCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/sector_{timestamp}.json"
    save_json(result, filepath)

    if result["total"] > 0:
        save_json(result, "staging/sector_cache.json")

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
