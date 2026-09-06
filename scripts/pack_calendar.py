#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万年历数据打包模块
将采集到的日历数据打包为统一格式数据包
输出：staging/calendar_package_*.json
"""

import json
import os
import sys
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils import get_timestamp, save_json, load_json, sign_data


# ============================================================
# 配置
# ============================================================

BOOK_NAME = "公开数据"
CHAPTER_NAME = "calendar"
VERSION = "2.0"


# ============================================================
# 打包函数
# ============================================================

def load_calendar_raw() -> dict:
    """加载原始日历数据"""
    raw_file = "staging/calendar_raw.json"

    if not os.path.exists(raw_file):
        print(f"❌ 原始文件不存在: {raw_file}")
        return None

    try:
        data = load_json(raw_file)
        if data.get("collection_status") != "success":
            print("⚠️ 采集状态不是 success，可能数据不完整")
        return data
    except Exception as e:
        print(f"❌ 加载原始数据失败: {e}")
        return None


def build_calendar_package(raw_data: dict) -> dict:
    """
    构建统一格式的万年历数据包
    """
    # 提取 trade_date
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")

    # 判断今日是否为交易日
    # 从日历数据中查找今日
    today_str = now.strftime("%Y-%m-%d")
    is_trading_day = False
    dst_active = False

    calendar_data = raw_data.get("data", {})
    years = calendar_data.get("years", {})

    # 查找今日所在的年份
    year_str = str(now.year)
    if year_str in years:
        year_data = years[year_str]
        days = year_data.get("days", [])
        for day in days:
            if day.get("date") == today_str:
                is_trading_day = day.get("a_share", {}).get("is_trading_day", False)
                dst_active = day.get("us", {}).get("dst_active", False)
                break

    # 构建数据包
    package = {
        "book": BOOK_NAME,
        "chapter": CHAPTER_NAME,
        "version": VERSION,
        "generated_at": get_timestamp(),
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": dst_active,
        "content": {
            "start_year": calendar_data.get("start_year", 1990),
            "end_year": calendar_data.get("end_year", 2030),
            "summary": calendar_data.get("summary", {}),
            "dst_info": {},
            "years": {},
        },
    }

    # 提取 DST 信息（当前年份）
    if year_str in years:
        package["content"]["dst_info"] = years[year_str].get("dst_info", {})

    # 压缩数据：保留年份级别的摘要，不展开每一天（数据量太大）
    # 但为了私密库查询需要，保留完整数据
    # 实际使用中，私密库可以根据需要拉取完整数据或摘要
    package["content"]["years"] = years

    return package


def main():
    """主函数"""
    print("=" * 60)
    print("📦 万年历数据打包")
    print("=" * 60)

    # 确保 staging 目录存在
    os.makedirs("staging", exist_ok=True)

    # 1. 加载原始数据
    raw_data = load_calendar_raw()
    if raw_data is None:
        print("❌ 无法加载原始数据，打包失败")
        sys.exit(1)

    # 2. 构建数据包
    package = build_calendar_package(raw_data)

    # 3. 签名
    signed_package = sign_data(package)

    # 4. 保存打包文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_file = f"staging/calendar_package_{timestamp}.json"

    save_json(package_file, signed_package)
    print(f"✅ 打包文件已保存: {package_file}")

    # 5. 打印摘要
    content = package.get("content", {})
    summary = content.get("summary", {})
    print("\n📊 打包摘要:")
    print(f"   📅 年份范围: {content.get('start_year')} ~ {content.get('end_year')}")
    print(f"   🇨🇳 A股交易日总数: {summary.get('a_share_total_trading_days', 0)}")
    print(f"   🇭🇰 港股交易日总数: {summary.get('hk_total_trading_days', 0)}")
    print(f"   🇺🇸 美股交易日总数: {summary.get('us_total_trading_days', 0)}")
    print(f"   📅 trade_date: {package.get('trade_date')}")
    print(f"   📅 is_trading_day: {package.get('is_trading_day')}")
    print(f"   🕐 dst_active: {package.get('dst_active')}")

    # 6. 清理临时文件（可选）
    # 保留 raw 文件用于调试，可定期清理
    print("\n✅ 万年历打包完成")


if __name__ == "__main__":
    main()
