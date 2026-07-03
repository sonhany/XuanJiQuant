"""下载全市场行业归属 (baostock 证监会行业分类) — 用于因子中性化

baostock query_stock_industry 一次返回全部5530只股票的行业，零反爬、秒级。
行业分类: 证监会行业分类 (如 J66货币金融服务、C39计算机通信制造)。

缓存: stock:industry:<code> → 行业大类 (取首字母+前2位，如 J66 → 金融)
      stock:industry_raw:<code> → 完整行业字符串

用法: python scripts/download_industry.py
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("industry")


def _industry_category(raw: str) -> str:
    """证监会行业代码 → 大类名称

    证监会分类: 字母+数字 (如 J66货币金融服务)
    取首字母作为大类 (J=金融业, C=制造业, K=房地产业...)
    """
    if not raw:
        return '未知'
    # 取字母部分作为大类 (A农L林O服务J金融K房地产C制造...)
    cat = raw[0] if raw[0].isalpha() else '其他'
    # 保留前3字符(字母+2位数字)作为中类，更细粒度
    code = raw[:3] if len(raw) >= 3 else raw
    return f'{cat}|{raw}'  # 大类字母|完整描述


def main():
    import baostock as bs
    cache = create_cache()

    logger.info("登录 baostock...")
    bs.login()

    logger.info("查询全市场行业归属...")
    rs = bs.query_stock_industry()
    if rs.error_code != '0':
        logger.error(f"查询失败: {rs.error_msg}")
        bs.logout()
        return

    rows = []
    while rs.next():
        rows.append(rs.get_row_data())

    logger.info(f"获取 {len(rows)} 只股票行业")

    ok = 0
    for row in rows:
        # row: [updateDate, code(sh.600000), code_name, industry, industryClassification]
        if len(row) < 4:
            continue
        full_code = row[1]  # sh.600000
        code = full_code.split('.')[1]  # 600000
        industry_raw = row[3]
        if industry_raw:
            cache.set(f'stock:industry:{code}', _industry_category(industry_raw))
            cache.set(f'stock:industry_raw:{code}', industry_raw)
            ok += 1

    bs.logout()
    logger.info(f"完成: {ok}/{len(rows)} 只写入行业缓存")

    # 验证: 抽样几只
    import random
    samples = random.sample([r[1].split('.')[1] for r in rows if len(r) > 3], min(5, len(rows)))
    logger.info("抽样验证:")
    for code in samples:
        ind = cache.get(f'stock:industry:{code}') or '无'
        logger.info(f"  {code}: {ind}")

    logger.info(f"行业缓存键: {len(cache.keys('stock:industry:*'))} 只")


if __name__ == '__main__':
    main()
