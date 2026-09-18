"""鍏ㄥ競鍦烘壒閲忎笅杞藉櫒 鈥?K绾?+ 鍏ㄩ噺璐㈠姟锛屾敮鎸佹柇鐐圭画浼?
璁捐鐩爣: 鍏ˋ鑲?~5500鍙紝K绾胯繎1骞?+ 鍏ㄩ噺80椤硅储鍔°€?鎬昏€楁椂: K绾縹10鍒嗛挓 + 璐㈠姟~5灏忔椂銆?
鍋ュ．鎬?
  - 鏂偣缁紶: 姣忓彧瀹屾垚绔嬪嵆鍐欏簱锛岃褰曞埌 data/download_progress.json
  - 闄愰€? 姣忓彧涔嬮棿 sleep锛岄伩鍏嶈鍙嶇埇灏佺
  - 閲嶈瘯: 鍗曞彧澶辫触閲嶈瘯3娆?  - 杩涘害鍙: 姣?0鍙墦鍗拌繘搴︼紝鍙殢鏃?Ctrl+C 鍚庨噸璺戠画浼?  - 涓ら樁娈? --phase kline (蹇? / --phase financial (鎱? / --phase both

鐢ㄦ硶:
  python scripts/download_all.py --phase kline        # 浠匥绾?10鍒嗛挓)
  python scripts/download_all.py --phase financial    # 浠呰储鍔?5灏忔椂)
  python scripts/download_all.py --phase both         # 鍏ㄩ儴
  python scripts/download_all.py --phase kline --limit 100  # 娴嬭瘯鐢紝鍙笅100鍙?  python scripts/download_all.py --resume             # 缁紶(榛樿灏辨槸缁紶)
"""
import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from typing import List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from quant.data.cache import create_cache

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("download_all")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROGRESS_FILE = os.path.join(ROOT, 'data', 'download_progress.json')
KLINE_COUNT = 250  # 杩?骞寸害250涓氦鏄撴棩


def load_progress() -> dict:
    """鍔犺浇杩涘害鏂囦欢 {kline_done: [...], financial_done: [...], started_at, ...}"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {'kline_done': [], 'financial_done': [], 'universe': [], 'started_at': None}


def save_progress(prog: dict):
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    prog['updated_at'] = datetime.now().isoformat(timespec='seconds')
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(prog, f, ensure_ascii=False)


def get_full_universe() -> List[str]:
    """鑾峰彇鍏ˋ鑲′唬鐮佹竻鍗?(~5500鍙?"""
    try:
        import akshare as ak
        from quant.data.universe import filter_trade_universe_codes
        df = ak.stock_info_a_code_name()
        codes = df['code'].astype(str).tolist()
        # 杩囨护: 鍙繚鐣?浣嶆暟瀛椼€佸墧闄ら€€甯?ST甯?閫€'瀛?
        valid = filter_trade_universe_codes(codes)
        logger.info(f"A-share universe: {len(valid)} symbols (raw={len(codes)})")
        return valid
    except Exception as e:
        logger.error(f"failed to fetch A-share universe, fallback to built-in seed: {e}")
        from quant.data.tencent_source import load_universe
        from quant.data.universe import filter_trade_universe_codes
        return filter_trade_universe_codes(load_universe())


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?#  闃舵1: K绾夸笅杞?(鑵捐璐㈢粡涓婚摼璺紱鏂版氮娆＄骇锛汢aostock 澶囩敤)
def download_klines(codes: List[str], cache, done: set) -> dict:
    """涓嬭浇K绾匡紝杩斿洖 {ok, skip, err}

    涓诲姏婧愯吘璁储缁忥紱鏂版氮璐㈢粡浣滀负娆＄骇婧愶紱Baostock 浠呬綔涓哄鐢ㄥ厹搴曘€?    """
    from quant.data.kline_reconciler import fetch_kline_dual
    from quant.data.tencent_source import normalize_code
    from quant.data.baostock_source import fetch_klines as bs_fetch, logout

    todo = [c for c in codes if c not in done]
    logger.info(f"=== kline phase: pending={len(todo)} done={len(done)} ===")
    logger.info("  source chain: TdxQuant primary, Tencent cross-check, Baostock fallback")

    ok = err = 0
    t0 = time.time()
    try:
        for i, code in enumerate(todo, 1):
            code = normalize_code(code)
            bars = None
            # TdxQuant primary, Tencent daily cross-check, Baostock final fallback.
            for attempt in range(2):
                try:
                    checked = fetch_kline_dual(code, count=KLINE_COUNT, period="1d")
                    bars = checked.get("bars") if checked.get("ok") else []
                    if bars:
                        break
                except Exception as e:
                    if attempt == 1:
                        logger.debug(f"[{code}] tdx/tencent failed: {e}")
                    time.sleep(0.5)
            if not bars:
                try:
                    bars = bs_fetch(code, count=KLINE_COUNT)
                except Exception as e:
                    logger.debug(f"[{code}] baostock fallback failed: {e}")
            if bars:
                cache.set(f'kline:{code}:d', bars)
                done.add(code)
                ok += 1
            else:
                err += 1

            # 杩涘害鏃ュ織 + 鎸佷箙鍖?(姣?0鍙?
            if i % 50 == 0 or i == len(todo):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(todo) - i) / rate / 60 if rate > 0 else 0
                logger.info(f"  kline [{i}/{len(todo)}] ok={ok} err={err} "
                            f"({rate:.2f}/s, ETA {eta:.0f} min)")
                prog = load_progress()
                prog['kline_done'] = sorted(done)
                save_progress(prog)

            time.sleep(0.1)
    finally:
        logout()  # 纭繚閫€鍑?baostock 鐧诲綍

    elapsed = time.time() - t0
    logger.info(f"kline phase finished: ok={ok} err={err}, {elapsed/60:.1f} min")
    return {'ok': ok, 'err': err}


# 鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺愨晲鈺?#  闃舵2: 璐㈠姟涓嬭浇 (鎱紝~5灏忔椂)
def download_financials(codes: List[str], cache, done: set) -> dict:
    """涓嬭浇鍏ㄩ噺80椤硅储鍔℃暟鎹紝杩斿洖 {ok, skip, err}"""
    from quant.data.financial_reconciler import fetch_financial_crosscheck

    todo = [c for c in codes if c not in done]
    logger.info(f"=== financial phase: pending={len(todo)} done={len(done)} ===")

    ok = skip = err = 0
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        code = str(code).split('.')[0]
        # Retry each symbol a few times.
        success = False
        for attempt in range(3):
            try:
                result = fetch_financial_crosscheck(code)
                if not result.get("ok"):
                    skip += 1
                    break
                cache.set(f'fin:crosscheck:{code}', result)
                if result.get("akshare_records"):
                    cache.set(f'fin:abstract:{code}', result["akshare_records"])
                else:
                    cache.set(f'fin:abstract:{code}', [result.get("merged") or {}])
                if result.get("tdx_raw"):
                    cache.set(f'fin:tdx:{code}', result["tdx_raw"])
                if result.get("tushare_records"):
                    cache.set(f'fin:tushare:{code}', result["tushare_records"])
                done.add(code)
                success = True
                break
            except Exception as e:
                if attempt == 2:
                    logger.debug(f"[{code}] financial failed: {e}")
                time.sleep(1.0)
        if success:
            ok += 1
        elif not (skip > ok + err):  # 宸茶skip鐨勪笉鍐嶈err
            if not success:
                # 鍒ゆ柇鏄惁琚玸kip鍒嗘敮澶勭悊
                pass

        # Progress log and checkpoint.
        if i % 20 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate / 60 if rate > 0 else 0
            logger.info(f"  financial [{i}/{len(todo)}] ok={ok} skip={skip} err={err} "
                        f"({rate:.2f}/s, ETA {eta:.0f} min)")
            prog = load_progress()
            prog['financial_done'] = sorted(done)
            save_progress(prog)

        time.sleep(0.3)  # 璐㈠姟鎺ュ彛鏇翠弗鏍硷紝闄愰€熸洿淇濆畧

    elapsed = time.time() - t0
    logger.info(f"financial phase finished: ok={ok} skip={skip} err={err}, {elapsed/60:.1f} min")
    return {'ok': ok, 'skip': skip, 'err': err}


def main():
    ap = argparse.ArgumentParser(description='鍏ㄥ競鍦烘壒閲忎笅杞?(K绾?璐㈠姟, 鏂偣缁紶)')
    ap.add_argument('--phase', choices=['kline', 'financial', 'both'], default='both',
                    help='涓嬭浇闃舵: kline(蹇? / financial(鎱? / both(榛樿)')
    ap.add_argument('--limit', type=int, default=0, help='闄愬埗涓嬭浇鏁伴噺(0=鍏ㄩ儴, 娴嬭瘯鐢?')
    ap.add_argument('--codes', type=str, default='', help='鑷畾涔変唬鐮佸垪琛?閫楀彿鍒嗛殧)')
    ap.add_argument('--fresh', action='store_true', help='蹇界暐杩涘害锛岄噸鏂颁笅杞?鍗遍櫓)')
    args = ap.parse_args()

    # 1. Determine stock universe.
    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
        codes = [c for c in codes if len(c) == 6 and c.isdigit()]
    else:
        codes = get_full_universe()
    if args.limit > 0:
        codes = codes[:args.limit]
    logger.info(f"target stocks: {len(codes)}")

    # 2. Load or initialize progress.
    prog = load_progress()
    if args.fresh or not prog.get('started_at'):
        prog = {'kline_done': [], 'financial_done': [], 'universe': codes,
                'started_at': datetime.now().isoformat(timespec='seconds')}
        save_progress(prog)
    kline_done = set(prog.get('kline_done', []))
    fin_done = set(prog.get('financial_done', []))
    logger.info(f"completed: kline={len(kline_done)} financial={len(fin_done)}")

    # 3. 鍐欏叆鑲＄エ姹?鍚嶇О鍒扮紦瀛?渚涘墠绔娇鐢?
    cache = create_cache()
    cache.set('stock:universe', codes)

    # 4. 鎵ц涓嬭浇
    results = {}
    if args.phase in ('kline', 'both'):
        results['kline'] = download_klines(codes, cache, kline_done)

    if args.phase in ('financial', 'both'):
        results['financial'] = download_financials(codes, cache, fin_done)

    # 5. Summary.
    logger.info("=" * 55)
    logger.info("download finished")
    kline_keys = len(cache.keys('kline:*:d'))
    fin_keys = len(cache.keys('fin:abstract:*'))
    logger.info(f"  kline: {kline_keys} stocks")
    logger.info(f"  financial: {fin_keys} stocks")
    logger.info(f"  cache keys: {cache.size()}")
    import os as _os
    db = os.path.join(ROOT, 'data', 'quant.db')
    if _os.path.exists(db):
        logger.info(f"  database: {_os.path.getsize(db)/1024/1024:.1f} MB")
    logger.info("=" * 55)


if __name__ == '__main__':
    main()

