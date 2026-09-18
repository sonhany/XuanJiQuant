import fs from 'fs';
import assert from 'assert';

assert(fs.existsSync('scripts/qlib_schedule.py'), 'Qlib schedule entry must exist');
const source = fs.readFileSync('scripts/qlib_schedule.py', 'utf8');

assert(source.includes('now.weekday() == 5'), 'Qlib weekly retraining must be Saturday-only');
assert(source.includes('is_intraday_window'), 'Qlib schedule must refuse heavy intraday execution');
assert(source.includes('collect_six_years'), 'weekly pipeline must incrementally complete the six-year dataset');
assert(source.includes('export_six_years'), 'weekly pipeline must export the gated six-year dataset');
assert(source.includes('workflow_baseline'), 'weekly pipeline must run the fixed official baseline');
assert(!source.includes('"approved"'), 'scheduler must never promote beyond candidate');
assert(source.includes('workflow_run_ids'), 'scheduler must preserve exact Recorder workflow identities');
assert(source.includes('monthly_pit_refresh'), 'scheduler must define monthly PIT refresh');
assert(source.includes('quarterly_walk_forward'), 'scheduler must define quarterly walk-forward training');
assert(source.includes('quality_six_years'), 'quarterly training must require the six-year quality gate');
assert(source.includes('schedule_cycle_succeeded'), 'only complete cycles may increment schedule success');
assert(source.includes('schedule_cycle_failed'), 'incomplete cycles must be audited as failures');
assert(source.includes('no_op'), 'no-new-trading-day cycles must be explicit no-ops');
assert(source.includes('qlib_official') && source.includes('xuanji_ashare'), 'both backtest engines are required');

console.log('qlib schedule contract tests passed');
