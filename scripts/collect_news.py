#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻采集脚本（N-13 迁移）
多源采集：东财个股新闻 / 天行数据 / NewsAPI
输出：原始新闻 JSON 到 staging/raw_news_{timestamp}.json
"""

import os
import sys
import json
import time
import argparse
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import requests
import logging

# 配置日志
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


# ============================================================
# 数据源采集器
# ============================================================

class NewsCollector:
    """多源新闻采集器"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or load_config()
        self.news_config = self.config.get('collect', {}).get('news', {})
        self.max_per_source = self.news_config.get('max_items_per_source', 15)
        self.sources = self.news_config.get('sources', {})
        self.timeout = 10
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })

    def collect_all(self) -> List[Dict[str, Any]]:
        """采集所有数据源"""
        all_news = []
        source_stats = {}

        for source_name, source_config in self.sources.items():
            if not source_config.get('enabled', True):
                continue

            logger.info(f"📡 采集数据源: {source_name}")
            try:
                if source_name == 'eastmoney':
                    news = self._fetch_eastmoney(source_config)
                elif source_name == 'tianxing':
                    news = self._fetch_tianxing(source_config)
                elif source_name == 'newsapi':
                    news = self._fetch_newsapi(source_config)
                else:
                    logger.warning(f"未知数据源: {source_name}")
                    continue

                count = len(news)
                all_news.extend(news)
                source_stats[source_name] = count
                logger.info(f"   ✅ {source_name}: 采集到 {count} 条新闻")

            except Exception as e:
                logger.error(f"   ❌ {source_name} 采集失败: {e}")
                source_stats[source_name] = 0

        logger.info(f"📊 总计采集: {len(all_news)} 条新闻")
        logger.info(f"📊 来源分布: {source_stats}")
        return all_news

    # ============================================================
    # 1. 东财个股新闻
    # ============================================================
    def _fetch_eastmoney(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集东财个股新闻"""
        # 使用东财公开API获取热点新闻
        url = "https://push2.eastmoney.com/api/qt/stock/get"
        params = {
            'invt': '2',
            'fltt': '1',
            'cb': 'jQuery',
            'fields': 'f12,f14,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f13,f15,f16,f17,f18,f19,f20,f21,f22,f23',
            'secid': '1.000001',
            'ut': 'fa5fd1943c7b386f172d6893dbfba10b',
            'wbp2u': '1',
            '_': str(int(time.time() * 1000))
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            # 东财返回的是JSONP格式，需要提取数据
            text = resp.text
            if 'jQuery' in text:
                start = text.find('(')
                end = text.rfind(')')
                if start != -1 and end != -1:
                    data = json.loads(text[start+1:end])
                    # 简化处理：如果无法解析，返回空
                    return self._fetch_eastmoney_fallback()
            return self._fetch_eastmoney_fallback()
        except Exception as e:
            logger.debug(f"东财API调用失败: {e}")
            return self._fetch_eastmoney_fallback()

    def _fetch_eastmoney_fallback(self) -> List[Dict[str, Any]]:
        """东财备选：使用新闻列表API"""
        url = "https://newsapi.eastmoney.com/kuaixun/v1/getnews_limited"
        params = {
            'pageIndex': '1',
            'pageSize': str(self.max_per_source),
            'type': '1'
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            data = resp.json()
            articles = data.get('data', {}).get('list', [])
            result = []
            for item in articles[:self.max_per_source]:
                title = item.get('title', '')
                summary = item.get('summary', '')
                publish_time = item.get('publishTime', '')
                source = item.get('source', '东方财富')
                url = item.get('url', '')
                result.append({
                    'title': title,
                    'summary': summary or title,
                    'content': summary or title,
                    'publish_time': publish_time,
                    'source': source,
                    'source_type': 'eastmoney',
                    'url': url or f"https://news.eastmoney.com/{int(time.time())}",
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"东财备选API失败: {e}")
            return []

    # ============================================================
    # 2. 天行数据
    # ============================================================
    def _fetch_tianxing(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集天行数据（国内/国际新闻）"""
        key = os.environ.get('TIANXING_API_KEY', config.get('key_env', ''))
        if not key:
            logger.debug("天行数据Key未配置")
            return []

        # 天行数据：国内新闻
        url = "https://api.tianapi.com/guonei/index"
        params = {'key': key, 'num': self.max_per_source}
        news_list = []
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get('code') == 200:
                    for item in data.get('newslist', []):
                        news_list.append({
                            'title': item.get('title', ''),
                            'summary': item.get('description', item.get('title', '')),
                            'content': item.get('content', item.get('title', '')),
                            'publish_time': item.get('ctime', ''),
                            'source': '天行数据',
                            'source_type': 'tianxing',
                            'url': item.get('url', ''),
                            'collected_at': datetime.now().isoformat()
                        })
            else:
                logger.debug(f"天行国内API返回: {resp.status_code}")
        except Exception as e:
            logger.debug(f"天行国内API调用失败: {e}")

        # 如果国内新闻不足，尝试国际新闻
        if len(news_list) < self.max_per_source // 2:
            try:
                url_intl = "https://api.tianapi.com/world/index"
                params_intl = {'key': key, 'num': self.max_per_source - len(news_list)}
                resp = self.session.get(url_intl, params=params_intl, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get('code') == 200:
                        for item in data.get('newslist', []):
                            news_list.append({
                                'title': item.get('title', ''),
                                'summary': item.get('description', item.get('title', '')),
                                'content': item.get('content', item.get('title', '')),
                                'publish_time': item.get('ctime', ''),
                                'source': '天行数据(国际)',
                                'source_type': 'tianxing',
                                'url': item.get('url', ''),
                                'collected_at': datetime.now().isoformat()
                            })
            except Exception as e:
                logger.debug(f"天行国际API调用失败: {e}")

        return news_list[:self.max_per_source]

    # ============================================================
    # 3. NewsAPI
    # ============================================================
    def _fetch_newsapi(self, config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """采集NewsAPI"""
        key = os.environ.get('NEWSAPI_KEY', config.get('key_env', ''))
        if not key:
            logger.debug("NewsAPI Key未配置")
            return []

        # 财经相关关键词
        keywords = ['finance', 'stock', 'market', 'economy']
        all_news = []

        for keyword in keywords[:2]:  # 限制关键词数量避免超配额
            url = "https://newsapi.org/v2/everything"
            params = {
                'q': keyword,
                'language': 'zh',
                'sortBy': 'publishedAt',
                'pageSize': self.max_per_source // 2,
                'apiKey': key
            }
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout)
                if resp.status_code == 200:
                    data = resp.json()
                    for article in data.get('articles', []):
                        title = article.get('title', '')
                        if '[Removed]' in title or not title:
                            continue
                        all_news.append({
                            'title': title,
                            'summary': article.get('description', title),
                            'content': article.get('content', title),
                            'publish_time': article.get('publishedAt', ''),
                            'source': article.get('source', {}).get('name', 'NewsAPI'),
                            'source_type': 'newsapi',
                            'url': article.get('url', ''),
                            'collected_at': datetime.now().isoformat()
                        })
            except Exception as e:
                logger.debug(f"NewsAPI调用失败 ({keyword}): {e}")

        return all_news[:self.max_per_source]


# ============================================================
# 辅助函数
# ============================================================

def generate_article_id(article: Dict[str, Any]) -> str:
    """生成文章唯一ID（URL指纹或MD5）"""
    url = article.get('url', '')
    if url:
        # 使用URL的MD5作为指纹
        return hashlib.md5(url.encode('utf-8')).hexdigest()
    # 备选：使用标题+来源的MD5
    title = article.get('title', '')
    source = article.get('source', '')
    key = f"{title}_{source}".encode('utf-8')
    return hashlib.md5(key).hexdigest()


def save_raw_news(news_list: List[Dict[str, Any]], output_dir: str = "staging"):
    """保存原始新闻到JSON"""
    os.makedirs(output_dir, exist_ok=True)

    # 添加唯一ID
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


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='多源新闻采集')
    parser.add_argument('--limit', type=int, default=15,
                        help='每条新闻源采集条数（默认15）')
    parser.add_argument('--output', type=str, default='staging',
                        help='输出目录（默认staging）')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("📡 data-collector 新闻采集启动")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📊 单源限制: {args.limit} 条")
    logger.info("=" * 50)

    # 加载配置并覆盖limit
    config = load_config()
    news_config = config.get('collect', {}).get('news', {})
    if args.limit:
        news_config['max_items_per_source'] = args.limit

    # 采集
    collector = NewsCollector(config)
    news_list = collector.collect_all()

    if not news_list:
        logger.warning("⚠️ 未采集到任何新闻")
        # 生成空数据包，避免后续流程中断
        news_list = []

    # 保存
    save_raw_news(news_list, args.output)

    logger.info("=" * 50)
    logger.info(f"✅ 新闻采集完成: {len(news_list)} 条")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
