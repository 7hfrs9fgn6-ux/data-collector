#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万年历采集模块
采集 A股/港股/美股 交易日、节假日、冬令时/夏令时切换信息
数据源：akshare（tool_trade_date_hist_sina）
输出：staging/calendar_raw_*.json
"""

import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

import akshare as ak
import pytz

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils import get_timestamp, save_json, load_config, sign_data

# ============================================================
# 配置
# ============================================================

DST_CONFIG = {
    # 美国夏令时：3月第二个周日 -> 11月第一个周日
    "us": {
        "start_month": 3,
        "start_weekday": 6,  # 周日
        "start_week": 2,     # 第二个
        "end_month": 11,
        "end_weekday": 6,    # 周日
        "end_week": 1,       # 第一个
    }
}

# 中国节假日（法定假日 + 调休），以 2026 年为例
# 实际生产环境应从 akshare 获取或维护完整列表
CHINA_HOLIDAYS_2026 = {
    "2026-01-01": "元旦",
    "2026-01-02": "元旦",
    "2026-02-17": "春节",
    "2026-02-18": "春节",
    "2026-02-19": "春节",
    "2026-02-20": "春节",
    "2026-02-23": "春节",
    "2026-04-06": "清明节",
    "2026-05-01": "劳动节",
    "2026-05-04": "劳动节",
    "2026-06-22": "端午节",
    "2026-09-28": "中秋节",
    "2026-10-01": "国庆节",
    "2026-10-02": "国庆节",
    "2026-10-05": "国庆节",
    "2026-10-06": "国庆节",
    "2026-10-07": "国庆节",
}

# 调休补班日（周末上班）
CHINA_WORKDAY_2026 = {
    "2026-02-14": "春节调休",
    "2026-02-21": "春节调休",
    "2026-04-26": "劳动节调休",
    "2026-05-09": "劳动节调休",
    "2026-09-26": "中秋节调休",
    "2026-10-10": "国庆节调休",
}

# 香港节假日（2026 年示例）
HK_HOLIDAYS_2026 = {
    "2026-01-01": "元旦",
    "2026-02-17": "农历年初一",
    "2026-02-18": "农历年初二",
    "2026-02-19": "农历年初三",
    "2026-04-03": "清明节",
    "2026-04-06": "复活节星期一",
    "2026-05-01": "劳动节",
    "2026-05-14": "佛诞",
    "2026-06-22": "端午节",
    "2026-07-01": "香港特别行政区成立纪念日",
    "2026-09-28": "中秋节翌日",
    "2026-10-01": "国庆日",
    "2026-10-21": "重阳节",
    "2026-12-25": "圣诞节",
    "2026-12-26": "圣诞节后第一个周日",
}

# 美国节假日（2026 年示例，纽交所休市）
US_HOLIDAYS_2026 = {
    "2026-01-01": "New Year's Day",
    "2026-01-19": "Martin Luther King Jr. Day",
    "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday",
    "2026-05-25": "Memorial Day",
    "2026-07-03": "Independence Day (observed)",
    "2026-09-07": "Labor Day",
    "2026-11-26": "Thanksgiving Day",
    "2026-12-25": "Christmas Day",
}


# ============================================================
# DST 计算函数
# ============================================================

def get_dst_start(year: int, config: dict) -> datetime:
    """
    计算夏令时开始日期
    规则：3月第二个周日
    """
    month = config["start_month"]
    weekday = config["start_weekday"]  # 6 = 周日
    week_num = config["start_week"]    # 2 = 第二个

    # 获取该月第一天
    first_day = datetime(year, month, 1)
    # 找到第一个周日
    days_until_first_sunday = (weekday - first_day.weekday()) % 7
    first_sunday = first_day + timedelta(days=days_until_first_sunday)
    # 加上 (week_num - 1) 周
    dst_start = first_sunday + timedelta(weeks=week_num - 1)

    return dst_start


def get_dst_end(year: int, config: dict) -> datetime:
    """
    计算夏令时结束日期
    规则：11月第一个周日
    """
    month = config["end_month"]
    weekday = config["end_weekday"]  # 6 = 周日
    week_num = config["end_week"]    # 1 = 第一个

    first_day = datetime(year, month, 1)
    days_until_first_sunday = (weekday - first_day.weekday()) % 7
    dst_end = first_day + timedelta(days=days_until_first_sunday)

    return dst_end


def is_dst_active(date: datetime, year: int) -> bool:
    """判断某日期是否处于美国夏令时"""
    config = DST_CONFIG["us"]
    dst_start = get_dst_start(year, config)
    dst_end = get_dst_end(year, config)

    # 夏令时在 dst_start 00:00 开始，dst_end 00:00 结束
    if dst_start <= date < dst_end:
        return True
    return False


# ============================================================
# 采集函数
# ============================================================

def fetch_trading_days_akshare(start_year: int = 1990, end_year: int = 2030) -> list:
    """
    从 akshare 获取 A 股交易日历
    """
    try:
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            print("⚠️ akshare 返回空数据")
            return []

        # 过滤年份范围
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[(df["trade_date"].dt.year >= start_year) & (df["trade_date"].dt.year <= end_year)]

        trading_days = df["trade_date"].dt.strftime("%Y-%m-%d").tolist()
        print(f"✅ akshare 获取 A 股交易日: {len(trading_days)} 天")
        return trading_days

    except Exception as e:
        print(f"❌ akshare 获取交易日失败: {e}")
        return []


def generate_full_calendar(year: int) -> dict:
    """
    生成指定年份的完整日历信息
    """
    config = DST_CONFIG["us"]
    dst_start = get_dst_start(year, config)
    dst_end = get_dst_end(year, config)

    # 构建日期字典
    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31)

    calendar_data = []
    current = start_date

    a_share_holidays = CHINA_HOLIDAYS_2026
    a_share_workdays = CHINA_WORKDAY_2026
    hk_holidays = HK_HOLIDAYS_2026
    us_holidays = US_HOLIDAYS_2026

    # 使用 akshare 获取 A 股交易日（如果可用）
    a_share_trading_days = fetch_trading_days_akshare(year, year)

    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        weekday = current.weekday()  # 0=周一, 6=周日
        is_weekend = weekday >= 5  # 周六或周日

        # ---- A 股交易日判断 ----
        if a_share_trading_days:
            # 使用 akshare 数据
            is_a_share_trading = date_str in a_share_trading_days
        else:
            # 降级：基于规则判断
            if is_weekend:
                is_a_share_trading = False
            elif date_str in a_share_holidays:
                is_a_share_trading = False
            elif date_str in a_share_workdays:
                is_a_share_trading = True
            else:
                is_a_share_trading = True

        # ---- 港股交易日判断 ----
        if is_weekend:
            is_hk_trading = False
        elif date_str in HK_HOLIDAYS_2026:
            is_hk_trading = False
        else:
            is_hk_trading = True

        # ---- 美股交易日判断 ----
        if is_weekend:
            is_us_trading = False
        elif date_str in US_HOLIDAYS_2026:
            is_us_trading = False
        else:
            is_us_trading = True

        # ---- DST 状态 ----
        dst_active = is_dst_active(current, year)

        day_info = {
            "date": date_str,
            "year": current.year,
            "month": current.month,
            "day": current.day,
            "weekday": weekday,
            "weekday_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][weekday],
            "is_weekend": is_weekend,
            "a_share": {
                "is_trading_day": is_a_share_trading,
                "holiday_name": a_share_holidays.get(date_str, ""),
                "is_workday": date_str in a_share_workdays,
                "workday_reason": a_share_workdays.get(date_str, ""),
            },
            "hk": {
                "is_trading_day": is_hk_trading,
                "holiday_name": hk_holidays.get(date_str, ""),
            },
            "us": {
                "is_trading_day": is_us_trading,
                "holiday_name": us_holidays.get(date_str, ""),
                "dst_active": dst_active,
                "dst_start": dst_start.strftime("%Y-%m-%d"),
                "dst_end": dst_end.strftime("%Y-%m-%d"),
            },
        }
        calendar_data.append(day_info)

        current += timedelta(days=1)

    return {
        "year": year,
        "total_days": len(calendar_data),
        "a_share_trading_days": sum(1 for d in calendar_data if d["a_share"]["is_trading_day"]),
        "hk_trading_days": sum(1 for d in calendar_data if d["hk"]["is_trading_day"]),
        "us_trading_days": sum(1 for d in calendar_data if d["us"]["is_trading_day"]),
        "dst_info": {
            "dst_start": dst_start.strftime("%Y-%m-%d"),
            "dst_end": dst_end.strftime("%Y-%m-%d"),
            "dst_active_current": is_dst_active(datetime.now(), year),
        },
        "days": calendar_data,
    }


def generate_multi_year_calendar(start_year: int = 1990, end_year: int = 2030) -> dict:
    """
    生成多年日历数据
    """
    result = {
        "start_year": start_year,
        "end_year": end_year,
        "generated_at": get_timestamp(),
        "years": {},
        "summary": {
            "total_years": end_year - start_year + 1,
            "a_share_total_trading_days": 0,
            "hk_total_trading_days": 0,
            "us_total_trading_days": 0,
        },
    }

    for year in range(start_year, end_year + 1):
        year_data = generate_full_calendar(year)
        result["years"][str(year)] = year_data
        result["summary"]["a_share_total_trading_days"] += year_data["a_share_trading_days"]
        result["summary"]["hk_total_trading_days"] += year_data["hk_trading_days"]
        result["summary"]["us_total_trading_days"] += year_data["us_trading_days"]

    return result


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    print("=" * 60)
    print("📅 万年历采集启动")
    print("=" * 60)

    # 确保 staging 目录存在
    os.makedirs("staging", exist_ok=True)

    # 采集年份范围
    start_year = 1990
    end_year = 2030

    print(f"📊 采集年份范围: {start_year} ~ {end_year}")

    try:
        calendar_data = generate_multi_year_calendar(start_year, end_year)

        # 添加元数据
        output = {
            "collection_status": "success",
            "source": "akshare + local_holidays",
            "data_type": "calendar",
            "start_year": start_year,
            "end_year": end_year,
            "generated_at": get_timestamp(),
            "data": calendar_data,
        }

        # 保存原始文件
        raw_file = "staging/calendar_raw.json"
        save_json(raw_file, output)
        print(f"✅ 原始数据已保存: {raw_file}")

        # 打印摘要
        summary = calendar_data["summary"]
        print("\n📊 采集摘要:")
        print(f"   📅 年份范围: {start_year} ~ {end_year} ({summary['total_years']} 年)")
        print(f"   🇨🇳 A股交易日总数: {summary['a_share_total_trading_days']}")
        print(f"   🇭🇰 港股交易日总数: {summary['hk_total_trading_days']}")
        print(f"   🇺🇸 美股交易日总数: {summary['us_total_trading_days']}")

        # 当前年份 DST 状态
        current_year = datetime.now().year
        if str(current_year) in calendar_data["years"]:
            dst_info = calendar_data["years"][str(current_year)]["dst_info"]
            print(f"\n🕐 {current_year} 年 DST 信息:")
            print(f"   夏令时开始: {dst_info['dst_start']}")
            print(f"   夏令时结束: {dst_info['dst_end']}")
            print(f"   当前 DST 状态: {'✅ 夏令时' if dst_info['dst_active_current'] else '❌ 冬令时'}")

        print("\n✅ 万年历采集完成")

    except Exception as e:
        print(f"❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    # 导入 pandas 用于 akshare 数据处理
    try:
        import pandas as pd
    except ImportError:
        # 如果未安装 pandas，降级处理
        print("⚠️ pandas 未安装，将使用本地规则生成日历")
        # 重新定义 fetch_trading_days_akshare 为空
        def fetch_trading_days_akshare(*args, **kwargs):
            return []
    main()
