#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
历史数据打包模块
将分散的历史数据文件合并为一个统一包
"""

import os
import sys
import json
import glob
from datetime import datetime

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")


def pack_historical():
    """打包所有历史数据"""
    print("📦 打包历史数据...")

    # 查找所有历史数据文件
    pattern = os.path.join(STAGING_DIR, "historical_*.json")
    files = glob.glob(pattern)

    # 排除已签名的文件
    files = [f for f in files if "_signed" not in f]

    if not files:
        print("   ⚠️ 没有找到历史数据文件")
        return None

    # 合并数据
    merged = {
        "package_type": "historical_data",
        "generated_at": datetime.now().isoformat(),
        "contents": {}
    }

    for filepath in files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                data_type = data.get('type', 'unknown')
                merged["contents"][data_type] = data
        except Exception as e:
            print(f"   ⚠️ 读取失败 {filename}: {e}")

    # 保存合并包
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(STAGING_DIR, f"historical_package_{timestamp}.json")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"   ✅ 已生成: {os.path.basename(output_file)}")
    return output_file


if __name__ == "__main__":
    pack_historical()
