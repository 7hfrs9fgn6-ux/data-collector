#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻打包脚本
将筛选后的新闻打包成标准JSON格式
"""

import os
import sys
import json
import glob
from datetime import datetime
from typing import List, Dict, Any
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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


def pack_news(articles: List[Dict[str, Any]], config: Dict[str, Any] = None) -> Dict[str, Any]:
    """打包新闻数据"""
    config = config or {}

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

    # 生成打包数据
    return {
        'book': 'data-collector',
        'chapter': 'news_aggregation',
        'version': '3.0',
        'generated_at': datetime.now().isoformat(),
        'period': {
            'start': (datetime.now() - timedelta(hours=1)).isoformat(),
            'end': datetime.now().isoformat()
        },
        'content': {
            'total': len(articles),
            'items': articles
        },
        'metadata': {
            'sources': list(source_stats.keys()),
            'source_stats': source_stats,
            'quality_score': min(1.0, len(articles) / 50)  # 50条以上得满分
        },
        'signature': None  # 由 sign_news.py 填充
    }


def main():
    logger.info("=" * 50)
    logger.info("📦 data-collector 新闻打包启动")
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

    # 打包
    package = pack_news(articles, config)

    # 保存打包文件
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(staging_dir, f"news_package_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 保存打包文件: {output_file}")
    logger.info(f"📊 打包统计: {len(articles)} 条, 来源 {len(package['metadata']['sources'])} 个")
    logger.info("=" * 50)
    logger.info("✅ 打包完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    from datetime import timedelta
    main()
