#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 安全检查脚本（完整版）
功能：
1. 扫描 JSON 数据，确保不含敏感关键词
2. 支持递归检查嵌套结构
3. 生成详细检查报告
4. 支持严格模式（发现违规即报错）
"""

import os
import sys
import re
import json
import glob
import argparse
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple

try:
    import yaml
except ImportError:
    yaml = None


# ============================================================
# 工具函数
# ============================================================

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    """加载配置文件"""
    if os.path.exists(config_path):
        try:
            if yaml:
                with open(config_path, 'r', encoding='utf-8') as f:
                    return yaml.safe_load(f) or {}
            else:
                import json
                with open(config_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"⚠️ 加载配置文件失败: {e}")
    return {}


def save_json(data: Any, filepath: str) -> bool:
    """保存 JSON 文件"""
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"❌ 保存失败: {e}")
        return False


def get_timestamp() -> str:
    """获取当前时间戳"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 安全扫描器
# ============================================================

class SecurityChecker:
    """安全扫描器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or load_config()
        self._load_patterns()

    def _load_patterns(self):
        """加载阻止规则"""
        sec_config = self.config.get('security_check', {})

        # 阻止的关键词（从配置读取，或使用默认）
        self.blocked_keywords = sec_config.get('blocked_keywords', [
            # V系统相关（绝对不能出现）
            "v-system",
            "vsystem",
            "VSystem",
            "V_System",
            "v_system",
            # 私密库相关
            "private_repo",
            "私密库",
            "内网",
            # 敏感信息
            "机密",
            "内部",
            # V系统专有术语
            "黄金坑",
            "高山位",
            "板块映射",
            "信号等级",
            "持仓信号",
            "风控层",
            "多因子融合",
            "影子系统",
        ])

        # 阻止的正则模式
        self.blocked_patterns = sec_config.get('blocked_patterns', [
            r'.*\.local$',
            r'.*\.internal$',
            r'.*\.private$',
            r'192\.168\.\d+\.\d+',
            r'10\.\d+\.\d+\.\d+',
            r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+'
        ])

        # 严格模式：发现违规即返回失败
        self.strict_mode = sec_config.get('strict_mode', False)

    def check_text(self, text: str) -> Tuple[bool, List[str]]:
        """
        检查文本是否包含敏感信息

        Args:
            text: 待检查的文本

        Returns:
            (is_safe, violations): 是否安全，违规列表
        """
        if not text:
            return True, []

        violations = []
        text_lower = text.lower()

        # 检查关键词
        for keyword in self.blocked_keywords:
            if keyword.lower() in text_lower:
                violations.append(f"包含阻止关键词: {keyword}")

        # 检查正则模式
        for pattern in self.blocked_patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"匹配阻止模式: {pattern}")
            except re.error:
                pass  # 忽略无效的正则

        return len(violations) == 0, violations

    def check_data(self, data: Any, path: str = "", depth: int = 0) -> Tuple[bool, List[Dict]]:
        """
        递归检查数据是否包含敏感信息

        Args:
            data: 待检查的数据
            path: 当前路径（用于定位）
            depth: 递归深度

        Returns:
            (is_safe, violations): 是否安全，违规详情列表
        """
        if depth > 20:  # 防止无限递归
            return True, []

        violations = []

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key

                # 检查键名
                is_safe, key_violations = self.check_text(key)
                if not is_safe:
                    for v in key_violations:
                        violations.append({
                            "path": current_path,
                            "type": "key",
                            "issue": v,
                            "value": key
                        })

                # 递归检查值
                sub_safe, sub_violations = self.check_data(value, current_path, depth + 1)
                if not sub_safe:
                    violations.extend(sub_violations)

        elif isinstance(data, list):
            for idx, item in enumerate(data):
                current_path = f"{path}[{idx}]"
                sub_safe, sub_violations = self.check_data(item, current_path, depth + 1)
                if not sub_safe:
                    violations.extend(sub_violations)

        elif isinstance(data, str):
            is_safe, text_violations = self.check_text(data)
            if not is_safe:
                for v in text_violations:
                    violations.append({
                        "path": path,
                        "type": "text",
                        "issue": v,
                        "value": data[:100] + "..." if len(data) > 100 else data
                    })

        # 其他类型（int, float, bool, None）跳过

        return len(violations) == 0, violations

    def check_file(self, filepath: str) -> Tuple[bool, List[Dict]]:
        """
        检查文件是否包含敏感信息

        Args:
            filepath: 文件路径

        Returns:
            (is_safe, violations): 是否安全，违规详情列表
        """
        violations = []

        # 检查文件是否存在
        if not os.path.exists(filepath):
            return False, [{"type": "error", "issue": f"文件不存在: {filepath}"}]

        # 读取文件
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return False, [{"type": "error", "issue": f"JSON解析失败: {e}"}]
        except Exception as e:
            return False, [{"type": "error", "issue": f"读取文件失败: {e}"}]

        # 检查文件名本身
        filename = os.path.basename(filepath)
        is_safe, name_violations = self.check_text(filename)
        if not is_safe:
            for v in name_violations:
                violations.append({
                    "path": "filename",
                    "type": "text",
                    "issue": v,
                    "value": filename
                })

        # 检查文件内容
        content_safe, content_violations = self.check_data(data)
        violations.extend(content_violations)

        return len(violations) == 0, violations


# ============================================================
# 主函数
# ============================================================

def scan_staging_files(staging_dir: str = "staging", strict: bool = False) -> Dict[str, Any]:
    """
    扫描暂存区所有文件

    Returns:
        Dict: 扫描结果统计
    """
    config = load_config()
    checker = SecurityChecker(config)

    # 如果配置中启用了严格模式，覆盖参数
    if checker.strict_mode:
        strict = True

    results = {
        "timestamp": get_timestamp(),
        "strict_mode": strict,
        "total": 0,
        "passed": 0,
        "failed": 0,
        "details": []
    }

    # 查找 staging 目录下所有 JSON 文件
    if not os.path.exists(staging_dir):
        results["details"].append({"message": f"暂存区目录不存在: {staging_dir}"})
        return results

    json_files = glob.glob(os.path.join(staging_dir, "*.json"))

    if not json_files:
        results["details"].append({"message": "暂存区无JSON文件"})
        return results

    for filepath in json_files:
        results["total"] += 1
        is_safe, violations = checker.check_file(filepath)

        if is_safe:
            results["passed"] += 1
            results["details"].append({
                "file": os.path.basename(filepath),
                "status": "✅ passed"
            })
        else:
            results["failed"] += 1
            results["details"].append({
                "file": os.path.basename(filepath),
                "status": "❌ failed",
                "violations": violations
            })

    # 保存扫描报告
    report_path = os.path.join(staging_dir, f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    save_json(results, report_path)

    # 打印摘要
    print("\n" + "=" * 60)
    print("📊 安全检查报告")
    print("=" * 60)
    print(f"📅 时间: {results['timestamp']}")
    print(f"📂 暂存区: {staging_dir}")
    print(f"📊 总计: {results['total']} 个文件")
    print(f"✅ 通过: {results['passed']} 个")
    print(f"❌ 失败: {results['failed']} 个")
    if results['failed'] > 0:
        print("=" * 60)
        print("⚠️ 违规详情:")
        for detail in results['details']:
            if detail['status'] == '❌ failed':
                print(f"\n  📁 {detail['file']}")
                for v in detail.get('violations', [])[:5]:
                    print(f"     - {v.get('issue', '')} (路径: {v.get('path', '')})")
                if len(detail.get('violations', [])) > 5:
                    print(f"     ... 共 {len(detail.get('violations', []))} 项违规")
    print("=" * 60)

    return results


def main():
    parser = argparse.ArgumentParser(description='数据安全检查')
    parser.add_argument('--dir', type=str, default='staging',
                        help='目标目录（默认staging）')
    parser.add_argument('--strict', action='store_true',
                        help='严格模式：发现违规即退出码1')
    args = parser.parse_args()

    print("=" * 60)
    print("🛡️ data-collector 安全检查启动")
    print(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 目录: {args.dir}")
    print(f"🔒 严格模式: {'启用' if args.strict else '禁用'}")
    print("=" * 60)

    result = scan_staging_files(args.dir, args.strict)

    # 严格模式下，如果有违规则退出码1
    if args.strict and result['failed'] > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
