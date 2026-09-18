import React, { useState } from 'react';
import { Landmark, Radio } from 'lucide-react';
import CninfoDisclosurePanel from './CninfoDisclosurePanel';
import Jin10DataPanel from './Jin10DataPanel';

type SourceTab = 'jin10' | 'cninfo';

const SOURCES: Array<{ key: SourceTab; label: string; description: string; icon: React.ReactNode }> = [
  {
    key: 'jin10',
    label: '金十数据',
    description: '宏观行情、市场快讯与财经日历',
    icon: <Radio aria-hidden="true" />,
  },
  {
    key: 'cninfo',
    label: '巨潮公告',
    description: 'A股公告、业绩快报、预告与定期报告',
    icon: <Landmark aria-hidden="true" />,
  },
];

const MarketInformationPanel: React.FC = () => {
  const [source, setSource] = useState<SourceTab>('jin10');

  return (
    <div className="market-information-panel">
      <style>{`
        .market-information-panel { width: 100%; min-width: 0; }
        .market-source-switch { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; margin-bottom: 12px; padding: 5px; border: 1px solid #1E293B; border-radius: 8px; background: #0B1220; }
        .market-source-tab { min-width: 0; height: 48px; display: flex; align-items: center; gap: 10px; padding: 0 13px; border: 1px solid transparent; border-radius: 6px; color: #64748B; background: transparent; cursor: pointer; text-align: left; }
        .market-source-tab:hover { color: #CBD5E1; background: #111827; }
        .market-source-tab[data-active="true"] { color: #E2E8F0; border-color: #334155; background: #172033; }
        .market-source-tab svg { width: 17px; height: 17px; flex: 0 0 auto; color: #38BDF8; }
        .market-source-copy { min-width: 0; }
        .market-source-copy strong, .market-source-copy span { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .market-source-copy strong { font-size: 13px; line-height: 1.2; }
        .market-source-copy span { margin-top: 3px; color: #64748B; font-size: 11px; }
        .market-source-tab:focus-visible { outline: 2px solid #38BDF8; outline-offset: 2px; }
        @media (max-width: 620px) {
          .market-source-switch { gap: 5px; margin-bottom: 10px; }
          .market-source-tab { height: 50px; padding: 0 10px; }
          .market-source-copy span { display: none; }
        }
      `}</style>
      <div className="market-source-switch" role="tablist" aria-label="市场资讯来源">
        {SOURCES.map((item) => (
          <button
            className="market-source-tab"
            data-active={source === item.key}
            data-market-source={item.key}
            key={item.key}
            onClick={() => setSource(item.key)}
            role="tab"
            aria-selected={source === item.key}
            type="button"
          >
            {item.icon}
            <span className="market-source-copy">
              <strong>{item.label}</strong>
              <span>{item.description}</span>
            </span>
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {source === 'jin10' ? <Jin10DataPanel /> : <CninfoDisclosurePanel />}
      </div>
    </div>
  );
};

export default MarketInformationPanel;
