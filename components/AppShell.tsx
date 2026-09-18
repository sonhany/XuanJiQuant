import React, { useEffect, useMemo, useState } from 'react';
import {
  BarChart3,
  Bell,
  Bot,
  BrainCircuit,
  ChevronLeft,
  Database,
  LayoutDashboard,
  LogOut,
  Menu,
  Radio,
  Shield,
  X,
  Zap,
  Cpu,
} from 'lucide-react';
import { roleCapabilities } from '../lib/workbench-state.mjs';
import xuanjiSymbol from '../public/branding/logo_symbol.svg';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';

type Session = { user: string; role: string };
type IndexData = { code: string; name: string; price: number; close: number; chg_pct?: number };

const WORKSPACES = [
  {
    label: '决策中心',
    items: [{ key: 'cockpit', label: '投资驾驶舱', icon: LayoutDashboard }],
  },
  {
    label: '策略研究',
    capability: 'canViewResearch',
    items: [
      { key: 'factor', label: '因子研究', icon: BarChart3 },
      { key: 'strategy', label: '策略运行', icon: BrainCircuit },
      { key: 'qlib', label: 'Qlib 实验', icon: Cpu },
    ],
  },
  {
    label: '交易与组合',
    items: [
      { key: 'execution', label: '模拟执行', icon: Zap },
      { key: 'paper', label: '模拟组合', icon: Bot },
    ],
  },
  {
    label: '风险与审计',
    items: [
      { key: 'risk', label: '风险监控', icon: Shield },
      { key: 'alerts', label: '告警中心', icon: Bell },
    ],
  },
  {
    label: '数据与系统',
    items: [
      { key: 'db', label: '市场数据', icon: Database },
      { key: 'jin10', label: '市场资讯', icon: Radio },
    ],
  },
];

const roleNames: Record<string, string> = {
  'paper-sandbox': '模拟盘操作员',
  'risk-review': '风险审阅员',
  research: '策略研究员',
};

const LiveIndexBar: React.FC = () => {
  const [indices, setIndices] = useState<IndexData[]>([]);
  useEffect(() => {
    let active = true;
    const load = async () => {
      try {
        const response = await fetch(`${API_BASE}/api/market/indices`);
        const payload = await response.json();
        if (active && payload.success && Array.isArray(payload.data)) setIndices(payload.data);
      } catch {
        if (active) setIndices([]);
      }
    };
    load();
    const timer = window.setInterval(load, 15_000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);

  return (
    <div className="workbench-index-bar">
      {indices.length === 0 ? <span className="index-muted">行情连接中</span> : null}
      {indices.slice(0, 8).map((item) => {
        const pct = Number.isFinite(item.chg_pct)
          ? Number(item.chg_pct)
          : item.close ? ((item.price - item.close) / item.close) * 100 : 0;
        const color = pct > 0 ? '#F87171' : pct < 0 ? '#4ADE80' : '#94A3B8';
        return (
          <div className="index-item" key={item.code}>
            <span>{item.name}</span>
            <strong>{Number(item.price || 0).toFixed(2)}</strong>
            <em style={{ color }}>{pct > 0 ? '+' : ''}{pct.toFixed(2)}%</em>
          </div>
        );
      })}
    </div>
  );
};

export const AppShell: React.FC<{
  activeTab: string;
  onChange: (key: string) => void;
  session: Session;
  onLogout: () => void;
  children: React.ReactNode;
}> = ({ activeTab, onChange, session, onLogout, children }) => {
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const capabilities = useMemo(() => roleCapabilities(session.role), [session.role]);
  const workspaces = WORKSPACES.filter((group) => !group.capability || capabilities[group.capability]);
  const activeNavigationLabel = workspaces
    .flatMap((group) => group.items)
    .find((item) => item.key === activeTab)?.label || '工作台';

  const navigate = (key: string) => {
    onChange(key);
    setMobileOpen(false);
  };

  const renderNavContent = (navCollapsed: boolean, allowCollapse: boolean) => (
    <>
      <div className="shell-brand">
        <img src={xuanjiSymbol} alt="璇玑" />
        {!navCollapsed ? <div><strong>璇玑</strong><span>XUANJI QUANT</span></div> : null}
      </div>
      <div className="shell-nav-scroll">
        {workspaces.map((group) => (
          <section className="nav-group" key={group.label}>
            {!navCollapsed ? <div className="nav-group-label">{group.label}</div> : null}
            {group.items.map(({ key, label, icon: Icon }) => (
              <button
                type="button"
                className={`nav-item ${activeTab === key ? 'active' : ''}`}
                key={key}
                onClick={() => navigate(key)}
                title={navCollapsed ? label : undefined}
              >
                <Icon />
                {!navCollapsed ? <span>{label}</span> : null}
              </button>
            ))}
          </section>
        ))}
      </div>
      {!navCollapsed ? (
        <div className="sidebar-profile">
          <div>
            <strong>{session.user}</strong>
            <span>{roleNames[session.role] || session.role}</span>
          </div>
          <button type="button" onClick={onLogout} title="退出当前本地身份" aria-label="退出当前本地身份">
            <LogOut />
          </button>
        </div>
      ) : (
        <button className="sidebar-logout-collapsed" type="button" onClick={onLogout} title="退出当前本地身份" aria-label="退出当前本地身份">
          <LogOut />
        </button>
      )}
      {allowCollapse ? (
        <button type="button" className="collapse-button" onClick={() => setCollapsed((value) => !value)}>
          <ChevronLeft style={{ transform: navCollapsed ? 'rotate(180deg)' : undefined }} />
          {!navCollapsed ? <span>收起导航</span> : null}
        </button>
      ) : null}
    </>
  );

  return (
    <div className="workbench-root">
      <style>{`
        * { box-sizing: border-box; }
        html, body, #root { margin: 0; min-width: 0; min-height: 100%; background: #0B0F1A; }
        body { overflow: hidden; }
        button, input, select, textarea { font: inherit; }
        .workbench-root {
          --font-page-title: 20px;
          --font-page-title-mobile: 18px;
          --font-kpi: 24px;
          --font-kpi-mobile: 22px;
          --font-section: 14px;
          --font-body: 13px;
          --font-meta: 12px;
          --text-primary: #E2E8F0;
          --text-secondary: #CBD5E1;
          --text-muted: #94A3B8;
          --text-subtle: #718096;
          --text-disabled: #526076;
          height: 100dvh;
          display: flex;
          flex-direction: column;
          color: var(--text-primary);
          background: #0B0F1A;
          font-size: var(--font-body);
          line-height: 1.5;
          font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif;
        }
        .mobile-command-bar { display: none; }
        .mobile-command-title { min-width: 0; overflow: hidden; color: #CBD5E1; font-size: var(--font-section); font-weight: 700; text-overflow: ellipsis; white-space: nowrap; }
        .mobile-menu-button { width: 38px; height: 38px; display: inline-flex; align-items: center; justify-content: center; flex: 0 0 auto; border: 1px solid #334155; border-radius: 7px; color: #E2E8F0; background: #111827; cursor: pointer; }
        .mobile-menu-button svg { width: 16px; height: 16px; }
        .workbench-index-bar { min-height: 34px; display: flex; align-items: center; gap: 22px; padding: 0 16px; background: #0B0F1A; border-bottom: 1px solid #1E293B; overflow-x: auto; scrollbar-width: none; }
        .index-item { display: flex; align-items: center; gap: 7px; flex: 0 0 auto; white-space: nowrap; font-size: var(--font-body); color: #94A3B8; }
        .index-item strong, .index-item em { font-family: "JetBrains Mono", Consolas, monospace; font-style: normal; }
        .index-item strong { font-size: var(--font-body); color: #E2E8F0; }
        .index-muted { color: var(--text-muted); font-size: var(--font-body); }
        .shell-body { min-height: 0; flex: 1; display: flex; }
        .shell-sidebar { width: ${collapsed ? '64px' : '208px'}; flex: 0 0 ${collapsed ? '64px' : '208px'}; display: flex; flex-direction: column; background: #0D1422; border-right: 1px solid #1E293B; transition: width 160ms ease, flex-basis 160ms ease; }
        .shell-brand { height: 52px; display: flex; align-items: center; gap: 10px; padding: 0 13px; border-bottom: 1px solid #1E293B; }
        .shell-brand img { width: 34px; height: 34px; flex: 0 0 auto; }
        .shell-brand strong, .shell-brand span { display: block; white-space: nowrap; }
        .shell-brand strong { font-size: 14px; color: #F8FAFC; }
        .shell-brand span { margin-top: 2px; font-size: 11px; color: #D4A531; }
        .shell-nav-scroll { min-height: 0; flex: 1; overflow-y: auto; padding: 8px; }
        .nav-group { margin-bottom: 10px; }
        .nav-group-label { padding: 7px 9px 5px; color: var(--text-subtle); font-size: var(--font-meta); font-weight: 800; }
        .nav-item { width: 100%; height: 38px; display: flex; align-items: center; justify-content: ${collapsed ? 'center' : 'flex-start'}; gap: 9px; padding: 0 ${collapsed ? '0' : '10px'}; border: 0; border-radius: 6px; color: var(--text-muted); background: transparent; cursor: pointer; text-align: left; }
        .nav-item:hover { color: #D8E2EE; background: #151F2E; }
        .nav-item.active { color: #F8FAFC; background: #172235; box-shadow: inset 2px 0 0 #38BDF8; }
        .nav-item svg { width: 15px; height: 15px; flex: 0 0 auto; }
        .nav-item span { font-size: var(--font-body); font-weight: 650; white-space: nowrap; }
        .sidebar-profile { display: flex; align-items: center; gap: 8px; margin: 0 8px; padding: 10px; border-top: 1px solid #1E293B; }
        .sidebar-profile > div { min-width: 0; flex: 1; }
        .sidebar-profile strong, .sidebar-profile span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .sidebar-profile strong { color: var(--text-secondary); font-size: var(--font-body); }
        .sidebar-profile span { margin-top: 3px; color: var(--text-muted); font-size: var(--font-meta); }
        .sidebar-profile button, .sidebar-logout-collapsed { display: inline-flex; align-items: center; justify-content: center; border: 0; color: var(--text-muted); background: transparent; cursor: pointer; }
        .sidebar-profile button { width: 28px; height: 28px; flex: 0 0 auto; border-radius: 5px; }
        .sidebar-profile button:hover, .sidebar-logout-collapsed:hover { color: #E2E8F0; background: #172235; }
        .sidebar-profile svg, .sidebar-logout-collapsed svg { width: 14px; height: 14px; }
        .sidebar-logout-collapsed { width: 40px; height: 36px; margin: 0 auto; border-radius: 6px; }
        .collapse-button { height: 42px; display: flex; align-items: center; justify-content: ${collapsed ? 'center' : 'flex-start'}; gap: 8px; margin: 8px; padding: 0 10px; border: 1px solid #223047; border-radius: 6px; color: var(--text-muted); background: #101827; cursor: pointer; }
        .collapse-button svg { width: 14px; height: 14px; }
        .collapse-button span { font-size: var(--font-meta); }
        .shell-main { min-width: 0; flex: 1; overflow: auto; background: #0F172A; }
        .shell-content { width: min(2200px, 100%); min-height: 100%; margin: 0 auto; padding: 18px 22px 40px; }
        .workbench-mobile-nav { display: none; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (max-width: 760px) {
          body { overflow: hidden; }
          .workbench-root { --font-page-title: var(--font-page-title-mobile); --font-kpi: var(--font-kpi-mobile); }
          .mobile-command-bar { min-height: 52px; display: flex; align-items: center; gap: 10px; padding: 4px 10px; border-bottom: 1px solid #1E293B; background: #0D1422; }
          .mobile-menu-button { width: 44px; height: 44px; }
          .shell-sidebar { display: none; }
          .shell-content { padding: 12px 10px 32px; overflow-x: hidden; }
          .workbench-index-bar { padding: 0 10px; gap: 18px; }
          .workbench-mobile-nav { display: flex; position: fixed; inset: 0; z-index: 100; }
          .mobile-nav-backdrop { position: absolute; inset: 0; border: 0; background: rgba(2, 6, 23, 0.72); }
          .mobile-nav-panel { position: relative; width: min(82vw, 290px); height: 100%; display: flex; flex-direction: column; background: #0D1422; border-right: 1px solid #263449; box-shadow: 18px 0 50px rgba(0,0,0,.35); }
          .mobile-nav-close { position: absolute; z-index: 1; right: 7px; top: 4px; width: 44px; height: 44px; display: inline-flex; align-items: center; justify-content: center; border: 1px solid #263449; border-radius: 6px; color: #94A3B8; background: #111827; cursor: pointer; }
          .mobile-nav-close svg { width: 15px; height: 15px; }
          .mobile-nav-panel .nav-item { min-height: 44px; }
        }
        @media (prefers-reduced-motion: reduce) {
          *, *::before, *::after { scroll-behavior: auto !important; transition-duration: 0.01ms !important; animation-duration: 0.01ms !important; animation-iteration-count: 1 !important; }
        }
      `}</style>
      <LiveIndexBar />
      <div className="mobile-command-bar">
        <button className="mobile-menu-button" type="button" onClick={() => setMobileOpen(true)} aria-label="打开导航">
          <Menu />
        </button>
        <span className="mobile-command-title">{activeNavigationLabel}</span>
      </div>
      <div className="shell-body">
        <aside className="shell-sidebar">{renderNavContent(collapsed, true)}</aside>
        <main className="shell-main">
          <div className="shell-content" key={activeTab}>{children}</div>
        </main>
      </div>
      {mobileOpen ? (
        <div className="workbench-mobile-nav">
          <button className="mobile-nav-backdrop" type="button" onClick={() => setMobileOpen(false)} aria-label="关闭导航" />
          <aside className="mobile-nav-panel">
            <button className="mobile-nav-close" type="button" onClick={() => setMobileOpen(false)} title="关闭导航"><X /></button>
            {renderNavContent(false, false)}
          </aside>
        </div>
      ) : null}
    </div>
  );
};
