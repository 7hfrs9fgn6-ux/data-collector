#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万年历数据打包模块（知识库模式）
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

KNOWLEDGE_LIBRARY_DIR = "knowledge_library"
CALENDAR_DIR = os.path.join(KNOWLEDGE_LIBRARY_DIR, "calendar")
CALENDAR_FILE = os.path.join(CALENDAR_DIR, "calendar_knowledge.jsonl")
META_FILE = os.path.join(CALENDAR_DIR, "meta.json")

BOOK_NAME = "公开数据"
CHAPTER_NAME = "calendar_status"
VERSION = "2.0"

SIGNING_KEY = os.environ.get("SIGNING_KEY", "")


def find_date_in_knowledge(date_str: str, year: int) -> dict:
    """在知识库中查找指定日期的信息"""
    if not os.path.exists(CALENDAR_FILE):
        return None

    try:
        with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    year_data = json.loads(line)
                    if year_data.get("year") == year:
                        for day in year_data.get("days", []):
                            if day.get("date") == date_str:
                                return day
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"⚠️ 读取知识库失败: {e}")

    return None


def load_meta_info() -> dict:
    """加载元数据信息，如果不存在则从 JSONL 中提取"""
    meta = {}

    # 优先读取 meta.json
    if os.path.exists(META_FILE):
        try:
            meta = load_json(META_FILE)
            return meta
        except Exception as e:
            print(f"⚠️ 读取 meta.json 失败: {e}")

    # 降级：从 JSONL 文件中提取年份
    if os.path.exists(CALENDAR_FILE):
        years = []
        try:
            with open(CALENDAR_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            data = json.loads(line)
                            if "year" in data:
                                years.append(data["year"])
                        except:
                            continue
            if years:
                meta = {
                    "total_years": len(years),
                    "years": sorted(years),
                    "last_updated": get_timestamp(),
                }
                print(f"📊 从 JSONL 提取年份信息: {len(years)} 年")
        except Exception as e:
            print(f"⚠️ 读取 JSONL 失败: {e}")

    return meta


def get_current_date_status() -> dict:
    """获取当前日期的状态信息"""
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    year = now.year

    day_info = find_date_in_knowledge(date_str, year)

    if day_info is None:
        is_weekend = now.weekday() >= 5
        return {
            "date": date_str,
            "year": year,
            "is_trading_day": not is_weekend,
            "is_weekend": is_weekend,
            "dst_active": False,
            "source": "fallback_rules",
            "holiday_name": "",
        }

    return {
        "date": date_str,
        "year": year,
        "is_trading_day": day_info.get("a_share", {}).get("is_trading_day", False),
        "is_weekend": day_info.get("is_weekend", False),
        "dst_active": day_info.get("us", {}).get("dst_active", False),
        "holiday_name": day_info.get("a_share", {}).get("holiday_name", ""),
        "source": "knowledge_library",
    }


def main():
    """主函数"""
    print("=" * 60)
    print("📦 万年历状态打包（知识库模式）")
    print("=" * 60)

    os.makedirs("staging", exist_ok=True)

    if not SIGNING_KEY:
        print("⚠️ 警告: SIGNING_KEY 环境变量未设置")

    # 1. 获取当前日期状态
    status = get_current_date_status()

    print(f"\n📅 当前日期状态:")
    print(f"   📅 日期: {status['date']}")
    print(f"   📊 交易日: {'✅' if status['is_trading_day'] else '❌'}")
    print(f"   🕐 DST 状态: {'✅ 夏令时' if status['dst_active'] else '❌ 冬令时'}")
    if status.get('holiday_name'):
        print(f"   🎉 节假日: {status['holiday_name']}")

    # 2. 加载 meta 信息
    meta = load_meta_info()
    years_range = ""
    if meta.get("years"):
        years_list = meta.get("years", [])
        years_range = f"{years_list[0]} ~ {years_list[-1]}" if years_list else "N/A"

    # 3. 构建数据包
    package = {
        "book": BOOK_NAME,
        "chapter": CHAPTER_NAME,
        "version": VERSION,
        "generated_at": get_timestamp(),
        "trade_date": status["date"],
        "is_trading_day": status["is_trading_day"],
        "dst_active": status["dst_active"],
        "content": {
            "current_date": status["date"],
            "is_trading_day": status["is_trading_day"],
            "is_weekend": status["is_weekend"],
            "dst_active": status["dst_active"],
            "holiday_name": status.get("holiday_name", ""),
            "source": status.get("source", ""),
            "knowledge_summary": {
                "total_years": meta.get("total_years", 0),
                "years_range": years_range,
                "last_updated": meta.get("last_updated", ""),
            }
        },
    }

    # 4. 签名
    if SIGNING_KEY:
        signed_package = sign_data(package, SIGNING_KEY)
    else:
        signed_package = package
        print("⚠️ 未签名（SIGNING_KEY 未设置）")

    # 5. 保存打包文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    package_file = f"staging/calendar_status_package_{timestamp}.json"

    # ✅ 正确：文件路径在前，数据在后
    save_json(package_file, signed_package)
    print(f"\n✅ 状态包已保存: {package_file}")

    print("\n✅ 万年历状态打包完成")


if __name__ == "__main__":
    main()
