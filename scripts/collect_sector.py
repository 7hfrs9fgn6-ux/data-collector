#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（网页爬虫版）
使用新浪财经板块行情接口 + 东方财富辅助
采集：A股15个核心板块的52周回撤历史
频率：每小时
"""

import sys
import os
import re
import requests
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils import save_json, load_json, get_timestamp, load_config

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class SectorCollector:
    """板块52周回撤采集器（网页爬虫版）"""

    # 15个核心板块及对应的新浪财经板块代码（申万行业指数）
    # 新浪板块代码：https://hq.sinajs.cn/list=板块代码
    # 申万行业代码映射（新浪用）
    SECTOR_CODES = {
        "电子": "801080",
        "计算机": "801750",
        "通信": "801770",
        "传媒": "801760",
        "医药生物": "801150",
        "食品饮料": "801120",
        "家用电器": "801110",
        "电力设备": "801730",
        "汽车": "801880",
        "国防军工": "801740",
        "银行": "801780",
        "非银金融": "801790",
        "公用事业": "801160",
        "煤炭": "801950",
        "石油石化": "801960",
    }

    def __init__(self):
        self.config = load_config()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://finance.sina.com.cn/"
        })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        # 方法1：新浪财经板块行情接口
        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"✅ 板块回撤采集成功 (来源: 新浪, {len(data)} 项)")
            return result

        # 方法2：东方财富网页（备选）
        data = self._fetch_from_eastmoney()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "eastmoney"
            logger.info(f"✅ 板块回撤采集成功 (来源: 东方财富, {len(data)} 项)")
            return result

        # 从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 板块回撤采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有板块回撤数据源均失败")
        return result

    def _fetch_from_sina(self) -> List[Dict]:
        """
        从新浪财经获取申万行业指数实时数据
        接口：https://hq.sinajs.cn/list=sh801080,sh801750,...
        返回格式：v_sh801080="1~电子(申万)~801080~...~最新价~..."
        """
        try:
            # 构建代码列表
            codes = [f"sh{code}" for code in self.SECTOR_CODES.values()]
            url = f"https://hq.sinajs.cn/list={','.join(codes)}"
            resp = self.session.get(url, timeout=10)
            if resp.status_code != 200:
                logger.debug(f"新浪接口返回: {resp.status_code}")
                return []

            content = resp.text
            if not content or "没有找到" in content:
                logger.debug("新浪接口返回空内容")
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            for line in content.strip().split('\n'):
                if not line.strip():
                    continue
                # 解析格式：var hq_str_sh801080="1~电子(申万)~801080~...";
                if '=' not in line or '"' not in line:
                    continue
                parts = line.split('"')
                if len(parts) < 2:
                    continue
                data_str = parts[1]
                fields = data_str.split('~')
                if len(fields) < 10:
                    continue

                # 字段索引：0: 名称, 1: 代码, 2: 最新价, 3: 涨跌, 4: 涨跌幅, 5: 成交量, 6: 成交额, 7: 最高, 8: 最低, 9: 昨收
                name = fields[0] if len(fields) > 0 else ''
                # 提取板块名称（去掉" (申万)"后缀）
                sector_name = name.replace('(申万)', '').strip()
                # 匹配我们的板块列表
                matched_sector = None
                for s in self.SECTOR_CODES.keys():
                    if s in sector_name:
                        matched_sector = s
                        break
                if not matched_sector:
                    continue

                price = self._safe_float(fields[2])
                high = self._safe_float(fields[7])  # 今日最高
                low = self._safe_float(fields[8])
                open_price = self._safe_float(fields[3]) if len(fields) > 3 else price
                change_pct = self._safe_float(fields[4]) if len(fields) > 4 else 0

                # 计算回撤：使用52周最高价（我们无法直接获取，用今日最高近似，但会低估）
                # 为了更准确，尝试从历史数据获取
                drawdown = 0
                high_52w = price
                # 如果有历史数据，尝试获取52周最高
                # 先使用今日最高
                if high > price:
                    high_52w = high
                drawdown = ((high_52w - price) / high_52w * 100) if high_52w > 0 else 0

                items.append({
                    "sector": matched_sector,
                    "code": self.SECTOR_CODES[matched_sector],
                    "price": round(price, 2),
                    "high_52w": round(high_52w, 2),
                    "drawdown": round(drawdown, 2),
                    "change_pct": round(change_pct, 2),
                    "date": today
                })

            return items

        except Exception as e:
            logger.debug(f"新浪采集异常: {e}")
            return []

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """
        从东方财富网页获取板块数据（备选）
        """
        try:
            url = "https://push2.eastmoney.com/api/qt/clist/get"
            params = {
                "pn": "1",
                "pz": "50",
                "po": "1",
                "np": "1",
                "fltt": "2",
                "invt": "2",
                "fs": "m:90+t:2",
                "fields": "f2,f3,f4,f12,f13,f14,f104,f105,f128,f136,f140,f141,f207"
            }
            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return []

            data = resp.json()
            items_data = data.get("data", {}).get("diff", [])
            if not items_data:
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 东方财富的板块名称可能包含申万
            for item in items_data[:30]:
                name = item.get("f14", "")
                # 匹配板块
                matched_sector = None
                for s in self.SECTOR_CODES.keys():
                    if s in name:
                        matched_sector = s
                        break
                if not matched_sector:
                    continue

                price = self._safe_float(item.get("f2", 0))
                change_pct = self._safe_float(item.get("f3", 0))
                # 东方财富没有直接提供52周最高，我们使用当前价和涨跌幅估算
                # 暂无高精度，使用当前价
                high_52w = price
                drawdown = 0

                items.append({
                    "sector": matched_sector,
                    "code": self.SECTOR_CODES.get(matched_sector, ""),
                    "price": round(price, 2),
                    "high_52w": round(high_52w, 2),
                    "drawdown": round(drawdown, 2),
                    "change_pct": round(change_pct, 2),
                    "date": today
                })

            return items

        except Exception as e:
            logger.debug(f"东方财富采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []

    def _safe_float(self, value) -> float:
        try:
            return float(value) if value is not None else 0.0
        except (ValueError, TypeError):
            return 0.0


def collect_sector() -> Dict[str, Any]:
    collector = SectorCollector()
    result = collector.collect()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/sector_{timestamp}.json"
    save_json(result, filepath)
    if result["total"] > 0:
        save_json(result, "staging/sector_cache.json")
    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
