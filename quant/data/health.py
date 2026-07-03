"""数据健康检查 — 扫 Redis 找出异常股票

输出: logs/data_health.json
{
  "checked_at": "2026-06-09T11:30:00",
  "total_codes": 380,
  "issues": {
    "missing_kline":     ["..."],  # universe 里但无 K 线数据
    "invalid_schema":    [{code, error}],
    "price_jump":        [{code, date, prev, cur, ratio}],
    "stale":             [{code, last_date, days_ago}],  # 最后一根 K 线超过 7 天
    "incomplete_fields": [{code, missing}],
  },
  "summary": {"healthy": 350, "issues": 30}
}
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from quant.data.cache import create_cache
from quant.data.schema import validate_bar, REQUIRED_FIELDS, SchemaError

logger = logging.getLogger("health")


def run_health_check(output_path: str = None) -> Dict[str, Any]:
    cache = create_cache()
    universe = cache.get('stock:universe') or []

    report: Dict[str, Any] = {
        'checked_at': datetime.now().isoformat(timespec='seconds'),
        'total_codes': len(universe),
        'issues': {
            'missing_kline':     [],
            'invalid_schema':    [],
            'price_jump':        [],
            'stale':             [],
            'incomplete_fields': [],
        },
    }

    today = datetime.now().date()
    healthy_count = 0

    for code in universe:
        raw = cache.get(f'kline:{code}:d')
        if not raw or not isinstance(raw, list) or len(raw) == 0:
            report['issues']['missing_kline'].append(code)
            continue

        # 字段完整性 (检查首尾两根)
        sample_bar = raw[-1] if isinstance(raw[-1], dict) else {}
        missing = [f for f in REQUIRED_FIELDS if f not in sample_bar]
        if missing:
            report['issues']['incomplete_fields'].append({'code': code, 'missing': missing})
            continue

        # Schema 校验最近 10 根
        bad = None
        for bar in raw[-10:]:
            try:
                validate_bar(bar)
            except SchemaError as e:
                bad = str(e)
                break
        if bad:
            report['issues']['invalid_schema'].append({'code': code, 'error': bad[:200]})
            continue

        # 跳变检查 (最近 60 根)
        recent = raw[-60:] if len(raw) >= 60 else raw
        jumped = False
        for i in range(1, len(recent)):
            prev = float(recent[i-1].get('close', 0) or 0)
            cur = float(recent[i].get('close', 0) or 0)
            if prev <= 0 or cur <= 0:
                continue
            ratio = cur / prev
            if ratio > 1.3 or ratio < 0.7:
                report['issues']['price_jump'].append({
                    'code':  code,
                    'date':  recent[i].get('date'),
                    'prev':  round(prev, 4),
                    'cur':   round(cur, 4),
                    'ratio': round(ratio, 3),
                })
                jumped = True
                break
        if jumped:
            continue

        # 是否过期
        last_date_str = recent[-1].get('date', '')
        try:
            last_date = datetime.strptime(last_date_str, '%Y%m%d').date()
            days_ago = (today - last_date).days
            if days_ago > 7:
                report['issues']['stale'].append({
                    'code':      code,
                    'last_date': last_date_str,
                    'days_ago':  days_ago,
                })
                continue
        except ValueError:
            pass

        healthy_count += 1

    issue_total = sum(len(v) for v in report['issues'].values())
    report['summary'] = {'healthy': healthy_count, 'issues': issue_total}

    # 写出
    if output_path is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        os.makedirs(os.path.join(root, 'logs'), exist_ok=True)
        output_path = os.path.join(root, 'logs', 'data_health.json')

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    logger.info(f"Health report written: {output_path} (healthy={healthy_count}, issues={issue_total})")
    return report


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    report = run_health_check()
    s = report['summary']
    print(f"\nHealth Summary: healthy={s['healthy']} / total={report['total_codes']} (issues={s['issues']})")
    for category, items in report['issues'].items():
        if items:
            print(f"  {category}: {len(items)}")
            for item in items[:3]:
                print(f"    {item}")
            if len(items) > 3:
                print(f"    ... and {len(items)-3} more")
