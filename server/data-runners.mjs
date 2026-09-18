import { PersistentRunner } from './persistent_runner.mjs';

export const dataReadRunner = new PersistentRunner('data_runner.py', 'data-read');
export const dataRealtimeRunner = new PersistentRunner('data_runner.py', 'data-realtime');
export const dataStocksRunner = new PersistentRunner('data_runner.py', 'data-stocks');
export const marketStreamHotRunner = new PersistentRunner('data_runner.py', 'market-stream-hot');
export const marketStreamFullRunner = new PersistentRunner('data_runner.py', 'market-stream-full');

export function closeDataRunners() {
  for (const runner of [
    dataReadRunner,
    dataRealtimeRunner,
    dataStocksRunner,
    marketStreamHotRunner,
    marketStreamFullRunner,
  ]) runner.close();
}
