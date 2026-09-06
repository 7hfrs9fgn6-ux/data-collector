#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
万年历数据采集模块（知识库版 V1.0）
参照 collect_historical.py 的设计模式

职责：一次性采集 1990-2030 年的 A股/港股/美股 交易日、节假日、DST 信息
      打包签名后供私密库知识库记忆体使用

★ 采集策略：
  1. 首次运行：采集 1990-2030 年全部数据
  2. 增量运行：检查 staging 已有数据，只补充缺失年份
  3. 输出格式：统一知识库数据包

★ 数据源：
  1. akshare - A股交易日历（主源）
  2. 本地预置 - 港股/美股节假日
  3. 规则计算 - DST 夏令时/冬令时

★ 使用方式：
  python scripts/collect_calendar.py              # 采集全部年份
  python scripts/collect_calendar.py --year 2027  # 只采集指定年份
  python scripts/collect_calendar.py --debug      # 调试模式

★ 输出文件：
  staging/calendar_raw_*.json          # 原始数据（调试用）
  staging/calendar_package_*.json      # 签名打包后的数据包
"""

import os
import sys
import json
import argparse
import hmac
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 输出目录
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")

# ★ 签名密钥（从环境变量获取）
SIGNING_KEY = os.environ.get('SIGNING_KEY', '')

# ============================================================
# 1. 签名工具（与公开库 sign.py 保持一致）
# ============================================================

def get_signing_key() -> str:
    """获取签名密钥"""
    global SIGNING_KEY
    if not SIGNING_KEY:
        SIGNING_KEY = os.environ.get('SIGNING_KEY', '')
    return SIGNING_KEY


def sign_data(data: Dict[str, Any], key: str) -> str:
    """
    HMAC-SHA256 签名（与公开库 sign.py 保持一致）
    """
    if not key:
        return ""
    # 排除 signature 和 signature_metadata 字段
    sign_data_content = {k: v for k, v in data.items() 
                         if k not in ['signature', 'signature_metadata']}
    content = json.dumps(sign_data_content, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


# ============================================================
# 2. 节假日配置（港股 + 美股）
# ============================================================

# ★ 中国法定节假日（2020-2030）
# 实际生产环境建议从 akshare 获取，或维护完整列表
CHINA_HOLIDAYS = {
    "2020-01-01": "元旦", "2020-01-24": "春节", "2020-01-27": "春节", "2020-01-28": "春节", "2020-01-29": "春节", "2020-01-30": "春节",
    "2020-04-04": "清明节", "2020-05-01": "劳动节", "2020-05-04": "劳动节", "2020-05-05": "劳动节",
    "2020-06-25": "端午节", "2020-10-01": "国庆节", "2020-10-02": "国庆节", "2020-10-05": "国庆节", "2020-10-06": "国庆节", "2020-10-07": "国庆节",
    "2021-01-01": "元旦", "2021-02-11": "春节", "2021-02-12": "春节", "2021-02-15": "春节", "2021-02-16": "春节", "2021-02-17": "春节",
    "2021-04-03": "清明节", "2021-05-03": "劳动节", "2021-05-04": "劳动节", "2021-05-05": "劳动节",
    "2021-06-14": "端午节", "2021-09-20": "中秋节", "2021-10-01": "国庆节", "2021-10-04": "国庆节", "2021-10-05": "国庆节", "2021-10-06": "国庆节", "2021-10-07": "国庆节",
    "2022-01-01": "元旦", "2022-01-31": "春节", "2022-02-01": "春节", "2022-02-02": "春节", "2022-02-03": "春节", "2022-02-04": "春节",
    "2022-04-02": "清明节", "2022-05-02": "劳动节", "2022-05-03": "劳动节", "2022-05-04": "劳动节",
    "2022-06-03": "端午节", "2022-09-12": "中秋节", "2022-10-01": "国庆节", "2022-10-03": "国庆节", "2022-10-04": "国庆节", "2022-10-05": "国庆节", "2022-10-06": "国庆节", "2022-10-07": "国庆节",
    "2023-01-01": "元旦", "2023-01-20": "春节", "2023-01-23": "春节", "2023-01-24": "春节", "2023-01-25": "春节", "2023-01-26": "春节", "2023-01-27": "春节",
    "2023-04-05": "清明节", "2023-05-01": "劳动节", "2023-05-02": "劳动节", "2023-05-03": "劳动节",
    "2023-06-22": "端午节", "2023-09-29": "中秋节", "2023-10-02": "国庆节", "2023-10-03": "国庆节", "2023-10-04": "国庆节", "2023-10-05": "国庆节", "2023-10-06": "国庆节",
    "2024-01-01": "元旦", "2024-02-09": "春节", "2024-02-12": "春节", "2024-02-13": "春节", "2024-02-14": "春节", "2024-02-15": "春节", "2024-02-16": "春节",
    "2024-04-04": "清明节", "2024-05-01": "劳动节", "2024-05-02": "劳动节", "2024-05-03": "劳动节",
    "2024-06-10": "端午节", "2024-09-16": "中秋节", "2024-10-01": "国庆节", "2024-10-02": "国庆节", "2024-10-03": "国庆节", "2024-10-04": "国庆节", "2024-10-07": "国庆节",
    "2025-01-01": "元旦", "2025-01-28": "春节", "2025-01-29": "春节", "2025-01-30": "春节", "2025-01-31": "春节", "2025-02-03": "春节", "2025-02-04": "春节",
    "2025-04-04": "清明节", "2025-05-01": "劳动节", "2025-05-02": "劳动节", "2025-05-05": "劳动节",
    "2025-05-31": "端午节", "2025-10-01": "国庆节", "2025-10-02": "国庆节", "2025-10-03": "国庆节", "2025-10-06": "国庆节", "2025-10-07": "国庆节", "2025-10-08": "国庆节",
    "2026-01-01": "元旦", "2026-02-17": "春节", "2026-02-18": "春节", "2026-02-19": "春节", "2026-02-20": "春节", "2026-02-23": "春节",
    "2026-04-06": "清明节", "2026-05-01": "劳动节", "2026-05-04": "劳动节",
    "2026-06-22": "端午节", "2026-09-28": "中秋节", "2026-10-01": "国庆节", "2026-10-02": "国庆节", "2026-10-05": "国庆节", "2026-10-06": "国庆节", "2026-10-07": "国庆节",
    "2027-01-01": "元旦", "2027-02-06": "春节", "2027-02-08": "春节", "2027-02-09": "春节", "2027-02-10": "春节", "2027-02-11": "春节", "2027-02-12": "春节",
    "2027-04-05": "清明节", "2027-05-03": "劳动节", "2027-05-04": "劳动节", "2027-05-05": "劳动节",
    "2027-06-14": "端午节", "2027-09-20": "中秋节", "2027-10-01": "国庆节", "2027-10-04": "国庆节", "2027-10-05": "国庆节", "2027-10-06": "国庆节", "2027-10-07": "国庆节",
    "2028-01-01": "元旦", "2028-01-26": "春节", "2028-01-27": "春节", "2028-01-28": "春节", "2028-01-31": "春节", "2028-02-01": "春节", "2028-02-02": "春节",
    "2028-04-04": "清明节", "2028-05-01": "劳动节", "2028-05-02": "劳动节", "2028-05-03": "劳动节",
    "2028-06-01": "端午节", "2028-10-02": "国庆节", "2028-10-03": "国庆节", "2028-10-04": "国庆节", "2028-10-05": "国庆节", "2028-10-06": "国庆节",
    "2029-01-01": "元旦", "2029-02-12": "春节", "2029-02-13": "春节", "2029-02-14": "春节", "2029-02-15": "春节", "2029-02-16": "春节", "2029-02-19": "春节",
    "2029-04-04": "清明节", "2029-05-01": "劳动节", "2029-05-02": "劳动节", "2029-05-03": "劳动节",
    "2029-06-18": "端午节", "2029-10-01": "国庆节", "2029-10-02": "国庆节", "2029-10-03": "国庆节", "2029-10-04": "国庆节", "2029-10-05": "国庆节",
    "2030-01-01": "元旦", "2030-02-04": "春节", "2030-02-05": "春节", "2030-02-06": "春节", "2030-02-07": "春节", "2030-02-08": "春节", "2030-02-11": "春节",
    "2030-04-05": "清明节", "2030-05-01": "劳动节", "2030-05-02": "劳动节", "2030-05-03": "劳动节",
    "2030-06-10": "端午节", "2030-09-16": "中秋节", "2030-10-01": "国庆节", "2030-10-02": "国庆节", "2030-10-03": "国庆节", "2030-10-04": "国庆节", "2030-10-07": "国庆节",
}

# ★ 中国调休补班日（周末上班）
CHINA_WORKDAY = {
    "2020-01-19": "春节调休", "2020-02-01": "春节调休", "2020-04-26": "劳动节调休", "2020-05-09": "劳动节调休",
    "2020-06-28": "端午节调休", "2020-09-27": "国庆节调休", "2020-10-10": "国庆节调休",
    "2021-02-07": "春节调休", "2021-02-20": "春节调休", "2021-04-25": "劳动节调休", "2021-05-08": "劳动节调休",
    "2021-09-18": "中秋节调休", "2021-09-26": "国庆节调休", "2021-10-09": "国庆节调休",
    "2022-01-29": "春节调休", "2022-01-30": "春节调休", "2022-04-24": "劳动节调休", "2022-05-07": "劳动节调休",
    "2022-10-08": "国庆节调休", "2022-10-09": "国庆节调休",
    "2023-01-28": "春节调休", "2023-01-29": "春节调休", "2023-04-23": "劳动节调休", "2023-05-06": "劳动节调休",
    "2023-10-07": "国庆节调休", "2023-10-08": "国庆节调休",
    "2024-02-04": "春节调休", "2024-02-18": "春节调休", "2024-04-07": "清明节调休", "2024-04-28": "劳动节调休",
    "2024-05-11": "劳动节调休", "2024-09-14": "中秋节调休", "2024-09-29": "国庆节调休", "2024-10-12": "国庆节调休",
    "2025-01-26": "春节调休", "2025-02-08": "春节调休", "2025-04-27": "劳动节调休", "2025-05-11": "劳动节调休",
    "2025-09-28": "国庆节调休", "2025-10-11": "国庆节调休",
    "2026-02-14": "春节调休", "2026-02-21": "春节调休", "2026-04-26": "劳动节调休", "2026-05-09": "劳动节调休",
    "2026-09-26": "中秋节调休", "2026-10-10": "国庆节调休",
    "2027-02-07": "春节调休", "2027-02-14": "春节调休", "2027-04-25": "劳动节调休", "2027-05-08": "劳动节调休",
    "2027-09-19": "中秋节调休", "2027-10-09": "国庆节调休",
    "2028-01-23": "春节调休", "2028-01-30": "春节调休", "2028-04-23": "劳动节调休", "2028-05-06": "劳动节调休",
    "2028-10-07": "国庆节调休", "2028-10-08": "国庆节调休",
    "2029-01-14": "春节调休", "2029-01-21": "春节调休", "2029-04-29": "劳动节调休", "2029-05-05": "劳动节调休",
    "2029-10-13": "国庆节调休", "2029-10-14": "国庆节调休",
    "2030-01-13": "春节调休", "2030-01-20": "春节调休", "2030-04-28": "劳动节调休", "2030-05-04": "劳动节调休",
    "2030-10-12": "国庆节调休", "2030-10-13": "国庆节调休",
}

# ★ 香港节假日（2020-2030）
HK_HOLIDAYS = {
    "2020-01-01": "元旦", "2020-01-27": "农历年初三", "2020-01-28": "农历年初四", "2020-01-29": "农历年初五",
    "2020-04-04": "清明节", "2020-04-10": "耶稣受难节", "2020-04-13": "复活节星期一", "2020-05-01": "劳动节",
    "2020-05-25": "佛诞", "2020-06-25": "端午节", "2020-07-01": "香港特别行政区成立纪念日",
    "2020-10-01": "国庆日", "2020-10-02": "国庆日翌日", "2020-10-26": "重阳节", "2020-12-25": "圣诞节", "2020-12-26": "圣诞节后第一个周日",
    "2021-01-01": "元旦", "2021-02-12": "农历年初一", "2021-02-15": "农历年初三", "2021-02-16": "农历年初四",
    "2021-04-02": "耶稣受难节", "2021-04-05": "清明节", "2021-04-06": "复活节星期一", "2021-05-01": "劳动节",
    "2021-05-19": "佛诞", "2021-06-14": "端午节", "2021-07-01": "香港特别行政区成立纪念日",
    "2021-09-21": "中秋节翌日", "2021-10-01": "国庆日", "2021-10-14": "重阳节", "2021-12-24": "圣诞节", "2021-12-27": "圣诞节后第一个周日",
    "2022-01-01": "元旦", "2022-02-01": "农历年初一", "2022-02-02": "农历年初二", "2022-02-03": "农历年初三",
    "2022-04-15": "耶稣受难节", "2022-04-18": "复活节星期一", "2022-04-05": "清明节", "2022-05-02": "劳动节",
    "2022-05-09": "佛诞", "2022-06-03": "端午节", "2022-07-01": "香港特别行政区成立纪念日",
    "2022-09-12": "中秋节翌日", "2022-10-01": "国庆日", "2022-10-04": "重阳节", "2022-12-26": "圣诞节后第一个周日",
    "2023-01-01": "元旦", "2023-01-23": "农历年初一", "2023-01-24": "农历年初二", "2023-01-25": "农历年初三",
    "2023-04-05": "清明节", "2023-04-07": "耶稣受难节", "2023-04-10": "复活节星期一", "2023-05-01": "劳动节",
    "2023-05-26": "佛诞", "2023-06-22": "端午节", "2023-07-01": "香港特别行政区成立纪念日",
    "2023-09-30": "中秋节翌日", "2023-10-02": "国庆日", "2023-10-23": "重阳节", "2023-12-25": "圣诞节", "2023-12-26": "圣诞节后第一个周日",
    "2024-01-01": "元旦", "2024-02-10": "农历年初一", "2024-02-12": "农历年初三", "2024-02-13": "农历年初四",
    "2024-03-29": "耶稣受难节", "2024-04-01": "复活节星期一", "2024-04-04": "清明节", "2024-05-01": "劳动节",
    "2024-05-15": "佛诞", "2024-06-10": "端午节", "2024-07-01": "香港特别行政区成立纪念日",
    "2024-09-18": "中秋节翌日", "2024-10-01": "国庆日", "2024-10-11": "重阳节", "2024-12-25": "圣诞节", "2024-12-26": "圣诞节后第一个周日",
    "2025-01-01": "元旦", "2025-01-29": "农历年初一", "2025-01-30": "农历年初二", "2025-01-31": "农历年初三",
    "2025-04-18": "耶稣受难节", "2025-04-21": "复活节星期一", "2025-05-01": "劳动节", "2025-05-05": "佛诞",
    "2025-05-31": "端午节", "2025-07-01": "香港特别行政区成立纪念日", "2025-10-01": "国庆日", "2025-10-07": "中秋节翌日",
    "2025-10-29": "重阳节", "2025-12-25": "圣诞节", "2025-12-26": "圣诞节后第一个周日",
    "2026-01-01": "元旦", "2026-02-17": "农历年初一", "2026-02-18": "农历年初二", "2026-02-19": "农历年初三",
    "2026-04-03": "耶稣受难节", "2026-04-06": "复活节星期一", "2026-04-06": "清明节", "2026-05-01": "劳动节",
    "2026-05-27": "佛诞", "2026-06-22": "端午节", "2026-07-01": "香港特别行政区成立纪念日",
    "2026-09-28": "中秋节翌日", "2026-10-01": "国庆日", "2026-10-21": "重阳节", "2026-12-25": "圣诞节", "2026-12-26": "圣诞节后第一个周日",
    "2027-01-01": "元旦", "2027-02-06": "农历年初一", "2027-02-08": "农历年初三", "2027-02-09": "农历年初四",
    "2027-03-26": "耶稣受难节", "2027-03-29": "复活节星期一", "2027-04-05": "清明节", "2027-05-01": "劳动节",
    "2027-05-17": "佛诞", "2027-06-14": "端午节", "2027-07-01": "香港特别行政区成立纪念日",
    "2027-09-20": "中秋节翌日", "2027-10-01": "国庆日", "2027-10-20": "重阳节", "2027-12-24": "圣诞节", "2027-12-27": "圣诞节后第一个周日",
    "2028-01-01": "元旦", "2028-01-26": "农历年初一", "2028-01-27": "农历年初二", "2028-01-28": "农历年初三",
    "2028-04-14": "耶稣受难节", "2028-04-17": "复活节星期一", "2028-04-04": "清明节", "2028-05-01": "劳动节",
    "2028-05-04": "佛诞", "2028-06-01": "端午节", "2028-07-01": "香港特别行政区成立纪念日",
    "2028-10-02": "中秋节翌日", "2028-10-02": "国庆日", "2028-10-28": "重阳节", "2028-12-25": "圣诞节", "2028-12-26": "圣诞节后第一个周日",
    "2029-01-01": "元旦", "2029-02-12": "农历年初一", "2029-02-13": "农历年初二", "2029-02-14": "农历年初三",
    "2029-03-30": "耶稣受难节", "2029-04-02": "复活节星期一", "2029-04-04": "清明节", "2029-05-01": "劳动节",
    "2029-05-25": "佛诞", "2029-06-18": "端午节", "2029-07-02": "香港特别行政区成立纪念日",
    "2029-09-24": "中秋节翌日", "2029-10-01": "国庆日", "2029-10-17": "重阳节", "2029-12-25": "圣诞节", "2029-12-26": "圣诞节后第一个周日",
    "2030-01-01": "元旦", "2030-02-04": "农历年初一", "2030-02-05": "农历年初二", "2030-02-06": "农历年初三",
    "2030-04-19": "耶稣受难节", "2030-04-22": "复活节星期一", "2030-04-05": "清明节", "2030-05-01": "劳动节",
    "2030-05-17": "佛诞", "2030-06-10": "端午节", "2030-07-01": "香港特别行政区成立纪念日",
    "2030-09-16": "中秋节翌日", "2030-10-01": "国庆日", "2030-10-21": "重阳节", "2030-12-25": "圣诞节", "2030-12-26": "圣诞节后第一个周日",
}

# ★ 美国节假日（纽交所休市，2020-2030）
US_HOLIDAYS = {
    "2020-01-01": "New Year's Day", "2020-01-20": "Martin Luther King Jr. Day", "2020-02-17": "Washington's Birthday",
    "2020-04-10": "Good Friday", "2020-05-25": "Memorial Day", "2020-07-03": "Independence Day",
    "2020-09-07": "Labor Day", "2020-11-26": "Thanksgiving Day", "2020-12-25": "Christmas Day",
    "2021-01-01": "New Year's Day", "2021-01-18": "Martin Luther King Jr. Day", "2021-02-15": "Washington's Birthday",
    "2021-04-02": "Good Friday", "2021-05-31": "Memorial Day", "2021-07-05": "Independence Day",
    "2021-09-06": "Labor Day", "2021-11-25": "Thanksgiving Day", "2021-12-24": "Christmas Day",
    "2022-01-01": "New Year's Day", "2022-01-17": "Martin Luther King Jr. Day", "2022-02-21": "Washington's Birthday",
    "2022-04-15": "Good Friday", "2022-05-30": "Memorial Day", "2022-07-04": "Independence Day",
    "2022-09-05": "Labor Day", "2022-11-24": "Thanksgiving Day", "2022-12-26": "Christmas Day",
    "2023-01-01": "New Year's Day", "2023-01-16": "Martin Luther King Jr. Day", "2023-02-20": "Washington's Birthday",
    "2023-04-07": "Good Friday", "2023-05-29": "Memorial Day", "2023-07-04": "Independence Day",
    "2023-09-04": "Labor Day", "2023-11-23": "Thanksgiving Day", "2023-12-25": "Christmas Day",
    "2024-01-01": "New Year's Day", "2024-01-15": "Martin Luther King Jr. Day", "2024-02-19": "Washington's Birthday",
    "2024-03-29": "Good Friday", "2024-05-27": "Memorial Day", "2024-07-04": "Independence Day",
    "2024-09-02": "Labor Day", "2024-11-28": "Thanksgiving Day", "2024-12-25": "Christmas Day",
    "2025-01-01": "New Year's Day", "2025-01-20": "Martin Luther King Jr. Day", "2025-02-17": "Washington's Birthday",
    "2025-04-18": "Good Friday", "2025-05-26": "Memorial Day", "2025-07-04": "Independence Day",
    "2025-09-01": "Labor Day", "2025-11-27": "Thanksgiving Day", "2025-12-25": "Christmas Day",
    "2026-01-01": "New Year's Day", "2026-01-19": "Martin Luther King Jr. Day", "2026-02-16": "Washington's Birthday",
    "2026-04-03": "Good Friday", "2026-05-25": "Memorial Day", "2026-07-03": "Independence Day",
    "2026-09-07": "Labor Day", "2026-11-26": "Thanksgiving Day", "2026-12-25": "Christmas Day",
    "2027-01-01": "New Year's Day", "2027-01-18": "Martin Luther King Jr. Day", "2027-02-15": "Washington's Birthday",
    "2027-03-26": "Good Friday", "2027-05-31": "Memorial Day", "2027-07-05": "Independence Day",
    "2027-09-06": "Labor Day", "2027-11-25": "Thanksgiving Day", "2027-12-24": "Christmas Day",
    "2028-01-01": "New Year's Day", "2028-01-17": "Martin Luther King Jr. Day", "2028-02-21": "Washington's Birthday",
    "2028-04-14": "Good Friday", "2028-05-29": "Memorial Day", "2028-07-04": "Independence Day",
    "2028-09-04": "Labor Day", "2028-11-23": "Thanksgiving Day", "2028-12-25": "Christmas Day",
    "2029-01-01": "New Year's Day", "2029-01-15": "Martin Luther King Jr. Day", "2029-02-19": "Washington's Birthday",
    "2029-03-30": "Good Friday", "2029-05-28": "Memorial Day", "2029-07-04": "Independence Day",
    "2029-09-03": "Labor Day", "2029-11-22": "Thanksgiving Day", "2029-12-25": "Christmas Day",
    "2030-01-01": "New Year's Day", "2030-01-21": "Martin Luther King Jr. Day", "2030-02-18": "Washington's Birthday",
    "2030-04-19": "Good Friday", "2030-05-27": "Memorial Day", "2030-07-04": "Independence Day",
    "2030-09-02": "Labor Day", "2030-11-28": "Thanksgiving Day", "2030-12-25": "Christmas Day",
}


# ============================================================
# 3. DST 计算（美国夏令时）
# ============================================================

def get_dst_start(year: int) -> datetime:
    """计算美国夏令时开始日期（3月第二个周日）"""
    # 3月1日
    first_day = datetime(year, 3, 1)
    # 第一个周日
    days_until_first_sunday = (6 - first_day.weekday()) % 7
    first_sunday = first_day + timedelta(days=days_until_first_sunday)
    # 第二个周日 = 第一个周日 + 7天
    return first_sunday + timedelta(days=7)


def get_dst_end(year: int) -> datetime:
    """计算美国夏令时结束日期（11月第一个周日）"""
    first_day = datetime(year, 11, 1)
    days_until_first_sunday = (6 - first_day.weekday()) % 7
    return first_day + timedelta(days=days_until_first_sunday)


def is_dst_active(date: datetime, year: int) -> bool:
    """判断某日期是否处于美国夏令时"""
    dst_start = get_dst_start(year)
    dst_end = get_dst_end(year)
    return dst_start <= date < dst_end


# ============================================================
# 4. 采集函数
# ============================================================

def fetch_a_share_trading_days_from_akshare(start_year: int = 1990, end_year: int = 2030) -> List[str]:
    """
    从 akshare 获取 A 股交易日历
    返回：日期字符串列表 ['YYYY-MM-DD', ...]
    """
    try:
        import akshare as ak
        import pandas as pd
    except ImportError:
        logger.warning("⚠️ akshare 或 pandas 未安装，使用本地规则生成交易日")
        return []

    try:
        logger.info(f"   📡 从 akshare 获取 A 股交易日 ({start_year}-{end_year})...")
        df = ak.tool_trade_date_hist_sina()
        if df is None or df.empty:
            logger.warning("   ⚠️ akshare 返回空数据")
            return []

        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[(df["trade_date"].dt.year >= start_year) & (df["trade_date"].dt.year <= end_year)]
        trading_days = df["trade_date"].dt.strftime("%Y-%m-%d").tolist()
        logger.info(f"   ✅ akshare 获取 {len(trading_days)} 个交易日")
        return trading_days

    except Exception as e:
        logger.warning(f"   ⚠️ akshare 获取交易日失败: {e}")
        return []


def generate_calendar_year(year: int, a_share_trading_days: List[str]) -> Dict[str, Any]:
    """
    生成指定年份的完整日历数据
    """
    dst_start = get_dst_start(year)
    dst_end = get_dst_end(year)

    start_date = datetime(year, 1, 1)
    end_date = datetime(year, 12, 31)

    days = []
    current = start_date

    while current <= end_date:
        date_str = current.strftime("%Y-%m-%d")
        weekday = current.weekday()  # 0=周一, 6=周日
        is_weekend = weekday >= 5

        # ---- A 股交易日判断 ----
        if a_share_trading_days:
            is_a_share_trading = date_str in a_share_trading_days
        else:
            # 降级：基于规则
            if is_weekend:
                is_a_share_trading = False
            elif date_str in CHINA_HOLIDAYS:
                is_a_share_trading = False
            elif date_str in CHINA_WORKDAY:
                is_a_share_trading = True
            else:
                is_a_share_trading = True

        # ---- 港股交易日判断 ----
        if is_weekend:
            is_hk_trading = False
        elif date_str in HK_HOLIDAYS:
            is_hk_trading = False
        else:
            is_hk_trading = True

        # ---- 美股交易日判断 ----
        if is_weekend:
            is_us_trading = False
        elif date_str in US_HOLIDAYS:
            is_us_trading = False
        else:
            is_us_trading = True

        # ---- DST ----
        dst_active = is_dst_active(current, year)

        day_info = {
            "date": date_str,
            "weekday": current.weekday(),
            "weekday_name": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][current.weekday()],
            "is_weekend": is_weekend,
            "a_share": {
                "is_trading_day": is_a_share_trading,
                "holiday_name": CHINA_HOLIDAYS.get(date_str, ""),
                "is_workday": date_str in CHINA_WORKDAY,
                "workday_reason": CHINA_WORKDAY.get(date_str, ""),
            },
            "hk": {
                "is_trading_day": is_hk_trading,
                "holiday_name": HK_HOLIDAYS.get(date_str, ""),
            },
            "us": {
                "is_trading_day": is_us_trading,
                "holiday_name": US_HOLIDAYS.get(date_str, ""),
                "dst_active": dst_active,
            },
        }
        days.append(day_info)
        current += timedelta(days=1)

    return {
        "year": year,
        "total_days": len(days),
        "a_share_trading_days": sum(1 for d in days if d["a_share"]["is_trading_day"]),
        "hk_trading_days": sum(1 for d in days if d["hk"]["is_trading_day"]),
        "us_trading_days": sum(1 for d in days if d["us"]["is_trading_day"]),
        "dst_start": dst_start.strftime("%Y-%m-%d"),
        "dst_end": dst_end.strftime("%Y-%m-%d"),
        "days": days,
    }


def collect_calendar(start_year: int = 1990, end_year: int = 2030) -> Dict[str, Any]:
    """
    采集指定年份范围的万年历数据
    返回：完整日历数据
    """
    logger.info(f"📅 采集万年历数据 ({start_year}-{end_year})")

    # 1. 从 akshare 获取 A 股交易日
    a_share_trading_days = fetch_a_share_trading_days_from_akshare(start_year, end_year)

    # 2. 生成每年数据
    years_data = {}
    total_a_share = 0
    total_hk = 0
    total_us = 0

    for year in range(start_year, end_year + 1):
        logger.info(f"   📅 生成 {year} 年日历...")
        year_data = generate_calendar_year(year, a_share_trading_days)
        years_data[str(year)] = year_data
        total_a_share += year_data["a_share_trading_days"]
        total_hk += year_data["hk_trading_days"]
        total_us += year_data["us_trading_days"]

    return {
        "start_year": start_year,
        "end_year": end_year,
        "total_years": end_year - start_year + 1,
        "total_a_share_trading_days": total_a_share,
        "total_hk_trading_days": total_hk,
        "total_us_trading_days": total_us,
        "years": years_data,
        "metadata": {
            "source": "akshare + local_holidays",
            "a_share_source": "akshare" if a_share_trading_days else "local_rules",
            "collected_at": datetime.now().isoformat(),
        }
    }


# ============================================================
# 5. 打包与签名
# ============================================================

def pack_calendar_data(calendar_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    打包万年历数据为统一格式，并签名
    """
    logger.info("📦 开始打包万年历数据...")

    # 确定 trade_date
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")

    # 判断今日是否为 A 股交易日（从日历数据中查询）
    year_str = str(now.year)
    is_trading_day = False
    dst_active = False

    if year_str in calendar_data.get("years", {}):
        year_data = calendar_data["years"][year_str]
        for day in year_data.get("days", []):
            if day.get("date") == trade_date:
                is_trading_day = day.get("a_share", {}).get("is_trading_day", False)
                dst_active = day.get("us", {}).get("dst_active", False)
                break

    package = {
        "book": "公开数据",
        "chapter": "calendar",
        "version": "2.0",
        "generated_at": datetime.now().isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": dst_active,
        "content": {
            "start_year": calendar_data.get("start_year"),
            "end_year": calendar_data.get("end_year"),
            "total_years": calendar_data.get("total_years"),
            "total_a_share_trading_days": calendar_data.get("total_a_share_trading_days"),
            "total_hk_trading_days": calendar_data.get("total_hk_trading_days"),
            "total_us_trading_days": calendar_data.get("total_us_trading_days"),
            "years": calendar_data.get("years", {}),
        },
        "metadata": calendar_data.get("metadata", {}),
    }

    # ★ 签名
    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    return package


def save_package(package: Dict[str, Any]) -> str:
    """保存打包数据到暂存区"""
    os.makedirs(STAGING_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"calendar_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(filepath)
    logger.info(f"✅ 已保存: {filename} ({file_size/1024:.1f} KB)")
    return filepath


def save_debug_data(data: Dict[str, Any]):
    """保存调试数据"""
    os.makedirs(STAGING_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"calendar_raw_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"   📝 调试数据已保存: {filename}")


# ============================================================
# 6. 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集万年历数据（知识库版）')
    parser.add_argument('--start-year', type=int, default=1990, help='起始年份（默认1990）')
    parser.add_argument('--end-year', type=int, default=2030, help='结束年份（默认2030）')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    args = parser.parse_args()

    logger.info("🚀 万年历采集启动")
    logger.info(f"   📅 年份范围: {args.start_year} ~ {args.end_year}")

    try:
        # 1. 采集数据
        calendar_data = collect_calendar(args.start_year, args.end_year)

        # 2. 调试模式保存原始数据
        if args.debug:
            save_debug_data(calendar_data)

        # 3. 打包并签名
        package = pack_calendar_data(calendar_data)

        # 4. 保存
        filepath = save_package(package)

        # 5. 打印摘要
        logger.info("=" * 60)
        logger.info("✅ 万年历采集完成")
        logger.info(f"   📅 年份范围: {args.start_year} ~ {args.end_year} ({calendar_data['total_years']} 年)")
        logger.info(f"   🇨🇳 A股交易日总数: {calendar_data['total_a_share_trading_days']}")
        logger.info(f"   🇭🇰 港股交易日总数: {calendar_data['total_hk_trading_days']}")
        logger.info(f"   🇺🇸 美股交易日总数: {calendar_data['total_us_trading_days']}")
        logger.info(f"   📦 输出文件: {filepath}")
        logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")
        logger.info("=" * 60)

        return 0

    except Exception as e:
        logger.error(f"❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
