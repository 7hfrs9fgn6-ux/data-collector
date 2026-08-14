#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 北向资金采集模块（akshare 版）
使用 akshare 获取北向资金数据
频率：每30分钟
数据源：akshare → 新浪财经 → 缓存
"""

import sys
import os
import time
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

# 尝试导入 requests（用于备选方案）
try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NorthFlowCollector:
    """北向资金采集器（akshare）"""

    def __init__(self):
        self.config = load_config()
        self.session = None
        if HAS_REQUESTS:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": "https://data.eastmoney.com/"
            })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法1：akshare 北向资金
        data = self._fetch_from_akshare()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare"
            logger.info(f"✅ 北向资金采集成功 (来源: akshare, {len(data)} 项)")
            return result

        # 方法2：新浪财经
        data = self._fetch_from_sina()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "sina"
            logger.info(f"✅ 北向资金采集成功 (来源: 新浪财经, {len(data)} 项)")
            return result

        # 方法3：从缓存加载
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金采集成功 (来源: 缓存, {len(data)} 项)")
            return result

        logger.warning("⚠️ 所有北向资金数据源均失败")
        return result

    def _fetch_from_akshare(self) -> List[Dict]:
        try:
            import akshare as ak

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 方法1：获取北向资金日频数据
            try:
                # 注意：symbol 参数使用 "北上" 或 "北向"
                df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")
                if df is not None and not df.empty:
                    recent = df.tail(5)
                    for _, row in recent.iterrows():
                        # value 单位是万元，转换为亿元
                        value = row.get('value', 0) / 10000
                        items.append({
                            "type": "北向资金",
                            "date": row.get('date', today),
                            "净流入": round(float(value), 2),
                            "累计": round(float(row.get('cumulative', 0)) / 10000, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"akshare 北向资金接口失败: {e}")

            # 方法2：获取沪深股通各自数据
            try:
                hgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
                sgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="深股通")

                if hgt_df is not None and not hgt_df.empty and sgt_df is not None and not sgt_df.empty:
                    hgt_recent = hgt_df.tail(3)
                    sgt_recent = sgt_df.tail(3)

                    # 按日期合并
                    hgt_dict = {row.get('date', ''): row for _, row in hgt_recent.iterrows()}
                    sgt_dict = {row.get('date', ''): row for _, row in sgt_recent.iterrows()}

                    for date in sorted(set(hgt_dict.keys()) | set(sgt_dict.keys()), reverse=True)[:3]:
                        hgt_row = hgt_dict.get(date)
                        sgt_row = sgt_dict.get(date)
                        hgt_val = float(hgt_row.get('value', 0)) / 10000 if hgt_row else 0
                        sgt_val = float(sgt_row.get('value', 0)) / 10000 if sgt_row else 0
                        items.append({
                            "type": "北向资金",
                            "date": date,
                            "沪股通": round(hgt_val, 2),
                            "深股通": round(sgt_val, 2),
                            "合计": round(hgt_val + sgt_val, 2)
                        })
                    return items
            except Exception as e:
                logger.debug(f"akshare 沪深股通接口失败: {e}")

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 北向资金采集异常: {e}")
            return []

    def _fetch_from_sina(self) -> List[Dict]:
        """备用：从新浪财经获取北向资金"""
        if not HAS_REQUESTS or not self.session:
            return []

        try:
            # 新浪财经北向资金接口
            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/GlobalService.getHSG"
            params = {
                "page": "1",
                "num": "10"
            }

            resp = self.session.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return []

            # 新浪返回的是 JSONP 格式，需要处理
            text = resp.text
            if text.startswith('/*'):
                text = text[text.find('(')+1:text.rfind(')')]

            data = resp.json()
            if not data:
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []
            for row in data[:3]:
                items.append({
                    "type": "北向资金",
                    "date": row.get('date', today),
                    "沪股通": round(float(row.get('hgt', 0)), 2),
                    "深股通": round(float(row.get('sgt', 0)), 2),
                    "合计": round(float(row.get('hgt', 0)) + float(row.get('sgt', 0)), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"新浪财经北向资金采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            return data.get('items', [])
        return []


def collect_north_flow() -> Dict[str, Any]:
    collector = NorthFlowCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/north_flow_{timestamp}.json"
    save_json(result, filepath)

    if result["total"] > 0:
        save_json(result, "staging/north_flow_cache.json")

    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
