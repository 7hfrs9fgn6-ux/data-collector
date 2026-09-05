#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场数据打包模块（大宗商品、板块、宏观、汇率）
将分散的市场数据文件合并为一个统一包
★ 2026-09-06 新建：统一市场数据打包，移除美股依赖
"""

import os
import sys
import json
import glob
from datetime import datetime
import pytz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")


def get_beijing_time():
    """获取北京时间（带时区）"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(beijing_tz)


def get_trade_date(beijing_time):
    """获取交易日日期（北京时间日期）"""
    return beijing_time.strftime("%Y-%m-%d")


def is_trading_day(beijing_time):
    """判断是否为交易日（根据星期）"""
    weekday = beijing_time.weekday()
    return weekday < 5


def is_dst_active(beijing_time):
    """判断中国当前是否处于夏令时（中国没有夏令时，固定返回False）"""
    return False


def pack_market():
    """打包所有市场数据（大宗商品、板块、宏观、汇率）"""
    print("📦 打包市场数据...")

    # 获取北京时间
    beijing_time = get_beijing_time()
    trade_date = get_trade_date(beijing_time)
    is_trading = is_trading_day(beijing_time)
    dst_active = is_dst_active(beijing_time)

    # 查找所有市场数据文件
    # 这些文件由 collect_commodity.py, collect_sector.py, collect_macro.py, collect_forex.py 生成
    patterns = [
        "commodity_*.json",
        "sector_*.json",
        "macro_*.json",
        "forex_*.json"
    ]

    merged = {
        "book": "公开数据",
        "chapter": "market",
        "version": "2.0",
        "generated_at": beijing_time.isoformat(),
        "trade_date": trade_date,
        "is_trading_day": is_trading,
        "dst_active": dst_active,
        "package_type": "market_data",
        "contents": {
            "commodity": {},
            "sector": {},
            "macro": {},
            "forex": {}
        }
    }

    for pattern in patterns:
        full_pattern = os.path.join(STAGING_DIR, pattern)
        files = glob.glob(full_pattern)
        # 排除已签名的文件
        files = [f for f in files if "_signed" not in f]

        for filepath in files:
            filename = os.path.basename(filepath)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 根据文件类型归类
                    if "commodity" in filename:
                        merged["contents"]["commodity"] = data
                    elif "sector" in filename:
                        merged["contents"]["sector"] = data
                    elif "macro" in filename:
                        merged["contents"]["macro"] = data
                    elif "forex" in filename:
                        merged["contents"]["forex"] = data
            except Exception as e:
                print(f"   ⚠️ 读取失败 {filename}: {e}")

    # 检查是否采集到了数据
    has_data = any(
        merged["contents"][key] 
        for key in ["commodity", "sector", "macro", "forex"]
    )

    if not has_data:
        print("   ⚠️ 没有找到任何市场数据文件")
        return None

    # 保存合并包
    timestamp = beijing_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(STAGING_DIR, f"market_package_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已生成: {os.path.basename(output_file)}")
    print(f"   📅 交易日: {trade_date}, 是否交易日: {is_trading}")
    print(f"   📊 包含: 大宗商品={bool(merged['contents']['commodity'])}, "
          f"板块={bool(merged['contents']['sector'])}, "
          f"宏观={bool(merged['contents']['macro'])}, "
          f"汇率={bool(merged['contents']['forex'])}")
    return output_file


if __name__ == "__main__":
    pack_market()
