#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
P1阶段：爬虫降级模块
提供各数据源的网页爬虫兜底能力
"""

from .base_scraper import BaseScraper
from .commodity_scraper import CommodityScraper, scrape_commodities
from .macro_scraper import MacroScraper, scrape_macro
from .sector_scraper import SectorScraper, scrape_sectors

__all__ = [
    'BaseScraper',
    'CommodityScraper',
    'scrape_commodities',
    'MacroScraper',
    'scrape_macro',
    'SectorScraper',
    'scrape_sectors',
]
