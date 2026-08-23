#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观高级数据采集模块（日频/最新值）- V1.3.4
版本： V1.3.4
更新日期： 2026-08-23

★ V1.3.4 修复：
  - 国债收益率：使用 bond_zh_us_rate 的 "中国国债收益率10年" 列
  - 该接口已成功返回数据，直接提取即可
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
from datetime import datetime
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


def parse_date_simple(s: str) -> Optional[str]:
    if s is None:
        return None
    s = str(s).strip()
    if re.match(r'^\d{6}$', s):
        return f"{s[:4]}-{s[4:6]}"
    match = re.search(r'(\d{4})年(\d{1,2})月?', s)
    if match:
        return f"{match.group(1)}-{match.group(2).zfill(2)}"
    if re.match(r'^\d{4}-\d{2}$', s):
        return s
    return None


def is_data_reasonable(data_type: str, value: float) -> bool:
    if data_type == 'm2':
        return 100 <= value <= 500
    elif data_type == 'social_financing':
        return 0.5 <= value <= 10.0
    elif data_type == 'ppi':
        return -15 <= value <= 25
    elif data_type == 'shibor':
        return 0.5 <= value <= 10.0
    elif data_type == 'bond_yield':
        return 1.0 <= value <= 6.0
    return True


# ============================================================
# ★ V1.3.4 核心修复：国债收益率 - 使用 bond_zh_us_rate
# ============================================================

def fetch_bond_yield(debug: bool = False) -> Optional[Dict[str, Any]]:
    """
    采集十年期国债收益率
    主方案：akshare bond_zh_us_rate -> "中国国债收益率10年" 列
    备选：中国债券信息网官方页面
    """
    logger.info("   采集十年期国债收益率...")
    today = datetime.now().strftime("%Y-%m-%d")

    # ============================================================
    # 方法1：akshare bond_zh_us_rate（已确认可用）
    # ============================================================
    try:
        import akshare as ak
        import pandas as pd

        if debug:
            logger.debug("   尝试 akshare bond_zh_us_rate...")

        df = ak.bond_zh_us_rate()
        if df is not None and not df.empty:
            if debug:
                logger.debug(f"   bond_zh_us_rate 列名: {list(df.columns)}")

            # ★ 直接提取 "中国国债收益率10年" 列的最新非空值
            # 该列包含完整的中国10年期国债收益率历史数据
            column_name = None
            for col in df.columns:
                if '中国国债收益率10年' in col or '中国10年期国债' in col:
                    column_name = col
                    break

            if column_name is None:
                # 如果没找到，尝试模糊匹配
                for col in df.columns:
                    if '中国' in col and '10年' in col and '国债' in col:
                        column_name = col
                        break

            if column_name:
                # 获取该列最新的非空值（从最后一行往前找）
                latest_row = None
                for idx in range(len(df) - 1, -1, -1):
                    value = df.iloc[idx].get(column_name)
                    if value is not None and pd.notna(value):
                        try:
                            value_float = float(value)
                            if is_data_reasonable('bond_yield', value_float):
                                latest_row = df.iloc[idx]
                                break
                        except (ValueError, TypeError):
                            continue

                if latest_row is not None:
                    value = latest_row.get(column_name)
                    try:
                        value = float(value)
                        # 获取日期
                        date_col = None
                        for col in df.columns:
                            if '日期' in col or 'date' in col.lower():
                                date_col = col
                                break
                        if date_col is None:
                            date_col = df.columns[0]

                        date_val = latest_row.get(date_col)
                        if date_val is None:
                            date_val = today
                        elif hasattr(date_val, 'strftime'):
                            date_val = date_val.strftime("%Y-%m-%d")
                        else:
                            date_val = str(date_val)[:10]

                        if is_data_reasonable('bond_yield', value):
                            logger.info(f"   ✅ 十年期国债收益率(bond_zh_us_rate): {value:.2f}% (日期: {date_val})")
                            return {
                                "date": date_val,
                                "value": round(value, 2),
                                "source": "bond_zh_us_rate"
                            }
                    except Exception as e:
                        logger.debug(f"   提取国债收益率失败: {e}")
            else:
                logger.debug("   未找到中国国债收益率10年列")
        else:
            logger.debug("   bond_zh_us_rate 返回空数据")
    except Exception as e:
        logger.debug(f"   bond_zh_us_rate 失败: {e}")

    # ============================================================
    # 方法2：中国债券信息网官方页面（备选）
    # ============================================================
    try:
        import requests
        from bs4 import BeautifulSoup

        url = "https://yield.chinabond.com.cn/cbweb-czb-web/czb/moreInfo"
        params = {"date": today.replace("-", ""), "locale": "cn_ZH"}
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

        if debug:
            logger.debug(f"   尝试中国债券信息网: {url}")

        response = requests.get(url, params=params, headers=headers, timeout=10)
        response.encoding = 'utf-8'

        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            tables = soup.find_all('table')
            for table in tables:
                rows = table.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        first_cell = cells[0].get_text().strip()
                        if '10年' in first_cell or '10Y' in first_cell or '10年期' in first_cell:
                            value_text = cells[1].get_text().strip()
                            match = re.search(r'([\d.]+)', value_text)
                            if match:
                                value = float(match.group(1))
                                if is_data_reasonable('bond_yield', value):
                                    logger.info(f"   ✅ 十年期国债收益率(官方): {value:.2f}%")
                                    return {
                                        "date": today,
                                        "value": round(value, 2),
                                        "source": "chinabond_official"
                                    }
    except Exception as e:
        logger.debug(f"   中国债券信息网失败: {e}")

    logger.warning("   ⚠️ 十年期国债收益率采集失败（所有方法均失败）")
    return None


# ============================================================
# 2. M2（已稳定）
# ============================================================

def fetch_m2(debug: bool = False) -> Optional[Dict[str, Any]]:
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

        date_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

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

        df['_parse_date'] = df[date_col].apply(lambda x: parse_date_simple(str(x)) if x else None)
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

        if value > 1000:
            value = value / 10000

        if not is_data_reasonable('m2', value):
            logger.warning(f"   ⚠️ M2值异常: {value}万亿元")
            return None

        logger.info(f"   ✅ M2: {value:.1f}万亿元 (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": "万亿元",
            "source": "eastmoney"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ M2采集异常: {e}")
        return None


# ============================================================
# 3. 社会融资规模（已稳定）
# ============================================================

def fetch_social_financing(debug: bool = False) -> Optional[Dict[str, Any]]:
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

        date_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        value_col = None
        for col in df.columns:
            if '社会融资规模增量' in col or '社会融资规模' in col:
                value_col = col
                break
        if value_col is None:
            value_col = df.columns[1]

        df['_parse_date'] = df[date_col].apply(lambda x: parse_date_simple(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])

        if df.empty:
            logger.warning("   ⚠️ 社融日期解析失败")
            return None

        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]

        date_val = latest.get('_parse_date')
        value = latest.get(value_col)

        if debug:
            logger.debug(f"   ★ 社融值: {value} (列: {value_col})")

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

        if value > 100:
            value = value / 10000

        if not is_data_reasonable('social_financing', value):
            logger.warning(f"   ⚠️ 社会融资规模值异常: {value:.4f}万亿元")
            return None

        logger.info(f"   ✅ 社会融资规模: {value:.1f}万亿元 (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": "万亿元",
            "source": "data-center"
        }
    except Exception as e:
        logger.warning(f"   ⚠️ 社会融资规模采集异常: {e}")
        return None


# ============================================================
# 4. PPI（已稳定）
# ============================================================

def fetch_ppi(debug: bool = False) -> Optional[Dict[str, Any]]:
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

        date_col = None
        for col in df.columns:
            if '月份' in col or '日期' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

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

        df['_parse_date'] = df[date_col].apply(lambda x: parse_date_simple(str(x)) if x else None)
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

        if value > 20:
            if '同比增长' not in value_col:
                for col in df.columns:
                    if '同比增长' in col or '同比' in col:
                        try:
                            actual_value = float(latest.get(col, 0))
                            if -15 <= actual_value <= 25:
                                value = actual_value
                                if debug:
                                    logger.debug(f"   PPI: 使用同比增长列: {value:+.1f}%")
                                break
                        except:
                            pass
                if value > 20:
                    value = value - 100

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
        "version": "1.3.4",
        "contents": {}
    }

    if bond:
        package["contents"]["bond_yield"] = bond
        logger.info(f"   ✅ 包含十年期国债收益率: {bond.get('value')}% ({bond.get('source')})")
    else:
        logger.warning("   ⚠️ 十年期国债收益率数据缺失")

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
    parser.add_argument('--debug', action='store_true', help='启用调试模式')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("🚀 开始采集宏观高级数据...")
    logger.info(f"   🐞 调试模式: {args.debug}")

    bond_data = fetch_bond_yield(debug=args.debug)
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
