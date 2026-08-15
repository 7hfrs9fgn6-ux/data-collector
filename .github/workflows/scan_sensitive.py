#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库敏感信息扫描脚本
用途：扫描公开库代码，确保不包含 V 系统专有信息
运行方式：python scripts/scan_sensitive.py
返回码：0=通过，1=发现敏感信息
"""

import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional


# ============================================================
# 敏感模式定义
# ============================================================

# 1. V系统专有术语（中文）
V_SYSTEM_TERMS = [
    r'V系统',
    r'v-system',
    r'VSystem',
    r'v_system',
    r'V-系统',
    r'V系統',
]

# 2. 持仓基金代码（6位数字，以00或01开头）
FUND_CODES = [
    r'009777',  # 中欧阿尔法混合C
    r'006229',  # 中欧医疗创新股票C
    r'001632',  # 天弘食品饮料ETF联接C
    r'260108',  # 景顺长城新兴成长A
    r'012414',  # 招商中证白酒指数C
    r'012417',  # 招商国证生物医药C
]

# 3. V系统内部路径引用
INTERNAL_PATHS = [
    r'from\s+core\.',
    r'from\s+data_adapter\.',
    r'from\s+output_layer\.',
    r'import\s+core\.',
    r'import\s+data_adapter\.',
    r'import\s+output_layer\.',
    r'core/',
    r'data_adapter/',
    r'output_layer/',
]

# 4. V系统策略关键词
STRATEGY_KEYWORDS = [
    r'state_machine',
    r'risk_control',
    r'signal_level',
    r'多因子',
    r'multi_factor',
    r'风控',
    r'黄金坑',
    r'高山位',
    r'回撤因子',
    r'资金因子',
    r'消息因子',
    r'估值因子',
    r'动量因子',
    r'三维验证',
    r'sentiment_score',
    r'sector_signal',
    r'push_notifier',
    r'notion_storage',
    r'firebase',
    r'memory_interface',
    r'shadow_system',
    r'ds_agent',
    r'bounary_checker',
    r'data_source_router',
]

# 5. API Key / Token 硬编码检测
API_KEY_PATTERNS = [
    r'api[_-]?key\s*=\s*["\']([^"\']+)["\']',
    r'token\s*=\s*["\']([^"\']+)["\']',
    r'secret\s*=\s*["\']([^"\']+)["\']',
    r'password\s*=\s*["\']([^"\']+)["\']',
    r'credential\s*=\s*["\']([^"\']+)["\']',
    r'AUTH_TOKEN\s*=\s*["\']([^"\']+)["\']',
    r'BEARER_TOKEN\s*=\s*["\']([^"\']+)["\']',
]


# ============================================================
# 扫描函数
# ============================================================

def scan_file(filepath: Path) -> Dict[str, List[Tuple[int, str]]]:
    """
    扫描单个文件，返回敏感信息列表
    返回: {类别: [(行号, 匹配内容), ...]}
    """
    results: Dict[str, List[Tuple[int, str]]] = {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        results["ERROR"] = [(0, f"读取文件失败: {e}")]
        return results
    
    for line_num, line in enumerate(lines, 1):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith('#'):
            continue
        
        # 1. V系统专有术语
        for pattern in V_SYSTEM_TERMS:
            if re.search(pattern, line, re.IGNORECASE):
                if "V系统术语" not in results:
                    results["V系统术语"] = []
                results["V系统术语"].append((line_num, line_stripped[:80]))
                break
        
        # 2. 持仓基金代码
        for pattern in FUND_CODES:
            if re.search(pattern, line):
                if "持仓基金代码" not in results:
                    results["持仓基金代码"] = []
                results["持仓基金代码"].append((line_num, line_stripped[:80]))
                break
        
        # 3. 内部路径引用
        for pattern in INTERNAL_PATHS:
            if re.search(pattern, line, re.IGNORECASE):
                if "内部路径引用" not in results:
                    results["内部路径引用"] = []
                results["内部路径引用"].append((line_num, line_stripped[:80]))
                break
        
        # 4. 策略关键词
        for pattern in STRATEGY_KEYWORDS:
            if re.search(pattern, line, re.IGNORECASE):
                if "策略关键词" not in results:
                    results["策略关键词"] = []
                results["策略关键词"].append((line_num, line_stripped[:80]))
                break
        
        # 5. API Key 硬编码
        for pattern in API_KEY_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if match:
                # 排除环境变量读取（os.environ.get、os.getenv）
                if 'os.environ' in line or 'os.getenv' in line:
                    continue
                if "API Key硬编码" not in results:
                    results["API Key硬编码"] = []
                results["API Key硬编码"].append((line_num, line_stripped[:80]))
                break
    
    return results


def scan_directory(directory: Path) -> Dict[str, Dict]:
    """
    扫描整个目录
    返回: {文件路径: {类别: [(行号, 内容), ...]}}
    """
    results = {}
    py_files = list(directory.rglob("*.py"))
    
    if not py_files:
        print(f"⚠️ 未找到 Python 文件: {directory}")
        return results
    
    for py_file in py_files:
        # 跳过虚拟环境目录
        if 'venv' in str(py_file) or '__pycache__' in str(py_file) or '.pytest_cache' in str(py_file):
            continue
        file_results = scan_file(py_file)
        if file_results:
            results[str(py_file.relative_to(directory.parent))] = file_results
    
    return results


# ============================================================
# 报告输出
# ============================================================

def print_report(results: Dict[str, Dict]) -> int:
    """
    打印扫描报告，返回敏感信息总数
    """
    total_issues = 0
    
    print("=" * 70)
    print("🔍 公开库敏感信息扫描报告")
    print("=" * 70)
    
    if not results:
        print("\n✅ 未发现敏感信息！")
        print("=" * 70)
        return 0
    
    for filepath, file_results in sorted(results.items()):
        print(f"\n📄 {filepath}")
        print("-" * 50)
        
        for category, items in file_results.items():
            if category == "ERROR":
                print(f"   ❌ {items[0][1]}")
                total_issues += 1
                continue
            
            print(f"   ⚠️ {category}: {len(items)} 处")
            for line_num, content in items[:3]:  # 只显示前3处
                print(f"      行 {line_num}: {content}")
            if len(items) > 3:
                print(f"      ... 还有 {len(items) - 3} 处")
            total_issues += len(items)
    
    print("\n" + "=" * 70)
    print(f"📊 总计发现 {total_issues} 处敏感信息")
    
    if total_issues > 0:
        print("\n❌ 敏感信息扫描失败，请清理上述内容")
        print("   （注意：允许使用 os.environ.get() 从环境变量读取密钥）")
    else:
        print("\n✅ 敏感信息扫描通过")
    
    print("=" * 70)
    return total_issues


# ============================================================
# 主函数
# ============================================================

def main():
    # 获取脚本所在目录（公开库根目录）
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    
    print(f"📂 扫描目录: {repo_root}")
    print(f"📂 脚本目录: {script_dir}")
    
    # 扫描 scripts 目录
    scripts_dir = repo_root / "scripts"
    results = {}
    
    if scripts_dir.exists():
        print(f"✅ 找到 scripts 目录，开始扫描...")
        results = scan_directory(scripts_dir)
    else:
        print(f"⚠️ scripts 目录不存在: {scripts_dir}")
        print(f"📂 尝试扫描当前目录: {repo_root}")
        results = scan_directory(repo_root)
    
    # 打印报告
    total_issues = print_report(results)
    
    # 返回码
    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
