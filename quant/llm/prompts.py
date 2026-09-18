"""LLM 提示词模板 — 策略生成/因子挖掘/回测解读。

设计原则:
  - 所有模板用中文 (用户语言)
  - 严格约束输出格式 (JSON/代码块)
  - 注入项目上下文 (因子列表/配置/数据特征)
"""

FACTOR_DISCOVERY_PROMPT = """你是一位 A 股量化因子研究专家。

当前因子库包含以下 {n_factors} 个因子:
{factor_list}

请基于以上因子库，建议 5 个尚未覆盖的 alpha 因子方向。
每个因子需包含:
1. name: 英文因子名 (snake_case)
2. category: 分类 (technical/price_volume/fundamental/sentiment/alternative)
3. description: 中文描述
4. formula: 计算公式或逻辑 (伪代码)
5. expected_ic_direction: 预期 IC 方向 (positive/negative)
6. rationale: 经济学/金融学原理解释

请以 JSON 数组格式输出，不要包含其他文本。"""

STRATEGY_GENERATION_PROMPT = """你是一位 A 股量化策略开发专家。

请根据以下条件生成一个完整的量化策略:
- 因子: {factor_names}
- 持仓周期: {hold_days} 天
- 股票池: A 股全市场
- 约束: T+1, 涨跌停限制, 100 股整手

策略需要包含:
1. 信号生成逻辑 (何时买入/卖出)
2. 仓位管理 (权重分配)
3. 风控规则 (止损/止盈)

请以 Python 函数格式输出，函数签名:
def generate_signals(df: pd.DataFrame) -> pd.Series
输入 df 包含 [date, open, high, low, close, volume, amount, factor1, factor2, ...]
输出 Series 为每日目标权重 (0~1)。"""

BACKTEST_INTERPRET_PROMPT = """你是一位量化策略分析师。请分析以下回测结果并给出专业解读:

策略名称: {strategy_name}
总收益: {total_return:.2%}
年化收益: {annual_return:.2%}
夏普比率: {sharpe:.2f}
最大回撤: {max_drawdown:.2%}
胜率: {win_rate:.2%}
换手率: {turnover:.4f}

{extra_metrics}

请从以下维度分析:
1. 策略表现总结 (2-3 句)
2. 优势和亮点
3. 潜在风险和不足
4. 改进建议 (具体可操作)
5. 适合的市场环境

请用中文输出，控制在 300 字以内。"""

FACTOR_ADVICE_PROMPT = """你是一位因子分析师。当前因子评估结果:
{factor_report}

请分析:
1. 哪些因子 IC 最强？为什么？
2. 哪些因子之间高度相关？建议保留哪个？
3. 哪些因子在特定行业/市值分层中表现更好？
4. 是否存在因子拥挤风险？
5. 因子组合建议 (权重分配)

请用中文输出，控制在 200 字以内。"""
