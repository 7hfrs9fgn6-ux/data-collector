#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宏观高级数据采集模块（日频/最新值）
版本： V1.1
更新日期： 2026-08-23
职责： 每日采集用于宏观象限判断的日频/最新宏观数据

★ V1.1 修复（2026-08-23）：
  - M2：增加日期解析和时间排序，取最新月份数据
  - 社会融资规模：增加日期解析和时间排序，取最新月份数据
  - PPI：增加日期解析和时间排序，取最新月份数据
  - 国债收益率：增加备用接口 bond_china_yield
  - 增加数据合理性校验（M2/社融/PPI 值域检查）
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

# 导入公开库已有的签名工具
try:
    from scripts.sign import sign_data
except ImportError:
    # 如果 sign.py 不存在，定义备用签名函数
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

# 输出目录
STAGING_DIR = os.path.join(PROJECT_ROOT, "staging")

# ★ 签名密钥（从环境变量获取）
SIGNING_KEY = os.environ.get('SIGNING_KEY', '')


def get_signing_key() -> str:
    """获取签名密钥"""
    global SIGNING_KEY
    if not SIGNING_KEY:
        SIGNING_KEY = os.environ.get('SIGNING_KEY', '')
    return SIGNING_KEY


def parse_chinese_date(date_str: str) -> Optional[str]:
    """
    解析中文日期格式为 YYYY-MM
    支持格式：
      - "2008年01" -> "2008-01"
      - "202604" -> "2026-04"
      - "2026-08-23" -> "2026-08"
      - "2026年8月" -> "2026-08"
    """
    if date_str is None:
        return None
    
    date_str = str(date_str).strip()
    
    # 格式: "2008年01" 或 "2008年1月"
    match = re.search(r'(\d{4})年(\d{1,2})(?:月)?', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2).zfill(2)}"
    
    # 格式: "202604" (6位数字)
    match = re.search(r'^(\d{4})(\d{2})$', date_str)
    if match:
        return f"{match.group(1)}-{match.group(2)}"
    
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
    """
    数据合理性校验
    """
    if data_type == 'm2':
        # M2 应在 100-500 万亿元之间（中国M2约305万亿）
        return 100 <= value <= 500
    elif data_type == 'social_financing':
        # 社会融资规模存量应在 100-500 万亿元之间
        return 100 <= value <= 500
    elif data_type == 'ppi':
        # PPI 同比一般在 -10% ~ +20% 之间
        return -15 <= value <= 25
    elif data_type == 'bond_yield':
        # 国债收益率一般在 1% ~ 6% 之间
        return 1 <= value <= 6
    elif data_type == 'shibor':
        # SHIBOR 一般在 0.5% ~ 10% 之间
        return 0.5 <= value <= 10
    return True


# ============================================================
# 1. 十年期国债收益率（日频）
# ============================================================

def fetch_bond_yield() -> Optional[Dict[str, Any]]:
    """
    采集中国十年期国债收益率（日频）
    数据源：新浪财经（akshare）
    返回：{"date": "2026-08-23", "value": 2.85, "source": "sina"}
    """
    logger.info("   采集十年期国债收益率...")
    try:
        import akshare as ak
        
        # 方法1：使用 bond_gb_zh_sina
        try:
            df = ak.bond_gb_zh_sina(symbol="中国10年期国债")
            if df is not None and not df.empty:
                # 按日期排序，取最新
                date_col = None
                for col in df.columns:
                    if '日期' in col or 'date' in col.lower() or '时间' in col:
                        date_col = col
                        break
                if date_col:
                    df[date_col] = pd.to_datetime(df[date_col], errors='coerce')
                    df = df.sort_values(date_col, ascending=False)
                    latest = df.iloc[0]
                else:
                    latest = df.iloc[-1]
                
                # 获取日期
                date_val = latest.get(date_col) if date_col else None
                if date_val is None:
                    date_val = datetime.now().strftime("%Y-%m-%d")
                elif hasattr(date_val, 'strftime'):
                    date_val = date_val.strftime("%Y-%m-%d")
                else:
                    date_val = str(date_val)[:10]
                
                # 收益率列名
                value = None
                for col in ['收益率', 'yield', 'value', '收盘']:
                    if col in latest:
                        try:
                            value = float(latest[col])
                            break
                        except (ValueError, TypeError):
                            continue
                
                if value is not None and is_data_reasonable('bond_yield', value):
                    logger.info(f"   ✅ 十年期国债收益率: {value:.2f}% (日期: {date_val})")
                    return {"date": date_val, "value": round(value, 2), "source": "sina"}
        except Exception as e:
            logger.debug(f"   bond_gb_zh_sina 失败: {e}")
        
        # 方法2：使用 bond_china_yield（备用）
        try:
            df = ak.bond_china_yield(start_date="2026-01-01")
            if df is not None and not df.empty:
                # 查找 '10年' 行
                for _, row in df.iterrows():
                    term = row.get('期限') or row.get('term') or row.get('品种')
                    if term and ('10年' in str(term) or '10Y' in str(term)):
                        value = row.get('收益率') or row.get('yield') or row.get('value')
                        if value:
                            try:
                                value = float(value)
                                if is_data_reasonable('bond_yield', value):
                                    date_val = datetime.now().strftime("%Y-%m-%d")
                                    logger.info(f"   ✅ 十年期国债收益率(备用): {value:.2f}%")
                                    return {"date": date_val, "value": round(value, 2), "source": "bond_china_yield"}
                            except:
                                pass
        except Exception as e:
            logger.debug(f"   bond_china_yield 失败: {e}")
        
        # 方法3：使用 bond_zh_us_rate（作为最后备选）
        try:
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
                                        logger.info(f"   ✅ 十年期国债收益率(备选2): {value:.2f}%")
                                        return {"date": date_val, "value": round(value, 2), "source": "bond_zh_us_rate"}
                                except:
                                    pass
        except Exception as e:
            logger.debug(f"   bond_zh_us_rate 失败: {e}")
        
        logger.warning("   ⚠️ 十年期国债收益率采集失败（所有接口均失败）")
        return None
    except ImportError:
        logger.error("   ❌ akshare 未安装")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ 十年期国债收益率采集异常: {e}")
        return None


# ============================================================
# 2. M2货币供应量（最新月度）
# ============================================================

def fetch_m2() -> Optional[Dict[str, Any]]:
    """
    采集M2货币供应量（最新月度）
    数据源：东方财富（akshare）
    返回：{"date": "2026-07", "value": 305.2, "unit": "万亿元", "source": "eastmoney"}
    """
    logger.info("   采集M2货币供应量...")
    try:
        import akshare as ak
        import pandas as pd
        
        df = ak.macro_china_money_supply()
        if df is None or df.empty:
            logger.warning("   ⚠️ M2数据为空")
            return None
        
        logger.debug(f"   M2 列名: {list(df.columns)}")
        
        # 识别列名
        month_col = None
        value_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower() or '时间' in col:
                month_col = col
            if 'M2' in col and '货币' in col:
                value_col = col
        
        if month_col is None:
            month_col = df.columns[0]
        if value_col is None:
            # 尝试找包含'M2'的列
            for col in df.columns:
                if 'M2' in col:
                    value_col = col
                    break
        if value_col is None:
            value_col = df.columns[1]
        
        # 解析日期并排序
        df['_parse_date'] = df[month_col].apply(lambda x: parse_chinese_date(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])
        
        if df.empty:
            logger.warning("   ⚠️ M2日期解析失败")
            return None
        
        # 按日期排序，取最新
        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]
        
        month_val = latest.get('_parse_date')
        value = latest.get(value_col)
        
        if value is None:
            logger.warning("   ⚠️ M2值缺失")
            return None
        
        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace(',', '').replace('万亿元', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ M2值解析失败: {value}")
                return None
        
        # 数据合理性校验
        if not is_data_reasonable('m2', value):
            logger.warning(f"   ⚠️ M2值异常: {value}万亿元（预期100-500）")
            return None
        
        logger.info(f"   ✅ M2: {value:.1f}万亿元 (月份: {month_val})")
        return {"date": month_val, "value": round(value, 1), "unit": "万亿元", "source": "eastmoney"}
    except ImportError:
        logger.error("   ❌ akshare 未安装")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ M2采集异常: {e}")
        return None


# ============================================================
# 3. 社会融资规模（最新月度）
# ============================================================

def fetch_social_financing() -> Optional[Dict[str, Any]]:
    """
    采集社会融资规模（最新月度）
    数据源：商务数据中心（akshare）
    返回：{"date": "2026-07", "value": 25.8, "unit": "万亿元", "source": "data-center"}
    """
    logger.info("   采集社会融资规模...")
    try:
        import akshare as ak
        import pandas as pd
        
        df = ak.macro_china_shrzgm()
        if df is None or df.empty:
            logger.warning("   ⚠️ 社会融资规模数据为空")
            return None
        
        logger.debug(f"   社融 列名: {list(df.columns)}")
        
        month_col = None
        value_col = None
        for col in df.columns:
            if '月份' in col or 'date' in col.lower() or '时间' in col:
                month_col = col
            if '社会融资' in col or '规模' in col:
                value_col = col
        
        if month_col is None:
            month_col = df.columns[0]
        if value_col is None:
            for col in df.columns:
                if '融资' in col or '存量' in col:
                    value_col = col
                    break
        if value_col is None:
            value_col = df.columns[1]
        
        # 解析日期并排序
        df['_parse_date'] = df[month_col].apply(lambda x: parse_chinese_date(str(x)) if x else None)
        df = df.dropna(subset=['_parse_date'])
        
        if df.empty:
            logger.warning("   ⚠️ 社融日期解析失败")
            return None
        
        df['_sort_date'] = pd.to_datetime(df['_parse_date'] + '-01', errors='coerce')
        df = df.sort_values('_sort_date', ascending=False)
        latest = df.iloc[0]
        
        month_val = latest.get('_parse_date')
        value = latest.get(value_col)
        
        if value is None:
            logger.warning("   ⚠️ 社会融资规模值缺失")
            return None
        
        try:
            value = float(value)
        except (ValueError, TypeError):
            val_str = str(value).replace(',', '').replace('万亿元', '').strip()
            nums = re.findall(r'[\d.]+', val_str)
            if nums:
                value = float(nums[0])
            else:
                logger.warning(f"   ⚠️ 社会融资规模值解析失败: {value}")
                return None
        
        # 数据合理性校验
        if not is_data_reasonable('social_financing', value):
            logger.warning(f"   ⚠️ 社会融资规模值异常: {value}万亿元（预期100-500）")
            return None
        
        logger.info(f"   ✅ 社会融资规模: {value:.1f}万亿元 (月份: {month_val})")
        return {"date": month_val, "value": round(value, 1), "unit": "万亿元", "source": "data-center"}
    except ImportError:
        logger.error("   ❌ akshare 未安装")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ 社会融资规模采集异常: {e}")
        return None


# ============================================================
# 4. PPI（最新月度）
# ============================================================

def fetch_ppi() -> Optional[Dict[str, Any]]:
    """
    采集PPI（最新月度）
    数据源：东方财富（akshare）
    返回：{"date": "2026-07", "value": -0.5, "unit": "%", "source": "eastmoney"}
    """
    logger.info("   采集PPI...")
    try:
        import akshare as ak
        import pandas as pd
        
        df = ak.macro_china_ppi()
        if df is None or df.empty:
            logger.warning("   ⚠️ PPI数据为空")
            return None
        
        logger.debug(f"   PPI 列名: {list(df.columns)}")
        
        date_col = None
        value_col = None
        for col in df.columns:
            if '日期' in col or 'date' in col.lower() or '时间' in col:
                date_col = col
            if 'PPI' in col or '工业品' in col:
                value_col = col
        
        if date_col is None:
            date_col = df.columns[0]
        if value_col is None:
            for col in df.columns:
                if '同比' in col or '价格' in col:
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
        
        # 数据合理性校验（PPI可能在-10%到+20%之间）
        if not is_data_reasonable('ppi', value):
            logger.warning(f"   ⚠️ PPI值异常: {value}%（预期-15~25）")
            return None
        
        logger.info(f"   ✅ PPI: {value:+.1f}% (月份: {date_val})")
        return {"date": date_val, "value": round(value, 1), "unit": "%", "source": "eastmoney"}
    except ImportError:
        logger.error("   ❌ akshare 未安装")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ PPI采集异常: {e}")
        return None


# ============================================================
# 5. SHIBOR隔夜/1周（日频）
# ============================================================

def fetch_shibor() -> Optional[Dict[str, Any]]:
    """
    采集SHIBOR隔夜和1周利率（日频）
    数据源：金十数据中心（akshare）
    返回：{"date": "2026-08-23", "overnight": 1.85, "one_week": 1.95, "source": "jin10"}
    """
    logger.info("   采集SHIBOR...")
    try:
        import akshare as ak
        import pandas as pd
        
        df = ak.macro_china_shibor_all()
        if df is None or df.empty:
            logger.warning("   ⚠️ SHIBOR数据为空")
            return None
        
        logger.debug(f"   SHIBOR 列名: {list(df.columns)}")
        
        date_col = None
        overnight_col = None
        week_col = None
        
        for col in df.columns:
            if '日期' in col or 'date' in col.lower():
                date_col = col
            if '隔夜' in col or 'O/N' in col or 'ON' in col:
                overnight_col = col
            if '1周' in col or '1W' in col or '一周' in col:
                week_col = col
        
        if date_col is None:
            date_col = df.columns[0]
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
        except:
            pass
        
        latest = df.iloc[0]
        
        # 获取日期
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
        
        # 如果没找到特定列，尝试取数值列
        if overnight is None and week is None:
            vals = []
            for col in df.columns:
                if col != date_col:
                    try:
                        v = float(latest.get(col, 0))
                        if v > 0 and v < 20:
                            vals.append(v)
                    except:
                        pass
            if vals:
                overnight = vals[0]
                week = vals[1] if len(vals) > 1 else vals[0]
        
        if overnight is not None and overnight > 0:
            logger.info(f"   ✅ SHIBOR: 隔夜 {overnight:.2f}%, 1周 {week if week else overnight:.2f}%")
            return {
                "date": date_val,
                "overnight": round(overnight, 2),
                "one_week": round(week if week else overnight, 2),
                "source": "jin10"
            }
        else:
            logger.warning("   ⚠️ SHIBOR值异常")
            return None
    except ImportError:
        logger.error("   ❌ akshare 未安装")
        return None
    except Exception as e:
        logger.warning(f"   ⚠️ SHIBOR采集异常: {e}")
        return None


# ============================================================
# 6. 打包与签名
# ============================================================

def pack_macro_advanced(
    bond: Optional[Dict],
    m2: Optional[Dict],
    social: Optional[Dict],
    ppi: Optional[Dict],
    shibor: Optional[Dict]
) -> Dict[str, Any]:
    """将所有采集到的数据打包为统一格式，并签名"""
    logger.info("📦 开始打包宏观高级数据...")
    
    package = {
        "package_type": "macro_advanced",
        "generated_at": datetime.now().isoformat(),
        "version": "1.1",
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


# ============================================================
# 7. 保存
# ============================================================

def save_package(package: Dict[str, Any]) -> str:
    """保存打包数据到暂存区"""
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
# 8. 主入口
# ============================================================

def main():
    parser = argparse.ArgumentParser(description='采集宏观高级数据（日频/最新值）')
    parser.add_argument('--all', action='store_true', default=True, help='采集所有数据（默认）')
    parser.add_argument('--bond', action='store_true', help='仅采集国债收益率')
    parser.add_argument('--m2', action='store_true', help='仅采集M2')
    parser.add_argument('--social', action='store_true', help='仅采集社会融资规模')
    parser.add_argument('--ppi', action='store_true', help='仅采集PPI')
    parser.add_argument('--shibor', action='store_true', help='仅采集SHIBOR')
    parser.add_argument('--debug', action='store_true', help='启用调试模式（打印列名）')
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("🚀 开始采集宏观高级数据...")
    
    # 确定采集哪些数据
    if args.bond:
        types = ['bond']
    elif args.m2:
        types = ['m2']
    elif args.social:
        types = ['social']
    elif args.ppi:
        types = ['ppi']
    elif args.shibor:
        types = ['shibor']
    else:
        types = ['bond', 'm2', 'social', 'ppi', 'shibor']
    
    bond_data = None
    m2_data = None
    social_data = None
    ppi_data = None
    shibor_data = None
    
    if 'bond' in types:
        bond_data = fetch_bond_yield()
        time.sleep(0.5)
    if 'm2' in types:
        m2_data = fetch_m2()
        time.sleep(0.5)
    if 'social' in types:
        social_data = fetch_social_financing()
        time.sleep(0.5)
    if 'ppi' in types:
        ppi_data = fetch_ppi()
        time.sleep(0.5)
    if 'shibor' in types:
        shibor_data = fetch_shibor()
        time.sleep(0.5)
    
    # 打包
    package = pack_macro_advanced(bond_data, m2_data, social_data, ppi_data, shibor_data)
    
    # 保存
    filepath = save_package(package)
    
    logger.info("✅ 宏观高级数据采集完成")
    logger.info(f"   📦 输出文件: {filepath}")
    logger.info(f"   📊 数据类型: {list(package['contents'].keys())}")
    logger.info(f"   🔐 签名状态: {'✅ 已签名' if package.get('signature') else '⚠️ 未签名'}")
    
    # 如果数据质量不好，返回非0退出码
    if len(package['contents']) < 3:
        logger.warning("⚠️ 采集到的数据类型少于3个，数据质量可能有问题")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
