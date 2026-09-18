/**
 * Unified data-management control plane.
 *
 * Read-heavy status and health requests reuse data_runner.py so browser
 * polling does not start a new Python interpreter for every request.
 * Process lifecycle remains owned by the dedicated managers.
 */
import { json, log, readBody } from '../http-utils.mjs';
import { PersistentRunner } from '../persistent_runner.mjs';
import {
  daemonMeta,
  startDaemon,
  stopDaemon,
} from '../sync_service_manager.mjs';
import { getUpdateProgress, startUpdate, stopUpdate } from '../update_manager.mjs';
import { marketStreamService } from '../market-stream-service.mjs';

const runner = new PersistentRunner('sync_runner.py');

async function callDataRunner(body, timeout = 30_000) {
  const result = await runner.call(body, timeout);
  if (!result || result.success !== true) {
    throw new Error(result?.error || `data runner action failed: ${body.action}`);
  }
  return result;
}

export async function handleSync(req, res) {
  try {
    const body = req.method === 'POST' ? await readBody(req) : {};
    const action = body.action || 'status';

    if (action === 'status') {
      const result = await callDataRunner({ action: 'sync_status' });
      const state = result.data || {};
      return json(res, 200, {
        success: true,
        data: {
          ...state,
          db: {
            stock_count: state.universe_size || 0,
            stocks_with_bars: state.kline_count || 0,
            stocks_with_bars_total: state.kline_total_count || 0,
            stocks_outside_universe: state.kline_extra_count || 0,
            stocks_missing: Math.max(
              0,
              Number(state.universe_size || 0) - Number(state.kline_count || 0),
            ),
            bar_count: state.sample_avg_bars || 0,
            date_range: state.latest_date
              ? { min: null, max: state.latest_date }
              : null,
            source: state.storage?.backend || 'unknown',
            key_count: state.storage?.key_count || 0,
            db_bytes: state.storage?.db_bytes || 0,
          },
          sources: state.source_health?.sources || [],
          data_date: state.latest_date || null,
          current_task: state.update?.running ? state.update : null,
        },
      });
    }

    if (action === 'health') {
      const result = await callDataRunner(
        { action: 'sync_health', force: body.force === true },
        60_000,
      );
      return json(res, 200, result);
    }

    if (action === 'catalog') {
      const result = await callDataRunner({ action: 'sync_catalog' });
      return json(res, 200, result);
    }

    if (action === 'stream_status') {
      return json(res, 200, { success: true, data: marketStreamService.snapshot() });
    }

    if (action === 'start') {
      const result = startDaemon({ codes: body.codes || [] });
      return json(res, result.success ? 200 : 409, result);
    }

    if (action === 'stop') {
      const result = stopDaemon();
      return json(res, result.success ? 200 : 409, result);
    }

    if (action === 'progress' || action === 'daemon_status') {
      const data = daemonMeta();
      return json(res, 200, {
        success: true,
        data: {
          ...data,
          realtime_fresh: data.heartbeat_fresh,
          watch_count: data.watch_count || 0,
          trading: {
            is_trading: !!data.is_trading,
            is_afterhours: !!data.is_afterhours,
            session: data.session || 'unknown',
          },
        },
      });
    }

    if (action === 'start_update') {
      const mode = body.mode === 'financial' ? 'financial' : 'kline';
      const limit = Math.max(0, Number.parseInt(body.limit, 10) || 0);
      const workers = Math.max(
        1,
        Number.parseInt(body.workers || process.env.XUANJI_UPDATE_WORKERS || '8', 10) || 8,
      );
      const result = startUpdate(mode, limit, workers, body.codes || []);
      return json(res, result.success ? 200 : 409, result);
    }

    if (action === 'stop_update') {
      const result = stopUpdate();
      return json(res, result.success ? 200 : 409, result);
    }

    if (action === 'update_progress') {
      return json(res, 200, getUpdateProgress());
    }

    return json(res, 400, { success: false, error: `unknown sync action: ${action}` });
  } catch (error) {
    log('SYNC', `control-plane error: ${error?.stack || error}`);
    return json(res, 500, { success: false, error: error?.message || String(error) });
  }
}
