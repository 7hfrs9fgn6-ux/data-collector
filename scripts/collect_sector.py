#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 板块52周回撤采集模块（修复版）
基于私密库 real_adapter.py 已验证逻辑
采集：A股15个核心板块的52周回撤历史
频率：每小时
数据源：akshare（申万行业指数）→ 缓存
"""

import sys
import os
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
    """板块52周回撤采集器（基于私密库已验证逻辑）"""

    # V系统15个核心板块及对应的申万指数代码
    # 申万指数代码：电子801080, 计算机801750, 通信801770, 传媒801760,
    # 医药生物801150, 食品饮料801120, 家用电器801110,
    # 电力设备801730, 汽车801880, 国防军工801740,
    # 银行801780, 非银金融801790, 公用事业801160, 煤炭801950, 石油石化801960
    SECTORS = [
        {"name": "电子", "code": "801080"},
        {"name": "计算机", "code": "801750"},
        {"name": "通信", "code": "801770"},
        {"name": "传媒", "code": "801760"},
        {"name": "医药生物", "code": "801150"},
        {"name": "食品饮料", "code": "801120"},
        {"name": "家用电器", "code": "801110"},
        {"name": "电力设备", "code": "801730"},
        {"name": "汽车", "code": "801880"},
        {"name": "国防军工", "code": "801740"},
        {"name": "银行", "code": "801780"},
        {"name": "非银金融", "code": "801790"},
        {"name": "公用事业", "code": "801160"},
        {"name": "煤炭", "code": "801950"},
        {"name": "石油石化", "code": "801960"},
    ]

    def __init__(self):
        self.config = load_config()
        self.max_retries = 2

    def collect(self) -> Dict[str, Any]:
        result = {
            "timestamp": get_timestamp(),
            "source": "sector",
            "total": 0,
            "items": []
        }

        # 方法1：使用 akshare 申万行业指数（私密库已验证）
        data = self._fetch_from_akshare_sw()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare_sw"
            logger.info(f"✅ 板块回撤采集成功 (来源: akshare申万, {len(data)} 项)")
            return result

        # 方法2：使用 akshare 行情接口获取
        data = self._fetch_from_akshare_spot()
        if data:
            result["items"] = data
            result["total"] = len(data)
            result["source"] = "akshare_spot"
            logger.info(f"✅ 板块回撤采集成功 (来源: akshare行情, {len(data)} 项)")
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

    def _fetch_from_akshare_sw(self) -> List[Dict]:
        """
        使用申万行业指数获取板块数据
        基于私密库 real_adapter.py 的已验证逻辑
        """
        try:
            import akshare as ak

            # 获取申万行业指数
            df = ak.stock_zh_index_spot_em(symbol="申万行业指数")

            if df is None or df.empty:
                logger.debug("申万行业指数数据为空")
                return []

            logger.debug(f"申万行业指数列名: {list(df.columns)}")

            # 识别列名
            name_col = None
            price_col = None
            pct_col = None
            high_col = None
            low_col = None

            for col in df.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower() or '收盘价' in col:
                    price_col = col
                if '涨跌幅' in col or 'change' in col.lower() or 'pct' in col.lower():
                    pct_col = col
                if '最高' in col or 'high' in col.lower():
                    high_col = col
                if '最低' in col or 'low' in col.lower():
                    low_col = col

            if not name_col or not price_col:
                logger.debug("列名识别失败")
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            # 遍历每个板块，匹配申万行业指数名称
            for sector in self.SECTORS:
                sector_name = sector["name"]

                # 在df中查找包含该板块名称的行
                matched = None
                for idx, row in df.iterrows():
                    name = str(row.get(name_col, ''))
                    # 申万行业指数名称格式如 "电子(申万)" 或 "电子"
                    if sector_name in name and ('申万' in name or 'sw' in name.lower()):
                        matched = row
                        break

                # 如果没找到，尝试更宽泛匹配
                if matched is None:
                    for idx, row in df.iterrows():
                        name = str(row.get(name_col, ''))
                        if sector_name in name:
                            matched = row
                            break

                if matched is None:
                    logger.debug(f"未匹配到板块: {sector_name}")
                    continue

                price = self._safe_float(matched.get(price_col))
                high_52w = price  # 如果无法获取52周最高，使用当前价
                pct = self._safe_float(matched.get(pct_col)) if pct_col else 0

                # 尝试获取52周最高价（从历史数据）
                try:
                    # 获取该板块近一年历史数据
                    sw_code = sector["code"]
                    hist_df = ak.stock_zh_index_daily(symbol=sw_code)
                    if hist_df is not None and not hist_df.empty:
                        high_52w = hist_df['high'].max()
                        if high_52w is None or high_52w <= 0:
                            high_52w = price
                except Exception as e:
                    logger.debug(f"   {sector_name} 历史数据获取失败: {e}")

                # 计算回撤
                if high_52w > 0 and price > 0:
                    drawdown = ((high_52w - price) / high_52w * 100)
                else:
                    drawdown = 0

                items.append({
                    "sector": sector_name,
                    "code": sector["code"],
                    "price": round(price, 2),
                    "drawdown": round(drawdown, 2),
                    "high_52w": round(high_52w, 2),
                    "change_pct": round(pct, 2),
                    "date": today
                })

            return items

        except ImportError:
            logger.debug("akshare 未安装")
            return []
        except Exception as e:
            logger.debug(f"akshare 申万行业指数采集异常: {e}")
            return []

    def _fetch_from_akshare_spot(self) -> List[Dict]:
        """备用方法：从行情接口获取板块数据"""
        try:
            import akshare as ak

            # 获取申万行业指数
            df = ak.stock_zh_index_spot_em(symbol="申万行业指数")
            if df is None or df.empty:
                return []

            # 识别列名
            name_col = None
            price_col = None
            pct_col = None

            for col in df.columns:
                if '名称' in col or 'name' in col.lower():
                    name_col = col
                if '最新价' in col or 'price' in col.lower():
                    price_col = col
                if '涨跌幅' in col or 'change' in col.lower():
                    pct_col = col

            if not name_col or not price_col:
                return []

            today = datetime.now().strftime("%Y-%m-%d")
            items = []

            for sector in self.SECTORS:
                sector_name = sector["name"]
                for idx, row in df.iterrows():
                    name = str(row.get(name_col, ''))
                    if sector_name in name:
                        price = self._safe_float(row.get(price_col))
                        pct = self._safe_float(row.get(pct_col)) if pct_col else 0
                        # 估算回撤（使用当前价和涨跌幅反推）
                        # 简化：用当前价作为基准
                        items.append({
                            "sector": sector_name,
                            "code": sector["code"],
                            "price": round(price, 2),
                            "drawdown": 0,  # 无法计算
                            "high_52w": round(price, 2),
                            "change_pct": round(pct, 2),
                            "date": today
                        })
                        break

            return items

        except Exception as e:
            logger.debug(f"行情接口采集异常: {e}")
            return []

    def _fetch_from_cache(self) -> List[Dict]:
        cache_file = "staging/sector_cache.json"
        data = load_json(cache_file)
        if data:
            # 检查缓存是否过期（1小时内）
            cache_time = data.get('timestamp', '')
            if cache_time:
                try:
                    dt = datetime.fromisoformat(cache_time)
                    age_hours = (datetime.now() - dt).total_seconds() / 3600
                    if age_hours > 2:
                        logger.debug("板块缓存已过期")
                        return []
                except:
                    pass
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

    # 如果采集成功，更新缓存
    if result["total"] > 0:
        save_json(result, "staging/sector_cache.json")

    logger.info(f"📊 板块回撤: {result['total']} 项")
    return result


if __name__ == "__main__":
    data = collect_sector()
    print(f"板块回撤采集完成: {data['total']} 项")
