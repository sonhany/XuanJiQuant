"""Human-readable factor metadata shared by API and UI."""

from __future__ import annotations


FACTOR_METADATA: dict[str, dict[str, str]] = {
    # Technical factors
    "ema_12": {"zh": "12日指数均线", "desc": "短周期指数移动均线，用于判断短线趋势方向"},
    "ema_26": {"zh": "26日指数均线", "desc": "中周期指数移动均线，用于判断中期趋势方向"},
    "macd_dif": {"zh": "MACD快慢差", "desc": "12日与26日EMA差值，反映趋势动能变化"},
    "macd_dea": {"zh": "MACD信号线", "desc": "DIF的平滑均线，用于确认趋势信号"},
    "macd_hist": {"zh": "MACD柱强度", "desc": "DIF与DEA差值放大，反映趋势动能强弱"},
    "rsi_6": {"zh": "6日强弱", "desc": "短周期RSI，识别短线超买超卖"},
    "rsi_12": {"zh": "12日强弱", "desc": "中短周期RSI，衡量价格上涨与下跌力量"},
    "rsi_24": {"zh": "24日强弱", "desc": "中周期RSI，观察较稳定的强弱状态"},
    "kdj_k": {"zh": "KDJ快线", "desc": "随机指标K值，反映短线位置变化"},
    "kdj_d": {"zh": "KDJ慢线", "desc": "随机指标D值，平滑K值用于确认信号"},
    "kdj_j": {"zh": "KDJ敏感线", "desc": "KDJ的放大偏离项，对短线拐点更敏感"},
    "boll_mid": {"zh": "布林中轨", "desc": "20日均线，作为价格中枢参考"},
    "boll_upper": {"zh": "布林上轨", "desc": "中轨上方两倍标准差，识别上沿压力和高波动"},
    "boll_lower": {"zh": "布林下轨", "desc": "中轨下方两倍标准差，识别下沿支撑和低位偏离"},
    "atr_14": {"zh": "14日真实波幅", "desc": "平均真实波幅，衡量价格绝对波动风险"},
    "williams_r_14": {"zh": "14日威廉超买", "desc": "威廉指标，衡量价格接近区间高低点的位置"},
    "roc_10": {"zh": "10日变动率", "desc": "当前收盘价相对10日前的变化速度"},
    "cci_20": {"zh": "20日顺势指标", "desc": "价格相对典型价格均值的偏离，用于判断趋势异常"},
    "bias_20": {"zh": "20日乖离率", "desc": "收盘价相对20日均线的偏离程度"},

    # Price-volume factors
    "ret_1": {"zh": "1日动量", "desc": "最近1个交易日收益率，反映短线涨跌动量"},
    "ret_5": {"zh": "5日动量", "desc": "最近5个交易日收益率，反映周级别价格动量"},
    "ret_10": {"zh": "10日动量", "desc": "最近10个交易日收益率，反映双周价格动量"},
    "ret_20": {"zh": "20日动量", "desc": "最近20个交易日收益率，反映月度价格动量"},
    "ret_60": {"zh": "60日动量", "desc": "最近60个交易日收益率，反映季度趋势动量"},
    "reversal_3": {"zh": "3日反转", "desc": "3日收益率的反向值，用于捕捉短线回归"},
    "reversal_5": {"zh": "5日反转", "desc": "5日收益率的反向值，用于捕捉周内反转"},
    "reversal_10": {"zh": "10日反转", "desc": "10日收益率的反向值，用于捕捉双周反转"},
    "volatility_5": {"zh": "5日波动率", "desc": "5日日收益波动标准差，衡量短线风险"},
    "volatility_20": {"zh": "20日波动率", "desc": "20日日收益波动标准差，衡量月度风险"},
    "volatility_60": {"zh": "60日波动率", "desc": "60日日收益波动标准差，衡量季度风险"},
    "range_pct": {"zh": "日内振幅", "desc": "当日最高价与最低价差额相对收盘价的比例"},
    "pvcorr_5": {"zh": "5日量价相关", "desc": "5日价格收益与成交量变化的相关性"},
    "pvcorr_10": {"zh": "10日量价相关", "desc": "10日价格收益与成交量变化的相关性"},
    "pvcorr_20": {"zh": "20日量价相关", "desc": "20日价格收益与成交量变化的相关性"},
    "pvbeta_20": {"zh": "20日量价贝塔", "desc": "价格收益对成交量变化的20日回归敏感度"},
    "mfi_14": {"zh": "14日资金流强弱", "desc": "结合典型价格和成交额的资金流强弱指标"},
    "obv_slope_10": {"zh": "10日OBV斜率", "desc": "能量潮10日变化斜率，观察量能趋势"},
    "ad_slope_10": {"zh": "10日派发吸筹斜率", "desc": "A/D线10日变化斜率，观察资金吸筹或派发"},
    "vwap_dev_20": {"zh": "20日均价偏离", "desc": "收盘价相对20日成交均价的偏离程度"},
    "turnover_5": {"zh": "5日平均成交量", "desc": "最近5日成交量均值，衡量短期活跃度"},
    "turnover_20": {"zh": "20日平均成交量", "desc": "最近20日成交量均值，衡量月度活跃度"},
    "vol_ratio_5": {"zh": "5日量比", "desc": "当前成交量相对20日均量的倍数"},
    "amt_ratio_5": {"zh": "5日成交额比", "desc": "当前成交额相对5日平均成交额的倍数"},
    "trend_strength": {"zh": "趋势强度", "desc": "20日均线相对60日均线的位置，衡量中期趋势"},
    "gap_pct": {"zh": "跳空幅度", "desc": "今日开盘价相对昨日收盘价的缺口比例"},
    "intraday_ret": {"zh": "日内收益", "desc": "当日收盘价相对开盘价的收益"},
    "overnight_ret": {"zh": "隔夜收益", "desc": "今日开盘价相对昨日收盘价的收益"},

    # Fundamental factors
    "roe": {"zh": "净资产收益率", "desc": "净利润相对净资产的收益能力"},
    "roa": {"zh": "总资产收益率", "desc": "净利润相对总资产的收益能力"},
    "gross_margin": {"zh": "毛利率", "desc": "主营业务毛利水平，衡量产品盈利空间"},
    "net_margin": {"zh": "净利率", "desc": "净利润率，衡量最终盈利能力"},
    "revenue_growth": {"zh": "营收增长率", "desc": "营业收入同比或环比增长能力"},
    "profit_growth": {"zh": "利润增长率", "desc": "净利润增长能力"},
    "debt_ratio": {"zh": "资产负债率", "desc": "负债相对资产比例，衡量杠杆风险"},
    "current_ratio": {"zh": "流动比率", "desc": "流动资产覆盖流动负债的能力"},
    "inventory_turnover": {"zh": "存货周转率", "desc": "存货周转效率，衡量经营效率"},
    "receivable_turnover": {"zh": "应收周转率", "desc": "应收账款回收效率"},
    "asset_turnover": {"zh": "总资产周转率", "desc": "资产创造收入的效率"},
}


def factor_chinese_name(factor_name: str) -> str:
    meta = FACTOR_METADATA.get(factor_name) or {}
    return meta.get("zh") or factor_name


def factor_description(factor_name: str) -> str:
    meta = FACTOR_METADATA.get(factor_name) or {}
    return meta.get("desc") or ""
