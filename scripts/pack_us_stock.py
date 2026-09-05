#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
美股数据打包模块（独立）
将 collect_us_stock.py 输出的签名文件打包成统一数据包格式
★ 2026-09-06 新建：统一美股数据包格式（含 trade_date / is_trading_day / dst_active）
"""

import os
import sys
import json
import glob
import hmac
import hashlib
import logging
from datetime import datetime, timedelta
import pytz

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def get_beijing_time():
    """获取北京时间（带时区）"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(beijing_tz)


def get_signing_key():
    """从环境变量获取签名密钥"""
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，使用默认测试密钥")
        return "test-key-do-not-use-in-production"
    return key


def sign_package(data: dict, key: str) -> str:
    """对数据包进行HMAC-SHA256签名（与公开库sign.py保持一致）"""
    sign_data = {k: v for k, v in data.items() if k != 'signature'}
    content = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)
    signature = hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def is_trading_day(date_obj):
    """判断是否为交易日（周六日休市）"""
    return date_obj.weekday() < 5


def find_latest_us_stock_file():
    """查找最新的美股签名文件"""
    pattern = os.path.join(STAGING_DIR, "us_stock_*_signed.json")
    files = glob.glob(pattern)
    # 排除缓存文件
    files = [f for f in files if "cache" not in f]
    if not files:
        return None
    files.sort(key=os.path.getmtime, reverse=True)
    return files[0]


def extract_trade_date_from_data(data):
    """从数据中提取交易日日期"""
    # 尝试从 items 中提取 date
    items = data.get("content", {}).get("items", [])
    if items and isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and item.get("date"):
                return item["date"]
    # 尝试从 payload 中提取
    if "payload" in data and isinstance(data["payload"], dict):
        payload = data["payload"]
        if "date" in payload:
            return payload["date"]
        if "items" in payload and isinstance(payload["items"], list):
            for item in payload["items"]:
                if isinstance(item, dict) and item.get("date"):
                    return item["date"]
    # 如果都没有，从 generated_at 推断
    generated_at = data.get("generated_at") or data.get("signed_at") or data.get("timestamp")
    if generated_at:
        try:
            # 尝试解析ISO格式
            if generated_at.endswith('Z'):
                generated_at = generated_at[:-1] + '+00:00'
            dt = datetime.fromisoformat(generated_at)
            # 美股收盘数据对应前一个交易日（因为美股收盘在次日凌晨）
            # 但为了简单，我们直接使用采集日期的前一天
            # 后续可结合万年历优化
            trade_date = dt.date() - timedelta(days=1)
            return trade_date.isoformat()
        except:
            pass
    # 最后兜底：使用当前日期减一天
    return (datetime.now().date() - timedelta(days=1)).isoformat()


def pack_us_stock():
    """打包美股数据"""
    logger.info("📦 开始打包美股数据...")

    # 查找最新的美股签名文件
    input_file = find_latest_us_stock_file()
    if not input_file:
        logger.error("❌ 未找到美股签名文件")
        return None

    logger.info(f"📂 输入文件: {input_file}")

    # 读取数据
    with open(input_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    # 提取数据内容
    content = raw_data.get("content", {})
    if not content:
        # 尝试从 payload 提取
        if "payload" in raw_data:
            content = raw_data["payload"]
        else:
            content = raw_data

    # 提取美股指数数据
    items = content.get("items", [])
    if not items:
        logger.warning("⚠️ 未找到 items 列表，可能数据格式不标准")
        # 尝试直接使用 content
        items = [{"name": k, "value": v} for k, v in content.items() if k not in ["timestamp", "source"]]

    # 获取北京时间
    beijing_time = get_beijing_time()
    trade_date_str = extract_trade_date_from_data(raw_data)
    # 如果 trade_date_str 是日期字符串，保持；否则使用当前日期减一天
    try:
        trade_date = datetime.fromisoformat(trade_date_str).date()
    except:
        trade_date = beijing_time.date() - timedelta(days=1)
        trade_date_str = trade_date.isoformat()

    is_trading = is_trading_day(beijing_time.date())
    dst_active = False  # 中国无夏令时

    # 构建统一数据包
    package = {
        "book": "公开数据",
        "chapter": "us_stock",
        "version": "2.0",
        "generated_at": beijing_time.isoformat(),
        "trade_date": trade_date_str,
        "is_trading_day": is_trading,
        "dst_active": dst_active,
        "content": {
            "us_market": {
                "indices": {},
                "total": len(items),
                "timestamp": content.get("timestamp", beijing_time.isoformat()),
                "source": "us_stock_collector"
            }
        }
    }

    # 填充指数数据
    # 名称映射
    name_map = {
        "道琼斯": "道琼斯",
        "纳斯达克": "纳斯达克",
        "标普500": "标普500",
        "^DJI": "道琼斯",
        "^IXIC": "纳斯达克",
        "^GSPC": "标普500",
    }

    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name", "")
        if not name:
            symbol = item.get("symbol", "")
            if symbol in name_map:
                name = name_map[symbol]
            else:
                # 尝试从symbol猜测
                if "DJI" in symbol:
                    name = "道琼斯"
                elif "IXIC" in symbol:
                    name = "纳斯达克"
                elif "GSPC" in symbol or "SPX" in symbol:
                    name = "标普500"
                else:
                    continue
        if name in name_map:
            cn_name = name_map[name]
        else:
            cn_name = name

        price = item.get("price", 0)
        pct_change = item.get("change_pct", item.get("pct_change", item.get("change", 0)))
        # 确保是数值
        try:
            pct_change = float(pct_change) if pct_change is not None else 0.0
            price = float(price) if price is not None else 0.0
        except:
            pct_change = 0.0
            price = 0.0

        package["content"]["us_market"]["indices"][cn_name] = {
            "price": price,
            "pct_change": pct_change,
            "symbol": item.get("symbol", ""),
            "date": item.get("date", trade_date_str)
        }

    if not package["content"]["us_market"]["indices"]:
        logger.error("❌ 未提取到任何指数数据，打包失败")
        return None

    # 添加英文兼容键
    en_map = {
        "纳斯达克": "nasdaq",
        "标普500": "sp500",
        "道琼斯": "dow"
    }
    for cn_name, data in package["content"]["us_market"]["indices"].items():
        if cn_name in en_map:
            en_key = en_map[cn_name]
            package["content"][en_key] = data["pct_change"]
            package["content"][en_key + "_pct"] = data["pct_change"]

    # 签名
    key = get_signing_key()
    package["signature"] = sign_package(package, key)
    package["signature_metadata"] = {
        "algorithm": "HMAC-SHA256",
        "timestamp": beijing_time.isoformat()
    }

    # 保存打包文件
    timestamp = beijing_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(STAGING_DIR, f"us_stock_package_{timestamp}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    logger.info(f"✅ 打包完成: {output_file}")
    logger.info(f"📊 包含指数: {len(package['content']['us_market']['indices'])} 个")
    logger.info(f"📅 交易日: {trade_date_str}, 是否交易日: {is_trading}")
    return output_file


if __name__ == "__main__":
    pack_us_stock()
