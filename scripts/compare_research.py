"""对比中性化前后的因子 IC，以及理想化 vs 真实回测的策略表现。

输出一份 markdown 报告到 data/research_comparison.md，量化"修真实性 + 加中性化"
对一套因子选股系统的影响。典型发现:
  - 中性化后 IC 会下降 (因为剥掉了风格 beta)，但保留下来的才是纯 alpha
  - 真实回测年化收益会显著低于理想化 (涨跌停+成本吃掉很大一块)

用法: python scripts/compare_research.py
前置: factor_evaluation.json + factor_evaluation_neutral.json +
      strategy_scan.json + strategy_scan_realistic.json 都已生成
"""
import json
import logging
import os
import sys
import time

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s', handlers=[logging.StreamHandler(sys.stdout)])
logger = logging.getLogger("compare")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, 'data')
FILES = {
    'ic_raw':      os.path.join(DATA, 'factor_evaluation.json'),
    'ic_neutral':  os.path.join(DATA, 'factor_evaluation_neutral.json'),
    'scan_ideal':  os.path.join(DATA, 'strategy_scan.json'),
    'scan_real':   os.path.join(DATA, 'strategy_scan_realistic.json'),
}
OUT_MD = os.path.join(DATA, 'research_comparison.md')


def load_json(path):
    if not os.path.exists(path):
        return None
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def fmt(x, pct=False, signed=False):
    if x is None:
        return 'N/A'
    if pct:
        return f"{x:+.2f}%" if signed else f"{x:.2f}%"
    return f"{x:+.4f}" if signed else f"{x:.4f}"


def compare_ic(ic_raw, ic_neutral):
    """生成因子 IC 对比表 (理想 vs 中性化)。"""
    if not ic_raw or not ic_neutral:
        return "（缺少 IC 数据文件，跳过）\n"
    raw_map = {f['factor']: f for f in ic_raw.get('factors', [])}
    neu_map = {f['factor']: f for f in ic_neutral.get('factors', [])}
    # 按 |IC_1d 原始| 降序
    order = sorted(raw_map.values(), key=lambda x: x.get('abs_ic_1d', 0), reverse=True)

    lines = []
    lines.append("### 因子 IC 对比：原始 vs 中性化 (行业+市值)\n")
    lines.append("> 中性化后 IC 下降属正常：剥掉的是风格 beta，保留下来的才是纯 alpha。\n")
    lines.append("> 一个因子如果中性化后 IC 大幅塌缩，说明它之前只是在选某个行业/大小盘。\n\n")
    lines.append("| 因子 | IC_1d 原始 | IC_1d 中性化 | 变化 | IR_1d 原始 | IR_1d 中性化 | 解读 |")
    lines.append("|------|-----------|-------------|------|-----------|-------------|------|")
    n_collapsed = 0
    for r in order[:15]:
        fn = r['factor']
        n = neu_map.get(fn, {})
        ic_r = r.get('ic_1d', 0)
        ic_n = n.get('ic_1d', 0)
        ir_r = r.get('ir_1d', 0)
        ir_n = n.get('ir_1d', 0)
        delta = ic_n - ic_r
        # 解读: 中性化后 IC 衰减超过 50% 视为"风格驱动"
        if abs(ic_r) > 1e-6:
            decay_ratio = abs(delta) / abs(ic_r)
        else:
            decay_ratio = 0
        if decay_ratio > 0.5:
            tag = '⚠️ 风格驱动'
            n_collapsed += 1
        elif decay_ratio > 0.2:
            tag = '部分风格'
        else:
            tag = '✓ 纯 alpha'
        lines.append(
            f"| `{fn}` | {fmt(ic_r, signed=True)} | {fmt(ic_n, signed=True)} | "
            f"{fmt(delta, signed=True)} | {fmt(ir_r, signed=True)} | {fmt(ir_n, signed=True)} | {tag} |"
        )
    lines.append("")
    lines.append(f"**结论**：Top 15 因子中有 **{n_collapsed} 个** 在中性化后 IC 衰减 >50%，"
                 "说明它们的预测力主要来自行业/市值暴露，而非真正的横截面选股能力。\n")
    return "\n".join(lines) + "\n"


def compare_scan(scan_ideal, scan_real):
    """生成策略回测对比表 (理想 vs 真实)。"""
    if not scan_ideal or not scan_real:
        return "（缺少策略扫描数据文件，跳过）\n"
    ideal_map = {s['factor']: s for s in scan_ideal.get('strategies', [])}
    real_map = {s['factor']: s for s in scan_real.get('strategies', [])}
    # 按理想化年化降序
    order = sorted(ideal_map.values(), key=lambda x: x.get('annual_return_pct', 0), reverse=True)

    lines = []
    lines.append("### 策略回测对比：理想化 vs 真实约束\n")
    lines.append("> 真实约束 = 涨跌停拒绝成交 + 单边 0.15% 交易成本 (印花税+佣金+滑点)。\n")
    lines.append("> 真实年化大幅下降是符合预期的——理想化回测总是高估收益。\n\n")
    lines.append("| 策略 | 方向 | 年化(理想) | 年化(真实) | 收益折损 | 夏普(理想) | 夏普(真实) | 涨停拒绝 |")
    lines.append("|------|------|-----------|-----------|---------|-----------|-----------|---------|")
    for s in order:
        fn = s['factor']
        r = real_map.get(fn, {})
        a_i = s.get('annual_return_pct', 0)
        a_r = r.get('annual_return_pct', 0)
        sh_i = s.get('sharpe', 0)
        sh_r = r.get('sharpe', 0)
        drag = a_i - a_r
        skips = r.get('limit_skips', 0)
        lines.append(
            f"| `{fn}` | {s.get('direction','')} | {fmt(a_i, pct=True, signed=True)} | "
            f"{fmt(a_r, pct=True, signed=True)} | {fmt(drag, pct=True, signed=True)} | "
            f"{fmt(sh_i, signed=True)} | {fmt(sh_r, signed=True)} | {skips} |"
        )
    lines.append("")
    # 整体折损统计
    if order:
        ideal_avg = sum(s.get('annual_return_pct', 0) for s in order) / len(order)
        real_vals = [real_map.get(s['factor'], {}).get('annual_return_pct', 0) for s in order]
        real_avg = sum(real_vals) / len(real_vals) if real_vals else 0
        lines.append(f"**结论**：平均年化从理想化的 **{ideal_avg:+.1f}%** 降到真实的 **{real_avg:+.1f}%**，"
                     f"交易摩擦+涨跌停吃掉约 **{ideal_avg - real_avg:.1f} 个百分点**。\n")
    return "\n".join(lines) + "\n"


def main():
    logger.info("=== 研究对比报告生成 ===")
    ic_raw = load_json(FILES['ic_raw'])
    ic_neutral = load_json(FILES['ic_neutral'])
    scan_ideal = load_json(FILES['scan_ideal'])
    scan_real = load_json(FILES['scan_real'])

    missing = [k for k, v in FILES.items() if not os.path.exists(v)]
    if missing:
        logger.warning(f"缺少文件: {missing}")
        logger.warning("请先运行: evaluate_factors.py [--neutralize], scan_strategies.py [--realistic]")

    md = []
    md.append("# 量化研究对比报告\n")
    md.append(f"生成时间: {time.strftime('%Y-%m-%d %H:%M')}\n")
    md.append("本报告对比两组成对实验，量化「修回测真实性 + 加因子中性化」对系统的影响。\n\n")
    md.append("---\n\n")

    if ic_raw:
        md.append(f"**原始 IC 评估**：{ic_raw.get('n_stocks')} 只股票，{len(ic_raw.get('factors',[]))} 个因子，"
                  f"评估时间 {ic_raw.get('evaluated_at')}\n")
    if ic_neutral:
        md.append(f"**中性化 IC 评估**：{ic_neutral.get('n_stocks')} 只股票，{len(ic_neutral.get('factors',[]))} 个因子，"
                  f"评估时间 {ic_neutral.get('evaluated_at')}\n\n")

    md.append(compare_ic(ic_raw, ic_neutral))
    md.append("---\n\n")
    md.append(compare_scan(scan_ideal, scan_real))

    md.append("---\n\n")
    md.append("### 方法论说明\n\n")
    md.append("- **因子中性化**：对每个截面，先用行业均值去均值，再对 log(成交额) 做 OLS 回归取残差。"
              "残差就是去除了「它是哪个行业、它是大盘还是小盘」之后的纯选股信号。\n")
    md.append("- **涨跌停拒绝**：当日收盘价触及涨跌停价 (含 0.2% 容差) 或一字板时，买/卖单被拒绝。"
              "主板 10%、ST 5%、科创/创业 20%、北交 30%。\n")
    md.append("- **交易成本**：单边 0.15% = 印花税 0.05% (卖出) + 佣金 0.03% + 滑点 0.05%。每次调仓扣一次。\n")
    md.append("- **注意**：本系统为研究/学习级别，真实交易还需考虑冲击成本、T+1、停牌、分红除权等更多细节。\n")

    with open(OUT_MD, 'w', encoding='utf-8') as f:
        f.write("\n".join(md))
    logger.info(f"报告已生成: {OUT_MD}")

    # 控制台简报
    print("\n" + "=" * 65)
    print("  研究对比简报")
    print("=" * 65)
    if ic_raw and ic_neutral:
        raw_top = ic_raw['factors'][0]
        neu_top = next((f for f in ic_neutral['factors']), None)
        if raw_top and neu_top:
            print(f"  原始最强因子: {raw_top['factor']} IC={raw_top['ic_1d']:+.4f}")
            # 找对应的中性化 IC
            neu_match = next((f for f in ic_neutral['factors'] if f['factor'] == raw_top['factor']), None)
            if neu_match:
                print(f"  中性化后    : {neu_match['ic_1d']:+.4f} (Δ={neu_match['ic_1d']-raw_top['ic_1d']:+.4f})")
    if scan_ideal and scan_real:
        bi = scan_ideal['strategies'][0] if scan_ideal.get('strategies') else None
        if bi:
            br = next((s for s in scan_real.get('strategies', []) if s['factor'] == bi['factor']), None)
            if br:
                print(f"  最佳策略 [{bi['factor']}]:")
                print(f"    理想年化: {bi['annual_return_pct']:+.1f}% → 真实年化: {br['annual_return_pct']:+.1f}%")
    print("=" * 65)


if __name__ == '__main__':
    main()
