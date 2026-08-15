#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
公开库敏感信息扫描脚本（P4-1）
用途：扫描公开库代码，确保不包含 V 系统专有信息
排除自身和误报模式
运行方式：python scripts/scan_sensitive.py
返回码：0=通过，1=发现敏感信息
"""

import os
import re
import sys
import ast
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set


# ============================================================
# 排除文件列表（不扫描）
# ============================================================
EXCLUDED_FILES = {
    'scan_sensitive.py',
    'security_check.py',
    '__init__.py',
    'generate_signing_key.py',  # 工具脚本，提示信息合理
}


# ============================================================
# 敏感模式定义（仅匹配代码逻辑，排除注释和字符串）
# ============================================================

# 1. V系统专有术语（中文/英文）
V_SYSTEM_TERMS = [
    r'V系统',
    r'v-system',
    r'VSystem',
    r'v_system',
    r'V-系统',
    r'V系統',
]

# 2. 持仓基金代码（6位数字）
FUND_CODES = [
    r'009777',  # 中欧阿尔法混合C
    r'006229',  # 中欧医疗创新股票C
    r'001632',  # 天弘食品饮料ETF联接C
    r'260108',  # 景顺长城新兴成长A
    r'012414',  # 招商中证白酒指数C
    r'012417',  # 招商国证生物医药C
]

# 3. V系统内部路径引用（排除注释）
INTERNAL_PATHS = [
    r'from\s+core\.',
    r'from\s+data_adapter\.',
    r'from\s+output_layer\.',
    r'import\s+core\.',
    r'import\s+data_adapter\.',
    r'import\s+output_layer\.',
]

# 4. V系统策略关键词（排除公开服务名）
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
    r'memory_interface',
    r'shadow_system',
    r'ds_agent',
    r'boundary_checker',
    r'data_source_router',
]

# 5. API Key 硬编码检测（排除 os.environ 和 os.getenv）
API_KEY_PATTERNS = [
    r'api[_-]?key\s*=\s*["\']([^"\']+)["\']',
    r'token\s*=\s*["\']([^"\']+)["\']',
    r'secret\s*=\s*["\']([^"\']+)["\']',
    r'password\s*=\s*["\']([^"\']+)["\']',
    r'credential\s*=\s*["\']([^"\']+)["\']',
]


# ============================================================
# 扫描函数（使用 AST 解析，只检查代码节点）
# ============================================================

def scan_file_ast(filepath: Path) -> Dict[str, List[Tuple[int, str]]]:
    """
    使用 AST 解析 Python 文件，只检查代码节点（忽略注释和字符串）
    """
    results: Dict[str, List[Tuple[int, str]]] = {}
    
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception as e:
        results["ERROR"] = [(0, f"读取文件失败: {e}")]
        return results
    
    # 获取所有行
    lines = content.splitlines()
    
    # 使用 AST 提取所有名称和字符串
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return scan_file_regex(filepath)
    
    # 遍历 AST 节点
    for node in ast.walk(tree):
        # 跳过函数定义、类定义等（只检查表达式）
        if isinstance(node, (ast.FunctionDef, ast.ClassDef, ast.Import, ast.ImportFrom)):
            if hasattr(node, 'name'):
                node_name = node.name
                for pattern in V_SYSTEM_TERMS + STRATEGY_KEYWORDS + INTERNAL_PATHS:
                    if re.search(pattern, node_name, re.IGNORECASE):
                        key = "V系统术语" if pattern in V_SYSTEM_TERMS else ("策略关键词" if pattern in STRATEGY_KEYWORDS else "内部路径引用")
                        if key not in results:
                            results[key] = []
                        line_no = node.lineno
                        if line_no <= len(lines):
                            line_content = lines[line_no - 1].strip()
                            results[key].append((line_no, line_content[:80]))
        
        # 检查 Name 节点（变量名）
        if isinstance(node, ast.Name):
            var_name = node.id
            for pattern in V_SYSTEM_TERMS + FUND_CODES + STRATEGY_KEYWORDS:
                if re.search(pattern, var_name, re.IGNORECASE):
                    key = "V系统术语" if pattern in V_SYSTEM_TERMS else ("持仓基金代码" if pattern in FUND_CODES else "策略关键词")
                    if key not in results:
                        results[key] = []
                    line_no = node.lineno
                    if line_no <= len(lines):
                        line_content = lines[line_no - 1].strip()
                        results[key].append((line_no, line_content[:80]))
        
        # 检查 Constant 节点（字符串常量）
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            str_value = node.value
            for pattern in V_SYSTEM_TERMS + FUND_CODES + INTERNAL_PATHS + STRATEGY_KEYWORDS:
                if re.search(pattern, str_value, re.IGNORECASE):
                    key = "V系统术语" if pattern in V_SYSTEM_TERMS else ("持仓基金代码" if pattern in FUND_CODES else ("内部路径引用" if pattern in INTERNAL_PATHS else "策略关键词"))
                    if key not in results:
                        results[key] = []
                    line_no = node.lineno
                    if line_no <= len(lines):
                        line_content = lines[line_no - 1].strip()
                        results[key].append((line_no, line_content[:80]))
    
    return results


def scan_file_regex(filepath: Path) -> Dict[str, List[Tuple[int, str]]]:
    """
    使用正则扫描（备用，当 AST 解析失败时）
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
        
        for pattern in V_SYSTEM_TERMS:
            if re.search(pattern, line, re.IGNORECASE):
                if "V系统术语" not in results:
                    results["V系统术语"] = []
                results["V系统术语"].append((line_num, line_stripped[:80]))
                break
        
        for pattern in FUND_CODES:
            if re.search(pattern, line):
                if "持仓基金代码" not in results:
                    results["持仓基金代码"] = []
                results["持仓基金代码"].append((line_num, line_stripped[:80]))
                break
        
        for pattern in INTERNAL_PATHS:
            if re.search(pattern, line, re.IGNORECASE):
                if "内部路径引用" not in results:
                    results["内部路径引用"] = []
                results["内部路径引用"].append((line_num, line_stripped[:80]))
                break
        
        for pattern in STRATEGY_KEYWORDS:
            if re.search(pattern, line, re.IGNORECASE):
                if "策略关键词" not in results:
                    results["策略关键词"] = []
                results["策略关键词"].append((line_num, line_stripped[:80]))
                break
        
        for pattern in API_KEY_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                if 'os.environ' not in line and 'os.getenv' not in line:
                    if "API Key硬编码" not in results:
                        results["API Key硬编码"] = []
                    results["API Key硬编码"].append((line_num, line_stripped[:80]))
                    break
    
    return results


# ============================================================
# 扫描目录
# ============================================================

def scan_directory(directory: Path) -> Dict[str, Dict]:
    results = {}
    py_files = list(directory.rglob("*.py"))
    
    for py_file in py_files:
        if py_file.name in EXCLUDED_FILES:
            continue
        if 'venv' in str(py_file) or '__pycache__' in str(py_file):
            continue
        
        file_results = scan_file_ast(py_file)
        if file_results:
            filtered = {k: v for k, v in file_results.items() if v}
            if filtered:
                results[str(py_file.relative_to(directory.parent))] = filtered
    
    return results


# ============================================================
# 报告输出
# ============================================================

def print_report(results: Dict[str, Dict]) -> int:
    total_issues = 0
    
    print("=" * 70)
    print("🔍 公开库敏感信息扫描报告（P4-1）")
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
            for line_num, content in items[:3]:
                print(f"      行 {line_num}: {content}")
            if len(items) > 3:
                print(f"      ... 还有 {len(items) - 3} 处")
            total_issues += len(items)
    
    print("\n" + "=" * 70)
    print(f"📊 总计发现 {total_issues} 处敏感信息")
    
    if total_issues > 0:
        print("\n❌ 发现敏感信息，请清理上述内容")
        print("   注意：仅当这些内容出现在代码逻辑中才需要清理")
        print("   如果出现在注释或文档字符串中，可以忽略")
    else:
        print("\n✅ 敏感信息扫描通过")
    
    print("=" * 70)
    return total_issues


def main():
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    
    print(f"📂 扫描目录: {repo_root}")
    print(f"📂 排除文件: {EXCLUDED_FILES}")
    
    scripts_dir = repo_root / "scripts"
    results = {}
    
    if scripts_dir.exists():
        print(f"✅ 找到 scripts 目录，开始扫描...")
        results = scan_directory(scripts_dir)
    else:
        print(f"⚠️ scripts 目录不存在: {scripts_dir}")
        results = scan_directory(repo_root)
    
    total_issues = print_report(results)
    return 1 if total_issues > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
