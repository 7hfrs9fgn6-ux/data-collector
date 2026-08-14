#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：爬虫基础框架
提供通用爬虫基类：指数退避重试、随机UA轮换、请求延迟
"""

import time
import random
import logging
from typing import Optional, Dict, Any
from abc import ABC, abstractmethod

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BaseScraper(ABC):
    """
    爬虫基类
    所有具体爬虫继承此类，实现 fetch() 和 parse() 方法
    """

    # 常见 User-Agent 池
    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
    ]

    def __init__(self, max_retries: int = 3, timeout: int = 15, delay_range: tuple = (1, 3)):
        """
        初始化爬虫

        Args:
            max_retries: 最大重试次数（含首次请求）
            timeout: 请求超时时间（秒）
            delay_range: 请求间延迟范围（秒），(min, max)
        """
        self.max_retries = max_retries
        self.timeout = timeout
        self.delay_range = delay_range
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """创建带重试机制的 Session"""
        session = requests.Session()

        # 配置重试策略（指数退避）
        retry_strategy = Retry(
            total=self.max_retries - 1,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _get_random_ua(self) -> str:
        """随机获取一个 User-Agent"""
        return random.choice(self.USER_AGENTS)

    def _random_delay(self):
        """随机延迟，避免请求频率过高"""
        delay = random.uniform(self.delay_range[0], self.delay_range[1])
        time.sleep(delay)

    def _get_headers(self) -> Dict[str, str]:
        """构造请求头"""
        return {
            'User-Agent': self._get_random_ua(),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

    def fetch(self, url: str, params: Optional[Dict] = None) -> Optional[str]:
        """
        抓取网页内容

        Args:
            url: 目标 URL
            params: 查询参数

        Returns:
            网页 HTML 内容（字符串），失败返回 None
        """
        headers = self._get_headers()

        # 随机延迟
        self._random_delay()

        try:
            response = self.session.get(
                url,
                params=params,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            response.encoding = response.apparent_encoding or 'utf-8'
            logger.info(f"Fetch success: {url}")
            return response.text
        except requests.exceptions.RequestException as e:
            logger.error(f"Fetch failed: {url}, error: {e}")
            return None

    @abstractmethod
    def scrape(self) -> Optional[Dict[str, Any]]:
        """
        执行爬取并解析数据

        Returns:
            结构化数据字典，失败返回 None
        """
        pass

    @abstractmethod
    def get_data_type(self) -> str:
        """
        返回数据类型标识

        Returns:
            数据类型字符串，如 'commodity', 'macro', 'sector'
        """
        pass
