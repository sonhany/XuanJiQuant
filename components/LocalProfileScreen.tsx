import React, { useState } from 'react';
import { ArrowRight, BarChart3, Bot, ShieldCheck } from 'lucide-react';
import xuanjiHorizontal from '../public/branding/logo_horizontal.svg';

const roles = [
  { key: 'paper-sandbox', label: '模拟盘操作员', note: '查看全部页面并操作模拟交易', icon: Bot },
  { key: 'risk-review', label: '风险审阅员', note: '聚焦风险、告警、执行审计', icon: ShieldCheck },
  { key: 'research', label: '策略研究员', note: '聚焦数据、因子、策略与实验', icon: BarChart3 },
];

export const LocalProfileScreen: React.FC<{
  onEnter: (profile: { user: string; role: string }) => void;
}> = ({ onEnter }) => {
  const [user, setUser] = useState('quant-operator');
  const [role, setRole] = useState('paper-sandbox');
  const [error, setError] = useState('');

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    if (!user.trim()) {
      setError('请输入本地操作员名称');
      return;
    }
    onEnter({ user: user.trim(), role });
  };

  return (
    <div className="profile-screen">
      <style>{`
        * { box-sizing: border-box; }
        html, body, #root { margin: 0; min-height: 100%; background: #08110F; }
        .profile-screen { min-height: 100vh; display: grid; grid-template-columns: minmax(0, 1fr) minmax(360px, 470px); color: #E7F5EF; background: #08110F; font-family: Inter, "PingFang SC", "Microsoft YaHei", sans-serif; }
        .profile-brief { min-height: 100vh; display: flex; flex-direction: column; justify-content: space-between; padding: clamp(28px, 5vw, 72px); border-right: 1px solid #1C302B; background: #0A1714; }
        .profile-logo { width: 220px; max-width: 70%; }
        .profile-brief h1 { max-width: 760px; margin: 56px 0 18px; font-size: clamp(34px, 5vw, 62px); line-height: 1.06; letter-spacing: 0; color: #F6FFFB; }
        .profile-brief p { max-width: 720px; margin: 0; color: #91AEA4; font-size: 15px; line-height: 1.8; }
        .profile-principles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 1px; margin-top: 48px; background: #1C302B; border: 1px solid #1C302B; }
        .profile-principles div { min-height: 86px; padding: 15px; background: #0A1714; }
        .profile-principles strong { display: block; color: #D4A531; font-size: 11px; }
        .profile-principles span { display: block; margin-top: 8px; color: #78958B; font-size: 11px; line-height: 1.55; }
        .profile-form-wrap { display: flex; align-items: center; padding: 34px; background: #0B1218; }
        .profile-form { width: 100%; }
        .profile-form h2 { margin: 0; color: #F8FAFC; font-size: 22px; }
        .profile-form .subcopy { margin: 8px 0 26px; color: #718096; font-size: 12px; line-height: 1.65; }
        .field-label { display: block; margin-bottom: 8px; color: #94A3B8; font-size: 11px; font-weight: 700; }
        .profile-input { width: 100%; height: 44px; padding: 0 12px; border: 1px solid #28364A; border-radius: 6px; outline: none; color: #E2E8F0; background: #0F172A; }
        .profile-input:focus { border-color: #38BDF8; }
        .role-options { display: grid; gap: 8px; margin-top: 18px; }
        .role-option { width: 100%; min-height: 66px; display: grid; grid-template-columns: 34px 1fr; align-items: center; gap: 10px; padding: 10px 12px; border: 1px solid #273449; border-radius: 6px; color: #CBD5E1; background: #0F172A; text-align: left; cursor: pointer; }
        .role-option.active { border-color: #3D8EA8; background: #10202A; box-shadow: inset 3px 0 0 #38BDF8; }
        .role-option svg { width: 18px; height: 18px; color: #38BDF8; }
        .role-option strong, .role-option span { display: block; }
        .role-option strong { font-size: 12px; }
        .role-option span { margin-top: 4px; color: #718096; font-size: 12px; }
        .profile-error { margin-top: 12px; color: #FCA5A5; font-size: 11px; }
        .enter-button { width: 100%; height: 44px; display: flex; align-items: center; justify-content: center; gap: 8px; margin-top: 18px; border: 1px solid #15916F; border-radius: 6px; color: #F0FFF9; background: #0D7A5F; font-weight: 800; cursor: pointer; }
        .enter-button svg { width: 15px; height: 15px; }
        .local-note { margin-top: 16px; padding: 11px 12px; border-left: 2px solid #D4A531; color: #718096; background: #111923; font-size: 12px; line-height: 1.6; }
        @media (max-width: 850px) {
          .profile-screen { grid-template-columns: 1fr; }
          .profile-brief { min-height: auto; padding: 28px 20px; border-right: 0; border-bottom: 1px solid #1C302B; }
          .profile-brief h1 { margin-top: 34px; font-size: 36px; }
          .profile-principles { grid-template-columns: 1fr; margin-top: 32px; }
          .profile-principles div { min-height: auto; }
          .profile-form-wrap { padding: 28px 18px 42px; }
        }
      `}</style>
      <section className="profile-brief">
        <div>
          <img className="profile-logo" src={xuanjiHorizontal} alt="璇玑 XUANJI" />
          <h1>专业投资者的量化决策工作台</h1>
          <p>同一账户、同一风险口径、同一审计链路。页面优先回答当前收益、暴露、回撤、风险和是否允许模拟交易。</p>
        </div>
        <div className="profile-principles">
          <div><strong>仅限模拟交易</strong><span>当前系统仅提供模拟交易执行路径。</span></div>
          <div><strong>风控优先</strong><span>关键状态不可验证时，交易操作默认阻断。</span></div>
          <div><strong>全程可审计</strong><span>策略、决策、风控、订单与告警保留来源。</span></div>
        </div>
      </section>
      <aside className="profile-form-wrap">
        <form className="profile-form" onSubmit={submit}>
          <h2>选择本地工作身份</h2>
          <p className="subcopy">此处用于调整页面权限与关注重点，不是服务端身份认证。</p>
          <label className="field-label" htmlFor="operator">操作员名称</label>
          <input id="operator" className="profile-input" value={user} onChange={(event) => setUser(event.target.value)} />
          <div className="role-options" aria-label="工作身份">
            {roles.map(({ key, label, note, icon: Icon }) => (
              <button className={`role-option ${role === key ? 'active' : ''}`} type="button" key={key} onClick={() => setRole(key)}>
                <Icon />
                <div><strong>{label}</strong><span>{note}</span></div>
              </button>
            ))}
          </div>
          {error ? <div className="profile-error">{error}</div> : null}
          <button className="enter-button" type="submit">进入工作台 <ArrowRight /></button>
          <div className="local-note">本地身份仅保存于当前浏览器。API 控制权限仍由本机来源、JSON 请求和服务端令牌独立校验。</div>
        </form>
      </aside>
    </div>
  );
};
