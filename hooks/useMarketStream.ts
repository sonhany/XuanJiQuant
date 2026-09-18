import { useEffect, useMemo, useRef, useState } from 'react';

import type { MarketStreamChannel, MarketStreamEvent, MarketStreamState } from '../lib/market-stream-types';

const RETRY_DELAYS = [1000, 2000, 5000, 10000];

type Options = {
  channels: MarketStreamChannel[];
  codes?: string[];
  enabled?: boolean;
  onEvent: (event: MarketStreamEvent) => void;
  fallback?: () => void | Promise<void>;
  fallbackIntervalMs: number;
};

export function useMarketStream({
  channels,
  codes = [],
  enabled = true,
  onEvent,
  fallback,
  fallbackIntervalMs,
}: Options) {
  const [status, setStatus] = useState<MarketStreamState>('connecting');
  const [lastEventAt, setLastEventAt] = useState<string>('');
  const [reconnects, setReconnects] = useState(0);
  const [truncated, setTruncated] = useState(false);
  const handlerRef = useRef(onEvent);
  const fallbackRef = useRef(fallback);
  const lastSequenceRef = useRef(0);
  const eventSourceRef = useRef<EventSource | null>(null);
  const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fallbackDelayRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const fallbackTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryIndexRef = useRef(0);
  handlerRef.current = onEvent;
  fallbackRef.current = fallback;

  const codesKey = useMemo(() => [...new Set(codes.map(String).filter(Boolean))].sort().join(','), [codes]);
  const channelsKey = useMemo(() => [...new Set(channels)].sort().join(','), [channels]);

  useEffect(() => {
    let disposed = false;
    const apiBase = (import.meta as any).env?.VITE_API_BASE || '';

    const clearRetry = () => {
      if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
      retryTimerRef.current = null;
    };
    const stopFallback = () => {
      if (fallbackDelayRef.current) clearTimeout(fallbackDelayRef.current);
      if (fallbackTimerRef.current) clearInterval(fallbackTimerRef.current);
      fallbackDelayRef.current = null;
      fallbackTimerRef.current = null;
    };
    const startFallback = () => {
      if (!fallbackRef.current || fallbackTimerRef.current || disposed || document.hidden) return;
      void fallbackRef.current();
      fallbackTimerRef.current = setInterval(() => void fallbackRef.current?.(), fallbackIntervalMs);
    };
    const closeSource = () => {
      const eventSource = eventSourceRef.current;
      if (eventSource) eventSource.close();
      eventSourceRef.current = null;
    };

    const connect = () => {
      if (disposed || !enabled || document.hidden) return;
      closeSource();
      setStatus('connecting');
      const query = new URLSearchParams({ channels: channelsKey, codes: codesKey });
      const eventSource = new EventSource(`${apiBase}/api/market-stream?${query.toString()}`);
      eventSourceRef.current = eventSource;
      eventSource.onopen = () => {
        retryIndexRef.current = 0;
        stopFallback();
        setStatus('live');
      };
      const receive = (type: MarketStreamChannel) => (raw: MessageEvent) => {
        let data;
        try { data = JSON.parse(String(raw.data || '{}')); } catch { return; }
        const sequence = Number(raw.lastEventId);
        if (Number.isFinite(sequence)) {
          if (sequence <= lastSequenceRef.current) return;
          lastSequenceRef.current = sequence;
        }
        if (type === 'stream_status') {
          setTruncated(Boolean(data?.truncated));
          if (data?.degraded) setStatus('degraded');
        }
        setLastEventAt(new Date().toISOString());
        handlerRef.current({ id: raw.lastEventId, type, data });
      };
      for (const channel of [...new Set([...channels, 'stream_status' as MarketStreamChannel])]) {
        eventSource.addEventListener(channel, receive(channel));
      }
      eventSource.onerror = () => {
        closeSource();
        setStatus('degraded');
        setReconnects(value => value + 1);
        if (!fallbackDelayRef.current) fallbackDelayRef.current = setTimeout(startFallback, 30_000);
        const delay = RETRY_DELAYS[Math.min(retryIndexRef.current, RETRY_DELAYS.length - 1)];
        retryIndexRef.current += 1;
        clearRetry();
        retryTimerRef.current = setTimeout(connect, delay);
      };
    };

    const onVisibility = () => {
      if (document.hidden) {
        closeSource();
        clearRetry();
        stopFallback();
        setStatus('paused');
      } else if (enabled) {
        connect();
      }
    };
    document.addEventListener('visibilitychange', onVisibility);
    if (enabled) connect(); else setStatus('closed');
    return () => {
      disposed = true;
      document.removeEventListener('visibilitychange', onVisibility);
      closeSource();
      clearRetry();
      stopFallback();
    };
  }, [channelsKey, codesKey, enabled, fallbackIntervalMs]);

  return { status, lastEventAt, reconnects, truncated };
}
