#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库 - 北向资金采集模块（防限流增强版）
使用多种数据源轮询 + 随机延迟 + 重试机制
频率：每30分钟
数据源：akshare → 新浪财经 → 东财API → 缓存
"""

import sys
import os
import time
import random
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

# ============================================================
# ★ 新增：导入 akshare-proxy-patch（必须在 akshare 之前）
# ============================================================
try:
    import akshare_proxy_patch  # type: ignore
    PATCH_LOADED = True
    logger.info("✅ akshare-proxy-patch 已加载")
except ImportError:
    PATCH_LOADED = False
    logger.warning("⚠️ akshare-proxy-patch 未安装，将使用普通模式")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False


class NorthFlowCollector:
    """北向资金采集器（防限流增强版）"""

    def __init__(self):
        self.config = load_config()
        self.session = None
        if HAS_REQUESTS:
            self.session = requests.Session()
            # 轮换 User-Agent
            self.user_agents = [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            ]
            self.session.headers.update({
                "User-Agent": random.choice(self.user_agents),
                "Referer": "https://data.eastmoney.com/",
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Connection": "keep-alive",
                "Cache-Control": "no-cache",
            })

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "north_flow",
            "total": 0,
            "items": []
        }

        # 方法列表（按优先级排序）- 将 akshare 放在最前面
        methods = [
            ("akshare", self._fetch_from_akshare),
            ("sina", self._fetch_from_sina),
            ("eastmoney", self._fetch_from_eastmoney),
        ]

        for method_name, method_func in methods:
            # 每个方法前随机延迟 1-3 秒，降低被限流风险
            delay = random.uniform(1.0, 3.0)
            logger.debug(f"⏳ 准备调用 {method_name}，延迟 {delay:.1f}s...")
            time.sleep(delay)

            try:
                data = method_func()
                if data:
                    result["items"] = data
                    result["total"] = len(data)
                    result["source"] = method_name
                    logger.info(f"✅ 北向资金采集成功 (来源: {method_name}, {len(data)} 项)")
                    # 保存到缓存
                    self._save_to_cache(data)
                    return result
                else:
                    logger.debug(f"   {method_name} 返回空")
            except Exception as e:
                logger.debug(f"   {method_name} 异常: {e}")
                continue

        # 所有方法都失败，尝试缓存
        data = self._fetch_from_cache()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "cache"
            logger.info(f"✅ 北向资金从缓存加载 ({len(data)} 项)")
            return result

        # ★ 新增：终极兜底（确保不崩溃）
        logger.warning("⚠️ 所有北向数据源失败，使用默认值（不影响核心功能）")
        result["items"] = [{
            "date": datetime.now().strftime("%Y-%m-%d"),
            "沪股通": 0,
            "深股通": 0,
            "合计": 0
        }]
        result["total"] = 1
        result["source"] = "default"
        return result

    # ----- 以下所有方法保持原样，未做任何修改 -----
    def _fetch_from_akshare(self) -> List[Dict]:
        """akshare 接口（带重试）"""
        try:
            import akshare as ak

            # 重试配置
            max_retries = 3
            retry_delays = [2, 4, 8]  # 指数退避

            for attempt in range(max_retries):
                try:
                    # 方法1：使用 "北上" 参数
                    df = ak.stock_hsgt_north_net_flow_in_em(symbol="北上")

                    if df is not None and not df.empty:
                        recent = df.tail(3)
                        items = []
                        for _, row in recent.iterrows():
                            value = row.get('value', 0)
                            # value 单位是万元，转换为亿元
                            if value and value != 0:
                                items.append({
                                    "date": row.get('date', datetime.now().strftime("%Y-%m-%d")),
                                    "合计": round(float(value) / 10000, 2)
                                })
                        if items:
                            return items

                    # 方法2：分别获取沪股通和深股通
                    hgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="沪股通")
                    sgt_df = ak.stock_hsgt_north_net_flow_in_em(symbol="深股通")

                    if hgt_df is not None and not hgt_df.empty and sgt_df is not None and not sgt_df.empty:
                        hgt_recent = hgt_df.tail(2)
                        sgt_recent = sgt_df.tail(2)

                        hgt_dict = {row.get('date', ''): row for _, row in hgt_recent.iterrows()}
                        sgt_dict = {row.get('date', ''): row for _, row in sgt_recent.iterrows()}

                        items = []
                        for date in sorted(set(hgt_dict.keys()) | set(sgt_dict.keys()), reverse=True)[:2]:
                            hgt_row = hgt_dict.get(date)
                            sgt_row = sgt_dict.get(date)
                            hgt_val = float(hgt_row.get('value', 0)) / 10000 if hgt_row else 0
                            sgt_val = float(sgt_row.get('value', 0)) / 10000 if sgt_row else 0

                            if hgt_val == 0 and sgt_val == 0:
                                continue

                            items.append({
                                "date": date,
                                "沪股通": round(hgt_val, 2),
                                "深股通": round(sgt_val, 2),
                                "合计": round(hgt_val + sgt_val, 2)
                            })
                        if items:
                            return items

                    # 如果返回空，且不是最后一次尝试，等待后重试
                    if attempt < max_retries - 1:
                        wait = retry_delays[attempt] + random.uniform(0.5, 1.5)
                        logger.debug(f"   akshare 返回空，{wait:.1f}s 后重试 ({attempt+1}/{max_retries})...")
                        time.sleep(wait)

                except Exception as e:
                    if "Connection" in str(e) or "Timeout" in str(e):
                        if attempt < max_retries - 1:
                            wait = retry_delays[attempt] + random.uniform(0.5, 1.5)
                            logger.debug(f"   akshare 连接异常，{wait:.1f}s 后重试 ({attempt+1}/{max_retries})...")
                            time.sleep(wait)
                            continue
                    raise

            return []

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 北向采集异常: {e}")
            return []

    def _fetch_from_sina(self) -> List[Dict]:
        """新浪财经北向资金接口"""
        if not HAS_REQUESTS or not self.session:
            return []

        try:
            # 随机更换 User-Agent
            self.session.headers.update({
                "User-Agent": random.choice(self.user_agents)
            })

            url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/GlobalService.getHSG"
            params = {
                "page": "1",
                "num": "5"
            }

            resp = self.session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                logger.debug(f"新浪北向 HTTP {resp.status_code}")
                return []

            data = resp.json()
            if not data:
                return []

            items = []
            for row in data[:3]:
                date = row.get('date', datetime.now().strftime("%Y-%m-%d"))
                hgt = row.get('hgt', 0)
                sgt = row.get('sgt', 0)

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "date": date,
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt) + float(sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"新浪北向采集异常: {e}")
            return []

    def _fetch_from_eastmoney(self) -> List[Dict]:
        """东方财富数据中心（备选）"""
        if not HAS_REQUESTS or not self.session:
            return []

        try:
            self.session.headers.update({
                "User-Agent": random.choice(self.user_agents)
            })

            url = "https://datacenter-web.eastmoney.com/api/data/v1/get"
            params = {
                "reportName": "RPT_HSGT_DAILY",
                "columns": "TRADE_DATE,HGT_NET_INFLOW,SGT_NET_INFLOW",
                "pageNumber": "1",
                "pageSize": "3",
                "sortColumns": "TRADE_DATE",
                "sortTypes": "-1",
                "source": "WEB",
                "client": "WEB"
            }

            resp = self.session.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                logger.debug(f"东财北向 HTTP {resp.status_code}")
                return []

            data = resp.json()
            if data.get("code") != 0:
                return []

            rows = data.get("result", {}).get("data", [])
            if not rows:
                return []

            items = []
            for row in rows[:2]:
                trade_date = row.get("TRADE_DATE", "")
                hgt = row.get("HGT_NET_INFLOW", 0)
                sgt = row.get("SGT_NET_INFLOW", 0)

                if hgt == 0 and sgt == 0:
                    continue

                items.append({
                    "date": trade_date[:10] if trade_date else datetime.now().strftime("%Y-%m-%d"),
                    "沪股通": round(float(hgt), 2),
                    "深股通": round(float(sgt), 2),
                    "合计": round(float(hgt + sgt), 2)
                })

            return items

        except Exception as e:
            logger.debug(f"东财北向采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/north_flow_cache.json"
        data = load_json(cache_file)
        if data:
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_minutes = (datetime.now() - dt).total_seconds() / 60
                    # 缓存有效 2 小时
                    if age_minutes > 120:
                        return []
                except:
                    pass
            return data.get('items', [])
        return []

    def _save_to_cache(self, items: List[Dict]):
        try:
            data = {
                "timestamp": get_timestamp(),
                "total": len(items),
                "items": items
            }
            save_json(data, "staging/north_flow_cache.json")
        except Exception as e:
            logger.debug(f"保存北向缓存失败: {e}")


def collect_north_flow() -> Dict[str, Any]:
    collector = NorthFlowCollector()
    result = collector.collect()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = f"staging/north_flow_{timestamp}.json"
    save_json(result, filepath)

    logger.info(f"📊 北向资金: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_north_flow()
    print(f"北向资金采集完成: {data['total']} 项")
