#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 宏观数据采集模块
采集：GDP、CPI、PMI等宏观经济指标
频率：每日1次
数据源：akshare → 缓存
★ 2026-08-14 新增：自动HMAC-SHA256签名 ★
★ 2026-08-15 修复：非交易日返回0值问题，动态缓存有效期 ★
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


# ============================================================
# ★ 非交易日检测
# ============================================================
def _is_weekend() -> bool:
    """判断今天是否是周末"""
    today = datetime.now().date()
    return today.weekday() >= 5


def _is_holiday() -> bool:
    """判断今天是否是节假日（2026年主要节假日）"""
    today = datetime.now().date()
    month, day = today.month, today.day
    holidays_2026 = [
        (1, 1),   # 元旦
        (1, 28), (1, 29), (1, 30), (1, 31), (2, 1), (2, 2), (2, 3),  # 春节
        (4, 4), (4, 5), (4, 6),  # 清明节
        (5, 1), (5, 2), (5, 3),  # 劳动节
        (5, 31), (6, 1), (6, 2),  # 端午节
        (10, 1), (10, 2), (10, 3), (10, 4), (10, 5), (10, 6), (10, 7),  # 国庆节
    ]
    return (month, day) in holidays_2026


def _is_trading_day() -> bool:
    """判断今天是否是交易日"""
    return not _is_weekend() and not _is_holiday()


def _get_cache_max_age_hours() -> int:
    """获取当前可接受的缓存最大年龄（小时）"""
    if _is_holiday():
        return 120   # 节假日：5天
    elif _is_weekend():
        return 72    # 周末：3天
    else:
        return 24    # 交易日：1天


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
            "total": N,
            "items": [...],
            "signature": "..."
        }
        """
        result = {
            "timestamp": get_timestamp(),
            "source": "macro",
            "total": 0,
            "items": []
        }

        # ★ 非交易日：优先使用缓存
        if not _is_trading_day():
            logger.info(f"📅 非交易日（周末/节假日），优先使用缓存数据")
            cached_data = self._fetch_from_cache()
            if cached_data and len(cached_data) > 0:
                result["items"] = cached_data
                result["total"] = len(cached_data)
                result["source"] = "cache"
                logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")
                # 签名并返回
                key = get_signing_key()
                if key:
                    result['signature'] = sign_data(result, key)
                else:
                    result['signature'] = None
                return result
            else:
                logger.warning("⚠️ 缓存无有效数据，尝试实时采集...")

        # 尝试从 akshare 实时采集
        try:
            data = self._fetch_from_akshare()
            if data and len(data) > 0:
                result["items"] = data
                result["total"] = len(data)
                result["source"] = "akshare"
                logger.info(f"✅ 宏观数据采集成功 (来源: akshare, {len(data)} 项)")
                # 保存到缓存
                self._save_to_cache(data)
            else:
                # 如果实时采集返回空，尝试缓存
                cached_data = self._fetch_from_cache()
                if cached_data and len(cached_data) > 0:
                    result["items"] = cached_data
                    result["total"] = len(cached_data)
                    result["source"] = "cache"
                    logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")
                else:
                    logger.warning("⚠️ 所有宏观数据源均失败，使用空数据")
        except Exception as e:
            logger.warning(f"⚠️ 宏观数据采集异常: {e}，尝试使用缓存")
            cached_data = self._fetch_from_cache()
            if cached_data and len(cached_data) > 0:
                result["items"] = cached_data
                result["total"] = len(cached_data)
                result["source"] = "cache"
                logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")

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
        """
        从 akshare 获取宏观数据
        ★ 修复：只返回有效数据（value > 0），无效数据不添加
        """
        try:
            import akshare as ak

            macro_data = []
            today = datetime.now().strftime("%Y-%m-%d")
            # 用于去重，避免重复添加相同指标
            indicators_found = set()

            # 1. 中国 GDP 数据
            try:
                gdp = ak.macro_china_gdp()
                if gdp is not None and not gdp.empty:
                    latest = gdp.iloc[-1]
                    value = float(latest.get('value', 0))
                    # ★ 只添加有效数据（value > 0）
                    if value > 0:
                        macro_data.append({
                            "indicator": "GDP",
                            "value": value,
                            "quarter": latest.get('quarter', ''),
                            "unit": "万亿元",
                            "date": latest.get('date', today)
                        })
                        indicators_found.add("GDP")
                        logger.debug(f"   GDP: {value} 万亿元")
                    else:
                        logger.debug("   GDP: 数据为空，跳过")
            except Exception as e:
                logger.debug(f"GDP 采集失败: {e}")

            # 2. 中国 CPI 数据
            try:
                cpi = ak.macro_china_cpi()
                if cpi is not None and not cpi.empty:
                    latest = cpi.iloc[-1]
                    value = float(latest.get('value', 0))
                    if value != 0:  # CPI 可以为负值（通缩），所以检查是否为 None 而不是 > 0
                        macro_data.append({
                            "indicator": "CPI",
                            "value": value,
                            "date": latest.get('date', today),
                            "unit": "%",
                            "change": "同比"
                        })
                        indicators_found.add("CPI")
                        logger.debug(f"   CPI: {value}%")
                    else:
                        logger.debug("   CPI: 数据为空，跳过")
            except Exception as e:
                logger.debug(f"CPI 采集失败: {e}")

            # 3. 中国 PMI 数据
            try:
                pmi = ak.macro_china_pmi()
                if pmi is not None and not pmi.empty:
                    latest = pmi.iloc[-1]
                    value = float(latest.get('value', 0))
                    if value > 0:
                        macro_data.append({
                            "indicator": "PMI",
                            "value": value,
                            "date": latest.get('date', today),
                            "unit": ""
                        })
                        indicators_found.add("PMI")
                        logger.debug(f"   PMI: {value}")
                    else:
                        logger.debug("   PMI: 数据为空，跳过")
            except Exception as e:
                logger.debug(f"PMI 采集失败: {e}")

            if macro_data:
                logger.info(f"   ✅ akshare 宏观: {len(macro_data)} 项 ({', '.join(indicators_found)})")
            else:
                logger.debug("   ℹ️ akshare 宏观: 无有效数据")
            return macro_data

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 宏观采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        """
        从缓存加载宏观数据
        ★ 修复：使用动态缓存有效期（交易日24h/周末72h/节假日120h）
        """
        cache_file = "staging/macro_cache.json"
        data = load_json(cache_file)
        if data:
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_hours = (datetime.now() - dt).total_seconds() / 3600
                    max_age = _get_cache_max_age_hours()
                    if age_hours > max_age:
                        logger.debug(f"宏观缓存已过期 ({age_hours:.1f}h > {max_age}h)")
                        return []
                    else:
                        logger.debug(f"宏观缓存有效 ({age_hours:.1f}h < {max_age}h)")
                except Exception as e:
                    logger.debug(f"缓存时间解析失败: {e}")
            items = data.get('items', [])
            # ★ 过滤掉 value=0 的无效数据
            valid_items = [item for item in items if item.get('value', 0) != 0]
            if valid_items:
                return valid_items
        return []

    def _save_to_cache(self, items: List[Dict]):
        """保存宏观数据到缓存"""
        if not items:
            return
        try:
            data = {
                "timestamp": get_timestamp(),
                "total": len(items),
                "items": items
            }
            save_json(data, "staging/macro_cache.json")
            logger.debug(f"📂 宏观缓存已保存 ({len(items)} 项)")
        except Exception as e:
            logger.debug(f"保存宏观缓存失败: {e}")


def collect_macro() -> Dict[str, Any]:
    """公开接口：采集宏观数据"""
    collector = MacroDataCollector()
    result = collector.collect()

    # 保存到暂存区（已包含签名）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/macro_{timestamp}.json"
    save_json(result, filepath)

    # 同时更新缓存
    if result.get('items'):
        # 缓存已经在 collect() 中保存了，但为了保险再次保存
        pass

    logger.info(f"📊 宏观数据: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    logger.info(f"📂 数据来源: {result['source']}")
    return result


if __name__ == "__main__":
    data = collect_macro()
    print(f"宏观数据采集完成: {data['total']} 项")
