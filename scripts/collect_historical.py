#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据采集模块
版本： 1.0
创建日期： 2026-08-19
职责： 采集几十年历史行情、宏观、事件数据

★ 采集内容：
  1. 历史行情数据 - 上证/深证/创业板 日线（30年）
  2. 历史宏观数据 - GDP、CPI、PPI、PMI、利率、社融
  3. 历史事件数据 - 重大政策、经济事件
  4. 历史板块数据 - 申万一级行业历史表现

★ 使用方式：
  python scripts/collect_historical.py --type market --years 30
  python scripts/collect_historical.py --type macro --years 30
  python scripts/collect_historical.py --type events --years 30
  python scripts/collect_historical.py --type sector --years 20
"""

import os
import sys
import json
import argparse
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 输出目录
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")


# ============================================================
# 1. 历史行情数据
# ============================================================

def fetch_historical_market(years: int = 30) -> Dict[str, Any]:
    """
    采集历史行情数据（上证、深证、创业板）

    Returns:
        {
            "type": "historical_market",
            "period": {"start": "1990-01-01", "end": "2026-08-19"},
            "data": {
                "上证指数": [{"date": "1990-12-19", "close": 99.98, ...}, ...],
                "深证成指": [...],
                "创业板指": [...]
            }
        }
    """
    logger.info(f"📈 开始采集历史行情数据 (回溯 {years} 年)")

    result = {
        "type": "historical_market",
        "period": {
            "start": (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d")
        },
        "data": {},
        "metadata": {
            "source": "akshare",
            "collected_at": datetime.now().isoformat()
        }
    }

    try:
        import akshare as ak
    except ImportError:
        logger.error("❌ akshare 未安装，无法采集历史行情数据")
        return result

    indices = [
        ("上证指数", "000001"),
        ("深证成指", "399001"),
        ("创业板指", "399006"),
    ]

    for name, code in indices:
        try:
            logger.info(f"   采集 {name} ({code})...")
            df = ak.stock_zh_index_daily(symbol=f"sh{code}")

            if df is not None and not df.empty:
                # 转换为字典列表
                data = []
                for _, row in df.iterrows():
                    # 只保留必要字段
                    record = {
                        "date": row.get('date', '').strftime("%Y-%m-%d") if hasattr(row.get('date', ''), 'strftime') else str(row.get('date', '')),
                        "open": float(row.get('open', 0)),
                        "high": float(row.get('high', 0)),
                        "low": float(row.get('low', 0)),
                        "close": float(row.get('close', 0)),
                        "volume": float(row.get('volume', 0))
                    }
                    data.append(record)

                # 限制数据量（只保留最近 years 年）
                if years > 0 and data:
                    cutoff_date = datetime.now() - timedelta(days=years * 365)
                    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
                    data = [d for d in data if d.get('date', '') >= cutoff_str]

                result["data"][name] = data
                logger.info(f"   ✅ {name}: {len(data)} 条记录")
            else:
                logger.warning(f"   ⚠️ {name}: 无数据")

            # 限流
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"   ⚠️ {name}: 采集失败 - {e}")

    return result


# ============================================================
# 2. 历史宏观数据
# ============================================================

def fetch_historical_macro(years: int = 30) -> Dict[str, Any]:
    """
    采集历史宏观数据

    Returns:
        {
            "type": "historical_macro",
            "period": {...},
            "data": {
                "GDP": [{"year": 1990, "value": ...}, ...],
                "CPI": [{"date": "1990-01", "value": ...}, ...],
                ...
            }
        }
    """
    logger.info(f"🏛️ 开始采集历史宏观数据 (回溯 {years} 年)")

    result = {
        "type": "historical_macro",
        "period": {
            "start": (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d")
        },
        "data": {},
        "metadata": {
            "source": "akshare",
            "collected_at": datetime.now().isoformat()
        }
    }

    try:
        import akshare as ak
    except ImportError:
        logger.error("❌ akshare 未安装，无法采集历史宏观数据")
        return result

    # ---- GDP ----
    try:
        logger.info("   采集 GDP 数据...")
        df = ak.macro_china_gdp_yearly()
        if df is not None and not df.empty:
            data = []
            for _, row in df.iterrows():
                year = str(row.get('年份', ''))
                if year:
                    data.append({
                        "year": year,
                        "gdp_yi": float(row.get('国内生产总值_亿元', 0)),
                        "growth": float(row.get('国内生产总值增长率_%', 0))
                    })
            result["data"]["GDP"] = data
            logger.info(f"   ✅ GDP: {len(data)} 条记录")
        else:
            logger.warning("   ⚠️ GDP: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ GDP: 采集失败 - {e}")

    # ---- CPI ----
    try:
        logger.info("   采集 CPI 数据...")
        df = ak.macro_china_cpi_monthly()
        if df is not None and not df.empty:
            data = []
            for _, row in df.iterrows():
                date = str(row.get('日期', ''))
                if date:
                    data.append({
                        "date": date,
                        "cpi": float(row.get('当月', 0)),
                        "cpi_year_over_year": float(row.get('同比增长', 0))
                    })
            # 限制数据量
            if years > 0 and data:
                cutoff_date = datetime.now() - timedelta(days=years * 365)
                cutoff_str = cutoff_date.strftime("%Y-%m")
                data = [d for d in data if d.get('date', '') >= cutoff_str]

            result["data"]["CPI"] = data
            logger.info(f"   ✅ CPI: {len(data)} 条记录")
        else:
            logger.warning("   ⚠️ CPI: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ CPI: 采集失败 - {e}")

    # ---- PMI ----
    try:
        logger.info("   采集 PMI 数据...")
        df = ak.macro_china_pmi_yearly()
        if df is not None and not df.empty:
            data = []
            for _, row in df.iterrows():
                date = str(row.get('日期', ''))
                if date:
                    data.append({
                        "date": date,
                        "pmi": float(row.get('PMI', 0))
                    })
            result["data"]["PMI"] = data
            logger.info(f"   ✅ PMI: {len(data)} 条记录")
        else:
            logger.warning("   ⚠️ PMI: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ PMI: 采集失败 - {e}")

    # ---- 利率 ----
    try:
        logger.info("   采集利率数据...")
        df = ak.macro_china_interest_rate()
        if df is not None and not df.empty:
            data = []
            for _, row in df.iterrows():
                date = str(row.get('日期', ''))
                if date:
                    data.append({
                        "date": date,
                        "rate_1y": float(row.get('一年期存款利率', 0)) if row.get('一年期存款利率') else None,
                        "rate_5y": float(row.get('五年期贷款利率', 0)) if row.get('五年期贷款利率') else None
                    })
            result["data"]["InterestRate"] = data
            logger.info(f"   ✅ 利率: {len(data)} 条记录")
        else:
            logger.warning("   ⚠️ 利率: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ 利率: 采集失败 - {e}")

    return result


# ============================================================
# 3. 历史事件数据
# ============================================================

def fetch_historical_events(years: int = 30) -> Dict[str, Any]:
    """
    采集历史事件数据（政策、经济事件）

    注：由于历史事件数据来源有限，这里使用预置的公开事件库
    实际生产环境中可接入 Wikipedia API 或新闻数据库

    Returns:
        {
            "type": "historical_events",
            "period": {...},
            "data": [...],
            "metadata": {...}
        }
    """
    logger.info(f"📰 开始采集历史事件数据 (回溯 {years} 年)")

    result = {
        "type": "historical_events",
        "period": {
            "start": (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d")
        },
        "data": [],
        "metadata": {
            "source": "public_repository",
            "collected_at": datetime.now().isoformat()
        }
    }

    # 预置公开事件数据（来自公开历史记录）
    events = [
        # 中国重大政策事件
        {"date": "1998-06-01", "title": "亚洲金融危机后中国启动积极财政政策", "type": "policy"},
        {"date": "2001-12-11", "title": "中国加入世界贸易组织（WTO）", "type": "policy"},
        {"date": "2005-07-21", "title": "人民币汇率制度改革", "type": "policy"},
        {"date": "2008-11-09", "title": "四万亿经济刺激计划", "type": "policy"},
        {"date": "2014-11-17", "title": "沪港通正式开通", "type": "policy"},
        {"date": "2015-06-01", "title": "A股纳入MSCI指数过程开始", "type": "policy"},
        {"date": "2016-01-01", "title": "熔断机制实施", "type": "policy"},
        {"date": "2018-03-22", "title": "中美贸易摩擦开始", "type": "policy"},
        {"date": "2019-07-22", "title": "科创板正式开市", "type": "policy"},
        {"date": "2020-01-23", "title": "新冠疫情爆发", "type": "event"},
        {"date": "2023-08-28", "title": "印花税减半征收", "type": "policy"},
        {"date": "2024-02-05", "title": "央行降准0.5个百分点", "type": "policy"},

        # 全球重要事件
        {"date": "2000-03-10", "title": "互联网泡沫破裂", "type": "event"},
        {"date": "2008-09-15", "title": "雷曼兄弟破产引发全球金融危机", "type": "event"},
        {"date": "2010-05-06", "title": "美股闪崩（闪电崩盘）", "type": "event"},
        {"date": "2020-03-09", "title": "全球股市暴跌（新冠冲击）", "type": "event"},
        {"date": "2022-02-24", "title": "俄乌冲突爆发", "type": "event"},
    ]

    # 过滤最近 years 年
    cutoff_date = datetime.now() - timedelta(days=years * 365)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    filtered = []
    for event in events:
        if event.get('date', '') >= cutoff_str:
            filtered.append(event)

    result["data"] = filtered
    logger.info(f"   ✅ 事件数据: {len(filtered)} 条 (过滤后)")

    return result


# ============================================================
# 4. 历史板块数据
# ============================================================

def fetch_historical_sector(years: int = 20) -> Dict[str, Any]:
    """
    采集历史板块数据（申万一级行业历史表现）

    Returns:
        {
            "type": "historical_sector",
            "period": {...},
            "data": {
                "电子": [{"date": "...", "close": ..., "change": ...}, ...],
                ...
            }
        }
    """
    logger.info(f"📊 开始采集历史板块数据 (回溯 {years} 年)")

    result = {
        "type": "historical_sector",
        "period": {
            "start": (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d"),
            "end": datetime.now().strftime("%Y-%m-%d")
        },
        "data": {},
        "metadata": {
            "source": "akshare",
            "collected_at": datetime.now().isoformat()
        }
    }

    try:
        import akshare as ak
    except ImportError:
        logger.error("❌ akshare 未安装，无法采集历史板块数据")
        return result

    # 申万一级行业
    sectors = [
        "电子", "计算机", "通信", "传媒", "医药生物",
        "食品饮料", "家用电器", "电力设备", "汽车", "国防军工",
        "银行", "非银金融", "公用事业", "煤炭", "石油石化"
    ]

    for sector in sectors:
        try:
            logger.info(f"   采集 {sector} 历史数据...")
            # 使用申万指数代码
            df = ak.stock_zh_index_daily_sw(symbol=sector)

            if df is not None and not df.empty:
                data = []
                for _, row in df.iterrows():
                    date = row.get('date', '')
                    if hasattr(date, 'strftime'):
                        date = date.strftime("%Y-%m-%d")

                    record = {
                        "date": date,
                        "close": float(row.get('close', 0)),
                        "change": float(row.get('pct_chg', 0)) if row.get('pct_chg') is not None else 0
                    }
                    data.append(record)

                # 限制数据量
                if years > 0 and data:
                    cutoff_date = datetime.now() - timedelta(days=years * 365)
                    cutoff_str = cutoff_date.strftime("%Y-%m-%d")
                    data = [d for d in data if d.get('date', '') >= cutoff_str]

                result["data"][sector] = data
                logger.info(f"   ✅ {sector}: {len(data)} 条记录")
            else:
                logger.warning(f"   ⚠️ {sector}: 无数据")

            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"   ⚠️ {sector}: 采集失败 - {e}")

    return result


# ============================================================
# 5. 打包与保存
# ============================================================

def save_historical_data(data: Dict[str, Any], data_type: str):
    """保存历史数据到暂存区"""
    os.makedirs(STAGING_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"historical_{data_type}_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 已保存: {filename} ({len(json.dumps(data))} 字符)")
    return filepath


# ============================================================
# 6. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集历史数据')
    parser.add_argument('--type', choices=['market', 'macro', 'events', 'sector', 'all'],
                       default='all', help='数据类型')
    parser.add_argument('--years', type=int, default=30,
                       help='回溯年数（默认30）')
    args = parser.parse_args()

    logger.info(f"🚀 开始采集历史数据 (类型: {args.type}, 年数: {args.years})")

    if args.type in ['market', 'all']:
        data = fetch_historical_market(args.years)
        save_historical_data(data, 'market')

    if args.type in ['macro', 'all']:
        data = fetch_historical_macro(args.years)
        save_historical_data(data, 'macro')

    if args.type in ['events', 'all']:
        data = fetch_historical_events(args.years)
        save_historical_data(data, 'events')

    if args.type in ['sector', 'all']:
        data = fetch_historical_sector(min(args.years, 20))  # 板块数据最多20年
        save_historical_data(data, 'sector')

    logger.info("✅ 历史数据采集完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
