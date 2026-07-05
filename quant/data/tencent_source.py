"""唯一数据源：腾讯财经 (qt.gtimg.cn / web.ifzq.gtimg.cn)

唯一口径：前复权日 K (qfq)
为什么前复权:
  1. 历史数据与今日价格连续（无除权跳变）
  2. 适合直接做因子计算、回测
  3. 与同花顺/雪球等主流终端口径一致

API:
  历史 K 线: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param=<sym>,day,,,<count>,qfq
            sym 形如 sh600519 / sz000001
  实时报价: http://qt.gtimg.cn/q=sh600519,sz000001,...
            返回 GBK 编码、半角分号分隔的字符串
"""
import json
import time
from typing import List, Dict, Optional, Iterable
import urllib.request
import urllib.error

from quant.data.schema import validate_bar, validate_series, validate_quote, SchemaError

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AlphaCouncil2/1.0"
TIMEOUT = 8


def _exchange_prefix(code: str) -> str:
    """根据 6 位代码首位推断交易所前缀"""
    c = code.split('.')[0]
    if len(c) != 6 or not c.isdigit():
        raise ValueError(f"invalid 6-digit code: {code!r}")
    first = c[0]
    if first in ('6', '9'):  return 'sh'
    if first in ('0', '3'):  return 'sz'
    if first in ('4', '8'):  return 'bj'
    raise ValueError(f"cannot determine exchange for code: {code!r}")


def normalize_code(code: str) -> str:
    """统一返回 6 位数字代码（不带交易所后缀）"""
    return code.split('.')[0]


def tencent_symbol(code: str) -> str:
    """转为腾讯接口要求的格式: sh600519 / sz000001 / bj430047"""
    c = normalize_code(code)
    return _exchange_prefix(c) + c


def _http_get(url: str, *, encoding: str = 'utf-8') -> str:
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT, 'Referer': 'http://gu.qq.com/'})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read().decode(encoding, errors='replace')


# ─── 历史 K 线 ──────────────────────────────────────────────

def fetch_klines(code: str, count: int = 640) -> List[Dict]:
    """拉取前复权日 K 线，返回符合 schema 的 list[dict]

    腾讯接口返回 JSON 结构（关键字段 qfqday，没有则 day）:
      {"code":0, "data": {"<sym>": {"qfqday": [["2024-01-02","94.50","95.00","95.20","94.30","12345"], ...]}}}

    每条数组: [date, open, close, high, low, volume]   ← 注意顺序
    """
    sym = tencent_symbol(code)
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={sym},day,,,{count},qfq"
    text = _http_get(url)
    try:
        data = json.loads(text)
    except Exception as e:
        raise SchemaError(f"[{code}] tencent kline JSON parse failed: {e}; head={text[:120]}")

    if data.get('code') != 0:
        raise SchemaError(f"[{code}] tencent returned code={data.get('code')} msg={data.get('msg')}")

    sym_data = (data.get('data') or {}).get(sym) or {}
    rows = sym_data.get('qfqday') or sym_data.get('day') or []
    if not rows:
        return []

    bars = []
    for r in rows:
        if len(r) < 6:
            continue
        d, o, c, h, l, v = r[0], r[1], r[2], r[3], r[4], r[5]
        # 腾讯日K接口通常只返回 6 字段(无成交额)；少数情况 row[6+] 含成交额(万元)
        amount = 0.0
        for cand in r[6:]:
            if isinstance(cand, (int, float)):
                amount = float(cand)
                break
            if isinstance(cand, str):
                try:
                    amount = float(cand)
                    break
                except ValueError:
                    continue
        try:
            date_str = str(d).replace('-', '')
            vol_int = int(float(v))       # 手
            close_f = float(c)
            if amount:
                # 腾讯成交额单位是万元 -> 元
                amount_yuan = amount * 10000
            else:
                # 接口未返回成交额时，用 成交量(手)×100 × 收盘价 估算(元)
                amount_yuan = vol_int * 100 * close_f
            bar = {
                'date':   date_str,
                'open':   float(o),
                'high':   float(h),
                'low':    float(l),
                'close':  close_f,
                'volume': vol_int,
                'amount': amount_yuan,
            }
            bars.append(validate_bar(bar))
        except SchemaError:
            continue   # 单根坏数据跳过

    return validate_series(bars, code=code)


# ─── 实时行情 ──────────────────────────────────────────────

# 腾讯 v_<sym>="..." 字段顺序（关键字段）:
#  [0]'',[1]name,[2]code,[3]price,[4]prev_close,[5]open,[6]volume,
#  [7]buy_vol,[8]sell_vol,...,[30]date(YYYYMMDDHHMMSS),...,[33]high,[34]low,...,[37]amount(万)
_QT_FIELDS = {
    'name': 1, 'code': 2, 'price': 3, 'prev_close': 4, 'open': 5,
    'volume': 6, 'date_time': 30, 'high': 33, 'low': 34, 'amount': 37,
}


def _parse_qt_line(line: str) -> Optional[Dict]:
    """解析单条 v_<sym>="<gbk-data>"; 行"""
    if '=' not in line or '"' not in line:
        return None
    try:
        var, payload = line.split('=', 1)
        sym = var.replace('v_', '').strip()
        body = payload.strip().strip(';').strip('"')
        parts = body.split('~')
        if len(parts) < 38:
            return None
        ts = parts[_QT_FIELDS['date_time']] or ''
        # ts 形如 "20260609145923"
        return validate_quote({
            'code':       sym[2:] if sym[:2] in ('sh', 'sz', 'bj') else sym,
            'name':       parts[_QT_FIELDS['name']],
            'price':      float(parts[_QT_FIELDS['price']]),
            'open':       float(parts[_QT_FIELDS['open']]),
            'high':       float(parts[_QT_FIELDS['high']]),
            'low':        float(parts[_QT_FIELDS['low']]),
            'prev_close': float(parts[_QT_FIELDS['prev_close']]),
            'volume':     int(float(parts[_QT_FIELDS['volume']])),
            'amount':     float(parts[_QT_FIELDS['amount']]) if parts[_QT_FIELDS['amount']] else 0.0,
            'timestamp':  ts,
        })
    except (SchemaError, ValueError, IndexError):
        return None


def fetch_quotes(codes: Iterable[str], batch: int = 50) -> Dict[str, Dict]:
    """批量拉实时行情。codes 任意数量，自动分批。返回 {code: quote_dict}"""
    code_list = [normalize_code(c) for c in codes]
    out: Dict[str, Dict] = {}
    for i in range(0, len(code_list), batch):
        chunk = code_list[i:i+batch]
        syms = ','.join(tencent_symbol(c) for c in chunk)
        try:
            text = _http_get(f"http://qt.gtimg.cn/q={syms}", encoding='gbk')
        except Exception:
            continue
        for line in text.split('\n'):
            q = _parse_qt_line(line.strip())
            if q:
                out[q['code']] = q
        time.sleep(0.05)  # 礼貌限速
    return out


# ─── 股票池 ────────────────────────────────────────────────

# 腾讯没有官方"全市场代码列表"接口；我们用一份精选种子列表
# 实际运行时会通过 fetch_quotes 失败回退过滤出有效代码
SEED_UNIVERSE_HINT = """\
通过 seed.py / download_all.py 主动维护股票池；
首次启动时使用内置 SEED_CODES（沪深 300 + 创业板 50 + 科创板 50）；
后续可通过追加 codes.txt 扩展。
"""


def load_universe(extra_file: Optional[str] = None) -> List[str]:
    """加载股票池：内置种子 + 可选 codes.txt 扩展"""
    seed = _builtin_seed()
    if extra_file:
        try:
            with open(extra_file, 'r', encoding='utf-8') as f:
                extra = [ln.strip().split('#')[0].strip() for ln in f]
                extra = [normalize_code(c) for c in extra if c and not c.startswith('#')]
                seed.extend(extra)
        except FileNotFoundError:
            pass
    # 去重 + 校验
    seen = set()
    out = []
    for c in seed:
        c = normalize_code(c)
        if len(c) != 6 or not c.isdigit():
            continue
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
    return out


def _builtin_seed() -> List[str]:
    """沪深 300 / 中证 500 / 创业板 / 科创板 精选"""
    # 上证主板（含蓝筹）
    sh = [
        '600000', '600009', '600010', '600011', '600015', '600016', '600018', '600019',
        '600025', '600027', '600028', '600029', '600030', '600031', '600036', '600048',
        '600050', '600061', '600066', '600085', '600089', '600100', '600104', '600109',
        '600111', '600115', '600118', '600132', '600150', '600160', '600170', '600183',
        '600188', '600196', '600219', '600233', '600271', '600276', '600297', '600299',
        '600309', '600332', '600346', '600352', '600362', '600369', '600372', '600383',
        '600406', '600426', '600436', '600438', '600460', '600482', '600487', '600489',
        '600519', '600547', '600570', '600585', '600588', '600600', '600606', '600637',
        '600655', '600660', '600690', '600703', '600733', '600741', '600745', '600754',
        '600760', '600795', '600803', '600809', '600837', '600848', '600875', '600885',
        '600886', '600887', '600893', '600900', '600905', '600918', '600919', '600926',
        '600958', '600989', '600999', '601006', '601009', '601012', '601021', '601066',
        '601088', '601100', '601111', '601138', '601155', '601162', '601166', '601169',
        '601186', '601216', '601225', '601229', '601231', '601238', '601258', '601288',
        '601318', '601319', '601328', '601336', '601360', '601377', '601390', '601398',
        '601600', '601601', '601607', '601618', '601628', '601633', '601658', '601668',
        '601669', '601688', '601698', '601728', '601766', '601788', '601800', '601816',
        '601818', '601838', '601857', '601865', '601877', '601878', '601881', '601888',
        '601898', '601899', '601901', '601916', '601919', '601933', '601939', '601985',
        '601988', '601989', '601995', '601998',
    ]
    # 深证主板 + 中小板
    sz_main = [
        '000001', '000002', '000063', '000066', '000100', '000157', '000333', '000338',
        '000408', '000425', '000538', '000568', '000596', '000625', '000651', '000661',
        '000708', '000725', '000768', '000776', '000783', '000786', '000792', '000800',
        '000826', '000858', '000876', '000895', '000938', '000963', '000977', '000999',
        '001979', '002001', '002007', '002008', '002024', '002027', '002032', '002049',
        '002050', '002120', '002129', '002142', '002146', '002180', '002230', '002236',
        '002241', '002252', '002271', '002304', '002311', '002352', '002371', '002410',
        '002414', '002415', '002460', '002463', '002466', '002475', '002493', '002508',
        '002555', '002594', '002600', '002601', '002602', '002607', '002624', '002673',
        '002714', '002736', '002841', '002916', '002938',
    ]
    # 创业板
    gem = [
        '300003', '300014', '300015', '300033', '300059', '300122', '300124', '300142',
        '300144', '300223', '300253', '300274', '300316', '300347', '300408', '300413',
        '300433', '300450', '300498', '300601', '300628', '300661', '300750', '300751',
        '300759', '300760', '300769', '300782', '300832', '300866', '300896', '300919',
        '300979', '300999',
    ]
    # 科创板
    star = [
        '688008', '688009', '688012', '688036', '688041', '688065', '688082', '688111',
        '688126', '688169', '688180', '688187', '688223', '688256', '688271', '688303',
        '688321', '688363', '688396', '688561', '688599', '688981',
    ]
    return sh + sz_main + gem + star
