#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
港股指数采集模块（公开库）
采集：恒生指数、恒生科技指数、国企指数
频率：每日 17:00（港股 16:00 收盘后）
数据源：akshare

★ 使用方式：
  python scripts/collect_hk_stock.py              # 采集全部指数
  python scripts/collect_hk_stock.py --debug      # 调试模式

★ 输出文件：
  staging/hk_stock_raw_*.json          # 原始数据（调试用）
  staging/hk_stock_package_*.json      # 签名打包后的数据包
"""

import os
import sys
import json
import argparse
import hmac
import hashlib
import logging
from datetime import datetime
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
    sign_data_content = {k: v for k, v in data.items() 
                         if k not in ['signature', 'signature_metadata']}
    content = json.dumps(sign_data_content, sort_keys=True, ensure_ascii=False)
    return hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()


# ============================================================
# 2. 采集函数
# ============================================================

def fetch_hk_stock_spot() -> List[Dict[str, Any]]:
    """
    从 akshare 采集港股指数实时行情（收盘后即收盘价）
    """
    try:
        import akshare as ak
    except ImportError:
        logger.error("❌ akshare 未安装")
        return []

    # 港股指数列表
    indices = [
        {"symbol": "HSI", "name": "恒生指数"},
        {"symbol": "HSCEI", "name": "恒生国企指数"},
        {"symbol": "HSTECH", "name": "恒生科技指数"},
    ]

    results = []

    for idx in indices:
        try:
            logger.info(f"   📡 采集 {idx['name']} ({idx['symbol']})...")

            # 方法1：使用 stock_hk_index_spot 获取实时行情
            try:
                df = ak.stock_hk_index_spot(symbol=idx["symbol"])
                if df is not None and not df.empty:
                    # 提取最新数据
                    row = df.iloc[-1] if len(df) > 1 else df.iloc[0]
                    
                    # 智能检测列名
                    price_col = None
                    change_pct_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'price' in col_lower or '最新价' in col or '现价' in col:
                            price_col = col
                        if 'change' in col_lower and 'pct' in col_lower or '涨跌幅' in col:
                            change_pct_col = col
                        if 'pct_chg' in col_lower or 'pctchange' in col_lower:
                            change_pct_col = col
                    
                    # 如果没找到，使用默认列名
                    if price_col is None:
                        # 尝试找数值列
                        for col in df.columns:
                            if df[col].dtype in ['float64', 'int64'] and col != change_pct_col:
                                price_col = col
                                break
                    if price_col is None:
                        price_col = df.columns[0]  # 兜底

                    price = float(row.get(price_col, 0))
                    change_pct = 0.0
                    if change_pct_col:
                        try:
                            change_pct = float(row.get(change_pct_col, 0))
                        except (ValueError, TypeError):
                            pass

                    # 获取日期（取当前日期）
                    date_str = datetime.now().strftime("%Y-%m-%d")

                    results.append({
                        "symbol": idx["symbol"],
                        "name": idx["name"],
                        "price": price,
                        "change_pct": change_pct,
                        "date": date_str,
                        "source": "akshare_spot",
                    })
                    logger.info(f"   ✅ {idx['name']}: {price} ({change_pct:+.2f}%)")
                    continue
            except Exception as e:
                logger.debug(f"      stock_hk_index_spot 失败: {e}")

            # 方法2：使用 stock_hk_index_daily 获取日线数据（降级）
            try:
                df = ak.stock_hk_index_daily(symbol=idx["symbol"])
                if df is not None and not df.empty:
                    # 取最近一天
                    row = df.iloc[-1]
                    
                    # 检测列名
                    date_col = None
                    close_col = None
                    change_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'date' in col_lower or '日期' in col or 'time' in col_lower:
                            date_col = col
                        if 'close' in col_lower or '收盘' in col:
                            close_col = col
                        if 'change' in col_lower and 'pct' in col_lower or '涨跌幅' in col:
                            change_col = col
                    
                    if close_col is None:
                        # 尝试找数值列
                        for col in df.columns:
                            if df[col].dtype in ['float64', 'int64'] and col != change_col:
                                close_col = col
                                break
                    if close_col is None:
                        continue

                    date_val = row.get(date_col)
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m-%d")
                    else:
                        date_str = str(date_val)[:10]

                    price = float(row.get(close_col, 0))
                    change_pct = 0.0
                    if change_col:
                        try:
                            change_pct = float(row.get(change_col, 0))
                        except (ValueError, TypeError):
                            pass

                    results.append({
                        "symbol": idx["symbol"],
                        "name": idx["name"],
                        "price": price,
                        "change_pct": change_pct,
                        "date": date_str,
                        "source": "akshare_daily",
                    })
                    logger.info(f"   ✅ {idx['name']}: {price} ({change_pct:+.2f}%) [日线]")
                    continue
            except Exception as e:
                logger.debug(f"      stock_hk_index_daily 失败: {e}")

            # 方法3：使用 index_hist_hk（备选）
            try:
                df = ak.index_hist_hk(symbol=idx["symbol"])
                if df is not None and not df.empty:
                    row = df.iloc[-1]
                    date_col = None
                    close_col = None
                    for col in df.columns:
                        col_lower = col.lower()
                        if 'date' in col_lower or '日期' in col:
                            date_col = col
                        if 'close' in col_lower or '收盘' in col:
                            close_col = col
                    if close_col is None:
                        continue
                    date_val = row.get(date_col)
                    if hasattr(date_val, 'strftime'):
                        date_str = date_val.strftime("%Y-%m-%d")
                    else:
                        date_str = str(date_val)[:10]
                    price = float(row.get(close_col, 0))
                    results.append({
                        "symbol": idx["symbol"],
                        "name": idx["name"],
                        "price": price,
                        "change_pct": 0.0,
                        "date": date_str,
                        "source": "akshare_index_hist",
                    })
                    logger.info(f"   ✅ {idx['name']}: {price} [历史接口]")
                    continue
            except Exception as e:
                logger.debug(f"      index_hist_hk 失败: {e}")

            # 全部失败
            logger.warning(f"   ⚠️ {idx['name']}: 所有接口均失败")
            results.append({
                "symbol": idx["symbol"],
                "name": idx["name"],
                "price": 0,
                "change_pct": 0.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "failed",
            })

        except Exception as e:
            logger.warning(f"   ⚠️ {idx['name']}: 采集异常 - {e}")
            results.append({
                "symbol": idx["symbol"],
                "name": idx["name"],
                "price": 0,
                "change_pct": 0.0,
                "date": datetime.now().strftime("%Y-%m-%d"),
                "source": "error",
            })

    return results


# ============================================================
# 3. 打包与签名
# ============================================================

def build_package(indices_data: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    构建统一格式的港股数据包
    """
    now = datetime.now()
    trade_date = now.strftime("%Y-%m-%d")

    # 从万年历获取今日是否为交易日（简化：如果港股有数据则认为是交易日）
    # 实际生产中，私密库会结合万年历判断
    is_trading_day = len(indices_data) > 0 and any(d.get('price', 0) > 0 for d in indices_data)

    # 判断 DST（港股不实行夏令时，固定为 false）
    dst_active = False

    # 构建指数列表
    indices = []
    for item in indices_data:
        indices.append({
            "symbol": item.get("symbol", ""),
            "name": item.get("name", ""),
            "price": item.get("price", 0),
            "change_pct": item.get("change_pct", 0.0),
            "date": item.get("date", trade_date),
            "source": item.get("source", "unknown"),
        })

    package = {
        "book": "公开数据",
        "chapter": "hk_stock",
        "version": "2.0",
        "generated_at": now.isoformat() + "+08:00",
        "trade_date": trade_date,
        "is_trading_day": is_trading_day,
        "dst_active": dst_active,
        "content": {
            "total": len(indices),
            "indices": indices,
        },
        "metadata": {
            "source": "akshare",
            "collected_at": now.isoformat(),
            "data_type": "hk_stock",
        },
    }

    # 签名
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
    filename = f"hk_stock_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    file_size = os.path.getsize(filepath)
    logger.info(f"✅ 已保存: {filename} ({file_size/1024:.1f} KB)")
    return filepath


def save_debug_data(data: List[Dict[str, Any]]):
    """保存调试数据"""
    os.makedirs(STAGING_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"hk_stock_raw_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    logger.info(f"   📝 调试数据已保存: {filename}")


# ============================================================
# 4. 主函数
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集港股指数数据')
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    args = parser.parse_args()

    logger.info("=" * 60)
    logger.info("🇭🇰 港股指数采集启动")
    logger.info("=" * 60)

    try:
        # 1. 采集数据
        indices_data = fetch_hk_stock_spot()

        # 2. 调试模式保存原始数据
        if args.debug:
            save_debug_data(indices_data)

        # 3. 统计
        success_count = sum(1 for d in indices_data if d.get('price', 0) > 0)
        total_count = len(indices_data)

        logger.info(f"   📊 采集统计: 成功 {success_count}/{total_count} 个指数")

        # 4. 打包并签名
        package = build_package(indices_data)

        # 5. 保存
        filepath = save_package(package)

        # 6. 打印摘要
        logger.info("=" * 60)
        logger.info("✅ 港股指数采集完成")
        logger.info(f"   🇭🇰 指数数量: {len(indices_data)}")
        logger.info(f"   ✅ 成功采集: {success_count}")
        logger.info(f"   ❌ 失败: {total_count - success_count}")
        logger.info(f"   📦 输出文件: {filepath}")
        logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")
        logger.info("=" * 60)

        return 0 if success_count > 0 else 1

    except Exception as e:
        logger.error(f"❌ 采集失败: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
