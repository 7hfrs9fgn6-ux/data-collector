#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 宏观数据采集模块（增强版）
采集：GDP、CPI、PMI等宏观经济指标
频率：每日1次
数据源：akshare → 缓存
★ 2026-08-14 新增：自动HMAC-SHA256签名 ★
★ 2026-08-15 修复：非交易日返回0值问题，动态缓存有效期 ★
★ 2026-08-20 修复：添加 generated_at 字段，增强错误日志 ★
★ 2026-08-20 增强：详细错误输出，便于排查 akshare 采集失败原因 ★
"""

import sys
import os
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, truncate_text, load_config, sign_data

# ★ 支持通过环境变量调整日志级别 ★
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.INFO),
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
    today = datetime.now().date()
    return today.weekday() >= 5


def _is_holiday() -> bool:
    today = datetime.now().date()
    month, day = today.month, today.day
    holidays_2026 = [
        (1, 1), (1, 28), (1, 29), (1, 30), (1, 31), (2, 1), (2, 2), (2, 3),
        (4, 4), (4, 5), (4, 6), (5, 1), (5, 2), (5, 3),
        (5, 31), (6, 1), (6, 2), (10, 1), (10, 2), (10, 3), (10, 4),
        (10, 5), (10, 6), (10, 7),
    ]
    return (month, day) in holidays_2026


def _is_trading_day() -> bool:
    return not _is_weekend() and not _is_holiday()


def _get_cache_max_age_hours() -> int:
    if _is_holiday():
        return 120
    elif _is_weekend():
        return 72
    else:
        return 24


class MacroDataCollector:
    """宏观数据采集器（增强版）"""

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2
        self.timeout = 15

    def collect(self) -> Dict[str, Any]:
        """
        采集宏观数据
        返回: {
            "timestamp": "...",
            "generated_at": "...",
            "source": "macro",
            "total": N,
            "items": [...],
            "signature": "..."
        }
        """
        timestamp = get_timestamp()
        result = {
            "timestamp": timestamp,
            "generated_at": timestamp,
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
                self._sign_result(result)
                return result
            else:
                logger.warning("⚠️ 缓存无有效数据，尝试实时采集...")

        # ★ 检查 akshare 是否可用
        if not self._check_akshare_available():
            logger.warning("⚠️ akshare 不可用，尝试从缓存加载")
            cached_data = self._fetch_from_cache()
            if cached_data and len(cached_data) > 0:
                result["items"] = cached_data
                result["total"] = len(cached_data)
                result["source"] = "cache"
                logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")
                self._sign_result(result)
                return result
            else:
                logger.error("❌ akshare 不可用且缓存无数据，采集失败")
                self._sign_result(result)
                return result

        # 尝试从 akshare 实时采集
        logger.info("📊 正在从 akshare 采集宏观数据...")
        try:
            data = self._fetch_from_akshare()
            if data and len(data) > 0:
                result["items"] = data
                result["total"] = len(data)
                result["source"] = "akshare"
                logger.info(f"✅ 宏观数据采集成功 (来源: akshare, {len(data)} 项)")
                self._save_to_cache(data)
            else:
                logger.warning("⚠️ akshare 实时采集返回空数据，尝试使用缓存")
                cached_data = self._fetch_from_cache()
                if cached_data and len(cached_data) > 0:
                    result["items"] = cached_data
                    result["total"] = len(cached_data)
                    result["source"] = "cache"
                    logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")
                else:
                    logger.error("❌ 所有宏观数据源均失败，返回空数据")
        except Exception as e:
            logger.error(f"❌ 宏观数据采集异常: {e}")
            # 尝试使用缓存
            cached_data = self._fetch_from_cache()
            if cached_data and len(cached_data) > 0:
                result["items"] = cached_data
                result["total"] = len(cached_data)
                result["source"] = "cache"
                logger.info(f"✅ 宏观数据从缓存加载 ({len(cached_data)} 项)")
            else:
                logger.error("❌ 缓存也无有效数据，返回空数据")

        self._sign_result(result)
        return result

    def _check_akshare_available(self) -> bool:
        """检查 akshare 是否可正常导入和调用"""
        try:
            import akshare as ak
            # 尝试简单调用（不获取数据，只测试导入）
            logger.debug("✅ akshare 导入成功")
            return True
        except ImportError as e:
            logger.error(f"❌ akshare 导入失败: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ akshare 初始化异常: {e}")
            return False

    def _sign_result(self, result: Dict[str, Any]) -> None:
        """签名结果（原地修改）"""
        key = get_signing_key()
        if key:
            result['signature'] = sign_data(result, key)
            logger.debug(f"🔐 宏观数据已签名: {result['signature'][:16]}...")
        else:
            result['signature'] = None
            logger.warning("⚠️ 宏观数据未签名（SIGNING_KEY 未设置）")

    def _fetch_from_akshare(self) -> List[Dict]:
        """
        从 akshare 获取宏观数据
        ★ 改进：详细记录每个指标采集失败的原因
        """
        try:
            import akshare as ak
        except ImportError as e:
            logger.error(f"❌ akshare 未安装: {e}")
            return []

        macro_data = []
        today = datetime.now().strftime("%Y-%m-%d")
        indicators_found = set()

        # 1. 中国 GDP 数据
        try:
            logger.debug("   🔍 尝试获取 GDP 数据...")
            gdp = ak.macro_china_gdp()
            if gdp is not None and not gdp.empty:
                latest = gdp.iloc[-1]
                value = float(latest.get('value', 0))
                if value > 0:
                    macro_data.append({
                        "indicator": "GDP",
                        "value": value,
                        "quarter": latest.get('quarter', ''),
                        "unit": "万亿元",
                        "date": latest.get('date', today)
                    })
                    indicators_found.add("GDP")
                    logger.info(f"   ✅ GDP: {value} 万亿元")
                else:
                    logger.warning("   ⚠️ GDP 数据无效（value=0），跳过")
            else:
                logger.warning("   ⚠️ GDP 数据为空")
        except Exception as e:
            logger.warning(f"   ❌ GDP 采集失败: {e}")

        # 2. 中国 CPI 数据
        try:
            logger.debug("   🔍 尝试获取 CPI 数据...")
            cpi = ak.macro_china_cpi()
            if cpi is not None and not cpi.empty:
                latest = cpi.iloc[-1]
                value = float(latest.get('value', 0))
                if value != 0:
                    macro_data.append({
                        "indicator": "CPI",
                        "value": value,
                        "date": latest.get('date', today),
                        "unit": "%",
                        "change": "同比"
                    })
                    indicators_found.add("CPI")
                    logger.info(f"   ✅ CPI: {value}%")
                else:
                    logger.warning("   ⚠️ CPI 数据无效（value=0），跳过")
            else:
                logger.warning("   ⚠️ CPI 数据为空")
        except Exception as e:
            logger.warning(f"   ❌ CPI 采集失败: {e}")

        # 3. 中国 PMI 数据
        try:
            logger.debug("   🔍 尝试获取 PMI 数据...")
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
                    logger.info(f"   ✅ PMI: {value}")
                else:
                    logger.warning("   ⚠️ PMI 数据无效（value=0），跳过")
            else:
                logger.warning("   ⚠️ PMI 数据为空")
        except Exception as e:
            logger.warning(f"   ❌ PMI 采集失败: {e}")

        if macro_data:
            logger.info(f"   📊 宏观数据采集汇总: {len(macro_data)} 项 ({', '.join(indicators_found)})")
        else:
            logger.warning("   ❌ 所有宏观指标均采集失败，请检查网络或 akshare 版本")
            # 输出调试建议
            logger.warning("   💡 建议: 1) 检查网络连接 2) 升级 akshare: pip install akshare --upgrade")
            logger.warning("   💡 建议: 3) 设置 LOG_LEVEL=DEBUG 查看详细错误")
        return macro_data

    def _fetch_from_cache(self) -> List[Dict]:
        """从缓存加载宏观数据（动态有效期）"""
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
                "generated_at": get_timestamp(),
                "total": len(items),
                "items": items
            }
            save_json(data, "staging/macro_cache.json")
            logger.debug(f"📂 宏观缓存已保存 ({len(items)} 项)")
        except Exception as e:
            logger.debug(f"保存宏观缓存失败: {e}")


def collect_macro() -> Dict[str, Any]:
    """公开接口：采集宏观数据"""
    logger.info("🚀 开始采集宏观数据...")
    collector = MacroDataCollector()
    result = collector.collect()

    # 确保 generated_at 字段存在
    if 'generated_at' not in result:
        result['generated_at'] = result.get('timestamp')

    # 保存到暂存区
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/macro_{timestamp}.json"
    save_json(result, filepath)
    logger.info(f"📁 已保存到: {filepath}")

    # 日志摘要
    logger.info(f"📊 宏观数据: {result['total']} 项")
    logger.info(f"🔐 签名状态: {'✅ 已签名' if result.get('signature') else '⚠️ 未签名'}")
    logger.info(f"📂 数据来源: {result['source']}")
    logger.info(f"📅 生成时间: {result.get('generated_at', '未知')}")
    if result['total'] == 0:
        logger.warning("⚠️ 本次采集未获取到任何宏观数据，请检查 akshare 接口或网络")
    return result


if __name__ == "__main__":
    data = collect_macro()
    print(f"宏观数据采集完成: {data['total']} 项")
    print(f"生成时间: {data.get('generated_at', '未知')}")
    if data['total'] == 0:
        print("⚠️ 未获取到数据，请检查 akshare 版本和网络")
        print("💡 可以尝试: LOG_LEVEL=DEBUG python scripts/collect_macro.py")
