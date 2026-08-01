#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻采集脚本（公开库版）
只使用完全免费、无需认证的数据源
"""

import os
import sys
import json
import time
import argparse
import hashlib
from datetime import datetime, timedelta
from typing import List, Dict, Any
import logging

try:
    import requests
except ImportError:
    print("❌ 缺少 requests 依赖，请安装: pip install requests")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("⚠️ 缺少 yaml 依赖，将使用 JSON 配置")
    yaml = None

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
    """免费新闻采集器（无需任何API Key）"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or load_config()
        self.news_config = self.config.get('collect', {}).get('news', {})
        self.max_per_source = self.news_config.get('max_items_per_source', 15)
        self.timeout = 10
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Referer': 'https://finance.eastmoney.com/'
        })

    def collect_all(self) -> List[Dict[str, Any]]:
        """采集所有免费数据源"""
        all_news = []
        source_stats = {}

        # 数据源1：东方财富快讯（免费公开接口）
        try:
            news = self._fetch_eastmoney()
            all_news.extend(news)
            source_stats['eastmoney'] = len(news)
            logger.info(f"   ✅ eastmoney: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ eastmoney 采集失败: {e}")
            source_stats['eastmoney'] = 0

        # 数据源2：新浪财经新闻（免费公开接口）
        try:
            news = self._fetch_sina()
            all_news.extend(news)
            source_stats['sina'] = len(news)
            logger.info(f"   ✅ sina: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ sina 采集失败: {e}")
            source_stats['sina'] = 0

        # 数据源3：网易财经新闻（免费公开接口）
        try:
            news = self._fetch_163()
            all_news.extend(news)
            source_stats['163'] = len(news)
            logger.info(f"   ✅ 163: 采集到 {len(news)} 条新闻")
        except Exception as e:
            logger.error(f"   ❌ 163 采集失败: {e}")
            source_stats['163'] = 0

        logger.info(f"📊 总计采集: {len(all_news)} 条新闻")
        logger.info(f"📊 来源分布: {source_stats}")
        return all_news

    def _fetch_eastmoney(self) -> List[Dict[str, Any]]:
        """采集东方财富快讯（免费公开接口）"""
        url = "https://newsapi.eastmoney.com/kuaixun/v1/getnews_limited"
        params = {
            'pageIndex': '1',
            'pageSize': str(self.max_per_source),
            'type': '1'
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                logger.debug(f"东财API返回: {resp.status_code}")
                return self._fetch_eastmoney_fallback()

            data = resp.json()
            articles = data.get('data', {}).get('list', [])

            result = []
            for item in articles[:self.max_per_source]:
                title = item.get('title', '')
                if not title:
                    continue
                result.append({
                    'title': title,
                    'summary': item.get('summary', title),
                    'content': item.get('content', title),
                    'publish_time': item.get('publishTime', ''),
                    'source': '东方财富',
                    'source_type': 'eastmoney',
                    'url': item.get('url', f"https://news.eastmoney.com/{int(time.time())}"),
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"东财API调用失败: {e}")
            return []

    def _fetch_eastmoney_fallback(self) -> List[Dict[str, Any]]:
        """东财备选：抓取HTML页面"""
        url = "https://finance.eastmoney.com/"
        try:
            resp = self.session.get(url, timeout=self.timeout)
            if resp.status_code != 200:
                return []
            # 简化处理：解析HTML获取新闻标题
            import re
            html = resp.text
            titles = re.findall(r'<a[^>]*>([^<]*财经[^<]*)</a>', html)
            result = []
            for title in titles[:self.max_per_source]:
                if len(title) > 10:
                    result.append({
                        'title': title.strip(),
                        'summary': title.strip(),
                        'content': title.strip(),
                        'publish_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                        'source': '东方财富',
                        'source_type': 'eastmoney',
                        'url': '',
                        'collected_at': datetime.now().isoformat()
                    })
            return result
        except Exception as e:
            logger.debug(f"东财备选失败: {e}")
            return []

    def _fetch_sina(self) -> List[Dict[str, Any]]:
        """采集新浪财经新闻（免费公开接口）"""
        url = "https://api.finance.sina.com.cn/api/finance_api"
        params = {
            'page': '1',
            'num': str(self.max_per_source),
            'type': '1'
        }
        try:
            # 尝试使用新浪财经公开API
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get('result', {}).get('data', [])

            result = []
            for item in items[:self.max_per_source]:
                title = item.get('title', '')
                if not title:
                    continue
                result.append({
                    'title': title,
                    'summary': item.get('summary', title),
                    'content': item.get('content', title),
                    'publish_time': item.get('ctime', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    'source': '新浪财经',
                    'source_type': 'sina',
                    'url': item.get('url', ''),
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"新浪API调用失败: {e}")
            return []

    def _fetch_163(self) -> List[Dict[str, Any]]:
        """采集网易财经新闻（免费公开接口）"""
        url = "https://api.news.163.com/news/getList"
        params = {
            'page': '1',
            'size': str(self.max_per_source),
            'subId': 'finance'
        }
        try:
            resp = self.session.get(url, params=params, timeout=self.timeout)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items = data.get('data', [])

            result = []
            for item in items[:self.max_per_source]:
                title = item.get('title', '')
                if not title:
                    continue
                result.append({
                    'title': title,
                    'summary': item.get('summary', title),
                    'content': item.get('content', title),
                    'publish_time': item.get('ctime', datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
                    'source': '网易财经',
                    'source_type': '163',
                    'url': item.get('url', ''),
                    'collected_at': datetime.now().isoformat()
                })
            return result
        except Exception as e:
            logger.debug(f"网易API调用失败: {e}")
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
    """保存原始新闻到JSON"""
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
    parser = argparse.ArgumentParser(description='免费新闻采集')
    parser.add_argument('--limit', type=int, default=15,
                        help='每条新闻源采集条数（默认15）')
    parser.add_argument('--output', type=str, default='staging',
                        help='输出目录（默认staging）')
    args = parser.parse_args()

    logger.info("=" * 50)
    logger.info("📡 data-collector 新闻采集启动（公开库版·无需Key）")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info(f"📊 单源限制: {args.limit} 条")
    logger.info("=" * 50)

    config = load_config()
    collector = FreeNewsCollector(config)
    news_list = collector.collect_all()

    save_raw_news(news_list, args.output)

    logger.info("=" * 50)
    logger.info(f"✅ 新闻采集完成: {len(news_list)} 条")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
