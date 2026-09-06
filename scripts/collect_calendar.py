#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万年历采集模块（知识库模式）
采集 A股/港股/美股 交易日、节假日、冬令时/夏令时切换信息
数据源：akshare + 本地节假日库

采集策略：
- 首次运行：采集 1990-2030 年全部数据
- 后续运行：检查已有年份，只补充缺失年份
- 输出：写入 knowledge_library/calendar/calendar_knowledge.jsonl

去重机制：按 year 字段去重
"""

import json
import os
import sys
from datetime import datetime, timedelta

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.utils import get_timestamp, save_json, load_json

# ============================================================
# 配置
# ============================================================

KNOWLEDGE_LIBRARY_DIR = "knowledge_library"
CALENDAR_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "calendar")
CALENDAR_FILE = os.path.join(CALENDAR_DIR, "calendar_knowledge.jsonl")
META_FILE = os.path.join(CALENDAR_DIR, "meta.json")
CHECKPOINT_FILE = os.path.join(CALENDAR_DIR, "checkpoints", "collection_state.json")

# 默认采集年份范围
DEFAULT_START_YEAR = 1990
DEFAULT_END_YEAR = 2030

# 中国节假日（法定假日 + 调休），以 2026 年为例
# 实际应定期维护更新
CHINA_HOLIDAYS = {
    "2026": {
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
    },
}
CHINA_WORKDAY = {
    "2026": {
        "2026-02-14": "春节调休",
        "2026-02-21": "春节调休",
        "2026-04-26": "劳动节调休",
        "2026-05-09": "劳动节调休",
        "2026-09-26": "中秋节调休",
        "2026-10-10": "国庆节调休",
    },
}

HK_HOLIDAYS = {
    "2026": {
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
    },
}

US_HOLIDAYS = {
    "2026": {
        "2026-01-01": "New Year's Day",
        "2026-01-19": "Martin Luther King Jr. Day",
        "2026-02-16": "Washington's Birthday",
        "2026-04-03": "Good Friday",
        "2026-05-25": "Memorial Day",
        "2026-07-03": "Independence Day (observed)",
        "2026-09-07": "Labor Day",
        "2026-11-26": "Thanksgiving Day",
        "2026-12-25": "Christmas Day",
    },
}

DST_CONFIG = {
    "us": {
        "start_month": 3,
        "start_weekday": 6,
        "start_week": 2,
        "end_month": 11,
        "end_weekday": 6,
        "end_week": 1,
    }
}


# ============================================================
# DST 计算函数
# ============================================================

def get_dst_start(year: int, config: dict) -> datetime:
    """计算夏令时开始日期"""
    month = config["start_month"]
    weekday = config["start_weekday"]
    week_num = config["start_week"]

    first_day = datetime(year, month, 1)
    days_until_first_sunday = (weekday - first_day.weekday()) % 7
    first_sunday = first_day + timedelta(days=days_until_first_sunday)
    dst_start = first_sunday + timedelta(weeks=week_num - 1)
    return dst_start


def get_dst_end(year: int, config: dict) -> datetime:
    """计算夏令时结束日期"""
    month = config["end_month"]
    weekday = config["end_weekday"]
    week_num = config["end_week"]

    first_day = datetime(year, month, 1)
    days_until_first_sunday = (weekday - first_day.weekday()) % 7
    dst_end = first_day + timedelta(days=days_until_first_sunday)
    return dst_end


def is_dst_active(date: datetime, year: int) -> bool:
    """判断某日期是否处于美国夏令时"""
    config = DST_CONFIG["us"]
    dst_start = get_dst_start(year, config)
    dst_end = get_dst_end(year, config)
    return dst_start <= date < dst_end


# ============================================================
# 采集函数
# ============================================================

def fetch_trading_days_akshare(year: int) -> list:
    """
    从 akshare 获取 A 股交易日
    """
    try:
        import akshare as ak
        import pandas as pd

        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            print(f"⚠️ akshare 返回空数据 ({year})")
            return []

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[df["trade_date"].dt.year == year]

        trading_days = df["trade_date"].dt.strftime("%Y-%m-%d").tolist()
        print(f"✅ akshare 获取 {year} 年 A 股交易日: {len(trading_days)} 天")
        return trading_days

    except Exception as e:
        print(f"❌ akshare 获取 {year} 年交易日失败: {e}")
        return []


def generate_year_calendar(year: int, a_share_trading_days: list = None) -> dict:
    """
    生成指定年份的完整日历信息
    """
    if a_share_trading_days is None:
        a_share_trading_days = fetch_trading_days_akshare(year)

    config = DST_CONFIG["us"]
    dst_start = get_dst_start(year, config)
    dst_end = get_dst_end(year, config)

    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31)

    # 获取当年节假日字典
    year_str = str(year)
    a_share_holidays = CHINA_HOLIDAYS.get(year_str, {})
    a_share_workdays = CHINA_WORKDAY.get(year_str, {})
    hk_holidays = HK_HOLIDAYS.get(year_str, {})
    us_holidays = US_HOLIDAYS.get(year_str, {})

    days = []
    current = start_date

    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        weekday = current.weekday()
        is_weekend = weekday >= 5

        # ---- A 股交易日判断 ----
        if a_share_trading_days:
            is_a_share_trading = date_str in a_share_trading_days
        else:
            # 降级：基于规则
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
        elif date_str in hk_holidays:
            is_hk_trading = False
        else:
            is_hk_trading = True

        # ---- 美股交易日判断 ----
        if is_weekend:
            is_us_trading = False
        elif date_str in us_holidays:
            is_us_trading = False
        else:
            is_us_trading = True

        # ---- DST 状态 ----
        dst_active = is_dst_active(current, year)

        days.append({
            "date": date_str,
            "year": year,
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
            },
        })
        current += timedelta(days=1)

    return {
        "year": year,
        "total_days": len(days),
        "a_share_trading_days": sum(1 for d in days if d["a_share"]["is_trading_day"]),
        "hk_trading_days": sum(1 for d in days if d["hk"]["is_trading_day"]),
        "us_trading_days": sum(1 for d in days if d["us"]["is_trading_day"]),
        "dst_info": {
            "dst_start": dst_start.strftime("%Y-%m-%d"),
            "dst_end": dst_end.strftime("%Y-%m-%d"),
        },
        "days": days,
    }


def load_existing_years() -> set:
    """从已有 JSONL 文件中读取已采集的年份"""
    existing_years = set()

    if not os.path.exists(CALENDAR_FILE):
        return existing_years

    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        data = json.loads(line)
                        if "year" in data:
                            existing_years.add(data["year"])
                    except json.JSONDecodeError:
                        continue
        print(f"📂 已加载 {len(existing_years)} 个已采集年份: {sorted(existing_years)}")
    except Exception as e:
        print(f"⚠️ 读取已有数据失败: {e}")

    return existing_years


def append_year_to_knowledge(year_data: dict):
    """追加一年数据到 JSONL 文件"""
    # 确保目录存在
    os.makedirs(CALENDAR_DIR, exist_ok=True)
    os.makedirs(os.path.join(CALENDAR_DIR, "checkpoints"), exist_ok=True)

    with open(CALENDAR_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(year_data, ensure_ascii=False) + "\n")

    print(f"📝 已追加 {year_data['year']} 年数据")


def update_meta(existing_years: set):
    """更新元数据文件"""
    meta = {
        "data_type": "calendar",
        "description": "A股/港股/美股 交易日、节假日、DST 信息",
        "total_years": len(existing_years),
        "years": sorted(existing_years),
        "last_updated": get_timestamp(),
        "source": "akshare + local_holidays",
        "schema_version": "1.0",
    }

    save_json(META_FILE, meta)
    print(f"📋 元数据已更新: {META_FILE}")


# ============================================================
# 主函数
# ============================================================

def main():
    """主函数"""
    print("=" * 60)
    print("📅 万年历采集（知识库模式）")
    print("=" * 60)

    # 1. 加载已有年份
    existing_years = load_existing_years()

    # 2. 确定需要采集的年份
    start_year = DEFAULT_START_YEAR
    end_year = DEFAULT_END_YEAR

    # 动态扩展 end_year：如果当前年份 > end_year，自动扩展
    current_year = datetime.now().year
    if current_year > end_year:
        end_year = current_year + 1  # 预采下一年

    all_years = set(range(start_year, end_year + 1))
    missing_years = all_years - existing_years

    if not missing_years:
        print(f"✅ 所有年份 ({start_year} ~ {end_year}) 已采集，无需更新")
        print(f"📊 当前已有: {len(existing_years)} 年数据")
        update_meta(existing_years)
        return

    print(f"📊 需要采集 {len(missing_years)} 个缺失年份: {sorted(missing_years)}")

    # 3. 逐年代采集
    collected_count = 0
    failed_years = []

    for year in sorted(missing_years):
        print(f"\n--- 采集 {year} 年 ---")

        # 尝试从 akshare 获取
        a_share_trading_days = fetch_trading_days_akshare(year)

        # 如果 akshare 返回空，使用本地规则
        if not a_share_trading_days:
            print(f"⚠️ {year} 年 akshare 无数据，使用本地规则生成")
            # 本地规则：周末 + 节假日判断（不依赖 akshare）
            # 这里直接调用 generate_year_calendar 时不传 a_share_trading_days
            # 它会使用降级逻辑（本地节假日库）

        try:
            year_data = generate_year_calendar(year, a_share_trading_days)
            append_year_to_knowledge(year_data)
            collected_count += 1

            # 立即更新 meta（防止中途失败丢失进度）
            existing_years.add(year)
            update_meta(existing_years)

        except Exception as e:
            print(f"❌ 采集 {year} 年失败: {e}")
            failed_years.append(year)

    # 4. 最终报告
    print("\n" + "=" * 60)
    print("📊 采集报告")
    print("=" * 60)

    # 重新加载所有年份
    final_years = load_existing_years()

    print(f"   ✅ 成功采集: {collected_count} 年")
    print(f"   ❌ 失败: {len(failed_years)} 年" + (f" ({failed_years})" if failed_years else ""))
    print(f"   📂 当前总年份: {len(final_years)} 年")
    print(f"   📅 年份范围: {min(final_years) if final_years else 'N/A'} ~ {max(final_years) if final_years else 'N/A'}")

    if failed_years:
        print(f"\n⚠️ 以下年份采集失败，请手动检查:")
        for y in failed_years:
            print(f"   - {y}")

    print("\n✅ 万年历知识库更新完成")


if __name__ == "__main__":
    # 导入 pandas 用于 akshare 数据处理
    try:
        import pandas as pd
    except ImportError:
        print("⚠️ pandas 未安装，将使用本地规则生成日历")
    main()
