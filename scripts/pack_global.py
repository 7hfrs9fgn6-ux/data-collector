#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
外围数据汇总打包模块（公开库）
将港股、欧洲、美股、万年历数据汇总为统一外围数据包
采集/打包时间：每日 06:00（所有外围市场已收盘）
输出：global_package_*.json
"""

import sys
import os
import json
import glob
from datetime import datetime
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config, sign_data

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

STAGING_DIR = "staging"


def get_signing_key() -> str:
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，跳过签名")
        return ""
    return key


def find_latest_package(pattern: str) -> Dict[str, Any]:
    """找到最新的数据包文件并加载"""
    files = glob.glob(os.path.join(STAGING_DIR, pattern))
    if not files:
        return {}
    latest = max(files, key=os.path.getmtime)
    try:
        data = load_json(latest)
        if data:
            logger.debug(f"   ✅ 加载: {os.path.basename(latest)}")
        return data
    except Exception as e:
        logger.debug(f"   ⚠️ 加载失败 {os.path.basename(latest)}: {e}")
        return {}


def extract_indices(package: Dict[str, Any], source_name: str) -> List[Dict]:
    """从数据包中提取指数列表"""
    if not package:
        return []
    content = package.get('content', {})
    indices = content.get('indices', [])
    if not indices:
        # 兼容不同格式
        items = package.get('items', [])
        if items:
            return items
    return indices


def load_calendar_data() -> Dict[str, Any]:
    """加载万年历数据"""
    package = find_latest_package("calendar_package_*.json")
    if package:
        return package.get('content', {})
    return {}


def load_us_stock_data() -> Dict[str, Any]:
    """加载美股数据"""
    # 尝试从 us-stock-data Artifact 的打包文件读取
    # 或从本地采集文件读取
    package = find_latest_package("us_stock_package_*.json")
    if package:
        return package
    
    # 如果找不到打包文件，尝试采集文件
    raw = find_latest_package("us_stock_*.json")
    if raw:
        return raw
    return {}


def build_global_package() -> Dict[str, Any]:
    """构建统一外围数据包"""
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")

    logger.info("📦 开始汇总外围数据...")

    # 1. 加载港股数据
    hk_package = find_latest_package("hk_stock_package_*.json")
    hk_indices = extract_indices(hk_package, "hk_stock")
    logger.info(f"   🇭🇰 港股: {len(hk_indices)} 个指数")

    # 2. 加载欧洲数据
    eu_package = find_latest_package("eu_stock_package_*.json")
    eu_indices = extract_indices(eu_package, "eu_stock")
    logger.info(f"   🇪🇺 欧洲: {len(eu_indices)} 个指数")

    # 3. 加载美股数据
    us_package = load_us_stock_data()
    us_indices = extract_indices(us_package, "us_stock")
    logger.info(f"   🇺🇸 美股: {len(us_indices)} 个指数")

    # 4. 加载万年历数据
    calendar_data = load_calendar_data()
    logger.info(f"   📅 万年历: {'✅ 已加载' if calendar_data else '⚠️ 未找到'}")

    # 5. 判断是否交易日（从万年历获取）
    is_trading_day = False
    dst_active = False
    
    if calendar_data:
        years = calendar_data.get('years', {})
        year_str = str(now.year)
        if year_str in years:
            year_data = years[year_str]
            for day in year_data.get('days', []):
                if day.get('date') == trade_date:
                    is_trading_day = day.get('a_share', {}).get('is_trading_day', False)
                    dst_active = day.get('us', {}).get('dst_active', False)
                    break

    # 6. 构建统一包
    package = {
        "book": "公开数据",
        "chapter": "global_market",
        "version": "2.0",
        "generated_at": now.isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": dst_active,
        "content": {
            "hk_stock": {
                "total": len(hk_indices),
                "indices": hk_indices,
                "source": "hk_stock_package"
            },
            "eu_stock": {
                "total": len(eu_indices),
                "indices": eu_indices,
                "source": "eu_stock_package"
            },
            "us_stock": {
                "total": len(us_indices),
                "indices": us_indices,
                "source": "us_stock_package"
            },
            "calendar": calendar_data,
        },
        "metadata": {
            "source": "global_market_aggregator",
            "collected_at": now.isoformat(),
            "data_type": "global_market",
            "components": {
                "hk_available": len(hk_indices) > 0,
                "eu_available": len(eu_indices) > 0,
                "us_available": len(us_indices) > 0,
                "calendar_available": bool(calendar_data)
            }
        }
    }

    # 签名
    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 外围数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    # 统计汇总
    total_indices = len(hk_indices) + len(eu_indices) + len(us_indices)
    logger.info(f"   📊 汇总统计: 共 {total_indices} 个指数")
    logger.info(f"   📅 trade_date: {trade_date}, is_trading_day: {is_trading_day}")

    return package


def save_package(package: Dict[str, Any]) -> str:
    """保存打包数据"""
    os.makedirs(STAGING_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"global_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    save_json(package, filepath)
    logger.info(f"✅ 已保存: {filename}")

    # 同时保存一份最新版本（覆盖）
    latest_path = os.path.join(STAGING_DIR, "global_package_latest.json")
    save_json(package, latest_path)

    file_size = os.path.getsize(filepath)
    logger.info(f"   📦 文件大小: {file_size/1024:.1f} KB")
    return filepath


def main():
    logger.info("=" * 60)
    logger.info("🌍 外围数据汇总打包启动")
    logger.info("=" * 60)

    try:
        package = build_global_package()
        filepath = save_package(package)

        logger.info("=" * 60)
        logger.info("✅ 外围数据汇总打包完成")
        logger.info(f"   📦 输出文件: {filepath}")
        logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"❌ 打包失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
