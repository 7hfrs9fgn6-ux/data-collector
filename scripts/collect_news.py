#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻采集脚本（公开库版）
基于 RSS/Atom + feedparser + GDELT/Hacker News
所有数据源无需 API Key，零泄露风险
"""

import os
import sys
import json
import time
import argparse
import hashlib
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

try:
    import feedparser
except ImportError:
    print("❌ 缺少 feedparser 依赖，请安装: pip install feedparser")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("❌ 缺少 requests 依赖，请安装: pip install requests")
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
    """加载配置文件"""
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
    """免费新闻采集器（RSS/Atom + GDELT + Hacker News）"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or load_config()
        self.news_config = self.config.get('collect', {}).get('news', {})
        self.max_per_source = self.news_config.get('max_items_per_source', 15)
        self.max_total = self.news_config.get('max_total_items', 80)
        self.timeout = 15
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (compatible; data-collector/1.0; +https://github.com/your-org/data-collector)',
            'Accept': 'application/json, application/rss+xml, application/xml, text/xml, */*',
        })

    # ============================================================
    # 数据源1：RSS/Atom 订阅源
    # ============================================================
    def _fetch_rss_feeds(self, feeds: List[str]) -> List[Dict[str, Any]]:
        """采集多个 RSS/Atom 订阅源"""
        all_items = []
        for feed_url in feeds:
            try:
                logger.debug(f"   📡 RSS 抓取: {feed_url}")
                parsed = feedparser.parse(feed_url)

                if parsed.bozo:
                    logger.debug(f"   ⚠️ RSS 解析警告: {parsed.bozo_exception}")

                count = 0
                for entry in parsed.entries[:self.max_per_source]:
                    title = entry.get('title', '')
                    if not title:
                        continue
                    all_items.append({
                        'title': title,
                        'summary': entry.get('summary', title),
                        'content': entry.get('content', [{'value': title}])[0].get('value', title),
                        'publish_time': entry.get('published', entry.get('updated', '')),
                        'source': entry.get('source', {}).get('title', 'RSS'),
                        'source_type': 'rss',
                        'url': entry.get('link', ''),
                        'collected_at': datetime.now().isoformat()
                    })
                    count += 1
                logger.info(f"   ✅ RSS({feed_url[:50]}...): 采集到 {count} 条")

            except Exception as e:
                logger.debug(f"   ❌ RSS 采集失败 ({feed_url}): {e}")

        return all_items

    # ============================================================
    # 数据源2：GDELT（全球新闻数据库）
    # ============================================================
    def _fetch_gdelt(self) -> List[Dict[str, Any]]:
        """采集 GDELT 最新新闻（无需 Key）"""
        # GDELT 的实时新闻流
        url = "https://api.gdeltproject.org/api/v2/doc/doc"
        params = {
            'query': 'source:news',
            'mode': 'artlist',
            'maxrecords': str(self.max_per_source),
            'format': 'json',
            't': 'days',  # 过去一天
            'timespan': '1h'  # 过去一小时
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"GDELT 返回: {resp.status_code}")
                return []

            data = resp.json()
            articles = data.get('articles', [])

            result = []
            for article in articles[:self.max_per_source]:
                title = article.get('title', '')
                if not title:
                    continue
                result.append({
                    'title': title,
                    'summary': article.get('snippet', title),
                    'content': article.get('snippet', title),
                    'publish_time': article.get('date', ''),
                    'source': article.get('source', 'GDELT'),
                    'source_type': 'gdelt',
                    'url': article.get('url', ''),
                    'collected_at': datetime.now().isoformat()
                })
            logger.info(f"   ✅ GDELT: 采集到 {len(result)} 条新闻")
            return result

        except Exception as e:
            logger.debug(f"GDELT 采集失败: {e}")
            return []

    # ============================================================
    # 数据源3：Hacker News（技术/创业新闻）
    # ============================================================
    def _fetch_hackernews(self) -> List[Dict[str, Any]]:
        """采集 Hacker News 最新新闻（无需 Key）"""
        try:
            # 获取最新 top stories ID 列表
            top_url = "https://hacker-news.firebaseio.com/v0/topstories.json"
            resp = self.session.get(top_url, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"HN 返回: {resp.status_code}")
                return []

            story_ids = resp.json()[:self.max_per_source * 2]  # 多取一些以防无效

            result = []
            for story_id in story_ids:
                if len(result) >= self.max_per_source:
                    break
                try:
                    story_url = f"https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
                    story_resp = self.session.get(story_url, timeout=self.timeout)
                    if story_resp.status_code != 200:
                        continue

                    data = story_resp.json()
                    title = data.get('title', '')
                    if not title or data.get('dead', False) or data.get('deleted', False):
                        continue

                    result.append({
                        'title': title,
                        'summary': f"Score: {data.get('score', 0)} | {data.get('by', 'unknown')}",
                        'content': title,
                        'publish_time': datetime.fromtimestamp(data.get('time', 0)).isoformat() if data.get('time') else '',
                        'source': 'Hacker News',
                        'source_type': 'hackernews',
                        'url': data.get('url', f"https://news.ycombinator.com/item?id={story_id}"),
                        'collected_at': datetime.now().isoformat()
                    })
                except Exception as e:
                    continue

            logger.info(f"   ✅ Hacker News: 采集到 {len(result)} 条新闻")
            return result

        except Exception as e:
            logger.debug(f"Hacker News 采集失败: {e}")
            return []

    # ============================================================
    # 数据源4：RSSHub 聚合（备选）
    # ============================================================
    def _fetch_rsshub(self) -> List[Dict[str, Any]]:
        """通过 RSSHub 聚合财经新闻（无需 Key）"""
        rsshub_routes = [
            "https://rsshub.app/eastmoney/kuaixun",
            "https://rsshub.app/finance/163/latest",
            "https://rsshub.app/sina/finance",
        ]

        all_items = []
        for route in rsshub_routes:
            try:
                parsed = feedparser.parse(route)
                if parsed.bozo:
                    continue
                count = 0
                for entry in parsed.entries[:self.max_per_source]:
                    title = entry.get('title', '')
                    if not title:
                        continue
                    all_items.append({
                        'title': title,
                        'summary': entry.get('summary', title),
                        'content': entry.get('content', [{'value': title}])[0].get('value', title),
                        'publish_time': entry.get('published', entry.get('updated', '')),
                        'source': 'RSSHub',
                        'source_type': 'rsshub',
                        'url': entry.get('link', ''),
                        'collected_at': datetime.now().isoformat()
                    })
                    count += 1
                if count > 0:
                    logger.info(f"   ✅ RSSHub({route}): 采集到 {count} 条")
                    break  # 成功一个即可
            except Exception as e:
                continue

        return all_items

    def collect_all(self) -> List[Dict[str, Any]]:
        """采集所有数据源"""
        all_news = []
        source_stats = {}

        # 从配置文件获取 RSS 源列表
        rss_feeds = self.news_config.get('rss_feeds', [
            "https://news.google.com/rss/search?q=finance+stocks+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://news.google.com/rss/search?q=economy+when:1d&hl=zh-CN&gl=CN&ceid=CN:zh-Hans",
            "https://feeds.bloomberg.com/markets/news.rss",
            "https://www.cnbc.com/id/10001147/device/rss/rss.html",
        ])

        # 1. RSS 源
        try:
            news = self._fetch_rss_feeds(rss_feeds)
            all_news.extend(news)
            source_stats['rss'] = len(news)
        except Exception as e:
            logger.error(f"   ❌ RSS 采集失败: {e}")
            source_stats['rss'] = 0

        # 2. GDELT
        try:
            news = self._fetch_gdelt()
            all_news.extend(news)
            source_stats['gdelt'] = len(news)
        except Exception as e:
            logger.error(f"   ❌ GDELT 采集失败: {e}")
            source_stats['gdelt'] = 0

        # 3. Hacker News
        try:
            news = self._fetch_hackernews()
            all_news.extend(news)
            source_stats['hackernews'] = len(news)
        except Exception as e:
            logger.error(f"   ❌ Hacker News 采集失败: {e}")
            source_stats['hackernews'] = 0

        # 4. RSSHub 备选（如果其他源都失败）
        if not all_news:
            try:
                news = self._fetch_rsshub()
                all_news.extend(news)
                source_stats['rsshub'] = len(news)
            except Exception as e:
                logger.error(f"   ❌ RSSHub 采集失败: {e}")
                source_stats['rsshub'] = 0

        # 截断到最大总数
        if len(all_news) > self.max_total:
            all_news = all_news[:self.max_total]

        logger.info(f"📊 总计采集: {len(all_news)} 条新闻")
        logger.info(f"📊 来源分布: {source_stats}")
        return all_news


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
    parser = argparse.ArgumentParser(description='免费新闻采集（RSS/Atom + GDELT + Hacker News）')
    parser.add_argument('--limit', type=int, default=15,
                        help='每条源采集条数（默认15）')
    parser.add_argument('--output', type=str, default='staging',
                        help='输出目录（默认staging）')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("📡 data-collector 新闻采集启动（RSS/Atom + GDELT + HN）")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📊 单源限制: {args.limit} 条")
    logger.info("=" * 50)

    config = load_config()
    collector = FreeNewsCollector(config)
    news_list = collector.collect_all()

    if news_list:
        save_raw_news(news_list, args.output)
    else:
        logger.warning("⚠️ 未采集到任何新闻，生成空包")
        save_raw_news([], args.output)

    logger.info("=" * 50)
    logger.info(f"✅ 新闻采集完成: {len(news_list)} 条")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
