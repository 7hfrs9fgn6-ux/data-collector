#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据打包模块
将分散的历史数据文件合并为一个统一包
★ 2026-09-06 升级：统一数据包格式（加北京时间 + trade_date + is_trading_day + dst_active）
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
    # 周六（5）或周日（6）为非交易日
    # 注意：节假日判断需要万年历，这里先做基础判断
    weekday = beijing_time.weekday()
    return weekday < 5


def is_dst_active(beijing_time):
    """判断中国当前是否处于夏令时（中国没有夏令时，固定返回False）"""
    # 中国自1991年起没有夏令时
    return False


def pack_historical():
    """打包所有历史数据"""
    print("📦 打包历史数据...")

    # 获取北京时间
    beijing_time = get_beijing_time()
    trade_date = get_trade_date(beijing_time)
    is_trading = is_trading_day(beijing_time)
    dst_active = is_dst_active(beijing_time)

    # 查找所有历史数据文件
    pattern = os.path.join(STAGING_DIR, "historical_*.json")
    files = glob.glob(pattern)

    # 排除已签名的文件
    files = [f for f in files if "_signed" not in f]

    if not files:
        print("   ⚠️ 没有找到历史数据文件")
        return None

    # 合并数据
    merged = {
        "book": "公开数据",
        "chapter": "historical",
        "version": "2.0",
        "generated_at": beijing_time.isoformat(),
        "trade_date": trade_date,
        "is_trading_day": is_trading,
        "dst_active": dst_active,
        "package_type": "historical_data",
        "contents": {}
    }

    for filepath in files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data_type = data.get('type', 'unknown')
                # 直接存储数据内容
                merged["contents"][data_type] = data.get('data', data)
        except Exception as e:
            print(f"   ⚠️ 读取失败 {filename}: {e}")

    # 保存合并包
    timestamp = beijing_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(STAGING_DIR, f"historical_package_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已生成: {os.path.basename(output_file)}")
    print(f"   📅 交易日: {trade_date}, 是否交易日: {is_trading}")
    return output_file


if __name__ == "__main__":
    pack_historical()
