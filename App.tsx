import React, { useState, useEffect, useRef } from 'react';
import { Database, BarChart3, BrainCircuit, Zap, Shield, TrendingUp, TrendingDown, Minus, ChevronRight, Bell, Bot, LayoutDashboard } from 'lucide-react';
import DbPanel from './components/DbPanel';
import FactorPanel from './components/FactorPanel';
import StrategyPanel from './components/StrategyPanel';
import ExecutionPanel from './components/ExecutionPanel';
import RiskPanel from './components/RiskPanel';
import AlertPanel from './components/AlertPanel';
import PaperPanel from './components/PaperPanel';
import DashboardPanel from './components/DashboardPanel';

const API_BASE = 'http://localhost:3334';

interface IndexData {
  code: string; name: string; price: number;
  open: number; close: number; high: number; low: number;
  volume: number; amount: number; chg_pct?: number;
}

const TABS = [
  { key: 'cockpit',   label: '驾驶舱',     icon: LayoutDashboard, accent: '#38BDF8' },
  { key: 'db',        label: '数据浏览',   icon: Database,    accent: '#F59E0B' },
  { key: 'factor',    label: '因子引擎',   icon: BarChart3,   accent: '#818CF8' },
  { key: 'strategy',  label: '策略运行',   icon: BrainCircuit,accent: '#34D399' },
  { key: 'execution', label: '交易执行',   icon: Zap,         accent: '#FB923C' },
  { key: 'paper',     label: '模拟盘',     icon: Bot,         accent: '#A78BFA' },
  { key: 'risk',      label: '风控监控',   icon: Shield,      accent: '#F472B6' },
  { key: 'alerts',    label: '监控告警',   icon: Bell,        accent: '#FB7185' },
];

// ─── Live Index Bar ───────────────────────────────────────────────
const LiveIndexBar: React.FC = () => {
  const [indices, setIndices] = useState<IndexData[]>([]);

  const load = () => {
    fetch(`${API_BASE}/api/market/indices`)
      .then(r => r.json())
      .then(j => { if (j.success && Array.isArray(j.data)) setIndices(j.data); })
      .catch(() => {});
  };

  useEffect(() => { load(); const t = setInterval(load, 12000); return () => clearInterval(t); }, []);

  return (
    <div style={{ background: '#0B0F1A', borderBottom: '1px solid #1E293B' }}>
      <div className="flex items-center h-9 px-5 gap-6 overflow-x-auto">
        {indices.length === 0 && (
          <span style={{ fontSize: 11, color: '#475569' }}>正在连接行情...</span>
        )}
        {indices.map(idx => {
          const price = typeof idx.price === 'number' ? idx.price : 0;
          const prevClose = typeof idx.close === 'number' ? idx.close : price;
          const changePct = typeof idx.chg_pct === 'number'
            ? idx.chg_pct
            : (prevClose !== 0 ? ((price - prevClose) / prevClose) * 100 : 0);
          const change = prevClose ? price - prevClose : 0;
          const up = changePct > 0;
          const down = changePct < 0;
          const cls = up ? '#EF4444' : down ? '#22C55E' : '#64748B';
          const pct = `${up ? '+' : ''}${changePct.toFixed(2)}%`;
          const Icon = up ? TrendingUp : down ? TrendingDown : Minus;
          return (
            <div key={idx.code} style={{ display: 'flex', alignItems: 'center', gap: 8, whiteSpace: 'nowrap', flexShrink: 0 }}>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#94A3B8' }}>{idx.name}</span>
              <span style={{ fontSize: 13, fontWeight: 700, fontFamily: 'JetBrains Mono, monospace', color: '#E2E8F0' }}>
                {price.toFixed(2)}
              </span>
              <span style={{ display: 'flex', alignItems: 'center', gap: 2, color: cls }}>
                <Icon style={{ width: 10, height: 10 }} />
                <span style={{ fontSize: 11, fontFamily: 'JetBrains Mono, monospace', fontWeight: 600 }}>{pct}</span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
};

// ─── Sidebar ───────────────────────────────────────────────────────
const Sidebar: React.FC<{ active: string; onChange: (k: string) => void }> = ({ active, onChange }) => {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <nav
      style={{
        width: collapsed ? 60 : 200,
        background: 'linear-gradient(180deg, #111827 0%, #0B0F1A 100%)',
        borderRight: '1px solid #1E293B',
        display: 'flex',
        flexDirection: 'column',
        transition: 'width 200ms ease',
        overflow: 'hidden',
        flexShrink: 0,
      }}
    >
      {/* Logo */}
      <div style={{ height: 56, display: 'flex', alignItems: 'center', padding: '0 14px', borderBottom: '1px solid #1E293B', gap: 10, cursor: 'pointer' }}
           onClick={() => setCollapsed(c => !c)}>
        <div style={{
          width: 32, height: 32, borderRadius: 8,
          background: 'linear-gradient(135deg, #F59E0B 0%, #D97706 100%)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          boxShadow: '0 0 16px rgba(245,158,11,0.35)',
        }}>
          <BarChart3 style={{ width: 18, height: 18, color: '#0B0F1A' }} />
        </div>
        {!collapsed && (
          <div>
            <div style={{ fontSize: 14, fontWeight: 800, color: '#F1F5F9', letterSpacing: -0.3 }}>AlphaCouncil</div>
            <div style={{ fontSize: 10, color: '#475569', letterSpacing: 1 }}>QUANT TERMINAL</div>
          </div>
        )}
      </div>

      {/* Nav items */}
      <div style={{ padding: '12px 8px', display: 'flex', flexDirection: 'column', gap: 3, flex: 1 }}>
        {TABS.map(tab => {
          const Icon = tab.icon;
          const isActive = active === tab.key;
          return (
            <button
              key={tab.key}
              onClick={() => onChange(tab.key)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                padding: collapsed ? '10px 0' : '10px 12px',
                justifyContent: collapsed ? 'center' : 'flex-start',
                borderRadius: 8,
                border: 'none',
                cursor: 'pointer',
                transition: 'all 150ms ease',
                background: isActive
                  ? `linear-gradient(90deg, ${tab.accent}18 0%, transparent 100%)`
                  : 'transparent',
                boxShadow: isActive ? `inset 2px 0 0 ${tab.accent}` : 'none',
              }}
            >
              <div style={{
                width: 32, height: 32, borderRadius: 8,
                background: isActive ? `${tab.accent}22` : '#1E293B',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                transition: 'all 150ms ease',
                flexShrink: 0,
              }}>
                <Icon style={{ width: 16, height: 16, color: isActive ? tab.accent : '#64748B' }} />
              </div>
              {!collapsed && (
                <span style={{
                  fontSize: 13, fontWeight: isActive ? 600 : 400,
                  color: isActive ? '#F1F5F9' : '#64748B',
                  transition: 'color 150ms ease',
                }}>
                  {tab.label}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {/* Collapse toggle */}
      <div style={{ padding: 12, borderTop: '1px solid #1E293B' }}>
        <button
          onClick={() => setCollapsed(c => !c)}
          style={{
            width: '100%', display: 'flex', alignItems: 'center', justifyContent: collapsed ? 'center' : 'flex-start',
            gap: 8, padding: '8px 10px', borderRadius: 6, border: 'none', cursor: 'pointer',
            background: '#1E293B', color: '#64748B', fontSize: 12,
            transition: 'all 150ms ease',
          }}
        >
          <ChevronRight style={{ width: 14, height: 14, transform: collapsed ? 'rotate(0deg)' : 'rotate(180deg)', transition: 'transform 200ms ease' }} />
          {!collapsed && <span>收起</span>}
        </button>
      </div>
    </nav>
  );
};

// ─── Panel Wrapper ────────────────────────────────────────────────
const PanelWrapper: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <div style={{
    flex: 1, overflowY: 'auto', padding: '24px 28px',
    background: 'linear-gradient(135deg, #0B0F1A 0%, #111827 50%, #0F172A 100%)',
    minHeight: '100vh',
  }}>
    {children}
  </div>
);

// ─── KeepAlive 面板容器 ──────────────────────────────────────────
// 性能优化: 首次切到某 tab 才挂载 (lazy mount), 挂载后永不卸载,
// 切走时用 display:none 隐藏 (保留 state/滚动位置/已拉数据/后台轮询)。
// 解决原来 key={activeTab} 导致每次切 tab 全量重挂载 + 重拉数据的延迟。
const KeepAlivePanels: React.FC<{ activeTab: string; panels: Record<string, React.ReactNode> }> = ({ activeTab, panels }) => {
  const [mounted, setMounted] = React.useState<Set<string>>(new Set([activeTab]));
  // 切到新 tab 时加入 mounted 集合 (已挂载的不重复挂)
  React.useEffect(() => {
    setMounted(prev => prev.has(activeTab) ? prev : new Set([...prev, activeTab]));
  }, [activeTab]);

  return (
    <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
      {TABS.map(tab => {
        if (!mounted.has(tab.key)) return null;  // 未访问过的 tab 不渲染
        const isActive = tab.key === activeTab;
        return (
          <div key={tab.key} style={{
            flex: 1, overflowY: 'auto', padding: '24px 28px',
            background: 'linear-gradient(135deg, #0B0F1A 0%, #111827 50%, #0F172A 100%)',
            minHeight: '100vh',
            display: isActive ? 'block' : 'none',  // 隐藏而非卸载
          }}>
            {panels[tab.key]}
          </div>
        );
      })}
    </div>
  );
};

// ─── App ───────────────────────────────────────────────────────────
const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState('cockpit');

  const panels: Record<string, React.ReactNode> = {
    cockpit:   <DashboardPanel />,
    db:        <DbPanel />,
    factor:    <FactorPanel />,
    strategy:  <StrategyPanel />,
    execution: <ExecutionPanel />,
    paper:     <PaperPanel />,
    risk:      <RiskPanel />,
    alerts:    <AlertPanel />,
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#0B0F1A',
      color: '#E2E8F0',
      fontFamily: "'Inter','PingFang SC','Microsoft YaHei',sans-serif",
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Google Fonts */}
      <style>{`
        /* 使用系统字体栈，避免受外部字体服务网络波动影响浏览器验证。 */
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #475569; }
        body { margin: 0; padding: 0; }
      `}</style>

      <LiveIndexBar />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden' }}>
        <Sidebar active={activeTab} onChange={setActiveTab} />
        <KeepAlivePanels activeTab={activeTab} panels={panels} />
      </div>
    </div>
  );
};

export default App;
