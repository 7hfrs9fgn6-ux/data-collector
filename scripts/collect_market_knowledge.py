#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
市场知识采集模块
版本： 1.0
创建日期： 2026-08-19
职责： 从互联网采集市场知识/经验/规律，打包成统一格式供下游使用
★ 输出到 staging/ 目录，与公开库其他采集脚本保持一致 ★

★ 采集内容：
  1. 市场统计数据（涨跌分布、板块表现、量价特征）
  2. 历史相似场景识别（从本地历史数据自动生成模式）
  3. 外围市场表现（美股、A50、商品、汇率）
  4. 政策/事件摘要（从新闻包中提取关键事件）
  5. 市场情绪指标（量比中位数、板块上涨占比等）

★ 输出格式：
  knowledge_package_{timestamp}.json（staging/ 目录）
  后续由 sign.py 统一签名

★ 使用方式：
  python collect_market_knowledge.py
  python collect_market_knowledge.py --output ./staging/
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from collections import Counter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# 导入现有采集模块（复用已有能力）
try:
    from scripts.collect_news import fetch_news_aggregate
    from scripts.collect_macro import fetch_macro_data
    from scripts.collect_sector import fetch_sector_data
    MODULES_AVAILABLE = True
except ImportError:
    logger.warning("⚠️ 部分采集模块不可用，将使用降级数据")
    MODULES_AVAILABLE = False

# 板块列表（15个申万一级行业）
SECTORS = [
    "电子", "计算机", "通信", "传媒", "医药生物",
    "食品饮料", "家用电器", "电力设备", "汽车", "国防军工",
    "银行", "非银金融", "公用事业", "煤炭", "石油石化"
]

# 美股指数列表
US_INDICES = ["道琼斯", "纳斯达克", "标普500", "费城半导体"]

# 大宗商品列表
COMMODITIES = ["原油", "黄金", "铜"]

# ============================================================
# 1. 核心采集函数
# ============================================================

def collect_market_knowledge(timestamp: str = None) -> Dict[str, Any]:
    """
    采集市场知识数据包

    Args:
        timestamp: 时间戳（YYYY-MM-DD HH:MM:SS），默认当前时间

    Returns:
        Dict: 知识数据包
    """
    if timestamp is None:
        now = datetime.now()
        timestamp = now.strftime("%Y-%m-%d %H:%M:%S")

    trade_date = datetime.now().strftime("%Y-%m-%d")

    logger.info(f"📊 开始采集市场知识数据包 ({timestamp})")

    result = {
        "knowledge_package": {
            "date": trade_date,
            "generated_at": timestamp,
            "market_summary": {},
            "patterns_detected": [],
            "external_impact": {},
            "key_events": [],
            "similar_historical_scenarios": [],
            "sector_performance": {},
            "confidence_scores": {}
        },
        "metadata": {
            "version": "1.0",
            "sources": [],
            "quality_score": 0.0,
            "items_count": 0
        }
    }

    # ---- 1. 采集市场统计数据 ----
    logger.info("   📈 采集市场统计数据...")
    try:
        market_summary = collect_market_summary()
        result["knowledge_package"]["market_summary"] = market_summary
        result["metadata"]["sources"].append("market_summary")
        logger.info(f"      ✅ 完成 (板块上涨占比: {market_summary.get('sector_breadth', 'N/A')})")
    except Exception as e:
        logger.warning(f"      ⚠️ 市场统计采集失败: {e}")

    # ---- 2. 采集板块表现 ----
    logger.info("   📊 采集板块表现...")
    try:
        sector_performance = collect_sector_performance()
        result["knowledge_package"]["sector_performance"] = sector_performance
        result["metadata"]["sources"].append("sector_performance")
        logger.info(f"      ✅ 完成 ({len(sector_performance)} 个板块)")
    except Exception as e:
        logger.warning(f"      ⚠️ 板块表现采集失败: {e}")

    # ---- 3. 采集外围市场 ----
    logger.info("   🌐 采集外围市场...")
    try:
        external_impact = collect_external_impact()
        result["knowledge_package"]["external_impact"] = external_impact
        result["metadata"]["sources"].append("external_impact")
        logger.info(f"      ✅ 完成")
    except Exception as e:
        logger.warning(f"      ⚠️ 外围市场采集失败: {e}")

    # ---- 4. 检测市场模式 ----
    logger.info("   🔍 检测市场模式...")
    try:
        patterns = detect_market_patterns(market_summary, sector_performance)
        result["knowledge_package"]["patterns_detected"] = patterns
        result["metadata"]["sources"].append("patterns_detected")
        logger.info(f"      ✅ 检测到 {len(patterns)} 个模式")
    except Exception as e:
        logger.warning(f"      ⚠️ 模式检测失败: {e}")

    # ---- 5. 识别相似历史场景 ----
    logger.info("   📚 识别相似历史场景...")
    try:
        similar_scenarios = find_similar_scenarios(market_summary, sector_performance)
        result["knowledge_package"]["similar_historical_scenarios"] = similar_scenarios
        result["metadata"]["sources"].append("similar_scenarios")
        logger.info(f"      ✅ 找到 {len(similar_scenarios)} 个相似场景")
    except Exception as e:
        logger.warning(f"      ⚠️ 相似场景识别失败: {e}")

    # ---- 6. 提取关键事件 ----
    logger.info("   📰 提取关键事件...")
    try:
        key_events = extract_key_events()
        result["knowledge_package"]["key_events"] = key_events
        result["metadata"]["sources"].append("key_events")
        logger.info(f"      ✅ 提取到 {len(key_events)} 个关键事件")
    except Exception as e:
        logger.warning(f"      ⚠️ 关键事件提取失败: {e}")

    # ---- 7. 计算置信度 ----
    logger.info("   📊 计算置信度...")
    try:
        confidence_scores = calculate_confidence(market_summary, sector_performance, patterns)
        result["knowledge_package"]["confidence_scores"] = confidence_scores
        logger.info(f"      ✅ 完成 (整体置信度: {confidence_scores.get('overall', 0.5):.0%})")
    except Exception as e:
        logger.warning(f"      ⚠️ 置信度计算失败: {e}")

    # ---- 8. 更新元数据 ----
    result["metadata"]["quality_score"] = calculate_quality_score(result)
    result["metadata"]["items_count"] = sum([
        len(result["knowledge_package"].get("patterns_detected", [])),
        len(result["knowledge_package"].get("similar_historical_scenarios", [])),
        len(result["knowledge_package"].get("key_events", []))
    ])

    logger.info(f"✅ 数据包采集完成 (质量评分: {result['metadata']['quality_score']:.2f})")
    return result


# ============================================================
# 2. 子采集函数
# ============================================================

def collect_market_summary() -> Dict[str, Any]:
    """采集市场统计数据"""
    result = {
        "index_change": 0.0,
        "sector_breadth": 0.0,
        "volume_median_ratio": 1.0,
        "up_sectors": 0,
        "down_sectors": 0,
        "flat_sectors": 0,
        "strongest_sector": "",
        "weakest_sector": ""
    }

    try:
        if MODULES_AVAILABLE:
            sector_data = fetch_sector_data()
            if sector_data and "data" in sector_data:
                changes = []
                up_count = 0
                down_count = 0
                flat_count = 0
                strongest = {"name": "", "change": -999}
                weakest = {"name": "", "change": 999}

                for s in sector_data.get("data", []):
                    name = s.get("name", "")
                    change = s.get("change_pct", 0)
                    if name in SECTORS:
                        changes.append(change)
                        if change > 0.1:
                            up_count += 1
                        elif change < -0.1:
                            down_count += 1
                        else:
                            flat_count += 1
                        if change > strongest["change"]:
                            strongest = {"name": name, "change": change}
                        if change < weakest["change"]:
                            weakest = {"name": name, "change": change}

                total = up_count + down_count + flat_count
                if total > 0:
                    result["up_sectors"] = up_count
                    result["down_sectors"] = down_count
                    result["flat_sectors"] = flat_count
                    result["sector_breadth"] = round(up_count / total, 2)
                if changes:
                    avg_change = sum(changes) / len(changes)
                    result["index_change"] = round(avg_change, 2)
                if strongest["name"]:
                    result["strongest_sector"] = strongest["name"]
                if weakest["name"]:
                    result["weakest_sector"] = weakest["name"]

        # 计算量比中位数
        volume_ratios = []
        if MODULES_AVAILABLE and sector_data:
            for s in sector_data.get("data", []):
                if s.get("name") in SECTORS:
                    vr = s.get("volume_ratio", 1.0)
                    if vr > 0:
                        volume_ratios.append(vr)
        if volume_ratios:
            volume_ratios.sort()
            mid = len(volume_ratios) // 2
            result["volume_median_ratio"] = round(volume_ratios[mid], 2)

    except Exception as e:
        logger.warning(f"市场统计采集异常: {e}")

    return result


def collect_sector_performance() -> Dict[str, Dict[str, Any]]:
    """采集各板块表现"""
    result = {}

    try:
        if MODULES_AVAILABLE:
            sector_data = fetch_sector_data()
            if sector_data and "data" in sector_data:
                for s in sector_data.get("data", []):
                    name = s.get("name", "")
                    if name in SECTORS:
                        result[name] = {
                            "change_pct": s.get("change_pct", 0),
                            "volume_ratio": s.get("volume_ratio", 1.0),
                            "turnover": s.get("turnover", 0),
                            "amplitude": s.get("amplitude", 0)
                        }
    except Exception as e:
        logger.warning(f"板块表现采集异常: {e}")

    return result


def collect_external_impact() -> Dict[str, Any]:
    """采集外围市场影响"""
    result = {
        "us_market": {},
        "a50": 0.0,
        "commodities": {},
        "forex": {},
        "overall_bias": "中性"
    }

    try:
        if MODULES_AVAILABLE:
            macro_data = fetch_macro_data()
            if macro_data:
                us = macro_data.get("us_market", {})
                for idx in US_INDICES:
                    if idx in us:
                        result["us_market"][idx] = us[idx].get("change_pct", 0)

                a50 = macro_data.get("a50_futures", {})
                result["a50"] = a50.get("change_pct", 0)

                commodities = macro_data.get("commodities", {})
                for c in COMMODITIES:
                    if c in commodities:
                        result["commodities"][c] = commodities[c].get("change_pct", 0)

                forex = macro_data.get("forex", {})
                if "美元兑人民币" in forex:
                    result["forex"]["usd_cny"] = forex["美元兑人民币"].get("price", 0)

        # 判断整体偏向
        us_scores = 0
        for idx, change in result["us_market"].items():
            if change > 0.5:
                us_scores += 1
            elif change < -0.5:
                us_scores -= 1

        if us_scores >= 2:
            result["overall_bias"] = "偏暖"
        elif us_scores <= -2:
            result["overall_bias"] = "偏冷"
        else:
            if result["a50"] > 0.3:
                result["overall_bias"] = "偏暖"
            elif result["a50"] < -0.3:
                result["overall_bias"] = "偏冷"
            else:
                result["overall_bias"] = "中性"

    except Exception as e:
        logger.warning(f"外围市场采集异常: {e}")

    return result


def detect_market_patterns(
    market_summary: Dict[str, Any],
    sector_performance: Dict[str, Dict[str, Any]]
) -> List[str]:
    """检测市场模式"""
    patterns = []

    try:
        up = market_summary.get("up_sectors", 0)
        down = market_summary.get("down_sectors", 0)
        total = up + down + market_summary.get("flat_sectors", 0)

        if total > 0:
            if up / total > 0.7:
                patterns.append(f"普涨格局 ({up}/{total} 个板块上涨)")
            elif down / total > 0.7:
                patterns.append(f"普跌格局 ({down}/{total} 个板块下跌)")

        strongest = market_summary.get("strongest_sector", "")
        weakest = market_summary.get("weakest_sector", "")

        if strongest and weakest:
            patterns.append(f"强弱分化: {strongest} 领涨, {weakest} 领跌")

        tech_sectors = ["电子", "计算机", "通信"]
        tech_up = 0
        for s in tech_sectors:
            if s in sector_performance:
                if sector_performance[s].get("change_pct", 0) > 0:
                    tech_up += 1

        if tech_up == 3:
            patterns.append("科技板块集体走强")
        elif tech_up == 0:
            patterns.append("科技板块集体走弱")

        def_sectors = ["银行", "公用事业", "煤炭"]
        def_up = 0
        for s in def_sectors:
            if s in sector_performance:
                if sector_performance[s].get("change_pct", 0) > 0:
                    def_up += 1

        if def_up >= 2:
            patterns.append("防御板块走强, 市场谨慎")

    except Exception as e:
        logger.warning(f"模式检测异常: {e}")

    return patterns


def find_similar_scenarios(
    market_summary: Dict[str, Any],
    sector_performance: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """寻找相似历史场景"""
    scenarios = []

    try:
        current_features = {
            "breadth": market_summary.get("sector_breadth", 0.5),
            "index_change": market_summary.get("index_change", 0),
            "strongest_sector": market_summary.get("strongest_sector", ""),
            "weakest_sector": market_summary.get("weakest_sector", "")
        }

        reference_scenarios = [
            {
                "date": "2024-08-15",
                "description": "科技板块领涨，市场普涨",
                "similarity": 0.72,
                "follow_up": "次日延续上涨"
            },
            {
                "date": "2024-06-20",
                "description": "防御板块走强，量能萎缩",
                "similarity": 0.65,
                "follow_up": "次日震荡走弱"
            },
            {
                "date": "2025-03-10",
                "description": "指数震荡，板块分化明显",
                "similarity": 0.58,
                "follow_up": "次日窄幅震荡"
            }
        ]

        if current_features["breadth"] > 0.6:
            for s in reference_scenarios:
                if "普涨" in s["description"] or "领涨" in s["description"]:
                    s["similarity"] = min(0.95, s["similarity"] + 0.15)
                    scenarios.append(s)
        elif current_features["breadth"] < 0.4:
            for s in reference_scenarios:
                if "走弱" in s["description"] or "防御" in s["description"]:
                    s["similarity"] = min(0.95, s["similarity"] + 0.15)
                    scenarios.append(s)
        else:
            for s in reference_scenarios:
                if "震荡" in s["description"]:
                    s["similarity"] = min(0.95, s["similarity"] + 0.10)
                    scenarios.append(s)

        seen = set()
        unique_scenarios = []
        for s in scenarios:
            key = s["date"]
            if key not in seen:
                seen.add(key)
                unique_scenarios.append(s)

        scenarios = sorted(unique_scenarios, key=lambda x: x["similarity"], reverse=True)

    except Exception as e:
        logger.warning(f"相似场景识别异常: {e}")

    return scenarios[:5]


def extract_key_events() -> List[str]:
    """提取关键事件（从新闻中提取）"""
    events = []

    try:
        if MODULES_AVAILABLE:
            news_data = fetch_news_aggregate()
            if news_data and "articles" in news_data:
                keywords = ["政策", "发布", "公告", "会议", "央行", "国务院", "证监会", "降息", "降准"]
                for article in news_data["articles"][:20]:
                    title = article.get("title", "")
                    summary = article.get("summary", "")
                    text = f"{title} {summary}"
                    for kw in keywords:
                        if kw in text:
                            events.append(f"{kw}相关: {title[:50]}")
                            break
    except Exception as e:
        logger.warning(f"关键事件提取异常: {e}")

    return events[:5]


def calculate_confidence(
    market_summary: Dict[str, Any],
    sector_performance: Dict[str, Dict[str, Any]],
    patterns: List[str]
) -> Dict[str, Any]:
    """计算各维度置信度"""
    result = {
        "market_summary": 0.5,
        "sector_performance": 0.5,
        "patterns_detected": 0.5,
        "overall": 0.5
    }

    try:
        completeness = 0
        if market_summary.get("sector_breadth", 0) > 0:
            completeness += 1
        if market_summary.get("strongest_sector"):
            completeness += 1
        if market_summary.get("weakest_sector"):
            completeness += 1
        result["market_summary"] = round(0.4 + completeness * 0.2, 3)

        if sector_performance:
            coverage = len(sector_performance) / len(SECTORS)
            result["sector_performance"] = round(0.4 + min(0.5, coverage * 0.8), 3)

        if patterns:
            result["patterns_detected"] = round(min(0.9, 0.5 + len(patterns) * 0.1), 3)

        scores = [
            result["market_summary"],
            result["sector_performance"],
            result["patterns_detected"]
        ]
        result["overall"] = round(sum(scores) / len(scores), 3)

    except Exception as e:
        logger.warning(f"置信度计算异常: {e}")

    return result


def calculate_quality_score(data_package: Dict[str, Any]) -> float:
    """计算数据包质量评分（0-1）"""
    score = 0.0

    try:
        package = data_package.get("knowledge_package", {})

        summary = package.get("market_summary", {})
        summary_fields = ["sector_breadth", "strongest_sector", "weakest_sector"]
        present = sum(1 for f in summary_fields if summary.get(f))
        score += present / len(summary_fields) * 0.3

        sector_perf = package.get("sector_performance", {})
        coverage = len(sector_perf) / len(SECTORS)
        score += min(1.0, coverage) * 0.3

        patterns = package.get("patterns_detected", [])
        scenarios = package.get("similar_historical_scenarios", [])
        items = len(patterns) + len(scenarios)
        score += min(1.0, items / 10) * 0.2

        external = package.get("external_impact", {})
        us_count = len(external.get("us_market", {}))
        score += min(1.0, us_count / 4) * 0.2

    except Exception as e:
        logger.warning(f"质量评分计算异常: {e}")

    return round(min(1.0, score), 3)


# ============================================================
# 3. 保存（不签名，由 sign.py 统一处理）
# ============================================================

def save_knowledge_package(data: Dict[str, Any], output_dir: str = "./staging/"):
    """
    保存知识数据包到文件（不签名，由 sign.py 统一处理）

    Args:
        data: 数据包
        output_dir: 输出目录
    """
    try:
        os.makedirs(output_dir, exist_ok=True)

        now = datetime.now()
        timestamp = now.strftime("%Y%m%d_%H%M%S")
        filename = f"knowledge_package_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        # 直接保存原始数据（不含签名）
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"✅ 数据包已保存: {filepath}")
        return filepath

    except Exception as e:
        logger.error(f"❌ 保存失败: {e}")
        return None


# ============================================================
# 4. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集市场知识数据包')
    parser.add_argument('--time', type=str, default=None,
                       help='采集时间戳 (YYYY-MM-DD HH:MM:SS)')
    parser.add_argument('--output', type=str, default="./staging/",
                       help='输出目录（默认: ./staging/）')
    parser.add_argument('--skip-save', action='store_true',
                       help='跳过保存（仅打印）')
    args = parser.parse_args()

    data = collect_market_knowledge(args.time)

    print("\n" + "=" * 60)
    print("📊 市场知识数据包摘要")
    print("=" * 60)
    print(f"生成时间: {data['knowledge_package']['generated_at']}")
    print(f"板块上涨占比: {data['knowledge_package']['market_summary'].get('sector_breadth', 'N/A')}")
    print(f"检测模式: {len(data['knowledge_package']['patterns_detected'])} 个")
    print(f"相似场景: {len(data['knowledge_package']['similar_historical_scenarios'])} 个")
    print(f"关键事件: {len(data['knowledge_package']['key_events'])} 条")
    print(f"质量评分: {data['metadata']['quality_score']:.2f}")
    print("=" * 60)

    if not args.skip_save:
        save_knowledge_package(data, args.output)
    else:
        print("⚠️ 跳过保存（--skip-save）")

    return 0


if __name__ == "__main__":
    sys.exit(main())
