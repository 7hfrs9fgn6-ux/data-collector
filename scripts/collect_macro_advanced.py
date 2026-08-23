#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观高级数据采集模块（日频/最新值）- 综合修复版
版本： V1.3
更新日期： 2026-08-23
职责： 每日采集用于宏观象限判断的日频/最新宏观数据

★ V1.3 综合修复：
  - 国债收益率：使用 requests 直连新浪财经（稳定）
  - PPI：增加自动修正（定基指数→变化率）
  - 所有数据：增加合理性校验
  - 调试模式：--debug 打印数据结构

★ 数据用途：
  - pre阶段：达利欧宏观象限检测器（国债收益率、M2、PPI）
  - intraday_a/b阶段：SHIBOR资金面感知
  - night阶段：外围流动性环境判断
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

# 添加项目根目录到路径
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


def is_data_reasonable(data_type: str, value: float) -> bool:
    """
    数据合理性校验
    """
    if data_type == 'bond_yield':
        return 1.0 <= value <= 6.0
    elif data_type == 'm2':
        return 100 <= value <= 500
    elif data_type == 'social_financing':
        return 1.0 <= value <= 30.0
    elif data_type == 'ppi':
        return -15 <= value <= 25
    elif data_type == 'shibor':
        return 0.5 <= value <= 10.0
    return True


# ============================================================
# 1. 国债收益率：直接用 requests 抓取（稳定）
# ============================================================

def fetch_bond_yield() -> Optional[Dict[str, Any]]:
    """
    采集中国十年期国债收益率
    主方案：requests 直连新浪财经
    备选：akshare bond_zh_us_rate
    """
    logger.info("   采集十年期国债收益率...")

    # 主方案：requests 直连新浪财经
    try:
        import requests
        # 新浪财经国债数据接口
        url = "http://hq.sinajs.cn/list=gb_10y_chn"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            content = response.text
            # 格式: var hq_str_gb_10y_chn="2026-08-23,2.85,2.84,...";
            match = re.search(r'"([^"]+)"', content)
            if match:
                parts = match.group(1).split(',')
                if len(parts) >= 2:
                    date_str = parts[0].strip()
                    # 确保日期格式正确
                    if re.match(r'\d{4}-\d{2}-\d{2}', date_str):
                        try:
                            value = float(parts[1].strip())
                            if is_data_reasonable('bond_yield', value):
                                logger.info(f"   ✅ 十年期国债收益率: {value:.2f}% (日期: {date_str})")
                                return {
                                    "date": date_str,
                                    "value": round(value, 2),
                                    "source": "sina_direct"
                                }
                            else:
                                logger.warning(f"   ⚠️ 国债收益率值异常: {value}")
                        except ValueError:
                            logger.debug("   国债收益率值解析失败")
    except ImportError:
        logger.debug("   requests 未安装，跳过直连")
    except Exception as e:
        logger.debug(f"   新浪直连失败: {e}")

    # 备选方案1：akshare bond_zh_us_rate
    try:
        import akshare as ak
        df = ak.bond_zh_us_rate()
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                country = row.get('国家') or row.get('country')
                if country and '中国' in str(country):
                    term = row.get('期限') or row.get('term')
                    if term and ('10年' in str(term) or '10Y' in str(term)):
                        value = row.get('收益率') or row.get('yield')
                        if value:
                            try:
                                value = float(value)
                                if is_data_reasonable('bond_yield', value):
                                    date_val = datetime.now().strftime("%Y-%m-%d")
                                    logger.info(f"   ✅ 十年期国债收益率(备选): {value:.2f}%")
                                    return {
                                        "date": date_val,
                                        "value": round(value, 2),
                                        "source": "bond_zh_us_rate"
                                    }
                            except:
                                pass
    except Exception as e:
        logger.debug(f"   bond_zh_us_rate 失败: {e}")

    # 备选方案2：akshare bond_china_yield
    try:
        import akshare as ak
        df = ak.bond_china_yield(start_date="2026-01-01")
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                term = row.get('期限') or row.get('term') or row.get('品种')
                if term and ('10年' in str(term) or '10Y' in str(term)):
                    value = row.get('收益率') or row.get('yield')
                    if value:
                        try:
                            value = float(value)
                            if is_data_reasonable('bond_yield', value):
                                date_val = datetime.now().strftime("%Y-%m-%d")
                                logger.info(f"   ✅ 十年期国债收益率(备选2): {value:.2f}%")
                                return {
                                    "date": date_val,
                                    "value": round(value, 2),
                                    "source": "bond_china_yield"
                                }
                        except:
                            pass
    except Exception as e:
        logger.debug(f"   bond_china_yield 失败: {e}")

    logger.warning("   ⚠️ 十年期国债收益率采集失败（所有接口均失败）")
    return None


# ============================================================
# 2. M2货币供应量
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

        # 找数值列
        value_col = None
        for col in df.columns:
            if col != date_col and 'M2' in col:
                value_col = col
                break
        if value_col is None:
            value_col = df.columns[1]

        # 按日期排序取最新
        try:
            df['_date_parsed'] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.sort_values('_date_parsed', ascending=False)
        except Exception as e:
            logger.debug(f"   M2日期排序失败: {e}")
            # 尝试用最后一行
            pass

        latest = df.iloc[0]

        # 获取日期
        date_val = latest.get(date_col)
        if date_val is None:
            date_val = datetime.now().strftime("%Y-%m")
        elif hasattr(date_val, 'strftime'):
            date_val = date_val.strftime("%Y-%m")
        else:
            date_val = str(date_val)[:7]

        # 获取值
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

        # 判断单位
        unit = "万亿元"
        if value > 10000:
            # 可能是亿元，转为万亿元
            value = value / 10000
            unit = "万亿元"

        # 合理性校验
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
# 3. 社会融资规模
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

        value_col = None
        for col in df.columns:
            if col != date_col and ('融资' in col or '规模' in col):
                value_col = col
                break
        if value_col is None:
            value_col = df.columns[1]

        # 按日期排序取最新
        try:
            df['_date_parsed'] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.sort_values('_date_parsed', ascending=False)
        except Exception as e:
            logger.debug(f"   社融日期排序失败: {e}")

        latest = df.iloc[0]

        date_val = latest.get(date_col)
        if date_val is None:
            date_val = datetime.now().strftime("%Y-%m")
        elif hasattr(date_val, 'strftime'):
            date_val = date_val.strftime("%Y-%m")
        else:
            date_val = str(date_val)[:7]

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

        # 判断单位
        unit = "万亿元"
        if value > 100:
            # 可能是亿元，转为万亿元
            value = value / 10000
            unit = "万亿元"

        # 合理性校验
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
# 4. PPI（自动修正定基指数）
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
            if '日期' in col or 'date' in col.lower():
                date_col = col
                break
        if date_col is None:
            date_col = df.columns[0]

        value_col = None
        for col in df.columns:
            if col != date_col and ('PPI' in col or '工业品' in col):
                value_col = col
                break
        if value_col is None:
            value_col = df.columns[1]

        # 按日期排序取最新
        try:
            df['_date_parsed'] = pd.to_datetime(df[date_col], errors='coerce')
            df = df.sort_values('_date_parsed', ascending=False)
        except Exception as e:
            logger.debug(f"   PPI日期排序失败: {e}")

        latest = df.iloc[0]

        date_val = latest.get(date_col)
        if date_val is None:
            date_val = datetime.now().strftime("%Y-%m")
        elif hasattr(date_val, 'strftime'):
            date_val = date_val.strftime("%Y-%m")
        else:
            date_val = str(date_val)[:7]

        value = latest.get(value_col)
        if value is None:
            logger.warning("   ⚠️ PPI值缺失")
            return None

        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace('%', '').replace('+', '').replace('，', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ PPI值解析失败: {value}")
                return None

        # ★ 自动修正：如果值 > 20，说明是定基指数（基期=100），需要转为变化率
        if value > 20:
            value = value - 100
            logger.debug(f"   PPI: 检测到定基指数，自动修正为 {value:+.1f}%")
        elif value > 10 and value < 20:
            # 可能是异常值，尝试检查
            logger.debug(f"   PPI值在10-20之间，可能异常: {value}")

        # 合理性校验
        if not is_data_reasonable('ppi', value):
            logger.warning(f"   ⚠️ PPI值异常: {value}%")
            return None

        logger.info(f"   ✅ PPI: {value:+.1f}% (月份: {date_val})")
        return {
            "date": date_val,
            "value": round(value, 1),
            "unit": "%",
            "source": "eastmoney",
            "note": "自动修正（定基指数→变化率）" if value > 20 else None
        }
    except Exception as e:
        logger.warning(f"   ⚠️ PPI采集异常: {e}")
        return None


# ============================================================
# 5. SHIBOR
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
            if '隔夜' in col or 'O/N' in col:
                overnight_col = col
            if '1周' in col or '一周' in col or '1W' in col:
                week_col = col

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

        # 如果没找到指定列，尝试取数值列
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
        "version": "1.3",
        "contents": {}
    }

    if bond:
        package["contents"]["bond_yield"] = bond
        logger.info(f"   ✅ 包含十年期国债收益率: {bond.get('value')}%")
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
    parser.add_argument('--debug', action='store_true', help='启用调试模式（打印列名）')
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    logger.info("🚀 开始采集宏观高级数据...")
    logger.info(f"   🐞 调试模式: {args.debug}")

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
