import React, { useState, useEffect } from 'react';
import {
  Database, BarChart3, BrainCircuit, Zap, Shield, TrendingUp, TrendingDown, Minus,
  ChevronRight, Bell, Bot, LayoutDashboard, LockKeyhole, ArrowRight, Network,
  ShieldCheck, FileSearch, Activity, Cpu, KeyRound
} from 'lucide-react';
import DbPanel from './components/DbPanel';
import FactorPanel from './components/FactorPanel';
import StrategyPanel from './components/StrategyPanel';
import ExecutionPanel from './components/ExecutionPanel';
import RiskPanel from './components/RiskPanel';
import AlertPanel from './components/AlertPanel';
import PaperPanel from './components/PaperPanel';
import DashboardPanel from './components/DashboardPanel';
import xuanjiSymbol from './Logo/logo_symbol.svg';
import xuanjiHorizontal from './Logo/logo_horizontal.svg';

const API_BASE = (import.meta as any).env?.VITE_API_BASE || '';

const BRAND_NAME = '璇玑';
const BRAND_ROMAN = 'XUANJI';
const BRAND_TAGLINE = 'AI 自主量化交易系统';

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

const architectureHighlights = [
  { icon: Network, title: 'AI 决策协议', text: 'target weights、rebalance plan、risk budget 统一输出，非标准结果直接废弃。' },
  { icon: ShieldCheck, title: '硬风控网关', text: '订单意图必须经过 verifier 与 risk gateway，AI 无法绕过仓位、熔断与 T+1 约束。' },
  { icon: FileSearch, title: '全链路回放', text: '决策、模型调用、风控原因、订单与成交以 run_id 串联，可追溯每一次交易。' },
];

const pipelineSteps = ['数据感知', '因子工厂', '策略晋升', '组合规划', '执行网关', '审计回放'];

const LoginScreen: React.FC<{ onLogin: (profile: { user: string; role: string }) => void }> = ({ onLogin }) => {
  const [user, setUser] = useState('quant-operator');
  const [accessKey, setAccessKey] = useState('');
  const [role, setRole] = useState('paper-sandbox');
  const [error, setError] = useState('');

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!user.trim()) {
      setError('请输入操作员账户');
      return;
    }
    onLogin({ user: user.trim(), role });
  };

  return (
    <div style={{
      minHeight: '100vh',
      background: '#07110F',
      color: '#E6F4EF',
      display: 'flex',
      alignItems: 'stretch',
      fontFamily: "'Inter','PingFang SC','Microsoft YaHei',sans-serif",
      position: 'relative',
      overflow: 'hidden',
    }}>
      <style>{`
        @media (max-width: 980px) {
          .xuanji-login-shell { grid-template-columns: 1fr !important; padding: 20px !important; }
          .xuanji-login-hero { min-height: auto !important; padding: 28px !important; }
          .xuanji-login-panel { padding: 24px !important; }
          .xuanji-pipeline { grid-template-columns: repeat(3, 1fr) !important; }
        }
        @media (max-width: 620px) {
          .xuanji-login-shell { padding: 12px !important; }
          .xuanji-login-hero { padding: 20px !important; }
          .xuanji-login-title { font-size: 34px !important; }
          .xuanji-highlight-grid { grid-template-columns: 1fr !important; }
          .xuanji-pipeline { grid-template-columns: repeat(2, 1fr) !important; }
        }
      `}</style>
      <div style={{
        position: 'absolute', inset: 0,
        backgroundImage: `
          linear-gradient(rgba(212,165,49,0.05) 1px, transparent 1px),
          linear-gradient(90deg, rgba(13,122,95,0.09) 1px, transparent 1px),
          linear-gradient(115deg, rgba(212,165,49,0.10) 0%, transparent 28%, rgba(13,122,95,0.10) 68%, transparent 100%),
          linear-gradient(135deg, #07110F 0%, #0B1F1A 45%, #08131E 100%)
        `,
        backgroundSize: '44px 44px, 44px 44px, 100% 100%, 100% 100%',
      }} />
      <div className="xuanji-login-shell" style={{
        position: 'relative',
        width: '100%',
        display: 'grid',
        gridTemplateColumns: 'minmax(0, 1.2fr) minmax(360px, 480px)',
        gap: 24,
        padding: 28,
      }}>
        <section className="xuanji-login-hero" style={{
          minHeight: 'calc(100vh - 56px)',
          border: '1px solid rgba(212,165,49,0.22)',
          borderRadius: 8,
          padding: 40,
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'space-between',
          background: 'linear-gradient(145deg, rgba(8,19,18,0.92), rgba(8,18,30,0.84))',
          boxShadow: '0 24px 80px rgba(0,0,0,0.35)',
        }}>
          <div>
            <img src={xuanjiHorizontal} alt="璇玑 XUANJI" style={{ width: 230, maxWidth: '70%', display: 'block', marginBottom: 44 }} />
            <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '7px 10px', border: '1px solid rgba(212,165,49,0.35)', borderRadius: 999, color: '#D4A531', fontSize: 12, marginBottom: 18 }}>
              <Activity style={{ width: 14, height: 14 }} />
              Autonomous Quant Terminal
            </div>
            <h1 className="xuanji-login-title" style={{ fontSize: 56, lineHeight: 1.05, margin: '0 0 18px', letterSpacing: 0, color: '#F7FFF9', fontWeight: 800 }}>
              {BRAND_NAME} {BRAND_ROMAN}
            </h1>
            <p style={{ fontSize: 18, lineHeight: 1.8, maxWidth: 760, color: '#A9C8BE', margin: 0 }}>
              面向中国 A 股的 AI 自主量化交易系统，将多模型决策、因子发现、策略晋升、组合再平衡、硬风控网关和结构化审计整合为一条可验证的交易闭环。
            </p>
          </div>

          <div>
            <div className="xuanji-pipeline" style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(6, minmax(0, 1fr))',
              gap: 8,
              marginBottom: 22,
            }}>
              {pipelineSteps.map((step, i) => (
                <div key={step} style={{
                  border: '1px solid rgba(13,122,95,0.34)',
                  borderRadius: 8,
                  padding: '10px 8px',
                  background: i === 4 ? 'rgba(127,29,29,0.38)' : 'rgba(7,17,15,0.64)',
                  color: i === 4 ? '#FECACA' : '#BFE9DC',
                  minHeight: 58,
                }}>
                  <div style={{ fontSize: 10, color: '#68897F', marginBottom: 6 }}>{String(i + 1).padStart(2, '0')}</div>
                  <div style={{ fontSize: 12, fontWeight: 700 }}>{step}</div>
                </div>
              ))}
            </div>
            <div className="xuanji-highlight-grid" style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12 }}>
              {architectureHighlights.map(({ icon: Icon, title, text }) => (
                <div key={title} style={{ border: '1px solid rgba(212,165,49,0.20)', borderRadius: 8, padding: 14, background: 'rgba(4,12,11,0.68)' }}>
                  <Icon style={{ width: 18, height: 18, color: '#D4A531', marginBottom: 10 }} />
                  <div style={{ fontSize: 13, fontWeight: 800, color: '#EAFBF4', marginBottom: 6 }}>{title}</div>
                  <div style={{ fontSize: 12, lineHeight: 1.6, color: '#84A99D' }}>{text}</div>
                </div>
              ))}
            </div>
          </div>
        </section>

        <aside className="xuanji-login-panel" style={{
          border: '1px solid rgba(212,165,49,0.28)',
          borderRadius: 8,
          padding: 30,
          background: 'rgba(8,17,20,0.92)',
          boxShadow: '0 24px 80px rgba(0,0,0,0.42)',
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 28 }}>
            <div style={{ width: 46, height: 46, borderRadius: 8, border: '1px solid rgba(212,165,49,0.36)', display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(13,122,95,0.16)' }}>
              <img src={xuanjiSymbol} alt="" style={{ width: 36, height: 36 }} />
            </div>
            <div>
              <div style={{ fontSize: 18, fontWeight: 900, color: '#F7FFF9' }}>{BRAND_NAME} 登录</div>
              <div style={{ fontSize: 12, letterSpacing: 1.2, color: '#D4A531' }}>{BRAND_ROMAN} SECURE ACCESS</div>
            </div>
          </div>

          <form onSubmit={submit} style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ fontSize: 12, color: '#89AFA3' }}>操作员账户</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, border: '1px solid #1F3A35', borderRadius: 8, padding: '0 12px', background: '#06100F' }}>
                <Cpu style={{ width: 16, height: 16, color: '#0D7A5F' }} />
                <input value={user} onChange={e => setUser(e.target.value)} style={{ flex: 1, height: 44, background: 'transparent', border: 0, outline: 'none', color: '#E6F4EF', fontSize: 14 }} />
              </div>
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ fontSize: 12, color: '#89AFA3' }}>访问密钥</span>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, border: '1px solid #1F3A35', borderRadius: 8, padding: '0 12px', background: '#06100F' }}>
                <KeyRound style={{ width: 16, height: 16, color: '#D4A531' }} />
                <input value={accessKey} onChange={e => setAccessKey(e.target.value)} type="password" placeholder="本地终端可留空" style={{ flex: 1, height: 44, background: 'transparent', border: 0, outline: 'none', color: '#E6F4EF', fontSize: 14 }} />
              </div>
            </label>
            <label style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <span style={{ fontSize: 12, color: '#89AFA3' }}>进入模式</span>
              <select value={role} onChange={e => setRole(e.target.value)} style={{ height: 44, border: '1px solid #1F3A35', borderRadius: 8, background: '#06100F', color: '#E6F4EF', padding: '0 12px', outline: 'none' }}>
                <option value="paper-sandbox">自治模拟盘沙箱</option>
                <option value="risk-review">风控审计工作台</option>
                <option value="research">因子/策略研究席</option>
              </select>
            </label>
            {error && <div style={{ color: '#FCA5A5', fontSize: 12 }}>{error}</div>}
            <button type="submit" style={{
              height: 46,
              marginTop: 4,
              border: '1px solid rgba(212,165,49,0.55)',
              borderRadius: 8,
              background: 'linear-gradient(135deg, #0D7A5F 0%, #05412F 58%, #9A7510 100%)',
              color: '#F8FFF9',
              fontWeight: 900,
              fontSize: 14,
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              gap: 8,
            }}>
              进入量化终端
              <ArrowRight style={{ width: 16, height: 16 }} />
            </button>
          </form>

          <div style={{ marginTop: 26, paddingTop: 18, borderTop: '1px solid #17322D', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 10 }}>
            {[
              ['Verifier', '决策校验'],
              ['Risk Gateway', '硬风控前置'],
              ['Audit Replay', '交易可回放'],
              ['Manual Gate', '实盘人工审批'],
            ].map(([k, v]) => (
              <div key={k} style={{ border: '1px solid #17322D', borderRadius: 8, padding: 10, background: 'rgba(5,12,12,0.6)' }}>
                <div style={{ color: '#D4A531', fontSize: 11, fontWeight: 800 }}>{k}</div>
                <div style={{ color: '#76978D', fontSize: 11, marginTop: 4 }}>{v}</div>
              </div>
            ))}
          </div>
          <div style={{ marginTop: 18, display: 'flex', gap: 8, alignItems: 'center', color: '#6E9388', fontSize: 11 }}>
            <LockKeyhole style={{ width: 13, height: 13, color: '#D4A531' }} />
            实盘自动交易默认关闭，仅在人工审批与熔断配置完整后开放。
          </div>
        </aside>
      </div>
    </div>
  );
};

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
          background: 'linear-gradient(135deg, rgba(13,122,95,0.22) 0%, rgba(212,165,49,0.16) 100%)',
          border: '1px solid rgba(212,165,49,0.35)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0,
          boxShadow: '0 0 16px rgba(13,122,95,0.25)',
        }}>
          <img src={xuanjiSymbol} alt="璇玑 XUANJI" style={{ width: 27, height: 27, display: 'block' }} />
        </div>
        {!collapsed && (
          <div>
            <div style={{ fontSize: 15, fontWeight: 800, color: '#E7FFF6', letterSpacing: 1 }}>璇玑</div>
            <div style={{ fontSize: 10, color: '#D4A531', letterSpacing: 1.6 }}>XUANJI QUANT</div>
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

// ─── 面板容器 ──────────────────────────────────────────────
// 安全/性能优先: 只挂载当前 tab, 避免隐藏面板继续轮询后台 API。
const KeepAlivePanels: React.FC<{ activeTab: string; panels: Record<string, React.ReactNode> }> = ({ activeTab, panels }) => (
  <div style={{ flex: 1, overflow: 'hidden', display: 'flex' }}>
    <div style={{
      flex: 1, overflowY: 'auto', padding: '24px 28px',
      background: 'linear-gradient(135deg, #0B0F1A 0%, #111827 50%, #0F172A 100%)',
      minHeight: '100vh',
    }}>
      {panels[activeTab]}
    </div>
  </div>
);

// ─── App ───────────────────────────────────────────────────────────
const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState('cockpit');
  const [session, setSession] = useState<{ user: string; role: string } | null>(() => {
    try {
      const raw = localStorage.getItem('xuanji:session');
      return raw ? JSON.parse(raw) : null;
    } catch {
      return null;
    }
  });

  const handleLogin = (profile: { user: string; role: string }) => {
    localStorage.setItem('xuanji:session', JSON.stringify({ ...profile, loginAt: new Date().toISOString() }));
    setSession(profile);
  };

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

  if (!session) {
    return <LoginScreen onLogin={handleLogin} />;
  }

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
