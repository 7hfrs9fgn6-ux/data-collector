#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 新闻筛选与去重脚本
功能：
1. URL指纹去重
2. Title MD5精确去重
3. 时效过滤（24小时内）
4. 格式校验
"""

import os
import sys
import json
import hashlib
import glob
from datetime import datetime, timedelta
from typing import List, Dict, Any, Set
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================
# 去重引擎
# ============================================================

class DedupeEngine:
    """新闻去重引擎"""

    def __init__(self, config: Dict[str, Any] = None):
        self.config = config or {}
        self.url_fingerprints: Set[str] = set()
        self.title_md5s: Set[str] = set()
        self.title_similarity_threshold = 0.85
        self.max_age_hours = 24

    def deduplicate(self, articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """执行去重"""
        if not articles:
            return []

        result = []
        duplicate_count = 0
        old_count = 0

        for article in articles:
            # 1. 时效检查
            if not self._is_fresh(article):
                old_count += 1
                continue

            # 2. URL指纹去重
            url_fp = self._get_url_fingerprint(article)
            if url_fp and url_fp in self.url_fingerprints:
                duplicate_count += 1
                continue
            if url_fp:
                self.url_fingerprints.add(url_fp)

            # 3. Title MD5去重
            title_md5 = self._get_title_md5(article)
            if title_md5 and title_md5 in self.title_md5s:
                duplicate_count += 1
                continue
            if title_md5:
                self.title_md5s.add(title_md5)

            result.append(article)

        # 记录去重统计
        logger.info(f"🔍 去重统计: 原始 {len(articles)} 条, 保留 {len(result)} 条, 去除重复 {duplicate_count} 条, 过期 {old_count} 条")
        return result

    def _is_fresh(self, article: Dict[str, Any]) -> bool:
        """检查文章是否在有效期内"""
        # 使用采集时间作为参考
        collected_at = article.get('collected_at')
        if collected_at:
            try:
                collected = datetime.fromisoformat(collected_at)
                age_hours = (datetime.now() - collected).total_seconds() / 3600
                if age_hours > self.max_age_hours:
                    return False
            except:
                pass

        # 使用发布时间作为备选
        publish_time = article.get('publish_time', '')
        if publish_time:
            try:
                # 尝试解析不同格式
                for fmt in ['%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S.%fZ']:
                    try:
                        published = datetime.strptime(publish_time, fmt)
                        age_hours = (datetime.now() - published).total_seconds() / 3600
                        if age_hours > self.max_age_hours:
                            return False
                        break
                    except:
                        continue
            except:
                pass

        # 默认通过（无法判断时保留）
        return True

    def _get_url_fingerprint(self, article: Dict[str, Any]) -> str:
        """获取URL指纹"""
        url = article.get('url', '')
        if not url:
            return None
        # 标准化URL：去除协议和www
        import re
        url = re.sub(r'^https?://', '', url)
        url = re.sub(r'^www\.', '', url)
        # 去除尾部斜杠
        url = url.rstrip('/')
        return hashlib.md5(url.encode('utf-8')).hexdigest()

    def _get_title_md5(self, article: Dict[str, Any]) -> str:
        """获取Title MD5"""
        title = article.get('title', '')
        if not title or len(title) < 5:
            return None
        # 去除常见干扰字符
        import re
        title = re.sub(r'[【】\[\]\(\)（）\s]', '', title)
        return hashlib.md5(title.encode('utf-8')).hexdigest()


# ============================================================
# 格式校验
# ============================================================

def validate_article(article: Dict[str, Any]) -> bool:
    """校验单条新闻格式"""
    required_fields = ['title', 'source_type']
    for field in required_fields:
        if field not in article or not article[field]:
            return False
    # title不能太短
    if len(article.get('title', '')) < 3:
        return False
    return True


def filter_articles(articles: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """过滤格式无效的文章"""
    result = []
    invalid_count = 0
    for article in articles:
        if validate_article(article):
            result.append(article)
        else:
            invalid_count += 1
    if invalid_count > 0:
        logger.info(f"🔍 格式过滤: 移除 {invalid_count} 条无效文章")
    return result


# ============================================================
# 主入口
# ============================================================

def main():
    logger.info("=" * 50)
    logger.info("🔍 data-collector 新闻筛选与去重启动")
    logger.info(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 50)

    # 查找最新的原始新闻文件
    staging_dir = "staging"
    raw_files = glob.glob(os.path.join(staging_dir, "raw_news_*.json"))

    if not raw_files:
        logger.warning("⚠️ 未找到原始新闻文件")
        return

    # 按修改时间排序，取最新的
    raw_files.sort(key=os.path.getmtime, reverse=True)
    latest_file = raw_files[0]

    logger.info(f"📂 读取: {latest_file}")

    with open(latest_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    articles = data.get('articles', [])
    logger.info(f"📊 原始新闻: {len(articles)} 条")

    # 1. 格式校验
    articles = filter_articles(articles)

    # 2. 去重
    dedupe_engine = DedupeEngine()
    articles = dedupe_engine.deduplicate(articles)

    # 3. 保存去重后的结果
    output_file = os.path.join(staging_dir, f"filtered_news_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'collected_at': datetime.now().isoformat(),
            'total': len(articles),
            'articles': articles,
            'dedupe_stats': {
                'url_fingerprints': len(dedupe_engine.url_fingerprints),
                'title_md5s': len(dedupe_engine.title_md5s)
            },
            'metadata': {
                'version': '1.0',
                'source': 'data-collector',
                'stage': 'filtered'
            }
        }, f, ensure_ascii=False, indent=2)

    logger.info(f"💾 保存筛选结果: {output_file} ({len(articles)} 条)")
    logger.info("=" * 50)
    logger.info("✅ 筛选与去重完成")
    logger.info("=" * 50)


if __name__ == "__main__":
    main()
