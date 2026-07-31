#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
暂存区清理模块
按 TTL 自动清理过期文件，控制存储空间
"""

import os
import shutil
import glob
from datetime import datetime, timedelta
from typing import Dict, List, Any, Optional

from utils import load_config, get_timestamp


class StagingCleaner:
    """暂存区清理器"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}
        self._load_config()

    def _load_config(self):
        """加载配置"""
        staging_config = self.config.get('staging', {})
        self.staging_path = staging_config.get('path', './staging/')
        self.ttl_hours = staging_config.get('ttl_hours', 24)
        self.max_size_mb = staging_config.get('max_size_mb', 100)
        self.max_files = staging_config.get('max_files', 100)
        
        # 确保路径以 / 结尾
        if not self.staging_path.endswith('/'):
            self.staging_path += '/'

    def clean_by_ttl(self) -> Dict[str, Any]:
        """
        按 TTL 清理过期文件
        
        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "ttl_hours": self.ttl_hours,
            "total": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        # 查找所有文件（不包含目录）
        files = glob.glob(f"{self.staging_path}*.*")
        
        # 排除 _signed.json 文件（这些是已签名的数据，优先保留）
        files = [f for f in files if not f.endswith('_signed.json')]

        # 检查目录是否存在
        if not os.path.exists(self.staging_path):
            result['details'].append({"message": "暂存区目录不存在"})
            return result

        cutoff_time = datetime.now() - timedelta(hours=self.ttl_hours)

        for filepath in files:
            result['total'] += 1
            
            # 获取文件修改时间
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
            except Exception as e:
                result['failed'] += 1
                result['details'].append({
                    "file": filepath,
                    "status": "failed",
                    "reason": str(e)
                })
                continue

            # 如果文件超过 TTL，删除
            if mtime < cutoff_time:
                try:
                    os.remove(filepath)
                    result['deleted'] += 1
                    result['details'].append({
                        "file": filepath,
                        "status": "deleted",
                        "reason": f"超过 {self.ttl_hours} 小时 TTL"
                    })
                except Exception as e:
                    result['failed'] += 1
                    result['details'].append({
                        "file": filepath,
                        "status": "failed",
                        "reason": str(e)
                    })
            else:
                result['skipped'] += 1

        return result

    def clean_by_size(self) -> Dict[str, Any]:
        """
        按空间限制清理文件
        
        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "max_size_mb": self.max_size_mb,
            "total": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        if not os.path.exists(self.staging_path):
            return result

        # 获取所有文件及其大小
        files = []
        for filepath in glob.glob(f"{self.staging_path}*.*"):
            try:
                size = os.path.getsize(filepath)
                mtime = os.path.getmtime(filepath)
                files.append({
                    "path": filepath,
                    "size": size,
                    "mtime": mtime
                })
            except Exception:
                continue

        result['total'] = len(files)

        # 按修改时间排序（最旧的在前）
        files.sort(key=lambda x: x['mtime'])

        # 计算当前总大小（MB）
        total_size = sum(f['size'] for f in files) / (1024 * 1024)
        
        if total_size <= self.max_size_mb:
            result['details'].append({
                "message": f"当前大小 {total_size:.1f}MB，未超过限制 {self.max_size_mb}MB"
            })
            result['skipped'] = len(files)
            return result

        # 需要删除的文件数量
        to_delete = []
        current_size = total_size
        for f in files:
            if current_size <= self.max_size_mb:
                break
            current_size -= f['size'] / (1024 * 1024)
            to_delete.append(f)

        # 执行删除
        for f in to_delete:
            try:
                os.remove(f['path'])
                result['deleted'] += 1
                result['details'].append({
                    "file": f['path'],
                    "status": "deleted",
                    "reason": f"超过空间限制 {self.max_size_mb}MB"
                })
            except Exception as e:
                result['failed'] += 1
                result['details'].append({
                    "file": f['path'],
                    "status": "failed",
                    "reason": str(e)
                })

        result['skipped'] = len(files) - len(to_delete)
        return result

    def clean_by_count(self) -> Dict[str, Any]:
        """
        按文件数量限制清理
        
        Returns:
            Dict: 清理结果统计
        """
        result = {
            "timestamp": get_timestamp(),
            "max_files": self.max_files,
            "total": 0,
            "deleted": 0,
            "skipped": 0,
            "failed": 0,
            "details": []
        }

        if not os.path.exists(self.staging_path):
            return result

        # 获取所有文件
        files = glob.glob(f"{self.staging_path}*.*")
        
        # 排除 _signed.json 文件
        files = [f for f in files if not f.endswith('_signed.json')]
        
        result['total'] = len(files)

        if len(files) <= self.max_files:
            result['details'].append({
                "message": f"当前 {len(files)} 个文件，未超过限制 {self.max_files}"
            })
            result['skipped'] = len(files)
            return result

        # 按修改时间排序（最旧的在前）
        files_with_time = []
        for f in files:
            try:
                mtime = os.path.getmtime(f)
                files_with_time.append({"path": f, "mtime": mtime})
            except Exception:
                continue

        files_with_time.sort(key=lambda x: x['mtime'])

        # 需要删除的数量
        to_delete_count = len(files) - self.max_files
        to_delete = files_with_time[:to_delete_count]

        for f in to_delete:
            try:
                os.remove(f['path'])
                result['deleted'] += 1
                result['details'].append({
                    "file": f['path'],
                    "status": "deleted",
                    "reason": f"超过文件数量限制 {self.max_files}"
                })
            except Exception as e:
                result['failed'] += 1
                result['details'].append({
                    "file": f['path'],
                    "status": "failed",
                    "reason": str(e)
                })

        result['skipped'] = len(files) - len(to_delete)
        return result

    def clean_all(self) -> Dict[str, Any]:
        """
        执行完整清理流程
        
        Returns:
            Dict: 综合清理结果
        """
        print("🧹 开始清理暂存区...")
        
        ttl_result = self.clean_by_ttl()
        count_result = self.clean_by_count()
        size_result = self.clean_by_size()

        # 汇总
        combined = {
            "timestamp": get_timestamp(),
            "ttl": ttl_result,
            "count": count_result,
            "size": size_result,
            "summary": {
                "total_deleted": (
                    ttl_result.get('deleted', 0) +
                    count_result.get('deleted', 0) +
                    size_result.get('deleted', 0)
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
        log_path = f"staging/cleanup_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        save_json(combined, log_path)

        print(f"✅ 清理完成: 删除 {combined['summary']['total_deleted']} 个文件")
        return combined


def save_json(data: Any, filepath: str) -> bool:
    """保存 JSON 文件"""
    import json
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存失败: {e}")
        return False


if __name__ == "__main__":
    config = load_config() if load_config else {}
    cleaner = StagingCleaner(config)
    result = cleaner.clean_all()
    
    print(f"\n📊 清理统计:")
    print(f"   TTL 清理: {result['ttl']['deleted']} 个")
    print(f"   数量限制: {result['count']['deleted']} 个")
    print(f"   空间限制: {result['size']['deleted']} 个")
    print(f"   总删除: {result['summary']['total_deleted']} 个")
