"""
全市场估值 -> 截面便宜度评分 + 中文PDF
输入: data/valuation_full.csv (scripts/value_universe.py 产出)
输出:
  data/valuation_scored.csv   含便宜度综合评分与分位
  data/valuation_full.pdf     全量估值表(按便宜度降序分页)
便宜度 = 对 E/P, B/P, S/P 三者做全市场截面百分位, 取均值(越高越便宜)
仅用正倍数; 亏损/负净资产个股跳过对应分项。
"""
import csv, os, sys, warnings
warnings.filterwarnings('ignore')
import numpy as np
from fpdf import FPDF

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC  = os.path.join(ROOT, 'data', 'valuation_full.csv')
OUT_CSV = os.path.join(ROOT, 'data', 'valuation_scored.csv')
OUT_PDF = os.path.join(ROOT, 'data', 'valuation_full.pdf')
FONT = r'C:\Windows\Fonts\simhei.ttf'

def f(x):
    try:
        if x is None or x == '':
            return None
        v = float(x)
        return v if v == v else None
    except Exception:
        return None

def load():
    rows = []
    with open(SRC, encoding='utf-8') as fh:
        for r in csv.DictReader(fh):
            if r.get('status') != 'OK':
                continue
            pe = f(r['pe']); pb = f(r['pb']); ps = f(r['ps'])
            if pe is None and pb is None and ps is None:
                continue
            rows.append({
                'code': r['code'], 'name': r['name'], 'price': f(r['price']),
                'pe': pe, 'pb': pb, 'ps': ps,
                'roe': f(r['roe']),
                'np': f(r['net_profit']), 'rev': f(r['revenue']),
            })
    return rows

def score(rows):
    eps = np.array([ (1.0/r['pe']) for r in rows if r['pe'] and r['pe'] > 0 ], dtype=float)
    bps = np.array([ (1.0/r['pb']) for r in rows if r['pb'] and r['pb'] > 0 ], dtype=float)
    sps = np.array([ (1.0/r['ps']) for r in rows if r['ps'] and r['ps'] > 0 ], dtype=float)
    def pct(arr, val):
        return float((arr <= val).mean() * 100.0) if len(arr) else None
    for r in rows:
        sc, n = 0.0, 0
        if r['pe'] and r['pe'] > 0:
            r['s_ep'] = pct(eps, 1.0/r['pe']); sc += r['s_ep']; n += 1
        else:
            r['s_ep'] = None
        if r['pb'] and r['pb'] > 0:
            r['s_bp'] = pct(bps, 1.0/r['pb']); sc += r['s_bp']; n += 1
        else:
            r['s_bp'] = None
        if r['ps'] and r['ps'] > 0:
            r['s_sp'] = pct(sps, 1.0/r['ps']); sc += r['s_sp']; n += 1
        else:
            r['s_sp'] = None
        r['score'] = round(sc / n, 1) if n else None
    rows.sort(key=lambda r: (r['score'] if r['score'] is not None else -1), reverse=True)
    for i, r in enumerate(rows, 1):
        r['rank'] = i
    return rows

def save_csv(rows):
    cols = ['rank','code','name','price','pe','pb','ps','roe','np_yi','rev_yi','s_ep','s_bp','s_sp','score']
    with open(OUT_CSV, 'w', encoding='utf-8', newline='') as fh:
        w = csv.writer(fh); w.writerow(cols)
        for r in rows:
            w.writerow([r['rank'], r['code'], r['name'],
                        r['price'], r['pe'], r['pb'], r['ps'], r['roe'],
                        round(r['np']/1e8,1) if r['np'] else '',
                        round(r['rev']/1e8,1) if r['rev'] else '',
                        r['s_ep'], r['s_bp'], r['s_sp'], r['score']])

class PDF(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font('CN','',8); self.set_text_color(120)
        self.cell(0,6,'全市场A股估值扫描 (便宜度降序)  ·  数据截至 2026-07-12  ·  倍数口径: 静LYR(最新年报)',0,1,'C')
        self.set_text_color(0)
    def footer(self):
        self.set_y(-12); self.set_font('CN','',8); self.set_text_color(120)
        self.cell(0,8,'第 %d 页' % self.page_no(),0,0,'C'); self.set_text_color(0)

def build_pdf(rows):
    pdf = FPDF(format='A4', orientation='L', unit='mm')
    pdf.add_font('CN','',FONT); pdf.add_font('CN','B',FONT)
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_margins(8,8,8)
    # title page
    pdf.add_page()
    pdf.set_font('CN','B',18); pdf.cell(0,14,'全市场 A 股估值扫描报告',0,1,'C')
    pdf.set_font('CN','',11)
    pdf.cell(0,8,'生成日期: 2026-07-12   数据来源: 新浪财经 (个股财务摘要 + 全市场行情)',0,1,'C')
    pdf.cell(0,7,'估值倍数口径: 静市盈率(LYR) / 市净率 / 市销率, 基于最新年度报告与当前股价',0,1,'C')
    pdf.cell(0,7,'便宜度评分: 对 E/P、B/P、S/P 做全市场截面百分位(0-100), 取均值, 越高越便宜',0,1,'C')
    pdf.ln(4)
    n = len(rows)
    valid_pe = sum(1 for r in rows if r['pe'] and r['pe']>0)
    pdf.set_font('CN','',11)
    pdf.cell(0,7,'样本量: %d 只   |   有效PE(盈利): %d  有效PB: %d  有效PS: %d'
             % (n, valid_pe, sum(1 for r in rows if r['pb'] and r['pb']>0),
                sum(1 for r in rows if r['ps'] and r['ps']>0)),0,1,'C')
    pdf.ln(2)
    pdf.set_font('CN','B',12); pdf.cell(0,8,'最便宜 Top 20 (按综合便宜度)',0,1,'L')
    pdf.set_font('CN','',9)
    for r in rows[:20]:
        pdf.cell(0,6,'%s %s   PE %.1f  PB %.2f  PS %.2f  评分 %.1f'
                 % (r['code'], r['name'], r['pe'] or 0, r['pb'] or 0, r['ps'] or 0, r['score'] or 0),0,1,'L')

    # table pages
    headers = ['排名','代码','名称','现价','PE','PB','PS','ROE%','净利(亿)','营收(亿)','便宜度']
    w = [12,18,34,16,16,14,14,14,24,24,18]
    pdf.add_page()
    pdf.set_font('CN','B',8)
    pdf.set_fill_color(230,230,230)
    for h,wi in zip(headers,w): pdf.cell(wi,7,h,1,0,'C',True)
    pdf.ln()
    pdf.set_font('CN','',8)
    fill=False
    for r in rows:
        if pdf.get_y() > 190:
            pdf.add_page()
            pdf.set_font('CN','B',8); pdf.set_fill_color(230,230,230)
            for h,wi in zip(headers,w): pdf.cell(wi,7,h,1,0,'C',True)
            pdf.ln(); pdf.set_font('CN','',8)
        pdf.set_fill_color(245,245,245) if fill else pdf.set_fill_color(255,255,255)
        pdf.cell(w[0],6,str(r['rank']),1,0,'C',fill)
        pdf.cell(w[1],6,r['code'],1,0,'C',fill)
        pdf.cell(w[2],6,r['name'][:12],1,0,'L',fill)
        pdf.cell(w[3],6,'%.2f'%(r['price'] or 0),1,0,'R',fill)
        pdf.cell(w[4],6,'%.1f'%(r['pe'] or 0) if r['pe'] else '-',1,0,'R',fill)
        pdf.cell(w[5],6,'%.2f'%(r['pb'] or 0) if r['pb'] else '-',1,0,'R',fill)
        pdf.cell(w[6],6,'%.2f'%(r['ps'] or 0) if r['ps'] else '-',1,0,'R',fill)
        pdf.cell(w[7],6,'%.1f'%(r['roe'] or 0) if r['roe'] else '-',1,0,'R',fill)
        pdf.cell(w[8],6,'%.1f'%(r['np']/1e8) if r['np'] else '-',1,0,'R',fill)
        pdf.cell(w[9],6,'%.1f'%(r['rev']/1e8) if r['rev'] else '-',1,0,'R',fill)
        pdf.cell(w[10],6,'%.1f'%(r['score'] or 0),1,0,'R',fill)
        pdf.ln(); fill = not fill
    pdf.output(OUT_PDF)

def main():
    rows = load()
    print('loaded OK rows:', len(rows))
    if not rows:
        print('no data yet'); return
    score(rows)
    save_csv(rows)
    build_pdf(rows)
    print('PDF ->', OUT_PDF, 'rows', len(rows))
    print('top3:', [(r['code'],r['name'],r['score']) for r in rows[:3]])

if __name__ == '__main__':
    main()
