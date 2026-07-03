"""全市场批量下载器 — K线 + 全量财务，支持断点续传

设计目标: 全A股 ~5500只，K线近1年 + 全量80项财务。
总耗时: K线~10分钟 + 财务~5小时。

健壮性:
  - 断点续传: 每只完成立即写库，记录到 data/download_progress.json
  - 限速: 每只之间 sleep，避免被反爬封禁
  - 重试: 单只失败重试3次
  - 进度可见: 每50只打印进度，可随时 Ctrl+C 后重跑续传
  - 两阶段: --phase kline (快) / --phase financial (慢) / --phase both

用法:
  python scripts/download_all.py --phase kline        # 仅K线(10分钟)
  python scripts/download_all.py --phase financial    # 仅财务(5小时)
  python scripts/download_all.py --phase both         # 全部
  python scripts/download_all.py --phase kline --limit 100  # 测试用，只下100只
  python scripts/download_all.py --resume             # 续传(默认就是续传)
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
KLINE_COUNT = 250  # 近1年约250个交易日


def load_progress() -> dict:
    """加载进度文件 {kline_done: [...], financial_done: [...], started_at, ...}"""
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
    """获取全A股代码清单 (~5500只)"""
    try:
        import akshare as ak
        df = ak.stock_info_a_code_name()
        codes = df['code'].astype(str).tolist()
        # 过滤: 只保留6位数字、剔除退市(ST带'退'字)
        valid = [c for c in codes if len(c) == 6 and c.isdigit()]
        logger.info(f"全A股清单: {len(valid)} 只 (过滤前 {len(codes)})")
        return valid
    except Exception as e:
        logger.error(f"获取全A股清单失败，回退到内置种子: {e}")
        from quant.data.tencent_source import load_universe
        return load_universe()


# ═══════════════════════════════════════════════════════════
#  阶段1: K线下载 (baostock 主力，~2小时；腾讯被封禁时备用)
# ═══════════════════════════════════════════════════════════
def download_klines(codes: List[str], cache, done: set) -> dict:
    """下载K线，返回 {ok, skip, err}

    主力源 baostock (反爬宽松、含成交额)；腾讯作为单股快速备选。
    """
    from quant.data.baostock_source import fetch_klines as bs_fetch, logout
    from quant.data.tencent_source import fetch_klines as tx_fetch, normalize_code

    todo = [c for c in codes if c not in done]
    logger.info(f"=== K线阶段: {len(todo)} 只待下载 (已完成 {len(done)}) ===")
    logger.info("  主力源: baostock (含成交额, 反爬宽松)")

    ok = err = 0
    t0 = time.time()
    try:
        for i, code in enumerate(todo, 1):
            code = normalize_code(code)
            bars = None
            # baostock 重试2次
            for attempt in range(2):
                try:
                    bars = bs_fetch(code, count=KLINE_COUNT)
                    if bars:
                        break
                except Exception as e:
                    if attempt == 1:
                        logger.debug(f"[{code}] baostock失败: {e}")
                    time.sleep(0.5)
            # baostock 失败则试腾讯(单只腾讯通常还能用)
            if not bars:
                try:
                    bars = tx_fetch(code, count=KLINE_COUNT)
                except Exception:
                    pass
            if bars:
                cache.set(f'kline:{code}:d', bars)
                done.add(code)
                ok += 1
            else:
                err += 1

            # 进度日志 + 持久化 (每50只)
            if i % 50 == 0 or i == len(todo):
                elapsed = time.time() - t0
                rate = i / elapsed if elapsed > 0 else 0
                eta = (len(todo) - i) / rate / 60 if rate > 0 else 0
                logger.info(f"  K线 [{i}/{len(todo)}] ok={ok} err={err} "
                            f"({rate:.2f}/s, ETA {eta:.0f}分)")
                prog = load_progress()
                prog['kline_done'] = sorted(done)
                save_progress(prog)

            time.sleep(0.1)  # baostock 礼貌限速
    finally:
        logout()  # 确保退出 baostock 登录

    elapsed = time.time() - t0
    logger.info(f"K线阶段完成: ok={ok} err={err}, {elapsed/60:.1f}分钟")
    return {'ok': ok, 'err': err}


# ═══════════════════════════════════════════════════════════
#  阶段2: 财务下载 (慢，~5小时)
# ═══════════════════════════════════════════════════════════
def download_financials(codes: List[str], cache, done: set) -> dict:
    """下载全量80项财务数据，返回 {ok, skip, err}"""
    from quant.data.akshare_source import fetch_financial_abstract

    todo = [c for c in codes if c not in done]
    logger.info(f"=== 财务阶段: {len(todo)} 只待下载 (已完成 {len(done)}) ===")

    ok = skip = err = 0
    t0 = time.time()
    for i, code in enumerate(todo, 1):
        code = str(code).split('.')[0]
        # 重试3次
        success = False
        for attempt in range(3):
            try:
                df = fetch_financial_abstract(code)  # 全量80项
                if df is None or df.empty:
                    skip += 1
                    break
                cache.set(f'fin:abstract:{code}', df.to_dict(orient='records'))
                done.add(code)
                success = True
                break
            except Exception as e:
                if attempt == 2:
                    logger.debug(f"[{code}] 财务失败: {e}")
                time.sleep(1.0)
        if success:
            ok += 1
        elif not (skip > ok + err):  # 已计skip的不再计err
            if not success:
                # 判断是否被skip分支处理
                pass

        # 进度日志 + 持久化
        if i % 20 == 0 or i == len(todo):
            elapsed = time.time() - t0
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(todo) - i) / rate / 60 if rate > 0 else 0
            logger.info(f"  财务 [{i}/{len(todo)}] ok={ok} skip={skip} err={err} "
                        f"({rate:.2f}/s, ETA {eta:.0f}分)")
            prog = load_progress()
            prog['financial_done'] = sorted(done)
            save_progress(prog)

        time.sleep(0.3)  # 财务接口更严格，限速更保守

    elapsed = time.time() - t0
    logger.info(f"财务阶段完成: ok={ok} skip={skip} err={err}, {elapsed/60:.1f}分钟")
    return {'ok': ok, 'skip': skip, 'err': err}


def main():
    ap = argparse.ArgumentParser(description='全市场批量下载 (K线+财务, 断点续传)')
    ap.add_argument('--phase', choices=['kline', 'financial', 'both'], default='both',
                    help='下载阶段: kline(快) / financial(慢) / both(默认)')
    ap.add_argument('--limit', type=int, default=0, help='限制下载数量(0=全部, 测试用)')
    ap.add_argument('--codes', type=str, default='', help='自定义代码列表(逗号分隔)')
    ap.add_argument('--fresh', action='store_true', help='忽略进度，重新下载(危险)')
    args = ap.parse_args()

    # 1. 确定股票池
    if args.codes:
        codes = [c.strip() for c in args.codes.split(',') if c.strip()]
        codes = [c for c in codes if len(c) == 6 and c.isdigit()]
    else:
        codes = get_full_universe()
    if args.limit > 0:
        codes = codes[:args.limit]
    logger.info(f"目标股票: {len(codes)} 只")

    # 2. 加载/初始化进度
    prog = load_progress()
    if args.fresh or not prog.get('started_at'):
        prog = {'kline_done': [], 'financial_done': [], 'universe': codes,
                'started_at': datetime.now().isoformat(timespec='seconds')}
        save_progress(prog)
    kline_done = set(prog.get('kline_done', []))
    fin_done = set(prog.get('financial_done', []))
    logger.info(f"已完成: K线 {len(kline_done)} / 财务 {len(fin_done)}")

    # 3. 写入股票池+名称到缓存(供前端使用)
    cache = create_cache()
    cache.set('stock:universe', codes)

    # 4. 执行下载
    results = {}
    if args.phase in ('kline', 'both'):
        results['kline'] = download_klines(codes, cache, kline_done)

    if args.phase in ('financial', 'both'):
        results['financial'] = download_financials(codes, cache, fin_done)

    # 5. 汇总
    logger.info("=" * 55)
    logger.info("下载完成!")
    kline_keys = len(cache.keys('kline:*:d'))
    fin_keys = len(cache.keys('fin:abstract:*'))
    logger.info(f"  K线: {kline_keys} 只")
    logger.info(f"  财务: {fin_keys} 只")
    logger.info(f"  总缓存键: {cache.size()}")
    import os as _os
    db = os.path.join(ROOT, 'data', 'quant.db')
    if _os.path.exists(db):
        logger.info(f"  数据库: {_os.path.getsize(db)/1024/1024:.1f} MB")
    logger.info("=" * 55)


if __name__ == '__main__':
    main()
