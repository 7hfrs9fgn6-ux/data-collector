#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
data-collector 签名密钥生成脚本
用户本地运行一次，生成 HMAC-SHA256 签名密钥
输出：密钥字符串，供配置到 GitHub Secrets
"""

import os
import sys
import secrets
import base64
from datetime import datetime


def generate_signing_key(length: int = 64) -> str:
    """生成安全的签名密钥"""
    # 使用 secrets 生成加密安全的随机字节
    key_bytes = secrets.token_bytes(length)
    # 转换为 Base64 字符串（可读且适合环境变量）
    key_b64 = base64.b64encode(key_bytes).decode('utf-8')
    return key_b64


def main():
    print("=" * 60)
    print("🔐 data-collector 签名密钥生成工具")
    print("=" * 60)
    print()
    print("📌 说明:")
    print("   1. 运行此脚本生成 HMAC-SHA256 签名密钥")
    print("   2. 将输出的密钥配置到以下仓库的 Secrets:")
    print("      - data-collector (公开库) → SIGNING_KEY")
    print("      - v-system-core (私密库) → SIGNING_KEY")
    print()
    print("🔑 生成的密钥 (请复制保存):")
    print("-" * 60)

    key = generate_signing_key(64)
    print(key)

    print("-" * 60)
    print()
    print("📋 配置步骤:")
    print("   1. 复制上面的密钥字符串")
    print("   2. 进入 GitHub 仓库 → Settings → Secrets and variables → Actions")
    print("   3. 点击 'New repository secret'")
    print("   4. Name: SIGNING_KEY")
    print("   5. Value: 粘贴上面复制的密钥")
    print("   6. 在两个仓库中重复此操作")
    print()
    print(f"⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 60)


if __name__ == "__main__":
    main()
