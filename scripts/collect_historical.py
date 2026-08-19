#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据采集模块
版本： 1.1
更新日期： 2026-08-19
职责： 采集几十年历史行情、宏观、事件数据

★ 采集内容：
  1. 历史行情数据 - 上证/深证/创业板 日线（30年）
  2. 历史宏观数据 - GDP、CPI、PMI
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
        logger.error("❌ akshare 未安装")
        return result

    # 指数列表：名称 -> 代码前缀
    indices = [
        ("上证指数", "sh000001"),
        ("深证成指", "sz399001"),
        ("创业板指", "sz399006"),
    ]

    for name, symbol in indices:
        try:
            logger.info(f"   采集 {name} ({symbol})...")
            df = ak.stock_zh_index_daily(symbol=symbol)

            if df is not None and not df.empty:
                # 智能检测列名
                date_col = None
                for col in df.columns:
                    if 'date' in col.lower():
                        date_col = col
                        break

                if date_col is None:
                    logger.warning(f"   ⚠️ {name}: 未找到日期列，跳过")
                    continue

                data = []
                for _, row in df.iterrows():
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue

                    # 日期格式化
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m-%d")
                    else:
                        date_str = str(date_val)[:10]

                    # 提取价格数据（尝试多种列名）
                    close = 0
                    for col in ['close', '收盘', '收盘价']:
                        if col in df.columns and row.get(col) is not None:
                            close = float(row.get(col, 0))
                            break

                    open_price = 0
                    for col in ['open', '开盘', '开盘价']:
                        if col in df.columns and row.get(col) is not None:
                            open_price = float(row.get(col, 0))
                            break

                    high = 0
                    for col in ['high', '最高', '最高价']:
                        if col in df.columns and row.get(col) is not None:
                            high = float(row.get(col, 0))
                            break

                    low = 0
                    for col in ['low', '最低', '最低价']:
                        if col in df.columns and row.get(col) is not None:
                            low = float(row.get(col, 0))
                            break

                    volume = 0
                    for col in ['volume', '成交量']:
                        if col in df.columns and row.get(col) is not None:
                            volume = float(row.get(col, 0))
                            break

                    record = {
                        "date": date_str,
                        "open": open_price,
                        "high": high,
                        "low": low,
                        "close": close,
                        "volume": volume
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

            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"   ⚠️ {name}: 采集失败 - {e}")

    return result


# ============================================================
# 2. 历史宏观数据
# ============================================================

def fetch_historical_macro(years: int = 30) -> Dict[str, Any]:
    """
    采集历史宏观数据（GDP、CPI、PMI）
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
        logger.error("❌ akshare 未安装")
        return result

    # ---- GDP（使用 maco_china_gdp） ----
    try:
        logger.info("   采集 GDP 数据...")
        # 尝试多个可能的接口
        gdp_data = None
        try:
            gdp_data = ak.macro_china_gdp()
        except Exception:
            pass

        if gdp_data is None or gdp_data.empty:
            try:
                gdp_data = ak.macro_china_gdp_yearly()
            except Exception:
                pass

        if gdp_data is not None and not gdp_data.empty:
            data = []
            # 智能检测列名
            year_col = None
            value_col = None
            growth_col = None
            for col in gdp_data.columns:
                if '年' in col or '年份' in col or 'year' in col.lower():
                    year_col = col
                if 'gdp' in col.lower() or '国内生产总值' in col or '总值' in col:
                    value_col = col
                if '增长' in col or '增速' in col or 'growth' in col.lower():
                    growth_col = col

            for _, row in gdp_data.iterrows():
                year = str(row.get(year_col, '')) if year_col else ''
                if year:
                    record = {"year": year}
                    if value_col:
                        record["gdp_yi"] = float(row.get(value_col, 0))
                    if growth_col:
                        record["growth"] = float(row.get(growth_col, 0))
                    data.append(record)

            # 限制数据量
            if years > 0 and data:
                cutoff_year = datetime.now().year - years
                data = [d for d in data if int(d.get('year', 0)) >= cutoff_year]

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
            date_col = None
            cpi_col = None
            yoy_col = None
            for col in df.columns:
                if '日期' in col or 'date' in col.lower():
                    date_col = col
                if '当月' in col or 'cpi' in col.lower():
                    cpi_col = col
                if '同比' in col or '增长' in col:
                    yoy_col = col

            for _, row in df.iterrows():
                date_val = row.get(date_col) if date_col else None
                if date_val is None:
                    continue
                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime("%Y-%m")
                else:
                    date_str = str(date_val)[:7]

                record = {"date": date_str}
                if cpi_col:
                    record["cpi"] = float(row.get(cpi_col, 0))
                if yoy_col:
                    record["cpi_yoy"] = float(row.get(yoy_col, 0))
                data.append(record)

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
            date_col = None
            pmi_col = None
            for col in df.columns:
                if '日期' in col or 'date' in col.lower():
                    date_col = col
                if 'pmi' in col.lower() or 'PMI' in col:
                    pmi_col = col

            for _, row in df.iterrows():
                date_val = row.get(date_col) if date_col else None
                if date_val is None:
                    continue
                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime("%Y-%m")
                else:
                    date_str = str(date_val)[:7]

                record = {"date": date_str}
                if pmi_col:
                    record["pmi"] = float(row.get(pmi_col, 0))
                data.append(record)

            if years > 0 and data:
                cutoff_date = datetime.now() - timedelta(days=years * 365)
                cutoff_str = cutoff_date.strftime("%Y-%m")
                data = [d for d in data if d.get('date', '') >= cutoff_str]

            result["data"]["PMI"] = data
            logger.info(f"   ✅ PMI: {len(data)} 条记录")
        else:
            logger.warning("   ⚠️ PMI: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ PMI: 采集失败 - {e}")

    return result


# ============================================================
# 3. 历史事件数据
# ============================================================

def fetch_historical_events(years: int = 30) -> Dict[str, Any]:
    """
    采集历史事件数据（政策、经济事件）
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

    # 预置公开事件数据
    events = [
        {"date": "1990-12-19", "title": "上海证券交易所正式开业", "type": "policy"},
        {"date": "1991-04-11", "title": "深圳证券交易所正式开业", "type": "policy"},
        {"date": "1992-01-01", "title": "邓小平南巡讲话", "type": "policy"},
        {"date": "1996-12-16", "title": "涨跌停板制度实施", "type": "policy"},
        {"date": "1998-06-01", "title": "亚洲金融危机后中国启动积极财政政策", "type": "policy"},
        {"date": "2001-12-11", "title": "中国加入世界贸易组织（WTO）", "type": "policy"},
        {"date": "2005-04-29", "title": "股权分置改革启动", "type": "policy"},
        {"date": "2005-07-21", "title": "人民币汇率制度改革", "type": "policy"},
        {"date": "2008-09-15", "title": "雷曼兄弟破产引发全球金融危机", "type": "event"},
        {"date": "2008-11-09", "title": "四万亿经济刺激计划", "type": "policy"},
        {"date": "2010-04-16", "title": "股指期货正式上市", "type": "policy"},
        {"date": "2014-11-17", "title": "沪港通正式开通", "type": "policy"},
        {"date": "2015-06-12", "title": "A股牛市见顶（5178点）", "type": "event"},
        {"date": "2016-01-01", "title": "熔断机制实施", "type": "policy"},
        {"date": "2016-12-05", "title": "深港通正式开通", "type": "policy"},
        {"date": "2018-03-22", "title": "中美贸易摩擦开始", "type": "policy"},
        {"date": "2019-06-13", "title": "科创板正式开板", "type": "policy"},
        {"date": "2020-01-23", "title": "新冠疫情爆发", "type": "event"},
        {"date": "2020-03-09", "title": "全球股市暴跌", "type": "event"},
        {"date": "2021-09-02", "title": "北京证券交易所宣布设立", "type": "policy"},
        {"date": "2022-02-24", "title": "俄乌冲突爆发", "type": "event"},
        {"date": "2023-08-28", "title": "印花税减半征收", "type": "policy"},
        {"date": "2024-02-05", "title": "央行降准0.5个百分点", "type": "policy"},
        {"date": "2024-09-24", "title": "央行宣布降息降准组合政策", "type": "policy"},
    ]

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
# 4. 历史板块数据（修复版）
# ============================================================

def fetch_historical_sector(years: int = 20) -> Dict[str, Any]:
    """
    采集历史板块数据（使用申万指数历史接口）
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
        logger.error("❌ akshare 未安装")
        return result

    # 申万一级行业代码映射
    sector_codes = {
        "电子": "801080",
        "计算机": "801750",
        "通信": "801770",
        "传媒": "801760",
        "医药生物": "801150",
        "食品饮料": "801120",
        "家用电器": "801110",
        "电力设备": "801730",
        "汽车": "801880",
        "国防军工": "801740",
        "银行": "801780",
        "非银金融": "801790",
        "公用事业": "801160",
        "煤炭": "801950",
        "石油石化": "801960"
    }

    for sector, code in sector_codes.items():
        try:
            logger.info(f"   采集 {sector} 历史数据 ({code})...")

            # 使用申万指数历史数据
            df = ak.index_hist_sw(symbol=code)

            if df is not None and not df.empty:
                data = []
                date_col = None
                close_col = None
                for col in df.columns:
                    if 'date' in col.lower():
                        date_col = col
                    if 'close' in col.lower() or '收盘' in col:
                        close_col = col

                if date_col is None:
                    logger.warning(f"   ⚠️ {sector}: 未找到日期列")
                    continue

                for _, row in df.iterrows():
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue

                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m-%d")
                    else:
                        date_str = str(date_val)[:10]

                    close_price = 0
                    if close_col:
                        close_price = float(row.get(close_col, 0))

                    record = {
                        "date": date_str,
                        "close": close_price
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
        data = fetch_historical_sector(min(args.years, 20))
        save_historical_data(data, 'sector')

    logger.info("✅ 历史数据采集完成")
    return 0


if __name__ == "__main__":
    sys.exit(main())
