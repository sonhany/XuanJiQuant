import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync('components/StrategyPanel.tsx', 'utf8');
const html = fs.readFileSync('index.html', 'utf8');

for (const label of [
  'F4 策略与组合验证',
  '仅供研究',
  '样本外窗口',
  '数据门禁',
  '成本压力',
  '容量约束',
  '目标行业上限',
  '候选硬上限',
  '持有期行业峰值',
  '1.5 倍成本',
  '正超额窗口占比低于 60%',
  '双倍成本下超额收益不为正',
  'f4_blocked',
  'pit_manifest_incomplete',
  "action: 'research_selection'",
  '每日因子/选股日',
  '最新完成 F4 证据日',
  '历史 F4 证据门禁',
  'PIT 数据可用日',
  '当前重验准备状态',
  '事件补跑',
  '每日研究选股组合',
  '不构成交易信号',
  'research_reason',
  'target_weight',
  'reference_close',
  '正在更新目标日期',
  '当前展示上一完整版本',
  'freshness_warning',
  '研究选股已过期',
  '候选数量',
  '逐窗口胜出规格',
  '已穷尽，等待下一数据版本',
  'f4_rejected_exhausted',
  'F5 实验模拟准入',
  '24 个预登记候选',
  '候选族',
  '验证胜出窗口',
  '1.0 倍成本',
  '2.0 倍成本',
  '研究结果，不代表已获交易权限',
]) {
  assert(source.includes(label), `F4 strategy surface must include: ${label}`);
}

assert(!source.includes('snapshot_proxy'), 'retired snapshot-proxy scan must not remain in the F4 surface');
assert(!source.includes('自动晋升生产'), 'F4 surface must not claim automatic production promotion');
assert(!source.includes('自动交易'), 'F4 surface must not claim automatic trading authority');
assert(!source.includes('不能晋升或执行'), 'F4 rejection must not be presented as a blanket ban on F5 experimental simulation');
assert(!source.includes('/ 规则 10%'), 'candidate factory must not display the retired Top20 single-name cap');
assert(!html.includes('AI 自主量化交易系统'), 'retired Agent identity must not remain in the browser title');
assert(source.includes("stressMetrics['2.0']"), '2.0 cost display must bind the verified third stress scenario');

console.log('F4 strategy UI contract tests passed');
