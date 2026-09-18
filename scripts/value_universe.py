"""
全市场 A 股相对估值扫描（PE/PB/PS，基于 sina 财务摘要 + sina 现价）
- 现价：ak.stock_zh_a_spot()（全市场，约 5500 只）
- 基本面：ak.stock_financial_abstract() 取最新年报的每股指标
  PE = 现价 / 基本每股收益(LYR)
  PB = 现价 / 每股净资产
  PS = 现价 / 每股营业总收入
- 支持断点续传：结果追加写 data/valuation_full.csv，已完成的 code 跳过
- 北交所(BJ)该接口不支持 -> 标记 NA
运行：python scripts/value_universe.py
"""
import akshare as ak
import sqlite3, os, sys, time, warnings, csv
warnings.filterwarnings('ignore')

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SPOT_CSV = os.path.join(ROOT, 'data', 'spot_prices.csv')
RES_CSV  = os.path.join(ROOT, 'data', 'valuation_full.csv')
LOG      = os.path.join(ROOT, 'data', 'valuation_log.txt')

def log(msg):
    line = time.strftime('%H:%M:%S') + ' ' + msg
    print(line, flush=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')

def pref(code):
    if code.startswith('60') or code.startswith('68') or code.startswith('9'):
        return 'SH' + code
    if code.startswith('8') or code.startswith('4') or code.startswith('92'):
        return 'BJ' + code
    return 'SZ' + code

def fetch_spot():
    if os.path.exists(SPOT_CSV):
        log('spot cache exists, load %s' % SPOT_CSV)
        rows = []
        with open(SPOT_CSV, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                try:
                    r['price'] = float(r['price'])
                except Exception:
                    r['price'] = None
                rows.append(r)
        return rows
    log('fetch sina spot (full market)...')
    sp = None
    for attempt in range(10):
        try:
            sp = ak.stock_zh_a_spot()
            if sp is not None and len(sp) > 1000:
                break
            sp = None
        except Exception as e:
            log('spot err %s retry %d' % (repr(e)[:80], attempt))
        time.sleep(8)
    if sp is None:
        raise RuntimeError('sina spot failed after retries')
    rows = []
    for _, r in sp.iterrows():
        code = str(r.iloc[0]).lower()          # e.g. sh600519 / bj920000
        name = str(r.iloc[1])
        try:
            price = float(r.iloc[2])
        except Exception:
            price = None
        dig = ''.join(ch for ch in code if ch.isdigit())
        rows.append({'code': dig, 'raw': code, 'name': name, 'price': price})
    with open(SPOT_CSV, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=['code','raw','name','price'])
        w.writeheader(); w.writerows(rows)
    log('spot saved %d rows' % len(rows))
    return rows

def latest_annual_col(df):
    cols = [c for c in df.columns if isinstance(c, str) and len(c) == 8 and c.isdigit()]
    annual = sorted([c for c in cols if c.endswith('1231')], reverse=True)
    if annual:
        return annual[0]
    return sorted(cols, reverse=True)[0] if cols else None

def get_val(df, ind, col):
    row = df[df['指标'] == ind]
    if len(row) == 0 or col is None:
        return None
    try:
        v = row[col].iloc[0]
        if v is None: return None
        v = float(v)
        if v != v:  # nan
            return None
        return v
    except Exception:
        return None

def extract(code):
    df = ak.stock_financial_abstract(symbol=pref(code))
    if df is None or len(df) == 0:
        return None
    col = latest_annual_col(df)
    eps  = get_val(df, '基本每股收益', col)
    bvps = get_val(df, '每股净资产', col)
    sps  = get_val(df, '每股营业总收入', col)
    np_  = get_val(df, '归母净利润', col)
    rev  = get_val(df, '营业总收入', col)
    dedu = get_val(df, '扣非净利润', col)
    roe  = get_val(df, '净资产收益率(ROE)', col)
    return {'period': col, 'eps': eps, 'bvps': bvps, 'sps': sps,
            'net_profit': np_, 'revenue': rev, 'dedu_net_profit': dedu, 'roe': roe}

def main():
    CAP = int(os.environ.get('VU_CAP', '0'))
    LOCK = os.path.join(ROOT, 'data', 'valuation.lock')
    if os.path.exists(LOCK):
        age = time.time() - os.path.getmtime(LOCK)
        if age < 300:
            log('lock fresh (<5min), another instance likely running -> exit')
            return
        else:
            log('stale lock (%.0fs), continue' % age)
    with open(LOCK, 'w') as f:
        f.write(str(os.getpid()))
    spot = fetch_spot()
    price_map = {r['code']: r for r in spot}
    done = set()
    if os.path.exists(RES_CSV):
        with open(RES_CSV, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                done.add(r['code'])
    log('already done %d, total %d' % (len(done), len(spot)))
    fields = ['code','name','price','period','eps','bvps','sps','pe','pb','ps',
              'net_profit','revenue','dedu_net_profit','roe','status']
    fresh = not os.path.exists(RES_CSV)
    with open(RES_CSV, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        if fresh: w.writeheader()
        cnt = 0
        for r in spot:
            code = r['code']
            if code in done:
                continue
            price = r['price']
            rec = {'code': code, 'name': r['name'], 'price': price,
                   'period':'', 'eps':'', 'bvps':'', 'sps':'', 'pe':'', 'pb':'',
                   'ps':'', 'net_profit':'', 'revenue':'', 'dedu_net_profit':'',
                   'roe':'', 'status':''}
            if price is None:
                rec['status'] = 'NO_PRICE'; w.writerow(rec); f.flush(); continue
            d = None
            for _ in range(3):
                try:
                    d = extract(code)
                    break
                except Exception as e:
                    err = repr(e)[:60]; time.sleep(1.5)
            if d is None:
                rec['status'] = 'ERR:' + err
                w.writerow(rec); f.flush(); time.sleep(0.3); continue
            if d is None:
                rec['status'] = 'NA'
            else:
                eps, bvps, sps = d['eps'], d['bvps'], d['sps']
                pe = round(price/eps, 2) if eps and eps > 0 else (round(price/eps,2) if eps and eps<0 else '')
                pb = round(price/bvps, 2) if bvps and bvps > 0 else (round(price/bvps,2) if bvps and bvps<0 else '')
                ps = round(price/sps, 2) if sps and sps > 0 else ''
                rec.update({'period': d['period'], 'eps': eps, 'bvps': bvps, 'sps': sps,
                            'pe': pe, 'pb': pb, 'ps': ps,
                            'net_profit': d['net_profit'], 'revenue': d['revenue'],
                            'dedu_net_profit': d['dedu_net_profit'], 'roe': d['roe'],
                            'status': 'OK'})
            w.writerow(rec); f.flush()
            cnt += 1
            if cnt % 50 == 0:
                log('progress %d done, last=%s' % (cnt, code))
            if CAP and cnt >= CAP:
                log('CAP %d reached, stop' % CAP); break
                with open(LOCK, 'w') as f:
                    f.write(str(os.getpid()))
            time.sleep(0.25)
    log('FINISHED')

if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        log('FATAL ' + repr(e))
        import traceback
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(traceback.format_exc())
        raise
