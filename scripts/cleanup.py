#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 暂存区清理脚本（完整版）
功能：
1. 按 TTL 清理过期文件
2. 按文件数量限制清理
3. 按空间大小限制清理
4. 排除已签名的重要文件
5. 生成清理日志
"""

import os
import sys
import glob
import json
import argparse
import time
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

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


def get_file_size_mb(filepath: str) -> float:
    """获取文件大小（MB）"""
    try:
        return os.path.getsize(filepath) / (1024 * 1024)
    except Exception:
        return 0


# ============================================================
# 清理器
# ============================================================

class StagingCleaner:
    """暂存区清理器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or load_config()
        self._load_config()

    def _load_config(self):
        """加载配置"""
        staging_config = self.config.get('staging', {})
        self.staging_path = staging_config.get('path', './staging/')
        self.ttl_hours = staging_config.get('ttl_hours', 24)
        self.max_size_mb = staging_config.get('max_size_mb', 100)
        self.max_files = staging_config.get('max_files', 100)
        self.cleanup_interval_hours = staging_config.get('cleanup_interval_hours', 6)

        # 确保路径以 / 结尾
        if not self.staging_path.endswith('/'):
            self.staging_path += '/'

        # 需要保护的文件模式（不删除）
        self.protected_patterns = [
            '_signed.json',      # 已签名的数据包
            'security_report_',  # 安全检查报告
            'cleanup_log_',      # 清理日志
        ]

    def _is_protected(self, filepath: str) -> bool:
        """检查文件是否受保护"""
        basename = os.path.basename(filepath)
        for pattern in self.protected_patterns:
            if pattern in basename:
                return True
        return False

    def _get_files(self) -> List[str]:
        """获取暂存区所有文件"""
        if not os.path.exists(self.staging_path):
            return []

        files = glob.glob(os.path.join(self.staging_path, "*.*"))
        # 排除目录
        return [f for f in files if os.path.isfile(f)]

    def clean_by_ttl(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        按 TTL 清理过期文件

        Args:
            dry_run: True=仅预览不删除

        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "type": "ttl",
            "ttl_hours": self.ttl_hours,
            "total": 0,
            "deleted": 0,
            "protected": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        files = self._get_files()
        if not files:
            return result

        cutoff_time = time.time() - (self.ttl_hours * 3600)
        result["total"] = len(files)

        for filepath in files:
            # 检查是否受保护
            if self._is_protected(filepath):
                result["protected"] += 1
                continue

            try:
                mtime = os.path.getmtime(filepath)
            except Exception as e:
                result["failed"] += 1
                result["details"].append({
                    "file": os.path.basename(filepath),
                    "status": "failed",
                    "reason": str(e)
                })
                continue

            if mtime < cutoff_time:
                result["deleted"] += 1
                result["details"].append({
                    "file": os.path.basename(filepath),
                    "status": "deleted" if not dry_run else "would_delete",
                    "age_hours": round((time.time() - mtime) / 3600, 1),
                    "reason": f"超过 {self.ttl_hours} 小时 TTL"
                })
                if not dry_run:
                    try:
                        os.remove(filepath)
                    except Exception as e:
                        result["failed"] += 1
                        result["details"][-1]["status"] = "failed"
                        result["details"][-1]["reason"] = str(e)
            else:
                result["skipped"] += 1

        return result

    def clean_by_size(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        按空间限制清理文件

        Args:
            dry_run: True=仅预览不删除

        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "type": "size",
            "max_size_mb": self.max_size_mb,
            "total": 0,
            "deleted": 0,
            "protected": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        files = self._get_files()
        if not files:
            return result

        # 获取所有文件信息（排除受保护的）
        file_info = []
        for filepath in files:
            if self._is_protected(filepath):
                result["protected"] += 1
                continue
            try:
                file_info.append({
                    "path": filepath,
                    "size": os.path.getsize(filepath),
                    "mtime": os.path.getmtime(filepath)
                })
            except Exception:
                continue

        result["total"] = len(file_info)

        if not file_info:
            return result

        # 按修改时间排序（最旧的在前）
        file_info.sort(key=lambda x: x['mtime'])

        # 计算当前总大小（MB）
        total_size = sum(f['size'] for f in file_info) / (1024 * 1024)

        if total_size <= self.max_size_mb:
            result["skipped"] = len(file_info)
            result["details"].append({
                "message": f"当前大小 {total_size:.1f}MB，未超过限制 {self.max_size_mb}MB"
            })
            return result

        # 需要删除的文件
        current_size = total_size
        to_delete = []
        for f in file_info:
            if current_size <= self.max_size_mb:
                break
            current_size -= f['size'] / (1024 * 1024)
            to_delete.append(f)

        # 执行删除
        for f in to_delete:
            result["deleted"] += 1
            result["details"].append({
                "file": os.path.basename(f['path']),
                "status": "deleted" if not dry_run else "would_delete",
                "size_mb": round(f['size'] / (1024 * 1024), 2),
                "reason": f"超过空间限制 {self.max_size_mb}MB"
            })
            if not dry_run:
                try:
                    os.remove(f['path'])
                except Exception as e:
                    result["failed"] += 1
                    result["details"][-1]["status"] = "failed"
                    result["details"][-1]["reason"] = str(e)

        result["skipped"] = len(file_info) - len(to_delete)
        return result

    def clean_by_count(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        按文件数量限制清理

        Args:
            dry_run: True=仅预览不删除

        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "type": "count",
            "max_files": self.max_files,
            "total": 0,
            "deleted": 0,
            "protected": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        files = self._get_files()
        if not files:
            return result

        # 过滤受保护文件
        unprotected = [f for f in files if not self._is_protected(f)]
        result["protected"] = len(files) - len(unprotected)
        result["total"] = len(unprotected)

        if len(unprotected) <= self.max_files:
            result["skipped"] = len(unprotected)
            return result

        # 按修改时间排序（最旧的在前）
        files_with_time = []
        for f in unprotected:
            try:
                files_with_time.append({
                    "path": f,
                    "mtime": os.path.getmtime(f)
                })
            except Exception:
                continue

        files_with_time.sort(key=lambda x: x['mtime'])

        # 需要删除的数量
        to_delete_count = len(files_with_time) - self.max_files
        to_delete = files_with_time[:to_delete_count]

        for f in to_delete:
            result["deleted"] += 1
            result["details"].append({
                "file": os.path.basename(f['path']),
                "status": "deleted" if not dry_run else "would_delete",
                "reason": f"超过文件数量限制 {self.max_files}"
            })
            if not dry_run:
                try:
                    os.remove(f['path'])
                except Exception as e:
                    result["failed"] += 1
                    result["details"][-1]["status"] = "failed"
                    result["details"][-1]["reason"] = str(e)

        result["skipped"] = len(unprotected) - len(to_delete)
        return result

    def clean_all(self, dry_run: bool = False) -> Dict[str, Any]:
        """
        执行完整清理流程

        Args:
            dry_run: True=仅预览不删除

        Returns:
            Dict: 综合清理结果
        """
        print("🧹 开始清理暂存区..." + (" (预览模式，不删除文件)" if dry_run else ""))

        ttl_result = self.clean_by_ttl(dry_run)
        count_result = self.clean_by_count(dry_run)
        size_result = self.clean_by_size(dry_run)

        # 汇总
        combined = {
            "timestamp": get_timestamp(),
            "dry_run": dry_run,
            "staging_path": self.staging_path,
            "ttl": ttl_result,
            "count": count_result,
            "size": size_result,
            "summary": {
                "total_deleted": (
                    ttl_result.get('deleted', 0) +
                    count_result.get('deleted', 0) +
                    size_result.get('deleted', 0)
                ),
                "total_protected": (
                    ttl_result.get('protected', 0) +
                    count_result.get('protected', 0) +
                    size_result.get('protected', 0)
                ),
                "total_skipped": (
                    ttl_result.get('skipped', 0) +
                    count_result.get('skipped', 0) +
                    size_result.get('skipped', 0)
                ),
                "total_failed": (
                    ttl_result.get('failed', 0) +
                    count_result.get('failed', 0) +
                    size_result.get('failed', 0)
                )
            }
        }

        # 保存清理日志
        if not dry_run:
            log_path = os.path.join(self.staging_path, f"cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
            save_json(combined, log_path)
            print(f"📝 清理日志已保存: {log_path}")

        # 打印摘要
        print("\n" + "=" * 60)
        print("📊 清理统计" + (" (预览)" if dry_run else ""))
        print("=" * 60)
        print(f"📅 时间: {combined['timestamp']}")
        print(f"📂 目录: {self.staging_path}")
        print(f"📊 删除: {combined['summary']['total_deleted']} 个文件")
        print(f"🛡️ 保护: {combined['summary']['total_protected']} 个文件")
        print(f"⏭️ 跳过: {combined['summary']['total_skipped']} 个文件")
        print(f"❌ 失败: {combined['summary']['total_failed']} 个文件")
        print("=" * 60)

        return combined


# ============================================================
# 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='暂存区清理工具')
    parser.add_argument('--dir', type=str, default='staging',
                        help='目标目录（默认staging）')
    parser.add_argument('--ttl', type=int, default=24,
                        help='TTL小时数（默认24）')
    parser.add_argument('--max-files', type=int, default=100,
                        help='最大文件数（默认100）')
    parser.add_argument('--max-size', type=int, default=100,
                        help='最大空间MB（默认100）')
    parser.add_argument('--dry-run', action='store_true',
                        help='预览模式，不删除文件')
    parser.add_argument('--days', type=int, default=7,
                        help='保留天数（同--ttl，兼容旧版）')
    args = parser.parse_args()

    # 兼容旧版 --days 参数
    ttl_hours = args.ttl
    if args.days and args.days != 7:  # 用户指定了 --days
        ttl_hours = args.days * 24

    print("=" * 60)
    print("🧹 data-collector 清理工具启动")
    print(f"📅 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"📂 目录: {args.dir}")
    print(f"📅 TTL: {ttl_hours} 小时")
    print(f"📊 最大文件: {args.max_files}")
    print(f"💾 最大空间: {args.max_size}MB")
    print(f"🔍 预览模式: {'启用' if args.dry_run else '禁用'}")
    print("=" * 60)

    # 加载配置并覆盖参数
    config = load_config()
    if 'staging' not in config:
        config['staging'] = {}

    config['staging']['path'] = args.dir
    config['staging']['ttl_hours'] = ttl_hours
    config['staging']['max_files'] = args.max_files
    config['staging']['max_size_mb'] = args.max_size

    cleaner = StagingCleaner(config)
    result = cleaner.clean_all(dry_run=args.dry_run)

    # 如果有文件被删除且不是预览模式，退出码0
    sys.exit(0 if result['summary']['total_failed'] == 0 else 1)


if __name__ == "__main__":
    main()
