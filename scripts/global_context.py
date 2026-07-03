"""全球实时动态采集 — 全球指数/汇率/商品 → AI risk regime 判断

安全设计:
  - 全球动态只能影响风险状态和仓位建议, 不能直接触发买入
  - trade_policy 分级: normal / reduce_only / no_new_position
  - 极端波动时自动收紧

数据源: 复用已有 Sina 指数接口 + 板块资金流 + 北向资金
持久化: global:context:latest, global:context:<YYYYMMDD>
"""
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _today() -> str:
    return datetime.now().strftime("%Y%m%d")


def _parse_sina_line(code: str, parts: list) -> dict:
    """按品种解析 Sina 行情 (不同品种字段含义不同, 不能统一解析)。

    格式参考 (实测):
      A股/港股指数 (sh/sz/hk): [0]=名称 [1]=现价 [2]=昨收 → chg=(price/prev-1)*100
      美股 (gb_):   [0]=名称 [1]=现价 [2]=涨跌幅(%) → chg 直接取
      台湾 (b_):    [0]=名称 [1]=现价 [2]=涨跌额 [3]=涨跌幅(%) → chg 取 [3]
      期货 (hf_):   [0]=现价 [2]=昨收 → chg=(price/prev-1)*100
      汇率 (fx_):   [0]=时间 [1]=买入 [2]=卖出 [5]=昨收 → 用 [2]/[5] 算 chg
    """
    if not parts or (len(parts) == 1 and not parts[0]):
        return None  # 空数据 (接口失效)

    def safe_float(v):
        try:
            return float(v) if v and v.strip() else 0
        except (ValueError, TypeError):
            return 0

    name, price, prev_close, chg_pct = code, 0, 0, 0

    if code.startswith(("sh", "sz")):
        # A股指数实时格式(实测): [0]名称 [1]今开 [2]昨收 [3]当前价 [4]高 [5]低
        # 注意: 不能按 [1]=现价 解析, 否则会把开盘价当作最新价, 全球动态显示失真。
        if len(parts) >= 4:
            name = parts[0] or code
            price = safe_float(parts[3])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
    elif code.startswith("gb_"):
        # 美股: [0]名 [1]现价 [2]=涨跌幅(%)直接给
        if len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            chg_pct = safe_float(parts[2])  # 已是百分比
            prev_close = price / (1 + chg_pct / 100) if chg_pct else price
    elif code.startswith("b_"):
        # 台湾等: [0]名 [1]现价 [2]涨跌额 [3]涨跌幅(%)
        if len(parts) >= 4:
            name = parts[0] or code
            price = safe_float(parts[1])
            chg_pct = safe_float(parts[3])
            prev_close = price - safe_float(parts[2])
    elif code.startswith("hf_"):
        # 期货: [0]现价 [2]昨收 (无名称, 由调用方汉化)
        if len(parts) >= 3:
            price = safe_float(parts[0])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
            name = ""
    elif code.startswith("fx_"):
        # 汇率: [0]时间 [1]买入 [2]卖出 [5]昨收 (无名称, 由调用方汉化)
        if len(parts) >= 6:
            price = safe_float(parts[2])  # 卖出价
            prev_close = safe_float(parts[5])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
            name = ""
    elif code.startswith("hk_") or code.startswith("rt_"):
        # 港股指数: rt_ 格式 [0]代码 [1]名称 [2]现价 [3]昨收; hk_ 常返回空
        if code.startswith("rt_") and len(parts) >= 4:
            name = parts[1] or parts[0] or code
            price = safe_float(parts[2])
            prev_close = safe_float(parts[3])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
        elif len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0
    else:
        # 兜底: 按 A股格式试
        if len(parts) >= 3:
            name = parts[0] or code
            price = safe_float(parts[1])
            prev_close = safe_float(parts[2])
            chg_pct = ((price / prev_close - 1) * 100) if prev_close > 0 else 0

    return {"name": name, "price": round(price, 4), "close": round(prev_close, 4), "prev_close": round(prev_close, 4), "chg_pct": round(chg_pct, 2)}


def _fetch_sina_indices(codes: list) -> dict:
    """通过 Sina 行情接口获取全球指数/汇率实时数据。

    按品种分别解析 (A股/美股/台湾/期货/汇率字段含义不同)。
    内置 1 次重试 (网络抖动容错): 首次失败 sleep 1s 后重试一次。
    """
    import time
    import urllib.request
    result = {}
    for attempt in range(2):  # 1 次初始 + 1 次重试
        try:
            url = f"http://hq.sinajs.cn/list={','.join(codes)}"
            req = urllib.request.Request(url, headers={"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                import re
                lines = resp.read().decode("gbk", errors="replace").split("\n")
                for line in lines:
                    m = re.match(r'var hq_str_(\S+)="(.*)"', line.strip())
                    if m and m.group(2):
                        code = m.group(1)
                        parts = m.group(2).split(",")
                        parsed = _parse_sina_line(code, parts)
                        if parsed:
                            result[code] = parsed
            if result:
                return result  # 成功拿到数据, 不再重试
        except Exception:
            if attempt == 0:
                time.sleep(1)  # 首次失败, 等 1s 重试
                continue
    return result


# 全球关键标的 Sina 代码 (已验证可用, 2026-07-03 实测)
# 注: Sina 不同品种前缀不同, _parse_sina_line 按前缀分别解析
GLOBAL_INDICES = {
    "A股大盘": ["sh000001", "sz399001", "sz399006", "sh000300"],
    "亚太": ["b_HSI", "rt_hkHSTECH", "b_TWSE", "b_NKY", "b_TPX", "b_KOSPI", "b_KOSDAQ"],   # 恒指/恒生科技/台湾/日韩
    "美股": ["gb_$ndx", "gb_dji"],                 # 纳指100/道指
    "汇率商品": ["hf_CL", "hf_GC", "fx_susdcny"],   # 原油/黄金/离岸人民币
}


def collect_global_context() -> dict:
    """采集全球实时动态, 输出 risk regime。"""
    all_codes = []
    for codes in GLOBAL_INDICES.values():
        all_codes.extend(codes)

    quotes = _fetch_sina_indices(all_codes)
    if not quotes:
        cached = cache.get("global:context:latest") or {}
        if cached:
            cached = dict(cached)
            cached["stale"] = True
            cached["error"] = "全球行情源暂不可用, 已回退最近一次缓存"
            return cached

    # 按类别组织 (商品/汇率类无中文名, 用映射汉化)
    NAME_MAP = {
        "hf_CL": "纽约原油",
        "hf_GC": "纽约黄金",
        "fx_susdcny": "离岸人民币",
    }
    categories = {}
    for cat, codes in GLOBAL_INDICES.items():
        cat_data = []
        for code in codes:
            if code in quotes:
                q = dict(quotes[code])
                if not q.get("name") or q["name"] == code:
                    q["name"] = NAME_MAP.get(code, q.get("name") or code)
                cat_data.append(q)
        categories[cat] = cat_data

    # 读取/刷新市场动态 (板块/北向)。失败时 market_data 内部会回退缓存。
    try:
        from scripts.market_data import fetch_sector_flow, fetch_northbound
        sector_flow = fetch_sector_flow()
        northbound = fetch_northbound()
    except Exception:
        sector_flow = cache.get("market:sector_flow:latest") or []
        northbound = cache.get("market:northbound:latest") or {}

    # 计算 risk regime
    risk_level = "low"
    risk_signals = []

    # A股大盘波动
    a_sh = quotes.get("sh000001", {})
    a_chg = abs(a_sh.get("chg_pct", 0))
    if a_chg > 2.0:
        risk_signals.append(f"A股大盘波动{a_chg:.1f}%")
        risk_level = "medium"

    # 美股波动
    ndx = quotes.get("gb_$ndx", {})
    ndx_chg = abs(ndx.get("chg_pct", 0))
    if ndx_chg > 3.0:
        risk_signals.append(f"纳斯达克波动{ndx_chg:.1f}%")
        risk_level = "high"

    # 汇率波动
    usdcny = quotes.get("fx_susdcny", {})
    if usdcny and abs(usdcny.get("chg_pct", 0)) > 0.5:
        risk_signals.append(f"人民币汇率波动{usdcny['chg_pct']:.2f}%")
        if risk_level == "low":
            risk_level = "medium"

    # 北向资金大幅流出
    nb_trend = northbound.get("trend", "")
    nb_flow = northbound.get("northFlow", 0)
    if nb_trend == "strong_outflow" or (isinstance(nb_flow, (int, float)) and nb_flow < -50):
        risk_signals.append(f"北向资金净流出{nb_flow}亿")
        if risk_level == "low":
            risk_level = "medium"

    # trade_policy
    if risk_level == "high":
        trade_policy = "no_new_position"
    elif risk_level == "medium":
        trade_policy = "reduce_only"
    else:
        trade_policy = "normal"

    context = {
        "collected_at": _now(),
        "date": _today(),
        "global_indices": categories,
        "northbound": northbound,
        "sector_flow_top3": sector_flow[:3],
        "risk_level": risk_level,
        "risk_signals": risk_signals,
        "trade_policy": trade_policy,
    }

    cache.set("global:context:latest", context)
    cache.set(f"global:context:{_today()}", context)
    return context


def get_status() -> dict:
    return cache.get("global:context:latest") or {"success": True, "latest": None}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="全球实时动态")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()
    if args.run:
        out = collect_global_context()
    else:
        out = get_status()
    print(json.dumps({"success": True, "data": out}, ensure_ascii=False, default=str))
