#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻打包脚本
将筛选后的新闻打包成标准JSON格式，并添加HMAC-SHA256签名
★ 2026-09-06 升级：统一数据包格式（加北京时间 + trade_date + is_trading_day + dst_active）
"""

import os
import sys
import json
import glob
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging
import pytz

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def get_beijing_time():
    """获取北京时间（带时区）"""
    beijing_tz = pytz.timezone('Asia/Shanghai')
    return datetime.now(beijing_tz)


def get_trade_date(beijing_time):
    """获取交易日日期（北京时间日期）"""
    return beijing_time.strftime("%Y-%m-%d")


def is_trading_day(beijing_time):
    """判断是否为交易日（根据星期）"""
    weekday = beijing_time.weekday()
    return weekday < 5


def is_dst_active(beijing_time):
    """判断当前是否处于夏令时（中国没有夏令时，固定返回False）"""
    return False


def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
    if os.path.exists(config_path):
        try:
            import yaml
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f) or {}
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
    return {}


def get_signing_key() -> str:
    """从环境变量获取签名密钥"""
    key = os.environ.get('SIGNING_KEY', '')
    if not key:
        logger.warning("⚠️ SIGNING_KEY 环境变量未设置，使用默认测试密钥")
        return "test-key-do-not-use-in-production"
    return key


def sign_package(data: dict, key: str) -> str:
    """
    对数据包进行HMAC-SHA256签名
    使用与私密库一致的序列化方式
    """
    sign_data = {k: v for k, v in data.items() if k != 'signature'}
    import json
    import hmac
    import hashlib
    content = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)
    signature = hmac.new(
        key.encode('utf-8'),
        content.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return signature


def pack_news(articles: List[Dict[str, Any]], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """打包新闻数据，自动添加签名"""
    config = config or {}

    # 获取北京时间
    beijing_time = get_beijing_time()
    trade_date = get_trade_date(beijing_time)
    is_trading = is_trading_day(beijing_time)
    dst_active = is_dst_active(beijing_time)

    # 应用条数限制
    max_items = config.get('collect', {}).get('news', {}).get('max_total_items', 80)
    if len(articles) > max_items:
        logger.info(f"📊 截断新闻: {len(articles)} → {max_items} 条")
        articles = articles[:max_items]

    # 统计来源分布
    source_stats = {}
    for article in articles:
        source = article.get('source', '未知')
        source_stats[source] = source_stats.get(source, 0) + 1

    # 生成打包数据（统一格式）
    package = {
        # 统一字段（所有数据包一致）
        "book": "公开数据",
        "chapter": "news_aggregation",
        "version": "2.0",
        "generated_at": beijing_time.isoformat(),
        "trade_date": trade_date,
        "is_trading_day": is_trading,
        "dst_active": dst_active,
        # 新闻特有字段
        "period": {
            "start": (beijing_time - timedelta(hours=1)).isoformat(),
            "end": beijing_time.isoformat()
        },
        "content": {
            "total": len(articles),
            "items": articles
        },
        "metadata": {
            "sources": list(source_stats.keys()),
            "source_stats": source_stats,
            "quality_score": min(1.0, len(articles) / 50)
        }
    }

    # ★ 自动添加签名 ★
    key = get_signing_key()
    package['signature'] = sign_package(package, key)

    # 添加签名元数据
    package['signature_metadata'] = {
        'algorithm': 'HMAC-SHA256',
        'timestamp': beijing_time.isoformat()
    }

    return package


def main():
    logger.info("=" * 50)
    logger.info("📦 data-collector 新闻打包启动（自动签名）")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    staging_dir = "staging"
    config = load_config()

    # 查找最新的筛选后文件
    filtered_files = glob.glob(os.path.join(staging_dir, "filtered_news_*.json"))

    if not filtered_files:
        logger.warning("⚠️ 未找到筛选后的新闻文件，尝试使用原始文件")
        raw_files = glob.glob(os.path.join(staging_dir, "raw_news_*.json"))
        if not raw_files:
            logger.error("❌ 未找到任何新闻文件")
            sys.exit(1)
        raw_files.sort(key=os.path.getmtime, reverse=True)
        latest_file = raw_files[0]
        logger.info(f"📂 使用原始文件: {latest_file}")
    else:
        filtered_files.sort(key=os.path.getmtime, reverse=True)
        latest_file = filtered_files[0]
        logger.info(f"📂 使用筛选文件: {latest_file}")

    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    articles = data.get('articles', [])
    logger.info(f"📊 输入新闻: {len(articles)} 条")

    # 打包（自动签名）
    package = pack_news(articles, config)
    signature = package.get('signature', '')
    logger.info(f"🔐 签名: {signature[:16] if signature else '无'}...")

    # 保存打包文件
    beijing_time = get_beijing_time()
    timestamp = beijing_time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(staging_dir, f"news_package_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 保存打包文件: {output_file}")
    logger.info(f"📊 打包统计: {len(articles)} 条, 来源 {len(package['metadata']['sources'])} 个")
    logger.info(f"📅 交易日: {package.get('trade_date')}, 是否交易日: {package.get('is_trading_day')}")
    logger.info("=" * 50)
    logger.info("✅ 打包完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    from datetime import timedelta
    main()
