#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观高级数据采集模块（日频/最新值）- 综合修复版 V1.3.1
版本： V1.3.1
更新日期： 2026-08-23

★ V1.3.1 修复：
  - parse_chinese_date 增加 YYYYMM 格式支持（如 201501 → 2015-01）
  - 社会融资规模：使用正确的日期列名 '月份'，增加 YYYYMM 解析
  - 国债收益率：暂时移除（接口失效），添加占位标记
  - 增加更详细的调试日志
"""

import os
import sys
import json
import argparse
import logging
import time
import hmac
import hashlib
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

try:
    from scripts.sign import sign_data
except ImportError:
    def sign_data(data: Dict[str, Any], key: str) -> str:
        if not key:
            return ""
        sign_data = {k: v for k, v in data.items() if k not in ['signature', 'signature_metadata']}
        content = json.dumps(sign_data, sort_keys=True, ensure_ascii=False)
        return hmac.new(
            key.encode('utf-8'),
            content.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")
SIGNING_KEY = os.environ.get('SIGNING_KEY', '')


def get_signing_key() -> str:
    global SIGNING_KEY
    if not SIGNING_KEY:
        SIGNING_KEY = os.environ.get('SIGNING_KEY', '')
    return SIGNING_KEY


def parse_chinese_date(date_str: str) -> Optional[str]:
    """
    解析中文日期格式为 YYYY-MM
    支持格式：
      - "2008年01" -> "2008-01"
      - "2008年01月" -> "2008-01"
      - "202604" -> "2026-04"  ★ V1.3.1 新增
      - "201501" -> "2015-01"  ★ V1.3.1 新增
      - "2026-08-23" -> "2026-08"
    """
    if date_str is None:
        return None

    date_str = str(date_str).strip()

    # 格式: "202604" (6位数字) ★ V1.3.1 新增
    match = re.search(r'^(\d{4})(\d{2})$', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2)}"

    # 格式: "2008年01" 或 "2008年1月"
    match = re.search(r'(\d{4})年(\d{1,2})(?:月)?', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2).zfill(2)}"

    # 格式: "2026-08-23" -> 取前7位
    if len(date_str) >= 7 and date_str[4] == '-':
        return date_str[:7]

    # 格式: "2026年08月"
    match = re.search(r'(\d{4})年(\d{1,2})月', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2).zfill(2)}"

    # 如果只是年份（4位数字）
    if re.match(r'^\d{4}$', date_str):
        return f"{date_str}-01"

    return None


def is_data_reasonable(data_type: str, value: float) -> bool:
    if data_type == 'm2':
        return 100 <= value <= 500
    elif data_type == 'social_financing':
        return 1.0 <= value <= 30.0
    elif data_type == 'ppi':
        return -15 <= value <= 25
    elif data_type == 'shibor':
        return 0.5 <= value <= 10.0
    return True


# ============================================================
# 1. 国债收益率（暂时禁用，接口失效）
# ============================================================

def fetch_bond_yield() -> Optional[Dict[str, Any]]:
    """
    采集中国十年期国债收益率
    目前所有接口均已失效，返回 None
    """
    logger.info("   采集十年期国债收益率...")
    logger.warning("   ⚠️ 国债收益率接口暂时不可用，跳过采集")
    return None


# ============================================================
# 2. M2货币供应量（已稳定）
# ============================================================

def fetch_m2(debug: bool = False) -> Optional[Dict[str, Any]]:
    """采集M2货币供应量（最新月度）"""
    logger.info("   采集M2货币供应量...")
    try:
        import akshare as ak
        import pandas as pd

        df = ak.macro_china_money_supply()
        if df is None or df.empty:
            logger.warning("   ⚠️ M2数据为空")
            return None

        if debug:
            logger.debug(f"   M2 列名: {list(df.columns)}")
            logger.debug(f"   M2 前3行:\n{df.head(3).to_string()}")

        # 识别列名
        date_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        # 找数值列（M2数量）
        value_col = None
        for col in df.columns:
            if 'M2' in col and '数量' in col:
                value_col = col
                break
        if value_col is None:
            for col in df.columns:
                if 'M2' in col:
                    value_col = col
                    break
        if value_col is None:
            value_col = df.columns[1]

        # 解析日期并排序
        df['_parse_date'] = df[date_col].apply(lambda x: parse_chinese_date(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])

        if df.empty:
            logger.warning("   ⚠️ M2日期解析失败")
            return None

        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]

        date_val = latest.get('_parse_date')
        value = latest.get(value_col)

        if value is None:
            logger.warning("   ⚠️ M2值缺失")
            return None

        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace(',', '').replace('万亿元', '').replace('亿元', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ M2值解析失败: {value}")
                return None

        # 单位转换：亿元 → 万亿元
        unit = "万亿元"
        if value > 1000:
            value = value / 10000
            unit = "万亿元"

        if not is_data_reasonable('m2', value):
            logger.warning(f"   ⚠️ M2值异常: {value}万亿元")
            return None

        logger.info(f"   ✅ M2: {value:.1f}万亿元 (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": unit,
            "source": "eastmoney"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ M2采集异常: {e}")
        return None


# ============================================================
# 3. 社会融资规模（修复日期解析）
# ============================================================

def fetch_social_financing(debug: bool = False) -> Optional[Dict[str, Any]]:
    """采集社会融资规模（最新月度）"""
    logger.info("   采集社会融资规模...")
    try:
        import akshare as ak
        import pandas as pd

        df = ak.macro_china_shrzgm()
        if df is None or df.empty:
            logger.warning("   ⚠️ 社会融资规模数据为空")
            return None

        if debug:
            logger.debug(f"   社融 列名: {list(df.columns)}")
            logger.debug(f"   社融 前3行:\n{df.head(3).to_string()}")

        # 识别列名
        date_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        # 找数值列（社会融资规模增量）
        value_col = None
        for col in df.columns:
            if '社会融资' in col and '增量' in col:
                value_col = col
                break
        if value_col is None:
            for col in df.columns:
                if '融资' in col or '规模' in col:
                    value_col = col
                    break
        if value_col is None:
            value_col = df.columns[1]

        # ★ V1.3.1 修复：使用 parse_chinese_date 解析日期（支持 YYYYMM）
        df['_parse_date'] = df[date_col].apply(lambda x: parse_chinese_date(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])

        if df.empty:
            logger.warning("   ⚠️ 社融日期解析失败")
            return None

        # 按日期排序取最新
        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]

        date_val = latest.get('_parse_date')
        value = latest.get(value_col)

        if value is None:
            logger.warning("   ⚠️ 社会融资规模值缺失")
            return None

        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace(',', '').replace('万亿元', '').replace('亿元', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ 社会融资规模值解析失败: {value}")
                return None

        # 单位：亿元 → 万亿元
        unit = "万亿元"
        if value > 100:
            value = value / 10000
            unit = "万亿元"

        if not is_data_reasonable('social_financing', value):
            logger.warning(f"   ⚠️ 社会融资规模值异常: {value}万亿元")
            return None

        logger.info(f"   ✅ 社会融资规模: {value:.1f}万亿元 (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": unit,
            "source": "data-center"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ 社会融资规模采集异常: {e}")
        return None


# ============================================================
# 4. PPI（已稳定）
# ============================================================

def fetch_ppi(debug: bool = False) -> Optional[Dict[str, Any]]:
    """采集PPI（最新月度）- 自动修正定基指数"""
    logger.info("   采集PPI...")
    try:
        import akshare as ak
        import pandas as pd

        df = ak.macro_china_ppi()
        if df is None or df.empty:
            logger.warning("   ⚠️ PPI数据为空")
            return None

        if debug:
            logger.debug(f"   PPI 列名: {list(df.columns)}")
            logger.debug(f"   PPI 前3行:\n{df.head(3).to_string()}")

        # 识别列名
        date_col = None
        for col in df.columns:
            if '月份' in col or '日期' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        # ★ 优先使用 '当月同比增长' 列（已经是变化率），其次使用 '当月'
        value_col = None
        for col in df.columns:
            if '同比增长' in col or '同比' in col:
                value_col = col
                break
        if value_col is None:
            for col in df.columns:
                if '当月' in col:
                    value_col = col
                    break
        if value_col is None:
            value_col = df.columns[1]

        # 解析日期并排序
        df['_parse_date'] = df[date_col].apply(lambda x: parse_chinese_date(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])

        if df.empty:
            logger.warning("   ⚠️ PPI日期解析失败")
            return None

        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]

        date_val = latest.get('_parse_date')
        value = latest.get(value_col)

        if value is None:
            logger.warning("   ⚠️ PPI值缺失")
            return None

        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace('%', '').replace('+', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ PPI值解析失败: {value}")
                return None

        # ★ 自动修正：如果值 > 20，说明是定基指数，转为变化率
        if value > 20:
            # 如果同时存在 '当月同比增长' 列，用那个值
            if '同比增长' not in value_col:
                # 尝试找 '当月同比增长' 列
                for col in df.columns:
                    if '同比增长' in col or '同比' in col:
                        try:
                            actual_value = float(latest.get(col, 0))
                            if -15 <= actual_value <= 25:
                                value = actual_value
                                logger.debug(f"   PPI: 使用 '同比增长' 列值: {value:+.1f}%")
                                break
                        except:
                            pass
                if value > 20:
                    value = value - 100
                    logger.debug(f"   PPI: 检测到定基指数，自动修正为 {value:+.1f}%")
        elif value > 10 and value < 20:
            logger.debug(f"   PPI值在10-20之间，可能异常: {value}")

        if not is_data_reasonable('ppi', value):
            logger.warning(f"   ⚠️ PPI值异常: {value}%")
            return None

        logger.info(f"   ✅ PPI: {value:+.1f}% (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": "%",
            "source": "eastmoney"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ PPI采集异常: {e}")
        return None


# ============================================================
# 5. SHIBOR（已稳定）
# ============================================================

def fetch_shibor(debug: bool = False) -> Optional[Dict[str, Any]]:
    """采集SHIBOR隔夜和1周利率"""
    logger.info("   采集SHIBOR...")
    try:
        import akshare as ak
        import pandas as pd

        df = ak.macro_china_shibor_all()
        if df is None or df.empty:
            logger.warning("   ⚠️ SHIBOR数据为空")
            return None

        if debug:
            logger.debug(f"   SHIBOR 列名: {list(df.columns)}")

        date_col = None
        for col in df.columns:
            if '日期' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        overnight_col = None
        week_col = None
        for col in df.columns:
            if 'O/N' in col or '隔夜' in col:
                overnight_col = col
            if '1W' in col or '1周' in col or '一周' in col:
                week_col = col

        if overnight_col is None:
            for col in df.columns:
                if '隔夜' in col:
                    overnight_col = col
                    break
        if week_col is None:
            for col in df.columns:
                if '1周' in col or '一周' in col:
                    week_col = col
                    break

        # 按日期排序取最新
        try:
            df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.sort_values(date_col, ascending=False)
        except Exception as e:
            logger.debug(f"   SHIBOR日期排序失败: {e}")

        latest = df.iloc[0]

        date_val = latest.get(date_col)
        if date_val is None:
            date_val = datetime.now().strftime("%Y-%m-%d")
        elif hasattr(date_val, 'strftime'):
            date_val = date_val.strftime("%Y-%m-%d")
        else:
            date_val = str(date_val)[:10]

        overnight = None
        week = None

        if overnight_col:
            try:
                overnight = float(latest.get(overnight_col, 0))
            except:
                pass

        if week_col:
            try:
                week = float(latest.get(week_col, 0))
            except:
                pass

        if overnight is None:
            for col in df.columns:
                if col != date_col:
                    try:
                        v = float(latest.get(col, 0))
                        if 0 < v < 20:
                            if overnight is None:
                                overnight = v
                            elif week is None:
                                week = v
                                break
                    except:
                        pass

        if overnight is None or not is_data_reasonable('shibor', overnight):
            logger.warning(f"   ⚠️ SHIBOR值异常: {overnight}")
            return None

        logger.info(f"   ✅ SHIBOR: 隔夜 {overnight:.2f}%, 1周 {week if week else overnight:.2f}%")
        return {
            "date": date_val,
            "overnight": round(overnight, 2),
            "one_week": round(week if week else overnight, 2),
            "source": "jin10"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ SHIBOR采集异常: {e}")
        return None


# ============================================================
# 6. 打包与签名
# ============================================================

def pack_macro_advanced(bond, m2, social, ppi, shibor) -> Dict[str, Any]:
    logger.info("📦 开始打包宏观高级数据...")

    package = {
        "package_type": "macro_advanced",
        "generated_at": datetime.now().isoformat(),
        "version": "1.3.1",
        "contents": {}
    }

    if bond:
        package["contents"]["bond_yield"] = bond
        logger.info(f"   ✅ 包含十年期国债收益率: {bond.get('value')}%")
    else:
        logger.warning("   ⚠️ 十年期国债收益率数据缺失（接口暂不可用）")

    if m2:
        package["contents"]["m2"] = m2
        logger.info(f"   ✅ 包含M2: {m2.get('value')}{m2.get('unit', '')}")
    else:
        logger.warning("   ⚠️ M2数据缺失")

    if social:
        package["contents"]["social_financing"] = social
        logger.info(f"   ✅ 包含社会融资规模: {social.get('value')}{social.get('unit', '')}")
    else:
        logger.warning("   ⚠️ 社会融资规模数据缺失")

    if ppi:
        package["contents"]["ppi"] = ppi
        logger.info(f"   ✅ 包含PPI: {ppi.get('value')}%")
    else:
        logger.warning("   ⚠️ PPI数据缺失")

    if shibor:
        package["contents"]["shibor"] = shibor
        logger.info(f"   ✅ 包含SHIBOR: 隔夜 {shibor.get('overnight')}%, 1周 {shibor.get('one_week')}%")
    else:
        logger.warning("   ⚠️ SHIBOR数据缺失")

    package["metadata"] = {
        "total_items": len(package["contents"]),
        "data_types": list(package["contents"].keys()),
        "collection_time": datetime.now().isoformat()
    }

    key = get_signing_key()
    if key:
        package["signature"] = sign_data(package, key)
        logger.info("   🔐 数据包已签名")
    else:
        package["signature"] = None
        logger.warning("   ⚠️ 签名密钥未设置")

    logger.info(f"   📊 打包完成: {len(package['contents'])} 个数据类型")
    return package


def save_package(package: Dict[str, Any]) -> str:
    os.makedirs(STAGING_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"macro_advanced_package_{timestamp}.json"
    filepath = os.path.join(STAGING_DIR, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(package, f, ensure_ascii=False, indent=2)
    file_size = os.path.getsize(filepath)
    logger.info(f"✅ 已保存: {filename} ({file_size/1024:.1f} KB)")
    return filepath


# ============================================================
# 7. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集宏观高级数据（日频/最新值）')
    parser.add_argument('--debug', action='store_true', help='启用调试模式（打印列名）')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("🚀 开始采集宏观高级数据...")
    logger.info(f"   🐞 调试模式: {args.debug}")

    # 国债收益率（暂时跳过）
    bond_data = fetch_bond_yield()
    time.sleep(0.5)

    m2_data = fetch_m2(debug=args.debug)
    time.sleep(0.5)

    social_data = fetch_social_financing(debug=args.debug)
    time.sleep(0.5)

    ppi_data = fetch_ppi(debug=args.debug)
    time.sleep(0.5)

    shibor_data = fetch_shibor(debug=args.debug)

    package = pack_macro_advanced(bond_data, m2_data, social_data, ppi_data, shibor_data)
    filepath = save_package(package)

    logger.info("✅ 宏观高级数据采集完成")
    logger.info(f"   📦 输出文件: {filepath}")
    logger.info(f"   📊 数据类型: {list(package['contents'].keys())}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
