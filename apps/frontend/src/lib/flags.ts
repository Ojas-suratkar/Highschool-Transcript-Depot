import { useCallback, useEffect, useState } from 'react';

const STORAGE_KEY = 'transcript-flags:v1';

function readFlags(): Set<string> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as string[];
    return new Set(Array.isArray(arr) ? arr : []);
  } catch {
    return new Set();
  }
}

function writeFlags(flags: Set<string>) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify([...flags]));
  } catch {
    /* ignore quota / disabled storage */
  }
}

/**
 * Per-browser "flag/star for reference" state, keyed by a stable id (blob name).
 * Persists to localStorage and keeps multiple mounted components in sync via a
 * window event so flagging a row in one place updates it everywhere.
 */
export function useFlags() {
  const [flags, setFlags] = useState<Set<string>>(() => readFlags());

  useEffect(() => {
    const sync = () => setFlags(readFlags());
    window.addEventListener('transcript-flags-changed', sync);
    window.addEventListener('storage', sync);
    return () => {
      window.removeEventListener('transcript-flags-changed', sync);
      window.removeEventListener('storage', sync);
    };
  }, []);

  const toggleFlag = useCallback((id: string) => {
    setFlags((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      writeFlags(next);
      window.dispatchEvent(new Event('transcript-flags-changed'));
      return next;
    });
  }, []);

  const isFlagged = useCallback((id: string) => flags.has(id), [flags]);

  return { flags, isFlagged, toggleFlag };
}
