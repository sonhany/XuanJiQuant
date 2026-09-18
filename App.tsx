import React, { lazy, Suspense, useEffect, useState } from 'react';
import { AppShell } from './components/AppShell';
import { LocalProfileScreen } from './components/LocalProfileScreen';
import { roleCapabilities } from './lib/workbench-state.mjs';

const AlertPanel = lazy(() => import('./components/AlertPanel'));
const DashboardPanel = lazy(() => import('./components/DashboardPanel'));
const DbPanel = lazy(() => import('./components/DbPanel'));
const ExecutionPanel = lazy(() => import('./components/ExecutionPanel'));
const FactorPanel = lazy(() => import('./components/FactorPanel'));
const MarketInformationPanel = lazy(() => import('./components/MarketInformationPanel'));
const PaperPanel = lazy(() => import('./components/PaperPanel'));
const QlibResearchPanel = lazy(() => import('./components/QlibResearchPanel'));
const RiskPanel = lazy(() => import('./components/RiskPanel'));
const StrategyPanel = lazy(() => import('./components/StrategyPanel'));

type Session = { user: string; role: string };

const rolePages: Record<string, string[]> = {
  'paper-sandbox': ['cockpit', 'db', 'factor', 'strategy', 'execution', 'paper', 'risk', 'alerts', 'jin10', 'qlib'],
  'risk-review': ['cockpit', 'execution', 'paper', 'risk', 'alerts', 'db', 'jin10'],
  research: ['cockpit', 'db', 'factor', 'strategy', 'risk', 'alerts', 'jin10', 'qlib'],
};

const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState('cockpit');
  const [session, setSession] = useState<Session | null>(() => {
    try {
      const raw = localStorage.getItem('xuanji:session');
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      return parsed?.user && parsed?.role ? { user: parsed.user, role: parsed.role } : null;
    } catch {
      return null;
    }
  });

  useEffect(() => {
    if (!session) return;
    const allowed = rolePages[session.role] || ['cockpit'];
    if (!allowed.includes(activeTab)) setActiveTab('cockpit');
  }, [activeTab, session]);

  const handleEnter = (profile: Session) => {
    localStorage.setItem('xuanji:session', JSON.stringify({ ...profile, entered_at: new Date().toISOString() }));
    setSession(profile);
    setActiveTab('cockpit');
  };

  const handleLogout = () => {
    localStorage.removeItem('xuanji:session');
    setSession(null);
    setActiveTab('cockpit');
  };

  if (!session) return <LocalProfileScreen onEnter={handleEnter} />;

  const capabilities = roleCapabilities(session.role);
  const panels: Record<string, React.ReactNode> = {
    cockpit: <DashboardPanel />,
    db: <DbPanel />,
    factor: capabilities.canViewResearch ? <FactorPanel /> : null,
    strategy: capabilities.canViewResearch ? <StrategyPanel /> : null,
    execution: <ExecutionPanel />,
    paper: <PaperPanel />,
    risk: <RiskPanel />,
    alerts: <AlertPanel />,
    jin10: <MarketInformationPanel />,
    qlib: capabilities.canViewResearch ? <QlibResearchPanel /> : null,
  };

  return (
    <AppShell
      activeTab={activeTab}
      onChange={setActiveTab}
      session={session}
      onLogout={handleLogout}
    >
      <Suspense fallback={<PanelLoading />}>
        {panels[activeTab] ?? <NoAccessPanel />}
      </Suspense>
    </AppShell>
  );
};

const PanelLoading: React.FC = () => (
  <div
    role="status"
    aria-label="页面加载中"
    style={{ minHeight: '56vh', display: 'grid', placeItems: 'center', color: '#64748B', fontSize: 13 }}
  >
    正在加载页面...
  </div>
);

const NoAccessPanel: React.FC = () => (
  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '60vh', color: '#64748B', fontSize: 14 }}>
    <div style={{ textAlign: 'center' }}>
      <div style={{ fontSize: 36, marginBottom: 12, opacity: 0.4 }}>🔒</div>
      <div>当前角色无权访问此页面</div>
      <div style={{ fontSize: 12, marginTop: 6, color: '#475569' }}>请联系管理员或切换角色</div>
    </div>
  </div>
);

export default App;
