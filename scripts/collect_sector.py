#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 板块52周回撤采集模块（增强稳定性）
从申万行业指数获取各板块52周回撤数据
频率：每小时
数据源：akshare（申万行业指数）→ 缓存
增加重试机制，提高云环境稳定性
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
    """板块52周回撤采集器（增强稳定性）"""

    def __init__(self):
        self.config = load_config()
        self.max_retries = 3  # 增加到3次
        self.timeout = 8      # 增加到8秒

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        # 先尝试从缓存读取（快速返回）
        cached = self._fetch_from_cache()
        if cached:
            result["items"] = cached
            result["total"] = len(cached)
            result["source"] = "cache"
            logger.info(f"✅ 板块回撤从缓存加载 ({len(cached)} 项)")
            # 缓存有效，但仍尝试后台更新（通过工作流下次触发）

        # 尝试实时采集（如果成功则覆盖缓存）
        data = self._fetch_all_sectors_with_retry()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare_sw"
            # 更新缓存
            self._save_to_cache(data)
            logger.info(f"✅ 板块回撤实时采集成功 ({len(data)} 项)")
            return result

        # 如果实时失败但有缓存，返回缓存
        if cached:
            logger.info(f"📂 实时采集失败，使用缓存数据")
            return result

        logger.warning("⚠️ 所有板块回撤数据源均失败")
        return result

    def _fetch_all_sectors_with_retry(self) -> List[Dict]:
        """带全局重试的采集"""
        max_global_retries = 2

        for global_attempt in range(max_global_retries):
            try:
                import akshare as ak
                from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError

                MAX_WORKERS = 8
                TIMEOUT = 12  # 增加到12秒

                # 先用简单方法获取整个数据表
                try:
                    df = ak.stock_zh_index_spot_em(symbol="申万行业指数")
                    if df is not None and not df.empty:
                        # 解析列名
                        name_col = None
                        price_col = None
                        high_col = None
                        for col in df.columns:
                            if '名称' in col or 'name' in col.lower():
                                name_col = col
                            if '最新价' in col or 'price' in col.lower():
                                price_col = col
                            if '最高' in col or 'high' in col.lower() or '52周最高' in col:
                                high_col = col

                        if name_col and price_col:
                            # 查找52周最高列
                            if not high_col:
                                for col in df.columns:
                                    if '52周' in col and ('最高' in col or '高' in col):
                                        high_col = col
                                        break

                            items = []
                            today = datetime.now().strftime("%Y-%m-%d")

                            for sector in SECTOR_CODES:
                                sector_name = sector["name"]
                                for _, row in df.iterrows():
                                    name = str(row.get(name_col, ''))
                                    if sector_name in name and ('申万' in name or 'sw' in name.lower()):
                                        price = self._safe_float(row.get(price_col))
                                        if price <= 0:
                                            continue

                                        high_52w = price
                                        if high_col:
                                            high_52w = self._safe_float(row.get(high_col))
                                        if high_52w <= 0:
                                            high_52w = price

                                        drawdown = ((high_52w - price) / high_52w * 100) if high_52w > 0 else 0

                                        items.append({
                                            "sector": sector_name,
                                            "code": sector["code"],
                                            "price": round(price, 2),
                                            "high_52w": round(high_52w, 2),
                                            "drawdown": round(drawdown, 2),
                                            "date": today
                                        })
                                        break

                            if items:
                                return items
                except Exception as e:
                    logger.debug(f"申万行业指数快速采集失败: {e}")

                # 备用：逐个获取（带重试）
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

                valid_results = [r for r in results if r is not None]
                if valid_results:
                    return valid_results

            except Exception as e:
                logger.debug(f"全局采集尝试 {global_attempt+1} 失败: {e}")
                if global_attempt < max_global_retries - 1:
                    time.sleep(1)

        return []

    def _fetch_single_sector(self, name: str, code: str) -> Optional[Dict]:
        """获取单个板块数据（带重试）"""
        for attempt in range(self.max_retries):
            try:
                import akshare as ak
                from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(ak.index_hist_sw, symbol=code)
                    try:
                        df = future.result(timeout=self.timeout)
                    except FuturesTimeoutError:
                        logger.debug(f"{name} AKShare 超时 ({self.timeout}s)")
                        if attempt < self.max_retries - 1:
                            time.sleep(0.5 * (attempt + 1))
                        continue

                if df is None or df.empty:
                    logger.debug(f"{name} 返回空数据")
                    continue

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

                if high_52w <= 0 or current <= 0:
                    logger.debug(f"{name} 数据异常: high={high_52w}, current={current}")
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
                logger.debug(f"{name} 尝试 {attempt+1}/{self.max_retries} 失败: {e}")
                if attempt < self.max_retries - 1:
                    time.sleep(0.5 * (attempt + 1))

        return None

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_minutes = (datetime.now() - dt).total_seconds() / 60
                    # 缓存有效期 2 小时
                    if age_minutes > 120:
                        return []
                except:
                    pass
            return data.get('items', [])
        return []

    def _save_to_cache(self, items: List[Dict]):
        try:
            data = {
                "timestamp": get_timestamp(),
                "total": len(items),
                "items": items
            }
            save_json(data, "staging/sector_cache.json")
        except Exception as e:
            logger.debug(f"保存缓存失败: {e}")

    def _safe_float(self, value) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0


def collect_sector() -> Dict[str, Any]:
    collector = SectorCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/sector_{timestamp}.json"
    save_json(result, filepath)

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
