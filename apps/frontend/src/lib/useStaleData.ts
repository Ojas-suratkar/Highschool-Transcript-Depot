import { useEffect, useRef, useState } from 'react';

const _cache = new Map<string, { data: unknown; ts: number }>();

// Persist list payloads to localStorage so a hard refresh shows the last-known
// data instantly (stale-while-revalidate), instead of a spinner. Kept small and
// fully guarded so quota errors never break rendering.
const LS_PREFIX = 'swr:';
const LS_MAX_BYTES = 1_500_000; // skip persisting unusually large payloads

function lsRead<T>(key: string): { data: T; ts: number } | null {
  try {
    const raw = localStorage.getItem(LS_PREFIX + key);
    if (!raw) return null;
    return JSON.parse(raw) as { data: T; ts: number };
  } catch {
    return null;
  }
}

function lsWrite(key: string, data: unknown) {
  try {
    const serialized = JSON.stringify({ data, ts: Date.now() });
    if (serialized.length > LS_MAX_BYTES) return;
    localStorage.setItem(LS_PREFIX + key, serialized);
  } catch {
    /* quota / serialization — ignore, in-memory cache still works */
  }
}

/** Seed the in-memory cache from localStorage on first access for a key. */
function primeFromLs<T>(key: string): { data: T; ts: number } | undefined {
  const mem = _cache.get(key);
  if (mem) return mem as { data: T; ts: number };
  const persisted = lsRead<T>(key);
  if (persisted) {
    _cache.set(key, persisted);
    return persisted;
  }
  return undefined;
}

/**
 * Stale-while-revalidate hook.
 * - Returns cached data instantly (loading=false) if available — including data
 *   persisted to localStorage from a previous session, so a hard refresh paints
 *   the last-known rows immediately.
 * - Fires a background refresh every time deps change.
 * - `refreshing` is true only when there is no cached data yet.
 */
export function useStaleData<T>(
  key: string,
  fetcher: () => Promise<T>,
  deps: unknown[],
  options?: { refreshIntervalMs?: number },
): { data: T | null; refreshing: boolean } {
  const hit = primeFromLs<T>(key);
  const [data, setData] = useState<T | null>(hit ? (hit.data as T) : null);
  const [refreshing, setRefreshing] = useState(!hit);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;
  const refreshIntervalMs = options?.refreshIntervalMs ?? 0;

  useEffect(() => {
    let cancelled = false;
    const cached = primeFromLs<T>(key);

    if (cached) {
      setData(cached.data as T);
      setRefreshing(false);
    } else {
      setRefreshing(true);
    }

    const run = () =>
      fetcherRef.current().then((result) => {
        if (cancelled) return;
        _cache.set(key, { data: result, ts: Date.now() });
        lsWrite(key, result);
        setData(result);
        setRefreshing(false);
      }).catch(() => {
        if (!cancelled) setRefreshing(false);
      });

    run();

    // Continuous background auto-refresh. Polls only while the tab is visible
    // (so background tabs don't hammer the API) and updates data silently in
    // place — no loading flash on each tick.
    let timer: ReturnType<typeof setInterval> | undefined;
    if (refreshIntervalMs > 0) {
      timer = setInterval(() => {
        if (typeof document !== 'undefined' && document.visibilityState !== 'visible') return;
        run();
      }, refreshIntervalMs);
    }

    return () => {
      cancelled = true;
      if (timer) clearInterval(timer);
    };
    // deps intentionally spread — key encodes them
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, refreshIntervalMs, ...deps]);

  return { data, refreshing };
}

/** Evict all cache entries (memory + persisted) that match a key prefix. */
export function invalidateCache(prefix: string) {
  for (const k of _cache.keys()) {
    if (k.startsWith(prefix)) _cache.delete(k);
  }
  try {
    const toRemove: string[] = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(LS_PREFIX + prefix)) toRemove.push(k);
    }
    toRemove.forEach((k) => localStorage.removeItem(k));
  } catch {
    /* ignore */
  }
}
