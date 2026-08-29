#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据采集模块（修复版 V2.0）
版本： 2.0
更新日期： 2026-08-29
职责： 采集几十年历史行情、宏观、事件数据，统一打包签名

★ 采集内容：
  1. 历史行情数据 - 上证/深证/创业板 日线（30年）
  2. 历史宏观数据 - GDP、CPI、PMI
  3. 历史事件数据 - 重大政策、经济事件
  4. 历史板块数据 - 申万一级行业历史表现

★ V2.0 修复（2026-08-29）：
  - 板块数据采集：增加超时控制（防止单接口卡死）
  - 板块数据采集：增加重试机制（每个接口最多重试 2 次）
  - 板块数据采集：增加详细的错误日志
  - 板块数据采集：单个板块失败不影响其他板块
  - main 函数：增加 try/except 包裹，防止单数据类型失败导致整体崩溃

★ V1.5 修复（2026-08-22）：
  - 宏观数据：全面增强列名智能匹配，支持更多字段变体
  - 增加调试日志，打印 DataFrame 结构和列名（仅在 debug 模式）
  - GDP：支持 '年份'、'year'、'统计时间' 等列名
  - CPI/PMI：支持 '日期'、'date'、'月份'、'时间' 等列名
  - 数值列：支持 'gdp'、'cpi'、'pmi'、'总值'、'当月'、'指数'、'value' 等

★ V1.4 修复：
  - 板块数据：修复日期列匹配，增加对 '日期' 列名的检测
  - 行情数据：增加 '日期' 列名支持

★ V1.3 修复：
  - 宏观数据：增加更多列名匹配模式
  - 板块数据：使用 stock_zh_index_hist 作为备选接口

★ 使用方式：
  python scripts/collect_historical.py --type all --years 30 --debug
"""

import os
import sys
import json
import argparse
import logging
import time
import hmac
import hashlib
import threading
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
    sign_data = {k: v for k, v in data.items() if k not in ['signature', 'signature_metadata']}
    content = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


# ============================================================
# 1. 历史行情数据（V1.4 增强日期列检测）
# ============================================================

def fetch_historical_market(years: int = 30) -> Dict[str, Any]:
    """采集历史行情数据（上证、深证、创业板）"""
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

    indices = [
        ("上证指数", "sh000001"),
        ("深证成指", "sz399001"),
        ("创业板指", "sz399006"),
    ]

    for name, symbol in indices:
        try:
            logger.info(f"   采集 {name} ({symbol})...")
            df = ak.stock_zh_index_daily(symbol=symbol)

            if df is None or df.empty:
                logger.warning(f"   ⚠️ {name}: 无数据")
                continue

            # 智能检测列名（增加 '日期' 支持）
            date_col = None
            close_col = None
            for col in df.columns:
                col_lower = col.lower()
                if 'date' in col_lower or 'time' in col_lower or '日期' in col:
                    date_col = col
                if 'close' in col_lower or '收盘' in col or 'price' in col_lower:
                    close_col = col

            if date_col is None:
                logger.warning(f"   ⚠️ {name}: 未找到日期列，列名: {list(df.columns)[:5]}")
                continue

            data = []
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
                    try:
                        close_price = float(row.get(close_col, 0))
                    except (ValueError, TypeError):
                        continue

                if close_price > 0:
                    data.append({"date": date_str, "close": close_price})

            if years > 0 and data:
                cutoff_date = datetime.now() - timedelta(days=years * 365)
                cutoff_str = cutoff_date.strftime("%Y-%m-%d")
                data = [d for d in data if d.get('date', '') >= cutoff_str]

            if data:
                result["data"][name] = data
                logger.info(f"   ✅ {name}: {len(data)} 条记录")
            else:
                logger.warning(f"   ⚠️ {name}: 无有效数据")

            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"   ⚠️ {name}: 采集失败 - {e}")

    return result


# ============================================================
# 2. 历史宏观数据（V1.5 全面增强）
# ============================================================

def fetch_historical_macro(years: int = 30, debug: bool = False) -> Dict[str, Any]:
    """
    采集历史宏观数据（GDP、CPI、PMI）
    ★ V1.5 增强：智能列名检测，支持更多字段变体
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

    # ---------- GDP ----------
    try:
        logger.info("   采集 GDP 数据...")
        gdp_data = None

        # 尝试多个接口
        for api_name in ['macro_china_gdp', 'macro_china_gdp_yearly']:
            try:
                gdp_data = getattr(ak, api_name)()
                if gdp_data is not None and not gdp_data.empty:
                    logger.debug(f"   ✅ GDP 使用接口: {api_name}")
                    break
            except Exception as e:
                logger.debug(f"   GDP {api_name} 失败: {e}")

        if gdp_data is not None and not gdp_data.empty:
            if debug:
                logger.debug(f"   GDP 列名: {list(gdp_data.columns)}")
                logger.debug(f"   GDP 前3行:\n{gdp_data.head(3).to_string()}")
            else:
                logger.debug(f"   GDP 列名: {list(gdp_data.columns)}")

            data = []
            # 智能检测列名
            year_col = None
            value_col = None

            # 常见年份列名
            year_candidates = ['年份', '年', 'year', '统计时间', '时间', 'date', '指标']
            # 常见数值列名
            value_candidates = ['gdp', 'GDP', '总值', 'value', '数值', '亿元', '国内生产总值']

            for col in gdp_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in year_candidates):
                    year_col = col
                    break
            if not year_col:
                # 如果没找到，尝试包含'年'的列
                for col in gdp_data.columns:
                    if '年' in col or 'year' in col.lower():
                        year_col = col
                        break
            if not year_col:
                # 尝试取第一列作为年份
                year_col = gdp_data.columns[0]
                logger.debug(f"   GDP: 未明确年份列，使用第一列 '{year_col}'")

            for col in gdp_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in value_candidates):
                    value_col = col
                    break
            if not value_col:
                # 尝试找任何数值列（排除年份列）
                for col in gdp_data.columns:
                    if col != year_col and gdp_data[col].dtype in ['float64', 'int64']:
                        value_col = col
                        break
            if not value_col:
                # 取最后一列
                value_col = gdp_data.columns[-1]
                logger.debug(f"   GDP: 未明确数值列，使用最后一列 '{value_col}'")

            logger.debug(f"   GDP 年份列: {year_col}, 数值列: {value_col}")

            for _, row in gdp_data.iterrows():
                try:
                    year_val = row.get(year_col)
                    if year_val is None:
                        continue
                    # 尝试转换为字符串并提取年份
                    year_str = str(year_val).strip()
                    # 如果包含'-'等，取前4位
                    if len(year_str) >= 4 and year_str[:4].isdigit():
                        year_str = year_str[:4]
                    elif not year_str.isdigit():
                        # 尝试提取数字
                        import re
                        digits = re.findall(r'\d{4}', year_str)
                        if digits:
                            year_str = digits[0]
                        else:
                            continue
                    if not year_str.isdigit():
                        continue
                    value = row.get(value_col)
                    if value is None:
                        continue
                    try:
                        value = float(value)
                    except (ValueError, TypeError):
                        continue
                    if value > 0:
                        data.append({"year": year_str, "gdp_yi": value})
                except Exception as e:
                    logger.debug(f"   GDP 行解析失败: {e}")

            if data:
                if years > 0:
                    cutoff_year = datetime.now().year - years
                    data = [d for d in data if int(d.get('year', 0)) >= cutoff_year]
                result["data"]["GDP"] = data
                logger.info(f"   ✅ GDP: {len(data)} 条记录")
            else:
                logger.warning("   ⚠️ GDP: 无有效数据")
        else:
            logger.warning("   ⚠️ GDP: 所有接口均无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ GDP: 采集失败 - {e}")

    # ---------- CPI ----------
    try:
        logger.info("   采集 CPI 数据...")
        cpi_data = None

        for api_name in ['macro_china_cpi_monthly', 'macro_china_cpi']:
            try:
                cpi_data = getattr(ak, api_name)()
                if cpi_data is not None and not cpi_data.empty:
                    logger.debug(f"   ✅ CPI 使用接口: {api_name}")
                    break
            except Exception as e:
                logger.debug(f"   CPI {api_name} 失败: {e}")

        if cpi_data is not None and not cpi_data.empty:
            if debug:
                logger.debug(f"   CPI 列名: {list(cpi_data.columns)}")
                logger.debug(f"   CPI 前3行:\n{cpi_data.head(3).to_string()}")
            else:
                logger.debug(f"   CPI 列名: {list(cpi_data.columns)}")

            data = []
            date_col = None
            value_col = None

            # 常见日期列名
            date_candidates = ['日期', 'date', '时间', '月份', 'month', '统计期间']
            # 常见数值列名
            value_candidates = ['cpi', 'CPI', '当月', '同比', '数值', 'value', '指数']

            for col in cpi_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in date_candidates):
                    date_col = col
                    break
            if not date_col:
                # 尝试包含'日期'或'月'的列
                for col in cpi_data.columns:
                    if '日期' in col or 'date' in col.lower() or '月' in col:
                        date_col = col
                        break
            if not date_col:
                # 默认第一列
                date_col = cpi_data.columns[0]
                logger.debug(f"   CPI: 未明确日期列，使用第一列 '{date_col}'")

            for col in cpi_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in value_candidates):
                    value_col = col
                    break
            if not value_col:
                for col in cpi_data.columns:
                    if col != date_col and cpi_data[col].dtype in ['float64', 'int64']:
                        value_col = col
                        break
            if not value_col:
                value_col = cpi_data.columns[-1]
                logger.debug(f"   CPI: 未明确数值列，使用最后一列 '{value_col}'")

            logger.debug(f"   CPI 日期列: {date_col}, 数值列: {value_col}")

            for _, row in cpi_data.iterrows():
                try:
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m")
                    else:
                        date_str = str(date_val).strip()
                        # 如果日期格式为 YYYY-MM-DD，取前7位
                        if len(date_str) >= 7 and date_str[4] == '-':
                            date_str = date_str[:7]
                        elif len(date_str) >= 4 and date_str[:4].isdigit():
                            # 可能是年份，补上月份
                            if len(date_str) == 4:
                                date_str = date_str + "-01"
                            else:
                                # 尝试提取 YYYY-MM
                                import re
                                match = re.search(r'(\d{4})-?(\d{1,2})', date_str)
                                if match:
                                    date_str = f"{match.group(1)}-{match.group(2).zfill(2)}"
                                else:
                                    continue
                    cpi_val = row.get(value_col)
                    if cpi_val is None:
                        continue
                    try:
                        cpi_val = float(cpi_val)
                    except (ValueError, TypeError):
                        continue
                    if cpi_val != 0:  # CPI 可能为负，保留
                        data.append({"date": date_str, "cpi": cpi_val})
                except Exception as e:
                    logger.debug(f"   CPI 行解析失败: {e}")

            if data:
                if years > 0:
                    cutoff_date = datetime.now() - timedelta(days=years * 365)
                    cutoff_str = cutoff_date.strftime("%Y-%m")
                    data = [d for d in data if d.get('date', '') >= cutoff_str]
                result["data"]["CPI"] = data
                logger.info(f"   ✅ CPI: {len(data)} 条记录")
            else:
                logger.warning("   ⚠️ CPI: 无有效数据")
        else:
            logger.warning("   ⚠️ CPI: 所有接口均无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ CPI: 采集失败 - {e}")

    # ---------- PMI ----------
    try:
        logger.info("   采集 PMI 数据...")
        pmi_data = None

        for api_name in ['macro_china_pmi_yearly', 'macro_china_pmi']:
            try:
                pmi_data = getattr(ak, api_name)()
                if pmi_data is not None and not pmi_data.empty:
                    logger.debug(f"   ✅ PMI 使用接口: {api_name}")
                    break
            except Exception as e:
                logger.debug(f"   PMI {api_name} 失败: {e}")

        if pmi_data is not None and not pmi_data.empty:
            if debug:
                logger.debug(f"   PMI 列名: {list(pmi_data.columns)}")
                logger.debug(f"   PMI 前3行:\n{pmi_data.head(3).to_string()}")
            else:
                logger.debug(f"   PMI 列名: {list(pmi_data.columns)}")

            data = []
            date_col = None
            value_col = None

            date_candidates = ['日期', 'date', '时间', '月份', 'month', '统计期间']
            value_candidates = ['pmi', 'PMI', '指数', 'value', '数值', '制造业PMI']

            for col in pmi_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in date_candidates):
                    date_col = col
                    break
            if not date_col:
                for col in pmi_data.columns:
                    if '日期' in col or 'date' in col.lower() or '月' in col:
                        date_col = col
                        break
            if not date_col:
                date_col = pmi_data.columns[0]
                logger.debug(f"   PMI: 未明确日期列，使用第一列 '{date_col}'")

            for col in pmi_data.columns:
                col_lower = col.lower().strip()
                if any(c in col_lower or col_lower in c for c in value_candidates):
                    value_col = col
                    break
            if not value_col:
                for col in pmi_data.columns:
                    if col != date_col and pmi_data[col].dtype in ['float64', 'int64']:
                        value_col = col
                        break
            if not value_col:
                value_col = pmi_data.columns[-1]
                logger.debug(f"   PMI: 未明确数值列，使用最后一列 '{value_col}'")

            logger.debug(f"   PMI 日期列: {date_col}, 数值列: {value_col}")

            for _, row in pmi_data.iterrows():
                try:
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m")
                    else:
                        date_str = str(date_val).strip()
                        if len(date_str) >= 7 and date_str[4] == '-':
                            date_str = date_str[:7]
                        elif len(date_str) >= 4 and date_str[:4].isdigit():
                            if len(date_str) == 4:
                                date_str = date_str + "-01"
                            else:
                                import re
                                match = re.search(r'(\d{4})-?(\d{1,2})', date_str)
                                if match:
                                    date_str = f"{match.group(1)}-{match.group(2).zfill(2)}"
                                else:
                                    continue
                    pmi_val = row.get(value_col)
                    if pmi_val is None:
                        continue
                    try:
                        pmi_val = float(pmi_val)
                    except (ValueError, TypeError):
                        continue
                    if pmi_val > 0:
                        data.append({"date": date_str, "pmi": pmi_val})
                except Exception as e:
                    logger.debug(f"   PMI 行解析失败: {e}")

            if data:
                if years > 0:
                    cutoff_date = datetime.now() - timedelta(days=years * 365)
                    cutoff_str = cutoff_date.strftime("%Y-%m")
                    data = [d for d in data if d.get('date', '') >= cutoff_str]
                result["data"]["PMI"] = data
                logger.info(f"   ✅ PMI: {len(data)} 条记录")
            else:
                logger.warning("   ⚠️ PMI: 无有效数据")
        else:
            logger.warning("   ⚠️ PMI: 所有接口均无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ PMI: 采集失败 - {e}")

    return result


# ============================================================
# 3. 历史事件数据（保持不变）
# ============================================================

def fetch_historical_events(years: int = 30) -> Dict[str, Any]:
    """采集历史事件数据（政策、经济事件）"""
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
        {"date": "2025-04-07", "title": "汇金公司宣布增持ETF", "type": "policy"},
        {"date": "2025-04-13", "title": "美国关税政策调整引发市场波动", "type": "event"},
        {"date": "2025-05-19", "title": "央行连续多日公开市场净投放", "type": "policy"},
    ]

    cutoff_date = datetime.now() - timedelta(days=years * 365)
    cutoff_str = cutoff_date.strftime("%Y-%m-%d")

    filtered = [e for e in events if e.get('date', '') >= cutoff_str]
    result["data"] = filtered
    logger.info(f"   ✅ 事件数据: {len(filtered)} 条 (过滤后)")

    return result


# ============================================================
# 4. 历史板块数据（V2.0 增强版 - 高稳定性）
# ============================================================

def fetch_historical_sector(years: int = 20, max_retries: int = 2) -> Dict[str, Any]:
    """
    采集历史板块数据（增强版 V2.0）
    ★ V2.0 增强（2026-08-29）：
       - 使用 threading 实现超时控制，防止单个接口卡死
       - 增加重试机制（每个接口最多重试 2 次）
       - 增加详细的错误日志，便于定位问题
       - 单个板块失败不影响其他板块
       - 如果板块全部失败，返回空数据（不阻塞整体打包）
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

    # ★ V2.0：使用 threading 实现超时控制
    def _call_with_timeout(func, timeout: int = 15) -> Any:
        """在超时时间内执行函数"""
        result = [None]
        exception = [None]

        def target():
            try:
                result[0] = func()
            except Exception as e:
                exception[0] = e

        thread = threading.Thread(target=target)
        thread.daemon = True
        thread.start()
        thread.join(timeout)

        if thread.is_alive():
            logger.debug(f"      ⏰ 超时 ({timeout}s)")
            return None

        if exception[0] is not None:
            logger.debug(f"      ❌ 异常: {str(exception[0])[:80]}")
            return None

        return result[0]

    success_count = 0
    fail_count = 0
    fail_details = []

    for sector, symbol in sector_codes.items():
        logger.info(f"   采集 {sector} 历史数据 ({symbol})...")
        start_time_sector = time.time()
        df = None
        error_messages = []

        # ★ V2.0：按稳定性排序的接口尝试列表
        api_attempts = [
            {
                "name": "stock_zh_index_hist",
                "func": lambda s=symbol: ak.stock_zh_index_hist(
                    symbol=s,
                    period="daily",
                    start_date=(datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")
                ),
                "timeout": 15
            },
            {
                "name": "index_hist_sw",
                "func": lambda s=symbol: ak.index_hist_sw(symbol=s),
                "timeout": 10
            }
        ]

        for attempt in api_attempts:
            if df is not None and not df.empty:
                break

            for retry in range(max_retries + 1):
                if df is not None and not df.empty:
                    break

                try:
                    logger.debug(f"      [{sector}] 尝试 {attempt['name']} (重试 {retry}/{max_retries})")
                    result_data = _call_with_timeout(attempt["func"], attempt["timeout"])

                    if result_data is not None and not result_data.empty:
                        df = result_data
                        logger.debug(f"      ✅ {sector}: {attempt['name']} 成功")
                        break
                    else:
                        msg = f"{attempt['name']} 返回空数据"
                        logger.debug(f"      ⚠️ {sector}: {msg}")
                        error_messages.append(msg)

                except Exception as e:
                    msg = f"{attempt['name']}: {str(e)[:80]}"
                    logger.debug(f"      ❌ {sector}: {msg}")
                    error_messages.append(msg)
                    time.sleep(1)  # 重试前等待

        if df is None or df.empty:
            elapsed = time.time() - start_time_sector
            logger.warning(f"   ⚠️ {sector}: 所有接口均无数据 (耗时 {elapsed:.1f}s)")
            fail_count += 1
            fail_details.append(f"{sector}: {', '.join(error_messages[-3:])}")
            continue

        # ★ 智能检测列名
        date_col = None
        close_col = None
        for col in df.columns:
            col_lower = col.lower()
            if 'date' in col_lower or '时间' in col or '日期' in col or 'day' in col_lower:
                date_col = col
            if 'close' in col_lower or '收盘' in col or 'price' in col_lower:
                close_col = col

        if date_col is None:
            logger.warning(f"   ⚠️ {sector}: 未找到日期列，列名: {list(df.columns)[:5]}")
            fail_count += 1
            continue

        # ★ 解析数据
        sector_data = []
        for _, row in df.iterrows():
            try:
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

                if close_price > 0:
                    sector_data.append({"date": date_str, "close": close_price})
            except (ValueError, TypeError, AttributeError):
                continue

        # ★ 按年份过滤
        if years > 0 and sector_data:
            cutoff_date = datetime.now() - timedelta(days=years * 365)
            cutoff_str = cutoff_date.strftime("%Y-%m-%d")
            sector_data = [d for d in sector_data if d.get('date', '') >= cutoff_str]

        if sector_data:
            result["data"][sector] = sector_data
            elapsed = time.time() - start_time_sector
            logger.info(f"   ✅ {sector}: {len(sector_data)} 条记录 (耗时 {elapsed:.1f}s)")
            success_count += 1
        else:
            elapsed = time.time() - start_time_sector
            logger.warning(f"   ⚠️ {sector}: 无有效数据 (耗时 {elapsed:.1f}s)")
            fail_count += 1

        # ★ V2.0：采集间隔（防止被限流）
        time.sleep(0.5)

    # ★ V2.0：最终统计
    logger.info(f"   📊 板块采集完成: 成功 {success_count}/{len(sector_codes)} 个, 失败 {fail_count} 个")

    if fail_details:
        logger.debug(f"   📝 失败详情: {fail_details[:5]}")

    # ★ V2.0：即使全部失败，也返回空数据（不阻塞整体打包）
    if success_count == 0:
        logger.warning("   ⚠️ 所有板块数据均采集失败，historical_package 将不包含板块数据")

    return result


# ============================================================
# 5. 统一打包与签名（保持不变）
# ============================================================

def pack_historical_data(
    market_data: Dict[str, Any],
    macro_data: Dict[str, Any],
    events_data: Dict[str, Any],
    sector_data: Dict[str, Any]
) -> Dict[str, Any]:
    """将所有历史数据打包为统一格式，并签名"""
    logger.info("📦 开始打包历史数据...")

    package = {
        "package_type": "historical_data",
        "generated_at": datetime.now().isoformat(),
        "version": "1.0",
        "contents": {}
    }

    if market_data and market_data.get('data'):
        package["contents"]["historical_market"] = market_data
        logger.info(f"   ✅ 包含市场数据: {len(market_data.get('data', {}))} 个指数")

    if macro_data and macro_data.get('data'):
        package["contents"]["historical_macro"] = macro_data
        logger.info(f"   ✅ 包含宏观数据: {len(macro_data.get('data', {}))} 个指标")

    if events_data and events_data.get('data'):
        package["contents"]["historical_events"] = events_data
        logger.info(f"   ✅ 包含事件数据: {len(events_data.get('data', []))} 条")

    if sector_data and sector_data.get('data'):
        package["contents"]["historical_sector"] = sector_data
        logger.info(f"   ✅ 包含板块数据: {len(sector_data.get('data', {}))} 个行业")

    package["metadata"] = {
        "total_items": sum(
            len(v.get('data', [])) if isinstance(v.get('data'), list) else len(v.get('data', {}))
            for v in package["contents"].values()
        ),
        "data_types": list(package["contents"].keys())
    }

    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    logger.info(f"   📊 打包完成: {len(package['contents'])} 个数据类型")
    return package


# ============================================================
# 6. 保存（保持不变）
# ============================================================

def save_package(package: Dict[str, Any]) -> str:
    """保存打包数据到暂存区"""
    os.makedirs(STAGING_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"historical_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(filepath)
    logger.info(f"✅ 已保存: {filename} ({file_size/1024:.1f} KB)")
    return filepath


def save_debug_data(data: Dict[str, Any], suffix: str):
    """保存调试数据"""
    os.makedirs(STAGING_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"historical_{suffix}_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


# ============================================================
# 7. 主入口（V2.0 增强错误处理）
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集历史数据（打包签名版）')
    parser.add_argument('--type', choices=['market', 'macro', 'events', 'sector', 'all'],
                       default='all', help='数据类型')
    parser.add_argument('--years', type=int, default=30, help='回溯年数（默认30）')
    parser.add_argument('--debug', action='store_true', help='启用调试模式（打印更多信息）')
    args = parser.parse_args()

    logger.info(f"🚀 开始采集历史数据 (类型: {args.type}, 年数: {args.years})")

    market_data = {}
    macro_data = {}
    events_data = {}
    sector_data = {}

    # ★ V2.0：每个采集函数独立 try/except，防止单个数据类型失败导致整体崩溃
    try:
        if args.type in ['market', 'all']:
            market_data = fetch_historical_market(args.years)
            if args.debug:
                save_debug_data(market_data, 'market')
    except Exception as e:
        logger.error(f"❌ 市场数据采集失败: {e}")
        # 即使失败，也使用空数据继续

    try:
        if args.type in ['macro', 'all']:
            macro_data = fetch_historical_macro(args.years, debug=args.debug)
            if args.debug:
                save_debug_data(macro_data, 'macro')
    except Exception as e:
        logger.error(f"❌ 宏观数据采集失败: {e}")

    try:
        if args.type in ['events', 'all']:
            events_data = fetch_historical_events(args.years)
            if args.debug:
                save_debug_data(events_data, 'events')
    except Exception as e:
        logger.error(f"❌ 事件数据采集失败: {e}")

    try:
        if args.type in ['sector', 'all']:
            sector_years = min(args.years, 20)
            sector_data = fetch_historical_sector(sector_years)
            if args.debug:
                save_debug_data(sector_data, 'sector')
    except Exception as e:
        logger.error(f"❌ 板块数据采集失败: {e}")
        logger.warning("   ⚠️ 板块数据采集失败，将生成不含板块数据的包")
        sector_data = {}

    has_data = any([
        market_data.get('data'),
        macro_data.get('data'),
        events_data.get('data'),
        sector_data.get('data')
    ])

    if not has_data:
        logger.warning("⚠️ 所有数据源均无数据，生成空包")
        package = {
            "package_type": "historical_data",
            "generated_at": datetime.now().isoformat(),
            "version": "1.0",
            "contents": {},
            "metadata": {
                "total_items": 0,
                "data_types": [],
                "note": "所有数据源均无数据",
                "errors": [
                    "市场数据: 无" if not market_data.get('data') else "正常",
                    "宏观数据: 无" if not macro_data.get('data') else "正常",
                    "事件数据: 无" if not events_data.get('data') else "正常",
                    "板块数据: 无" if not sector_data.get('data') else "正常"
                ]
            }
        }
        key = get_signing_key()
        if key:
            package["signature"] = sign_data(package, key)
        else:
            package["signature"] = None
    else:
        package = pack_historical_data(market_data, macro_data, events_data, sector_data)

    filepath = save_package(package)

    logger.info("✅ 历史数据采集完成")
    logger.info(f"   📦 输出文件: {filepath}")
    logger.info(f"   📊 数据包大小: {len(package.get('contents', {}))} 个数据类型")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
