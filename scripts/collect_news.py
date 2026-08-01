#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻采集脚本（公开库版）
使用 RSS + HTML 抓取，无需任何 API Key
"""

import os
import sys
import json
import time
import argparse
import hashlib
import re
from datetime import datetime
from typing import List, Dict, Any

try:
    import requests
except ImportError:
    print("❌ 缺少 requests 依赖，请安装: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("❌ 缺少 beautifulsoup4 依赖，请安装: pip install beautifulsoup4")
    sys.exit(1)

try:
    import yaml
except ImportError:
    yaml = None

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def load_config() -> Dict[str, Any]:
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.yaml')
    if os.path.exists(config_path):
        try:
            if yaml:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            else:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"加载配置文件失败: {e}")
    return {}


class FreeNewsCollector:
    """免费新闻采集器（RSS + HTML 抓取，无需API Key）"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or load_config()
        self.news_config = self.config.get('collect', {}).get('news', {})
        self.max_per_source = self.news_config.get('max_items_per_source', 15)
        self.timeout = 15
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        })

    def collect_all(self) -> List[Dict[str, Any]]:
        all_news = []
        source_stats = {}

        # 数据源1：东方财富 RSS
        try:
            news = self._fetch_eastmoney_rss()
            all_news.extend(news)
            source_stats['eastmoney'] = len(news)
            logger.info(f"   ✅ eastmoney: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ eastmoney 采集失败: {e}")
            source_stats['eastmoney'] = 0

        # 数据源2：新浪 RSS
        try:
            news = self._fetch_sina_rss()
            all_news.extend(news)
            source_stats['sina'] = len(news)
            logger.info(f"   ✅ sina: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ sina 采集失败: {e}")
            source_stats['sina'] = 0

        # 数据源3：网易 RSS（备用）
        try:
            news = self._fetch_163_rss()
            all_news.extend(news)
            source_stats['163'] = len(news)
            logger.info(f"   ✅ 163: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ 163 采集失败: {e}")
            source_stats['163'] = 0

        logger.info(f"📊 总计采集: {len(all_news)} 条新闻")
        logger.info(f"📊 来源分布: {source_stats}")
        return all_news

    def _fetch_eastmoney_rss(self) -> List[Dict[str, Any]]:
        """采集东方财富 RSS"""
        rss_url = "http://news.eastmoney.com/rss/news.xml"
        try:
            resp = self.session.get(rss_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"东财RSS返回: {resp.status_code}")
                return []

            # 解析 XML
            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)

            items = root.findall('./channel/item')
            result = []
            for item in items[:self.max_per_source]:
                title = item.find('title')
                link = item.find('link')
                pub_date = item.find('pubDate')
                description = item.find('description')

                title_text = title.text if title is not None else ''
                if not title_text:
                    continue

                result.append({
                    'title': title_text.strip(),
                    'summary': description.text.strip() if description is not None and description.text else title_text.strip(),
                    'content': title_text.strip(),
                    'publish_time': pub_date.text if pub_date is not None else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': '东方财富',
                    'source_type': 'eastmoney',
                    'url': link.text if link is not None else '',
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"东财RSS失败: {e}")
            return []

    def _fetch_sina_rss(self) -> List[Dict[str, Any]]:
        """采集新浪 RSS"""
        rss_url = "https://rss.sina.com.cn/roll/news/finance.xml"
        try:
            resp = self.session.get(rss_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"新浪RSS返回: {resp.status_code}")
                return []

            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)

            items = root.findall('./channel/item')
            result = []
            for item in items[:self.max_per_source]:
                title = item.find('title')
                link = item.find('link')
                pub_date = item.find('pubDate')
                description = item.find('description')

                title_text = title.text if title is not None else ''
                if not title_text:
                    continue

                result.append({
                    'title': title_text.strip(),
                    'summary': description.text.strip() if description is not None and description.text else title_text.strip(),
                    'content': title_text.strip(),
                    'publish_time': pub_date.text if pub_date is not None else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': '新浪财经',
                    'source_type': 'sina',
                    'url': link.text if link is not None else '',
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"新浪RSS失败: {e}")
            return []

    def _fetch_163_rss(self) -> List[Dict[str, Any]]:
        """采集网易 RSS"""
        rss_url = "https://news.163.com/special/00011K7l/news_finance.xml"
        try:
            resp = self.session.get(rss_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"网易RSS返回: {resp.status_code}")
                return []

            import xml.etree.ElementTree as ET
            root = ET.fromstring(resp.content)

            items = root.findall('./channel/item')
            result = []
            for item in items[:self.max_per_source]:
                title = item.find('title')
                link = item.find('link')
                pub_date = item.find('pubDate')
                description = item.find('description')

                title_text = title.text if title is not None else ''
                if not title_text:
                    continue

                result.append({
                    'title': title_text.strip(),
                    'summary': description.text.strip() if description is not None and description.text else title_text.strip(),
                    'content': title_text.strip(),
                    'publish_time': pub_date.text if pub_date is not None else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'source': '网易财经',
                    'source_type': '163',
                    'url': link.text if link is not None else '',
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"网易RSS失败: {e}")
            return []


def generate_article_id(article: Dict[str, Any]) -> str:
    """生成文章唯一ID"""
    url = article.get('url', '')
    if url:
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    title = article.get('title', '')
    source = article.get('source', '')
    key = f"{title}_{source}".encode('utf-8')
    return hashlib.md5(key).hexdigest()


def save_raw_news(news_list: List[Dict[str, Any]], output_dir: str = "staging"):
    os.makedirs(output_dir, exist_ok=True)
    for article in news_list:
        article['_id'] = generate_article_id(article)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"raw_news_{timestamp}.json"
    filepath = os.path.join(output_dir, filename)

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump({
            'collected_at': datetime.now().isoformat(),
            'total': len(news_list),
            'articles': news_list,
            'metadata': {
                'version': '1.0',
                'source': 'data-collector'
            }
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 保存原始新闻: {filepath} ({len(news_list)} 条)")
    return filepath


def main():
    parser = argparse.ArgumentParser(description='免费新闻采集（RSS + HTML）')
    parser.add_argument('--limit', type=int, default=15,
                        help='每条新闻源采集条数（默认15）')
    parser.add_argument('--output', type=str, default='staging',
                        help='输出目录（默认staging）')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("📡 data-collector 新闻采集启动（RSS版·无需Key）")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📊 单源限制: {args.limit} 条")
    logger.info("=" * 50)

    config = load_config()
    collector = FreeNewsCollector(config)
    news_list = collector.collect_all()

    if news_list:
        save_raw_news(news_list, args.output)
    else:
        # 生成空包，避免后续流程中断
        logger.warning("⚠️ 未采集到任何新闻，生成空包")
        save_raw_news([], args.output)

    logger.info("=" * 50)
    logger.info(f"✅ 新闻采集完成: {len(news_list)} 条")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
