#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 安全检查脚本
通用敏感词检查，不含任何项目特有信息
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
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class SecurityChecker:
    """安全扫描器 - 仅检查通用敏感词"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or load_config()
        self._load_patterns()

    def _load_patterns(self):
        """加载阻止规则 - 仅使用通用敏感词"""
        sec_config = self.config.get('security_check', {})

        # ✅ 修复：只保留通用敏感词，移除所有相关词汇
        self.blocked_keywords = sec_config.get('blocked_keywords', [
            "secret",
            "password",
            "api_key",
            "token",
            "credential",
            "confidential",
            "internal"
        ])

        self.blocked_patterns = sec_config.get('blocked_patterns', [
            r'.*\.local$',
            r'.*\.internal$',
            r'.*\.private$',
            r'192\.168\.\d+\.\d+',
            r'10\.\d+\.\d+\.\d+',
            r'172\.(1[6-9]|2[0-9]|3[0-1])\.\d+\.\d+'
        ])

        self.strict_mode = sec_config.get('strict_mode', False)

    def check_text(self, text: str) -> Tuple[bool, List[str]]:
        if not text:
            return True, []

        violations = []
        text_lower = text.lower()

        for keyword in self.blocked_keywords:
            if keyword.lower() in text_lower:
                violations.append(f"包含阻止关键词: {keyword}")

        for pattern in self.blocked_patterns:
            try:
                if re.search(pattern, text, re.IGNORECASE):
                    violations.append(f"匹配阻止模式: {pattern}")
            except re.error:
                pass

        return len(violations) == 0, violations

    def check_data(self, data: Any, path: str = "", depth: int = 0) -> Tuple[bool, List[Dict]]:
        if depth > 20:
            return True, []

        violations = []

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                is_safe, key_violations = self.check_text(key)
                if not is_safe:
                    for v in key_violations:
                        violations.append({
                            "path": current_path,
                            "type": "key",
                            "issue": v,
                            "value": key
                        })
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

        return len(violations) == 0, violations

    def check_file(self, filepath: str) -> Tuple[bool, List[Dict]]:
        violations = []

        if not os.path.exists(filepath):
            return False, [{"type": "error", "issue": f"文件不存在: {filepath}"}]

        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return False, [{"type": "error", "issue": f"JSON解析失败: {e}"}]
        except Exception as e:
            return False, [{"type": "error", "issue": f"读取文件失败: {e}"}]

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

        content_safe, content_violations = self.check_data(data)
        violations.extend(content_violations)

        return len(violations) == 0, violations


def scan_staging_files(staging_dir: str = "staging", strict: bool = False) -> Dict[str, Any]:
    config = load_config()
    checker = SecurityChecker(config)

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

    report_path = os.path.join(staging_dir, f"security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    save_json(results, report_path)

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

    if args.strict and result['failed'] > 0:
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
