import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import {
  fetchNotifications,
  markAllNotificationsRead,
  clearReadNotifications,
  type AppNotification,
} from '@/lib/api/notifications';
import { useTerm } from '@/contexts/TermContext';
import {
  APP_NOTIFY_EVENT,
  APP_TERM_DELETED_EVENT,
  type NotifyPayload,
  type TermDeletedPayload,
} from '@/lib/notify';

/** A term-scoped activity notification recorded from any app action. */
export type Activity = {
  id: string;
  term: string;
  kind: 'success' | 'error' | 'info' | 'warn';
  title: string;
  message?: string;
  ts: number;
  read: boolean;
};

const ACTIVITY_KEY = 'th_activity_log_v1';

/**
 * UI state for the notification system.
 *
 * The actual process jobs live in UploadJobsContext / ExtractionJobsContext
 * (which are nested inside this provider), so this store only owns the
 * notification *surface* state:
 *  - whether the side panel (macOS-style notification center) is open
 *  - `muted`: suppress the bottom-left corner toasts (the panel still collects)
 *  - `collapsedIds`: jobs the user collapsed — hidden from the corner, still
 *    listed in the panel
 *  - `seenIds`: jobs already seen in the panel — drives the header dot
 *
 * Collapsed/seen state is intentionally session-scoped (jobs themselves are
 * in-memory and reset on reload); only `muted` is persisted.
 */
type NotificationsContextValue = {
  panelOpen: boolean;
  openPanel: () => void;
  closePanel: () => void;
  togglePanel: () => void;

  muted: boolean;
  setMuted: (value: boolean) => void;

  collapsedIds: Set<string>;
  collapse: (id: string) => void;
  restore: (id: string) => void;

  seenIds: Set<string>;
  markSeen: (ids: string[]) => void;

  // Server-backed notification feed (auto-train, uploads, extraction, etc.)
  feed: AppNotification[];
  unreadCount: number;
  refreshFeed: () => void;
  markAllRead: () => void;
  clearRead: () => void;

  // Client-side, term-scoped activity log (every app action). Added when it
  // happens, marked read when the panel opens, removed when it closes.
  activities: Activity[];
  activityUnread: number;
  clearActivities: () => void;
};

const MUTE_KEY = 'th_notifications_muted';

const NotificationsContext = createContext<NotificationsContextValue>({
  panelOpen: false,
  openPanel: () => {},
  closePanel: () => {},
  togglePanel: () => {},
  muted: false,
  setMuted: () => {},
  collapsedIds: new Set(),
  collapse: () => {},
  restore: () => {},
  seenIds: new Set(),
  markSeen: () => {},
  feed: [],
  unreadCount: 0,
  refreshFeed: () => {},
  markAllRead: () => {},
  clearRead: () => {},
  activities: [],
  activityUnread: 0,
  clearActivities: () => {},
});

export function NotificationsProvider({ children }: { children: ReactNode }) {
  const [panelOpen, setPanelOpen] = useState(false);
  const [collapsedIds, setCollapsedIds] = useState<Set<string>>(() => new Set());
  const [seenIds, setSeenIds] = useState<Set<string>>(() => new Set());
  const [muted, setMutedState] = useState<boolean>(() => {
    try {
      return localStorage.getItem(MUTE_KEY) === '1';
    } catch {
      return false;
    }
  });

  const setMuted = useCallback((value: boolean) => {
    setMutedState(value);
    try {
      localStorage.setItem(MUTE_KEY, value ? '1' : '0');
    } catch {
      /* ignore */
    }
  }, []);

  const openPanel = useCallback(() => setPanelOpen(true), []);
  const closePanel = useCallback(() => setPanelOpen(false), []);
  const togglePanel = useCallback(() => setPanelOpen((v) => !v), []);

  // ── Term-scoped activity log ────────────────────────────────────────────────
  const { terms, currentTerm } = useTerm();
  const currentTermName = terms.find((t) => t.id === currentTerm)?.term_name ?? '';

  const [activities, setActivities] = useState<Activity[]>(() => {
    try {
      const raw = localStorage.getItem(ACTIVITY_KEY);
      const arr = raw ? (JSON.parse(raw) as Activity[]) : [];
      return Array.isArray(arr) ? arr.slice(0, 200) : [];
    } catch {
      return [];
    }
  });

  useEffect(() => {
    try {
      localStorage.setItem(ACTIVITY_KEY, JSON.stringify(activities.slice(0, 200)));
    } catch {
      /* ignore */
    }
  }, [activities]);

  // Any app action → a term-scoped activity notification.
  const termRef = useRef(currentTermName);
  termRef.current = currentTermName;
  useEffect(() => {
    const onNotify = (e: Event) => {
      const detail = (e as CustomEvent<NotifyPayload>).detail;
      if (!detail?.title) return;
      setActivities((prev) =>
        [
          {
            id: `act-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
            term: detail.term || termRef.current || 'General',
            kind: detail.kind || 'info',
            title: detail.title,
            message: detail.message,
            ts: Date.now(),
            read: false,
          },
          ...prev,
        ].slice(0, 200),
      );
    };
    window.addEventListener(APP_NOTIFY_EVENT, onNotify as EventListener);
    return () => window.removeEventListener(APP_NOTIFY_EVENT, onNotify as EventListener);
  }, []);

  // Deleting a term wipes its activity log so a recreated term of the same name
  // starts clean (activities are keyed by term name and persisted).
  useEffect(() => {
    const onTermDeleted = (e: Event) => {
      const detail = (e as CustomEvent<TermDeletedPayload>).detail;
      const name = detail?.termName;
      if (!name) return;
      setActivities((prev) => {
        const next = prev.filter((a) => a.term !== name);
        return next.length === prev.length ? prev : next;
      });
    };
    window.addEventListener(APP_TERM_DELETED_EVENT, onTermDeleted as EventListener);
    return () => window.removeEventListener(APP_TERM_DELETED_EVENT, onTermDeleted as EventListener);
  }, []);

  // Read when the panel opens; removed when it closes ("read then removed").
  const wasOpen = useRef(false);
  useEffect(() => {
    if (panelOpen && !wasOpen.current) {
      setActivities((prev) => (prev.some((a) => !a.read) ? prev.map((a) => ({ ...a, read: true })) : prev));
    } else if (!panelOpen && wasOpen.current) {
      setActivities((prev) => (prev.some((a) => a.read) ? prev.filter((a) => !a.read) : prev));
    }
    wasOpen.current = panelOpen;
  }, [panelOpen]);

  const clearActivities = useCallback(() => setActivities([]), []);
  const activityUnread = activities.filter((a) => !a.read && a.term === currentTermName).length;

  const collapse = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      if (prev.has(id)) return prev;
      const next = new Set(prev);
      next.add(id);
      return next;
    });
  }, []);

  const restore = useCallback((id: string) => {
    setCollapsedIds((prev) => {
      if (!prev.has(id)) return prev;
      const next = new Set(prev);
      next.delete(id);
      return next;
    });
  }, []);

  const markSeen = useCallback((ids: string[]) => {
    if (!ids.length) return;
    setSeenIds((prev) => {
      let changed = false;
      const next = new Set(prev);
      for (const id of ids) {
        if (!next.has(id)) {
          next.add(id);
          changed = true;
        }
      }
      return changed ? next : prev;
    });
  }, []);

  // Keep mute in sync across tabs.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === MUTE_KEY) setMutedState(e.newValue === '1');
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, []);

  // --- Server-backed notification feed (polled, visibility-gated) ---
  const [feed, setFeed] = useState<AppNotification[]>([]);
  const [unreadCount, setUnreadCount] = useState(0);
  const loadingRef = useRef(false);

  const refreshFeed = useCallback(async () => {
    if (loadingRef.current) return;
    loadingRef.current = true;
    try {
      const res = await fetchNotifications(60);
      setFeed(res.notifications || []);
      setUnreadCount(res.unread || 0);
    } catch {
      /* ignore transient failures */
    } finally {
      loadingRef.current = false;
    }
  }, []);

  const markAllRead = useCallback(async () => {
    setFeed((prev) => prev.map((n) => ({ ...n, read: true })));
    setUnreadCount(0);
    try {
      await markAllNotificationsRead();
    } catch {
      /* ignore */
    }
  }, []);

  const clearRead = useCallback(async () => {
    setFeed((prev) => prev.filter((n) => !n.read));
    try {
      await clearReadNotifications();
      await refreshFeed();
    } catch {
      /* ignore */
    }
  }, [refreshFeed]);

  useEffect(() => {
    refreshFeed();
    let timer: number | undefined;
    const tick = () => {
      if (typeof document === 'undefined' || document.visibilityState === 'visible') {
        refreshFeed();
      }
      timer = window.setTimeout(tick, 20000);
    };
    timer = window.setTimeout(tick, 20000);
    const onVisible = () => {
      if (document.visibilityState === 'visible') refreshFeed();
    };
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      if (timer) window.clearTimeout(timer);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [refreshFeed]);

  const value = useMemo<NotificationsContextValue>(
    () => ({
      panelOpen,
      openPanel,
      closePanel,
      togglePanel,
      muted,
      setMuted,
      collapsedIds,
      collapse,
      restore,
      seenIds,
      markSeen,
      feed,
      unreadCount,
      refreshFeed,
      markAllRead,
      clearRead,
      activities,
      activityUnread,
      clearActivities,
    }),
    [panelOpen, openPanel, closePanel, togglePanel, muted, setMuted, collapsedIds, collapse, restore, seenIds, markSeen, feed, unreadCount, refreshFeed, markAllRead, clearRead, activities, activityUnread, clearActivities],
  );

  return (
    <NotificationsContext.Provider value={value}>
      {children}
    </NotificationsContext.Provider>
  );
}

export function useNotifications() {
  return useContext(NotificationsContext);
}
