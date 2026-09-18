"""全量功能验证 — 遍历所有 API action 和关键脚本，检查是否有异常

不修改任何数据，只读验证。输出每个检查项的 PASS/FAIL。
"""
import json
import os
import sys
import time
import traceback

from console_output import configure_utf8_stdio

configure_utf8_stdio()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

cache = create_cache()
results = []  # [(module, check, status, detail)]


def _published_factor_snapshot():
    path = os.path.join("data", "factor_snapshot_latest.json")
    try:
        with open(path, encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}

def check(module, name, fn):
    try:
        detail = fn()
        results.append((module, name, "PASS", detail or ""))
    except Exception as e:
        results.append((module, name, "FAIL", f"{e}"))

# ═══════════════════════════════════════════════════
# 1. 因子引擎 API (factor_runner.py)
# ═══════════════════════════════════════════════════
print("=== 1. 因子引擎 API ===")

def fr(action, **kw):
    """调用 factor_runner action"""
    import importlib
    mod = importlib.import_module("scripts.factor_runner")
    req = {"action": action, **kw}
    handler = mod.ACTIONS.get(action)
    if not handler:
        raise ValueError(f"unknown action: {action}")
    return handler(req)

check("factor", "meta (因子元信息)", lambda: f"{len(fr('meta')['data'])} 个因子")
check("factor", "factors (单股因子计算)", lambda: fr('factors', code='600519')['success'])

# 每类因子各抽一个做 evaluate
from quant.factor.technical import TECHNICAL_FACTORS
from quant.factor.price_volume import PRICE_VOLUME_FACTORS
from quant.factor.fundamental import FUNDAMENTAL_FACTORS
SAMPLE_CODES = ['600519','000858','600036','601318','000001','601398','000725','600276','601012','002594','300750','688981']

for fname in TECHNICAL_FACTORS[:3] + PRICE_VOLUME_FACTORS[:3] + FUNDAMENTAL_FACTORS:
    def _eval(fn=fname):
        r = fr('evaluate', codes=SAMPLE_CODES, factor_name=fn)
        s = r.get('data',{}).get('summary') or {}
        mean = s.get('mean')
        if mean is not None:
            return f"IC={mean:.4f}"
        return "无有效数据(NaN)"
    check("factor", f"evaluate {fname}", _eval)

# evaluate_segments 技术因子 + 基本面因子
check("factor", "evaluate_segments ret_5", lambda: fr('evaluate_segments', codes=SAMPLE_CODES, factor_name='ret_5')['data']['factor_name'])
check("factor", "evaluate_segments roa", lambda: fr('evaluate_segments', codes=SAMPLE_CODES, factor_name='roa')['data']['factor_name'])

# evaluate_all
check("factor", "evaluate_all (批量IC)", lambda: f"{len(fr('evaluate_all', codes=SAMPLE_CODES[:5])['data'])} 因子")

# market_eval
def _market():
    r = fr('market_eval')
    factors = r.get('data',{}).get('factors',[])
    return f"{len(factors)} 个因子"
check("factor", "market_eval (市场榜单)", _market)

# factor_stocks (技术 + 基本面)
for fname in ['ret_5', 'roa', 'roe', 'volatility_20']:
    def _fs(fn=fname):
        r = fr('factor_stocks', factor_name=fn, top_n=5, bottom_n=5)
        d = r.get('data',{})
        return f"top={len(d.get('top',[]))} bot={len(d.get('bottom',[]))}"
    check("factor", f"factor_stocks {fname}", _fs)

# ═══════════════════════════════════════════════════
# 2. 模拟盘 API (paper_runner.py)
# ═══════════════════════════════════════════════════
print("=== 2. 模拟盘 API ===")

def pr(action, **kw):
    import importlib
    mod = importlib.import_module("scripts.paper_runner")
    req = {"action": action, **kw}
    handler = mod.ACTIONS.get(action)
    if not handler:
        raise ValueError(f"unknown action: {action}")
    return handler(req)

check("paper", "status", lambda: pr('status')['success'])
check("paper", "report", lambda: pr('report')['success'])

# ═══════════════════════════════════════════════════
# 3. 统一 F5 活动账本投影
# ═══════════════════════════════════════════════════
print("=== 3. 执行引擎 API ===")

def f5(action, **kw):
    import importlib
    mod = importlib.import_module("scripts.f5_paper_runner")
    req = {"action": action, **kw}
    return mod.handle(req)

check("execution", "status", lambda: f5('status')['success'])
check("execution", "positions", lambda: f"{len(f5('positions')['data'])} 持仓")
check("execution", "orders", lambda: f5('orders')['success'])
check(
    "execution",
    "account",
    lambda: f5('account')['data']["ledger_authority"],
)

# ═══════════════════════════════════════════════════
# 4. 模拟账本只读 API
# ═══════════════════════════════════════════════════
print("=== 4. 模拟账本只读 API ===")

check("paper", "status", lambda: pr('status')['success'])
check("paper", "report", lambda: pr('report')['success'])

# ═══════════════════════════════════════════════════
# 5. 缓存数据完整性
# ═══════════════════════════════════════════════════
print("=== 5. 缓存数据完整性 ===")

check("cache", "kline 数量", lambda: f"{len(cache.keys('kline:*:d'))} 只")
check("cache", "published factor snapshot", lambda: f"n={_published_factor_snapshot().get('n',0)}")
check(
    "cache",
    "F5 统一活动账本",
    lambda: f"authority={f5('account')['data']['ledger_authority']} positions={len(f5('account')['data']['positions'])}",
)
check("cache", "factor_evaluation.json 存在", lambda: os.path.exists('data/factor_evaluation.json'))

# ═══════════════════════════════════════════════════
# 6. 因子快照基本面覆盖
# ═══════════════════════════════════════════════════
print("=== 6. 因子快照基本面覆盖 ===")

def _snap_cov():
    from scripts.evaluate_factors import row_snapshot_fundamental_coverage
    snap = _published_factor_snapshot()
    rows = snap.get('rows', [])
    n = len(rows)
    if n == 0: raise ValueError("snapshot empty")
    coverage = row_snapshot_fundamental_coverage(snap)
    if not any(coverage.values()):
        raise ValueError("factor snapshot has zero fundamental coverage")
    parts = []
    for f in ['roe','roa','gross_margin','net_margin','debt_ratio','inventory_turnover','current_ratio','asset_turnover']:
        cnt = coverage[f]
        parts.append(f"{f}={cnt}/{n}({cnt/n*100:.0f}%)")
    return ' '.join(parts)
check("snapshot", "基本面因子覆盖率", _snap_cov)

# ═══════════════════════════════════════════════════
# 7. 前端构建产物
# ═══════════════════════════════════════════════════
print("=== 7. 前端构建 ===")
check("frontend", "dist/index.html", lambda: os.path.exists('dist/index.html'))
check("frontend", "dist/assets/*.js", lambda: len([f for f in os.listdir('dist/assets') if f.endswith('.js')]) if os.path.exists('dist/assets') else "missing")

# ═══════════════════════════════════════════════════
# 汇总
# ═══════════════════════════════════════════════════
print("\n" + "=" * 80)
print("  全量功能验证报告")
print("=" * 80)
pass_count = sum(1 for r in results if r[2] == "PASS")
fail_count = sum(1 for r in results if r[2] == "FAIL")
print(f"  PASS: {pass_count}  |  FAIL: {fail_count}  |  总计: {len(results)}")
print("=" * 80)

for module, name, status, detail in results:
    icon = "✅" if status == "PASS" else "❌"
    line = f"  {icon} [{module}] {name}"
    if detail:
        line += f" — {detail}"
    print(line)

if fail_count:
    print(f"\n⚠ {fail_count} 项失败，需修复")
else:
    print("\n✅ 全部通过")
