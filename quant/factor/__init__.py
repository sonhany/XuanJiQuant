"""Phase 2: 因子引擎

模块结构:
- technical.py: 19 个技术指标 (MA/EMA/MACD/RSI/KDJ/BOLL/ATR/CCI/WR/ROC)
- price_volume.py: 28 个量价因子 (动量/反转/波动/量价相关/资金流/换手/趋势)
- fundamental.py: 11 个基本面因子 (ROE/ROA/毛利率等，需 AKShare 财务数据)
- ic.py: IC 评估 (Rank IC + 衰减 + IR)
- engine.py: FactorEngine 主类 (批量计算 + 缓存)

数据约定:
- 输入 df 必须包含列: date, open, high, low, close, volume, amount
- 输出 df 在原列基础上追加因子列
- 所有 NaN/Inf 替换为 None (在 json 序列化时)
"""
from .engine import FactorEngine, FACTOR_CATEGORIES, ALL_FACTORS

__all__ = ["FactorEngine", "FACTOR_CATEGORIES", "ALL_FACTORS"]
