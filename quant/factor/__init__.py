"""Phase 2: 因子引擎

模块结构:
- technical.py: 19 个技术指标 (MA/EMA/MACD/RSI/KDJ/BOLL/ATR/CCI/WR/ROC)
- price_volume.py: 28 个量价因子 (动量/反转/波动/量价相关/资金流/换手/趋势)
- fundamental.py: 11 个基本面因子 (ROE/ROA/毛利率等，需 AKShare 财务数据)
- ic.py: IC 评估 (Rank IC + 衰减 + IR)
- engine.py: FactorEngine 主类 (批量计算 + 缓存)
- lens.py: FactorLens 全方位因子诊断 (分布/行业/市值/拥挤度/相关性)
- evaluation.py: 分组收益/多空/成本调整/相关性
- neutralize.py: 行业+市值中性化

数据约定:
- 输入 df 必须包含列: date, open, high, low, close, volume, amount
- 输出 df 在原列基础上追加因子列
- 所有 NaN/Inf 替换为 None (在 json 序列化时)
"""
from .engine import FactorEngine, FACTOR_CATEGORIES, ALL_FACTORS
from .lens import (
    winsorize, standardize, preprocess_factor,
    distribution_stats, industry_distribution, market_cap_distribution,
    crowding_analysis, correlation_matrix,
    factor_diagnosis, multi_factor_diagnosis,
)

__all__ = [
    "FactorEngine", "FACTOR_CATEGORIES", "ALL_FACTORS",
    "winsorize", "standardize", "preprocess_factor",
    "distribution_stats", "industry_distribution", "market_cap_distribution",
    "crowding_analysis", "correlation_matrix",
    "factor_diagnosis", "multi_factor_diagnosis",
]
