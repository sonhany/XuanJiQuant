export type MarketStreamChannel = 'hot_quotes' | 'market_top100' | 'cockpit_mark' | 'stream_status';

export type MarketStreamEvent<T = any> = {
  id: number | string;
  type: MarketStreamChannel;
  data: T;
};

export type MarketStreamState = 'connecting' | 'live' | 'degraded' | 'paused' | 'closed';
