#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据采集模块（修复版）
版本： V1.2
更新日期： 2026-08-22
职责： 采集几十年历史行情、宏观、事件数据，统一打包签名

★ 采集内容：
  1. 历史行情数据 - 上证/深证/创业板 日线（30年）
  2. 历史宏观数据 - GDP、CPI、PMI
  3. 历史事件数据 - 重大政策、经济事件
  4. 历史板块数据 - 申万一级行业历史表现

★ V1.2 修复内容：
  - 增加统一打包和 HMAC-SHA256 签名
  - 增加 generated_at 字段
  - 修复板块数据采集接口（增加多种备选方案）
  - 增加数据有效性验证
  - 增加空数据时的兜底处理

★ 使用方式：
  python scripts/collect_historical.py --type all --years 30
"""

import os
import sys
import json
import argparse
import logging
import time
import hmac
import hashlib
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
    # 排除 signature 字段
    sign_data = {k: v for k, v in data.items() if k not in ['signature', 'signature_metadata']}
    content = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


# ============================================================
# 1. 历史行情数据（增强版）
# ============================================================

def fetch_historical_market(years: int = 30) -> Dict[str, Any]:
    """
    采集历史行情数据（上证、深证、创业板）
    ★ 修复：增加多种数据源备选
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

    # 指数列表
    indices = [
        ("上证指数", "sh000001"),
        ("深证成指", "sz399001"),
        ("创业板指", "sz399006"),
    ]

    for name, symbol in indices:
        try:
            logger.info(f"   采集 {name} ({symbol})...")
            df = None

            # ★ 尝试多种接口
            try:
                df = ak.stock_zh_index_daily(symbol=symbol)
            except Exception as e:
                logger.debug(f"   stock_zh_index_daily 失败: {e}")
                try:
                    # 备选：使用 spot 接口
                    df = ak.stock_zh_index_spot()
                    if df is not None and not df.empty:
                        # 过滤出目标指数
                        df = df[df['代码'].str.contains(symbol.replace('sh', '').replace('sz', ''))]
                except Exception as e2:
                    logger.debug(f"   stock_zh_index_spot 备选失败: {e2}")

            if df is None or df.empty:
                logger.warning(f"   ⚠️ {name}: 所有接口均无数据")
                continue

            # 智能检测列名
            date_col = None
            for col in df.columns:
                if 'date' in col.lower():
                    date_col = col
                    break
            if date_col is None:
                for col in df.columns:
                    if 'time' in col.lower() or 'day' in col.lower():
                        date_col = col
                        break
            if date_col is None:
                logger.warning(f"   ⚠️ {name}: 未找到日期列")
                continue

            # 提取数据
            data = []
            for _, row in df.iterrows():
                date_val = row.get(date_col)
                if date_val is None:
                    continue

                if hasattr(date_val, 'strftime'):
                    date_str = date_val.strftime("%Y-%m-%d")
                else:
                    date_str = str(date_val)[:10]

                # 提取价格数据
                close = 0
                for col in ['close', '收盘', '收盘价', 'price']:
                    if col in df.columns and row.get(col) is not None:
                        try:
                            close = float(row.get(col, 0))
                            break
                        except (ValueError, TypeError):
                            continue

                if close == 0:
                    continue  # 跳过无效数据

                record = {
                    "date": date_str,
                    "close": close
                }
                data.append(record)

            # 限制数据量
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
# 2. 历史宏观数据（增强版）
# ============================================================

def fetch_historical_macro(years: int = 30) -> Dict[str, Any]:
    """采集历史宏观数据（GDP、CPI、PMI）"""
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

    # ---- GDP ----
    try:
        logger.info("   采集 GDP 数据...")
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
            year_col = None
            value_col = None
            for col in gdp_data.columns:
                if '年' in col or 'year' in col.lower():
                    year_col = col
                if 'gdp' in col.lower() or '总值' in col:
                    value_col = col

            if year_col and value_col:
                for _, row in gdp_data.iterrows():
                    year = str(row.get(year_col, ''))
                    if year:
                        try:
                            value = float(row.get(value_col, 0))
                            if value > 0:
                                data.append({"year": year, "gdp_yi": value})
                        except (ValueError, TypeError):
                            continue

            if data:
                if years > 0:
                    cutoff_year = datetime.now().year - years
                    data = [d for d in data if int(d.get('year', 0)) >= cutoff_year]
                result["data"]["GDP"] = data
                logger.info(f"   ✅ GDP: {len(data)} 条记录")
            else:
                logger.warning("   ⚠️ GDP: 无有效数据")
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
            for col in df.columns:
                if '日期' in col or 'date' in col.lower():
                    date_col = col
                if '当月' in col or 'cpi' in col.lower():
                    cpi_col = col

            if date_col and cpi_col:
                for _, row in df.iterrows():
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m")
                    else:
                        date_str = str(date_val)[:7]

                    try:
                        cpi = float(row.get(cpi_col, 0))
                        if cpi != 0:
                            data.append({"date": date_str, "cpi": cpi})
                    except (ValueError, TypeError):
                        continue

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

            if date_col and pmi_col:
                for _, row in df.iterrows():
                    date_val = row.get(date_col)
                    if date_val is None:
                        continue
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m")
                    else:
                        date_str = str(date_val)[:7]

                    try:
                        pmi = float(row.get(pmi_col, 0))
                        if pmi > 0:
                            data.append({"date": date_str, "pmi": pmi})
                    except (ValueError, TypeError):
                        continue

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
            logger.warning("   ⚠️ PMI: 无数据")
    except Exception as e:
        logger.warning(f"   ⚠️ PMI: 采集失败 - {e}")

    return result


# ============================================================
# 3. 历史事件数据
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

    # 预置公开事件数据（已扩充）
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

    filtered = []
    for event in events:
        if event.get('date', '') >= cutoff_str:
            filtered.append(event)

    result["data"] = filtered
    logger.info(f"   ✅ 事件数据: {len(filtered)} 条 (过滤后)")

    return result


# ============================================================
# 4. 历史板块数据（增强版）
# ============================================================

def fetch_historical_sector(years: int = 20) -> Dict[str, Any]:
    """
    采集历史板块数据
    ★ 修复：使用多种接口备选，增加列名智能检测
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
            df = None

            # ★ 尝试多种接口
            try:
                df = ak.index_hist_sw(symbol=code)
            except Exception as e:
                logger.debug(f"   index_hist_sw 失败: {e}")
                try:
                    # 备选：使用申万行情
                    df = ak.index_hist_fund_sw(symbol=code)
                except Exception as e2:
                    logger.debug(f"   index_hist_fund_sw 失败: {e2}")

            if df is None or df.empty:
                logger.warning(f"   ⚠️ {sector}: 所有接口均无数据")
                continue

            # ★ 智能检测列名
            date_col = None
            close_col = None

            for col in df.columns:
                col_lower = str(col).lower()
                if 'date' in col_lower or '日期' in str(col) or 'time' in col_lower:
                    date_col = col
                if 'close' in col_lower or '收盘' in str(col) or 'price' in col_lower:
                    close_col = col

            if date_col is None:
                # 尝试找任何包含日期的列
                for col in df.columns:
                    if 'day' in str(col).lower() or 'date' in str(col).lower():
                        date_col = col
                        break

            if date_col is None:
                logger.warning(f"   ⚠️ {sector}: 未找到日期列，列名: {list(df.columns)[:5]}...")
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
                result["data"][sector] = data
                logger.info(f"   ✅ {sector}: {len(data)} 条记录")
            else:
                logger.warning(f"   ⚠️ {sector}: 无有效数据")

            time.sleep(0.3)

        except Exception as e:
            logger.warning(f"   ⚠️ {sector}: 采集失败 - {e}")

    return result


# ============================================================
# 5. 统一打包与签名（★ V1.2 核心功能）
# ============================================================

def pack_historical_data(
    market_data: Dict[str, Any],
    macro_data: Dict[str, Any],
    events_data: Dict[str, Any],
    sector_data: Dict[str, Any]
) -> Dict[str, Any]:
    """
    将所有历史数据打包为统一格式，并签名
    """
    logger.info("📦 开始打包历史数据...")

    package = {
        "package_type": "historical_data",
        "generated_at": datetime.now().isoformat(),
        "version": "1.0",
        "contents": {}
    }

    # 只包含有数据的类型
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

    # 生成统计信息
    package["metadata"] = {
        "total_items": sum(
            len(v.get('data', [])) if isinstance(v.get('data'), list) else len(v.get('data', {}))
            for v in package["contents"].values()
        ),
        "data_types": list(package["contents"].keys())
    }

    # ★ 签名
    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置，数据包未签名")

    logger.info(f"   📊 打包完成: {len(package['contents'])} 个数据类型")

    return package


# ============================================================
# 6. 保存与上传
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
    """保存调试数据（用于排查问题）"""
    os.makedirs(STAGING_DIR, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"historical_{suffix}_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    logger.debug(f"📝 调试数据已保存: {filename}")


# ============================================================
# 7. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集历史数据（打包签名版）')
    parser.add_argument('--type', choices=['market', 'macro', 'events', 'sector', 'all'],
                       default='all', help='数据类型')
    parser.add_argument('--years', type=int, default=30,
                       help='回溯年数（默认30）')
    parser.add_argument('--debug', action='store_true',
                       help='启用调试模式，保存原始数据')
    args = parser.parse_args()

    logger.info(f"🚀 开始采集历史数据 (类型: {args.type}, 年数: {args.years})")

    market_data = {}
    macro_data = {}
    events_data = {}
    sector_data = {}

    # 1. 采集各类型数据
    if args.type in ['market', 'all']:
        market_data = fetch_historical_market(args.years)
        if args.debug:
            save_debug_data(market_data, 'market')

    if args.type in ['macro', 'all']:
        macro_data = fetch_historical_macro(args.years)
        if args.debug:
            save_debug_data(macro_data, 'macro')

    if args.type in ['events', 'all']:
        events_data = fetch_historical_events(args.years)
        if args.debug:
            save_debug_data(events_data, 'events')

    if args.type in ['sector', 'all']:
        sector_data = fetch_historical_sector(min(args.years, 20))
        if args.debug:
            save_debug_data(sector_data, 'sector')

    # 2. 检查是否有数据
    has_data = any([
        market_data.get('data'),
        macro_data.get('data'),
        events_data.get('data'),
        sector_data.get('data')
    ])

    if not has_data:
        logger.warning("⚠️ 所有数据源均无数据，生成空包（供测试）")
        # 生成空包以维持工作流运行
        package = {
            "package_type": "historical_data",
            "generated_at": datetime.now().isoformat(),
            "version": "1.0",
            "contents": {},
            "metadata": {
                "total_items": 0,
                "data_types": [],
                "note": "所有数据源均无数据"
            }
        }
        key = get_signing_key()
        if key:
            package["signature"] = sign_data(package, key)
        else:
            package["signature"] = None
    else:
        # 3. 打包并签名
        package = pack_historical_data(market_data, macro_data, events_data, sector_data)

    # 4. 保存
    filepath = save_package(package)

    logger.info("✅ 历史数据采集完成")
    logger.info(f"   📦 输出文件: {filepath}")
    logger.info(f"   📊 数据包大小: {len(package.get('contents', {}))} 个数据类型")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
