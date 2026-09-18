import assert from 'node:assert/strict';
import fs from 'node:fs';

const app = fs.readFileSync('App.tsx', 'utf8');
const heavyPanels = [
  'AlertPanel',
  'DashboardPanel',
  'DbPanel',
  'ExecutionPanel',
  'FactorPanel',
  'MarketInformationPanel',
  'PaperPanel',
  'QlibResearchPanel',
  'RiskPanel',
  'StrategyPanel',
];

for (const panel of heavyPanels) {
  assert(
    app.includes(`const ${panel} = lazy(() => import('./components/${panel}'))`),
    `${panel} must be split from the initial application bundle`,
  );
  assert(
    !app.includes(`import ${panel} from './components/${panel}'`),
    `${panel} must not retain a synchronous import`,
  );
}
assert(app.includes('<Suspense fallback={<PanelLoading />}>' ), 'lazy panels must expose a stable loading state');

console.log('P1 bundle splitting tests passed');
