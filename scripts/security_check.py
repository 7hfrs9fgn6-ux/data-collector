#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
安全检查模块
扫描数据内容，确保不含敏感信息
"""

import re
import os
import json
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

from utils import load_json, save_json, get_timestamp, load_config


class SecurityChecker:
    """安全扫描器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._load_blocked_patterns()

    def _load_blocked_patterns(self):
        """加载阻止规则"""
        sec_config = self.config.get('security_check', {})
        
        # 阻止的关键词
        self.blocked_keywords = sec_config.get('blocked_keywords', [
            "v-system",
            "vsystem",
            "VSystem",
            "V_System",
            "v_system",
            "private_repo",
            "内网",
            "机密",
            "内部"
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
            if re.search(pattern, text, re.IGNORECASE):
                violations.append(f"匹配阻止模式: {pattern}")
        
        return len(violations) == 0, violations

    def check_data(self, data: Any, path: str = "") -> Tuple[bool, List[Dict]]:
        """
        递归检查数据是否包含敏感信息
        
        Args:
            data: 待检查的数据
            path: 当前路径（用于定位）
            
        Returns:
            (is_safe, violations): 是否安全，违规详情列表
        """
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
                sub_safe, sub_violations = self.check_data(value, current_path)
                if not sub_safe:
                    violations.extend(sub_violations)
                    
        elif isinstance(data, list):
            for idx, item in enumerate(data):
                current_path = f"{path}[{idx}]"
                sub_safe, sub_violations = self.check_data(item, current_path)
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
                        "value": data[:100]  # 只记录前100字符
                    })
        # 其他类型（int, float, bool）跳过
        
        return len(violations) == 0, violations

    def check_file(self, filepath: str) -> Tuple[bool, List[Dict]]:
        """
        检查文件是否包含敏感信息
        
        Args:
            filepath: 文件路径
            
        Returns:
            (is_safe, violations): 是否安全，违规详情列表
        """
        data = load_json(filepath)
        if data is None:
            return False, [{"type": "error", "issue": f"无法读取文件: {filepath}"}]
        
        # 检查文件名本身
        filename = os.path.basename(filepath)
        is_safe, name_violations = self.check_text(filename)
        violations = []
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


def scan_staging_files() -> Dict[str, Any]:
    """
    扫描暂存区所有文件
    
    Returns:
        Dict: 扫描结果统计
    """
    import glob
    
    checker = SecurityChecker()
    results = {
        "timestamp": get_timestamp(),
        "total": 0,
        "passed": 0,
        "failed": 0,
        "details": []
    }
    
    # 查找 staging 目录下所有 JSON 文件
    files = glob.glob("staging/*.json")
    
    for filepath in files:
        results["total"] += 1
        is_safe, violations = checker.check_file(filepath)
        
        if is_safe:
            results["passed"] += 1
            results["details"].append({
                "file": filepath,
                "status": "passed"
            })
        else:
            results["failed"] += 1
            results["details"].append({
                "file": filepath,
                "status": "failed",
                "violations": violations
            })
    
    # 保存扫描报告
    report_path = f"staging/security_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    save_json(results, report_path)
    
    return results


def check_data_safety(data: Dict[str, Any]) -> Tuple[bool, str]:
    """
    公开接口：检查数据是否安全
    
    Returns:
        (is_safe, message): 是否安全，消息
    """
    config = load_config() if load_config else {}
    checker = SecurityChecker(config)
    is_safe, violations = checker.check_data(data)
    
    if is_safe:
        return True, "安全检查通过"
    else:
        return False, f"安全检查失败: {len(violations)} 项违规"


if __name__ == "__main__":
    result = scan_staging_files()
    print(f"安全检查完成: 总计 {result['total']} 个文件, "
          f"通过 {result['passed']} 个, "
          f"失败 {result['failed']} 个")
    
    if result['failed'] > 0:
        print("\n⚠️ 发现违规:")
        for detail in result['details']:
            if detail['status'] == 'failed':
                print(f"  📁 {detail['file']}")
                for v in detail.get('violations', [])[:3]:
                    print(f"     - {v.get('issue', '')}")
