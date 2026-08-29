#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观数据发布日历驱动模块
版本：V1.0
更新日期：2026-08-29
职责：按国家统计局官方发布日历驱动公开库采集，实现"发布日历驱动的精准采集"

核心功能：
1. 判断各宏观数据是否到了采集时间（基于官方发布日历）
2. 计算下一次采集日期
3. 生成采集状态摘要（用于日志和监控）
4. 支持手动触发和自动判断两种模式

设计原则：
- 不盲目每日拉取，按发布日历精准采集
- 减少无效采集，降低公开库运行成本
- 提高数据新鲜度，确保宏观数据及时更新

金融学依据：
- 发布日历驱动（Calendar-Driven Data Refresh）：专业数据供应商（Bloomberg、Wind）均按官方发布日历更新数据
- 数据时效性分级：不同频率的数据应有不同的更新策略，月度数据无需每日采集
- 缓存策略：低频数据（月度/季度）应采用"按需刷新"而非"定时刷新"
"""

import os
import json
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ============================================================
# 1. 发布日历配置
# ============================================================

@dataclass
class PublishSchedule:
    """单个数据类型的发布日程配置"""
    data_type: str                      # 数据类型: GDP/CPI/PMI
    frequency: str                      # 发布频率: monthly/quarterly
    publish_day: int or str             # 发布日: 13 或 "last_workday"
    publish_month: Optional[List[int]] = None  # 发布月份（季度数据需要）
    description: str = ""               # 描述
    
    def get_publish_date(self, year: int, month: int) -> Optional[date]:
        """
        计算指定年月的数据发布日期
        
        Args:
            year: 年份
            month: 月份
        
        Returns:
            发布日期（date对象），如果该月无发布则返回 None
        """
        # 检查月份是否匹配（季度数据）
        if self.frequency == "quarterly" and self.publish_month:
            if month not in self.publish_month:
                return None
        
        # 计算发布日
        if self.publish_day == "last_workday":
            # 每月最后一个工作日
            return self._get_last_workday(year, month)
        elif isinstance(self.publish_day, int):
            # 固定日期
            try:
                return date(year, month, self.publish_day)
            except ValueError:
                # 日期无效（如2月30日），回退到月末
                last_day = self._get_month_end(year, month)
                return min(date(year, month, self.publish_day), last_day)
        else:
            return None
    
    def is_publish_month(self, month: int) -> bool:
        """检查指定月份是否为发布月份"""
        if self.frequency == "monthly":
            return True
        elif self.frequency == "quarterly" and self.publish_month:
            return month in self.publish_month
        return False
    
    def _get_last_workday(self, year: int, month: int) -> date:
        """获取指定年月的最后一个工作日（周一至周五）"""
        # 获取月末
        last_day = self._get_month_end(year, month)
        # 向前调整到工作日
        while last_day.weekday() >= 5:  # 5=周六, 6=周日
            last_day = last_day - timedelta(days=1)
        return last_day
    
    def _get_month_end(self, year: int, month: int) -> date:
        """获取指定年月的月末日期"""
        if month == 12:
            return date(year, month, 31)
        next_month = date(year, month + 1, 1)
        return next_month - timedelta(days=1)


# ============================================================
# 2. 发布日历管理器
# ============================================================

class PublishCalendar:
    """
    发布日历管理器
    
    功能：
    1. 配置各类宏观数据的官方发布日历
    2. 判断当前是否应该采集新数据
    3. 计算下次采集日期
    4. 生成采集状态摘要
    
    使用方式：
        calendar = PublishCalendar()
        should_collect = calendar.should_collect("CPI")
        next_date = calendar.get_next_collect_date("GDP")
        summary = calendar.get_status_summary()
    
    数据来源依据（国家统计局官方发布日程）：
        - GDP：季后15日左右（1月、4月、7月、10月）
        - CPI：月后13日左右（每月13日左右）
        - PMI：每月最后一个工作日
    """
    
    # ★ 国家统计局官方发布日程（基于历史规律）
    # 数据来源：国家统计局官网、Wind、Bloomberg
    PUBLISH_SCHEDULE: Dict[str, PublishSchedule] = {
        "GDP": PublishSchedule(
            data_type="GDP",
            frequency="quarterly",
            publish_day=16,
            publish_month=[1, 4, 7, 10],
            description="季度GDP，季后16日左右发布（1月、4月、7月、10月）"
        ),
        "CPI": PublishSchedule(
            data_type="CPI",
            frequency="monthly",
            publish_day=13,
            description="月度CPI，月后13日左右发布"
        ),
        "PMI": PublishSchedule(
            data_type="PMI",
            frequency="monthly",
            publish_day="last_workday",
            description="月度PMI，每月最后一个工作日发布"
        ),
    }
    
    # ★ 数据采集的"安全窗口"（发布日后几天才开始采集）
    # 避免在数据发布当天立即采集，给数据源留出更新缓冲时间
    COLLECT_BUFFER_DAYS: Dict[str, int] = {
        "GDP": 1,    # GDP 发布后1天采集
        "CPI": 1,    # CPI 发布后1天采集
        "PMI": 1,    # PMI 发布后1天采集
        "default": 1,
    }
    
    # ★ 数据采集的"最大重试窗口"（数据发布后多少天内仍可采集）
    # 超过此窗口，等待下一个发布周期
    MAX_COLLECT_WINDOW_DAYS: Dict[str, int] = {
        "GDP": 7,    # GDP 发布后7天内可采集
        "CPI": 7,    # CPI 发布后7天内可采集
        "PMI": 3,    # PMI 发布后3天内可采集
        "default": 7,
    }
    
    def __init__(self, config: Optional[Dict] = None):
        """初始化发布日历管理器"""
        self.config = config or {}
        self._last_collect_records: Dict[str, date] = {}
        self._load_history()
        logger.debug("📅 PublishCalendar 初始化完成")
    
    def should_collect(self, data_type: str, force_check: bool = False) -> Tuple[bool, str]:
        """
        判断是否应该采集指定类型的数据
        
        Args:
            data_type: 数据类型 (GDP/CPI/PMI)
            force_check: 是否强制检查（忽略缓存）
        
        Returns:
            (是否应该采集, 原因说明)
        """
        if data_type not in self.PUBLISH_SCHEDULE:
            logger.debug(f"📅 {data_type}: 未配置发布日历，建议每月1日采集")
            # 未配置的数据类型，建议每月1日采集
            today = date.today()
            if today.day == 1:
                return True, "未配置数据的默认采集日（每月1日）"
            return False, f"未配置发布日历，下次采集日为下月1日"
        
        schedule = self.PUBLISH_SCHEDULE[data_type]
        today = date.today()
        
        # ★ 1. 计算本月的发布日期
        current_year = today.year
        current_month = today.month
        
        publish_date = schedule.get_publish_date(current_year, current_month)
        if publish_date is None:
            # 当前月不是发布月份（季度数据）
            # 计算下一个发布月份
            next_year, next_month = self._get_next_publish_month(current_year, current_month, schedule)
            next_publish_date = schedule.get_publish_date(next_year, next_month)
            if next_publish_date:
                return False, f"非发布月份，下次发布于 {next_publish_date.strftime('%Y-%m-%d')}"
            return False, f"非发布月份，且无法计算下次发布日期"
        
        # ★ 2. 检查是否已过发布日期
        if today < publish_date:
            return False, f"数据尚未发布，发布日期为 {publish_date.strftime('%Y-%m-%d')}"
        
        # ★ 3. 计算采集起始日期（发布日期 + 缓冲天数）
        buffer_days = self.COLLECT_BUFFER_DAYS.get(data_type, self.COLLECT_BUFFER_DAYS["default"])
        collect_start = publish_date + timedelta(days=buffer_days)
        
        if today < collect_start:
            return False, f"发布日未过缓冲期（{buffer_days}天），采集起始日为 {collect_start.strftime('%Y-%m-%d')}"
        
        # ★ 4. 检查是否在采集窗口内
        max_window = self.MAX_COLLECT_WINDOW_DAYS.get(data_type, self.MAX_COLLECT_WINDOW_DAYS["default"])
        collect_end = publish_date + timedelta(days=max_window)
        
        if today > collect_end:
            # 已超过采集窗口，等待下一个发布周期
            return False, f"已超过采集窗口（{max_window}天），等待下一期发布"
        
        # ★ 5. 检查是否已采集过本次数据
        last_collect = self._get_last_collect_date(data_type)
        if last_collect and last_collect >= publish_date:
            return False, f"本期数据已于 {last_collect.strftime('%Y-%m-%d')} 采集，无需重复"
        
        # ★ 6. 所有条件满足，应该采集
        return True, f"数据已发布，在采集窗口内（发布日期 {publish_date.strftime('%Y-%m-%d')}）"
    
    def get_next_collect_date(self, data_type: str) -> Optional[date]:
        """
        获取下一次采集日期
        
        Args:
            data_type: 数据类型
        
        Returns:
            下一次采集日期（date对象），如果无法计算则返回 None
        """
        if data_type not in self.PUBLISH_SCHEDULE:
            # 未配置的数据类型，建议每月1日
            today = date.today()
            if today.day <= 1:
                return date(today.year, today.month, 1)
            else:
                next_month = today.month + 1
                next_year = today.year
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                return date(next_year, next_month, 1)
        
        schedule = self.PUBLISH_SCHEDULE[data_type]
        today = date.today()
        
        # 从当前月开始查找
        for offset in range(0, 12):  # 最多查找12个月
            check_year = today.year
            check_month = today.month + offset
            while check_month > 12:
                check_month -= 12
                check_year += 1
            
            publish_date = schedule.get_publish_date(check_year, check_month)
            if publish_date is None:
                continue
            
            buffer_days = self.COLLECT_BUFFER_DAYS.get(data_type, self.COLLECT_BUFFER_DAYS["default"])
            collect_date = publish_date + timedelta(days=buffer_days)
            
            # 如果采集日期 >= 今天，返回
            if collect_date >= today:
                return collect_date
        
        return None
    
    def mark_collected(self, data_type: str, collect_date: Optional[date] = None) -> None:
        """
        标记某类数据已采集
        
        Args:
            data_type: 数据类型
            collect_date: 采集日期（默认为今天）
        """
        if collect_date is None:
            collect_date = date.today()
        
        self._last_collect_records[data_type] = collect_date
        self._save_history()
        logger.debug(f"📅 {data_type} 已标记采集: {collect_date.strftime('%Y-%m-%d')}")
    
    def get_last_collect_date(self, data_type: str) -> Optional[date]:
        """获取上次采集日期"""
        return self._get_last_collect_date(data_type)
    
    def get_status_summary(self) -> Dict[str, Any]:
        """
        获取所有数据类型的采集状态摘要
        
        Returns:
            状态摘要字典，包含：
                - timestamp: 当前时间
                - data_status: 各类数据的状态
                - pending_collect: 待采集列表
                - next_collect_dates: 下次采集日期
        """
        summary = {
            "timestamp": datetime.now().isoformat(),
            "data_status": {},
            "pending_collect": [],
            "next_collect_dates": {},
            "total_pending": 0,
        }
        
        for data_type in self.PUBLISH_SCHEDULE.keys():
            should, reason = self.should_collect(data_type)
            next_date = self.get_next_collect_date(data_type)
            last_date = self._get_last_collect_date(data_type)
            schedule = self.PUBLISH_SCHEDULE[data_type]
            
            status = {
                "data_type": data_type,
                "frequency": schedule.frequency,
                "description": schedule.description,
                "should_collect": should,
                "reason": reason,
                "next_collect_date": next_date.strftime("%Y-%m-%d") if next_date else None,
                "last_collect_date": last_date.strftime("%Y-%m-%d") if last_date else None,
                "is_publish_month": schedule.is_publish_month(date.today().month),
            }
            
            summary["data_status"][data_type] = status
            
            if should:
                summary["pending_collect"].append(data_type)
            
            if next_date:
                summary["next_collect_dates"][data_type] = next_date.strftime("%Y-%m-%d")
        
        summary["total_pending"] = len(summary["pending_collect"])
        
        return summary
    
    def get_status_text(self) -> str:
        """
        生成采集状态展示文本（用于日志和推送）
        """
        summary = self.get_status_summary()
        
        lines = []
        lines.append("📅 【宏观数据采集日历】")
        lines.append(f"   📊 当前时间: {summary['timestamp'][:10]}")
        lines.append("")
        
        for data_type, status in summary["data_status"].items():
            emoji = "🔴" if status["should_collect"] else "🟢" if status["last_collect_date"] else "🟡"
            lines.append(f"   {emoji} {data_type}: {status['frequency']}")
            lines.append(f"      描述: {status['description']}")
            lines.append(f"      上次采集: {status['last_collect_date'] or '从未采集'}")
            lines.append(f"      下次采集: {status['next_collect_date'] or '无法计算'}")
            if status["should_collect"]:
                lines.append(f"      ⚠️ 状态: 【待采集】{status['reason']}")
            else:
                lines.append(f"      ℹ️ 状态: {status['reason']}")
            lines.append("")
        
        if summary["pending_collect"]:
            lines.append(f"   ⚠️ 待采集数据: {', '.join(summary['pending_collect'])}")
        else:
            lines.append("   ✅ 所有数据已采集，无需操作")
        
        lines.append("")
        lines.append("   📌 建议：按发布日历驱动公开库采集，避免盲目每日拉取")
        
        return "\n".join(lines)
    
    # ============================================================
    # 私有方法
    # ============================================================
    
    def _get_last_collect_date(self, data_type: str) -> Optional[date]:
        """获取上次采集日期（内部方法）"""
        return self._last_collect_records.get(data_type)
    
    def _get_next_publish_month(self, year: int, month: int, schedule: PublishSchedule) -> Tuple[int, int]:
        """获取下一个发布月份"""
        if schedule.frequency == "monthly":
            # 月度数据：下个月
            if month == 12:
                return year + 1, 1
            return year, month + 1
        elif schedule.frequency == "quarterly" and schedule.publish_month:
            # 季度数据：下一个发布月份
            next_month = month + 1
            next_year = year
            while True:
                if next_month > 12:
                    next_month = 1
                    next_year += 1
                if next_month in schedule.publish_month:
                    return next_year, next_month
                next_month += 1
        return year, month
    
    def _load_history(self) -> None:
        """加载采集历史记录"""
        history_file = "memory_data/publish_collect_history.json"
        if os.path.exists(history_file):
            try:
                with open(history_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for data_type, date_str in data.items():
                        try:
                            self._last_collect_records[data_type] = datetime.strptime(date_str, "%Y-%m-%d").date()
                        except ValueError:
                            continue
                logger.debug(f"📅 加载采集历史: {len(self._last_collect_records)} 条记录")
            except Exception as e:
                logger.debug(f"加载采集历史失败: {e}")
    
    def _save_history(self) -> None:
        """保存采集历史记录"""
        try:
            os.makedirs("memory_data", exist_ok=True)
            history_file = "memory_data/publish_collect_history.json"
            data = {}
            for data_type, collect_date in self._last_collect_records.items():
                data[data_type] = collect_date.strftime("%Y-%m-%d")
            with open(history_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.debug(f"📅 采集历史已保存")
        except Exception as e:
            logger.warning(f"保存采集历史失败: {e}")


# ============================================================
# 3. 全局单例
# ============================================================

_CALENDAR: Optional[PublishCalendar] = None


def get_publish_calendar(config: Optional[Dict] = None) -> PublishCalendar:
    """获取全局发布日历管理器单例"""
    global _CALENDAR
    if _CALENDAR is None:
        _CALENDAR = PublishCalendar(config)
    return _CALENDAR


# ============================================================
# 4. 便捷函数
# ============================================================

def should_collect_macro(data_type: str) -> Tuple[bool, str]:
    """便捷函数：判断是否应该采集宏观数据"""
    return get_publish_calendar().should_collect(data_type)


def get_macro_status_text() -> str:
    """便捷函数：获取宏观数据采集状态文本"""
    return get_publish_calendar().get_status_text()


# ============================================================
# 5. 与公开库采集的集成接口
# ============================================================

def get_collect_plan() -> Dict[str, Any]:
    """
    获取采集计划（供公开库工作流使用）
    
    返回：
        {
            "should_run": True/False,        # 是否有需要采集的数据
            "pending_types": ["GDP", "CPI"], # 待采集的数据类型
            "reasons": {...},                # 各类型的采集原因
            "next_check": "2026-08-30",      # 下次检查时间
        }
    """
    calendar = get_publish_calendar()
    summary = calendar.get_status_summary()
    
    pending = summary.get("pending_collect", [])
    
    reasons = {}
    for data_type, status in summary["data_status"].items():
        reasons[data_type] = status.get("reason", "")
    
    return {
        "should_run": len(pending) > 0,
        "pending_types": pending,
        "reasons": reasons,
        "next_check": summary.get("next_collect_dates", {}),
        "timestamp": summary.get("timestamp"),
    }


def should_run_public_collector() -> bool:
    """
    判断公开库采集工作流是否应该运行
    
    用于 GitHub Actions 工作流中的条件判断
    """
    plan = get_collect_plan()
    return plan.get("should_run", False)


# ============================================================
# 6. 测试入口
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("=" * 60)
    print("🧪 PublishCalendar V1.0 测试")
    print("=" * 60)
    
    calendar = PublishCalendar()
    
    print("\n📊 各数据类型的采集判断:")
    print("-" * 60)
    
    for data_type in ["GDP", "CPI", "PMI"]:
        should, reason = calendar.should_collect(data_type)
        next_date = calendar.get_next_collect_date(data_type)
        last_date = calendar.get_last_collect_date(data_type)
        
        status = "✅ 待采集" if should else "⏸️ 等待"
        print(f"{data_type}: {status}")
        print(f"  原因: {reason}")
        print(f"  下次采集: {next_date.strftime('%Y-%m-%d') if next_date else '无法计算'}")
        print(f"  上次采集: {last_date.strftime('%Y-%m-%d') if last_date else '从未'}")
        print()
    
    print("\n📊 采集状态摘要:")
    print("-" * 60)
    print(calendar.get_status_text())
    
    print("\n📊 采集计划（供公开库工作流使用）:")
    print("-" * 60)
    plan = get_collect_plan()
    print(f"  应该运行: {'✅' if plan['should_run'] else '⏸️ 否'}")
    print(f"  待采集数据: {plan['pending_types']}")
    print(f"  各类型原因: {plan['reasons']}")
    print(f"  下次检查: {plan['next_check']}")
    
    print("\n📊 模拟采集标记:")
    print("-" * 60)
    calendar.mark_collected("CPI")
    print("  CPI 已标记为已采集")
    should, reason = calendar.should_collect("CPI")
    print(f"  CPI 再次检查: {'✅ 待采集' if should else '⏸️ 等待'} - {reason}")
    
    print("\n✅ PublishCalendar V1.0 测试完成")
