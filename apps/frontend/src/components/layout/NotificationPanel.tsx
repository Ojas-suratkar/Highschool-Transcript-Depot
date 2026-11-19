import { useEffect, useMemo, useRef, useState } from 'react';
import {
  Bell,
  CheckCheck,
  CheckCircle2,
  AlertTriangle,
  Loader2,
  PanelRightOpen,
  Trash2,
  Volume2,
  VolumeX,
  X,
} from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { cn } from '@/lib/utils';
import { useNotifications } from '@/contexts/NotificationsContext';
import { useUploadJobs } from '@/contexts/UploadJobsContext';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';
import { useTerm } from '@/contexts/TermContext';

type PanelItem = {
  id: string;
  kind: 'upload' | 'extraction';
  title: string;
  subtitle: string;
  status: string;
  statusLabel: string;
  percent: number;
  active: boolean;
  error?: string | null;
  dismiss: () => void;
};

function uploadStatusLabel(status: string) {
  switch (status) {
    case 'uploading':
      return 'Uploading';
    case 'completed':
      return 'Uploaded';
    case 'completed_with_errors':
      return 'Uploaded with errors';
    case 'failed':
      return 'Upload failed';
    case 'cancelled':
      return 'Cancelled';
    default:
      return status;
  }
}

function extractionStatusLabel(status: string) {
  switch (status) {
    case 'queued':
      return 'Queued';
    case 'running':
      return 'Extracting';
    case 'completed':
      return 'Completed';
    case 'completed_with_errors':
      return 'Completed with errors';
    case 'failed':
      return 'Failed';
    case 'cancelled':
      return 'Cancelled';
    default:
      return status;
  }
}

function feedIcon(level: string) {
  if (level === 'success') return <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />;
  if (level === 'error') return <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />;
  if (level === 'warning') return <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />;
  if (level === 'progress') return <Loader2 className="mt-0.5 h-4 w-4 shrink-0 animate-spin text-primary" />;
  return <Bell className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />;
}

function activityIcon(kind: string) {
  if (kind === 'success') return <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />;
  if (kind === 'error') return <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-destructive" />;
  if (kind === 'warn') return <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />;
  return <Bell className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />;
}

function timeAgoMs(ms: number): string {
  if (!ms || Number.isNaN(ms)) return '';
  const s = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function timeAgo(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const s = Math.max(0, Math.floor((Date.now() - t) / 1000));
  if (s < 60) return 'just now';
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

export function NotificationPanel() {
  const {
    panelOpen,
    closePanel,
    muted,
    setMuted,
    markSeen,
    feed,
    unreadCount,
    refreshFeed,
    markAllRead,
    clearRead,
    activities,
    clearActivities,
    collapsedIds,
    restore,
  } = useNotifications();
  const { jobs: uploadJobs, dismissJob: dismissUpload } = useUploadJobs();
  const { jobs: extractionJobs, dismissJob: dismissExtraction } = useExtractionJobs();
  const { terms, currentTerm } = useTerm();
  const currentTermName = terms.find((t) => t.id === currentTerm)?.term_name ?? '';
  // Term-scoped activity log — only the active term's actions.
  const termActivities = useMemo(
    () => activities.filter((a) => a.term === currentTermName),
    [activities, currentTermName],
  );

  // ── Adjustable panel width (drag the left edge; persisted) ──────────────────
  const WIDTH_KEY = 'th_notif_panel_width';
  const MIN_W = 320;
  const MAX_W = 720;
  const [width, setWidth] = useState<number>(() => {
    const raw = Number(localStorage.getItem(WIDTH_KEY));
    return raw >= MIN_W && raw <= MAX_W ? raw : 380;
  });
  const dragging = useRef(false);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      const next = Math.min(MAX_W, Math.max(MIN_W, window.innerWidth - e.clientX));
      setWidth(next);
    };
    const onUp = () => {
      if (!dragging.current) return;
      dragging.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      try {
        localStorage.setItem(WIDTH_KEY, String(width));
      } catch {
        /* ignore */
      }
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [width]);

  const items = useMemo<PanelItem[]>(() => {
    const uploads: PanelItem[] = uploadJobs.map((job) => ({
      id: String(job.id),
      kind: 'upload',
      title: job.programName || job.folderLabel || 'Upload',
      subtitle: `${job.yearIntake || 'Current term'} • ${job.totalFiles} file${job.totalFiles === 1 ? '' : 's'}`,
      status: job.status,
      statusLabel: uploadStatusLabel(job.status),
      percent: job.percentComplete ?? 0,
      active: job.status === 'uploading',
      error: job.error,
      dismiss: () => dismissUpload(String(job.id)),
    }));

    const extractions: PanelItem[] = extractionJobs.map((job) => ({
      id: String(job.id),
      kind: 'extraction',
      title: job.program_name || job.folder_label || 'Extraction',
      subtitle: `${job.year_intake || 'Current term'} • ${job.total_files || 0} file${job.total_files === 1 ? '' : 's'}`,
      status: job.status,
      statusLabel: extractionStatusLabel(job.status),
      percent: job.percent_complete ?? 0,
      active: job.status === 'queued' || job.status === 'running',
      error: job.error,
      dismiss: () => dismissExtraction(String(job.id)),
    }));

    // Active first, then everything else (newest contexts are already sorted).
    return [...uploads, ...extractions].sort(
      (a, b) => Number(b.active) - Number(a.active),
    );
  }, [uploadJobs, extractionJobs, dismissUpload, dismissExtraction]);

  // Opening the panel marks jobs seen + the server feed read (clears the dot).
  useEffect(() => {
    if (panelOpen) {
      markSeen(items.map((i) => i.id));
      refreshFeed();
      if (unreadCount > 0) markAllRead();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [panelOpen, items.length]);

  const hasItems = items.length > 0;
  const hasFeed = feed.length > 0;
  const hasActivities = termActivities.length > 0;

  const clearAll = () => {
    // Remove finished jobs + already-read feed items; leave active jobs in place.
    items.filter((i) => !i.active).forEach((i) => i.dismiss());
    clearRead();
    clearActivities();
  };

  const markEverythingRead = () => {
    markSeen(items.map((i) => i.id));
    markAllRead();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className={cn(
          'fixed inset-0 z-[60] bg-foreground/10 backdrop-blur-[1px] transition-opacity duration-200',
          panelOpen ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
        onClick={closePanel}
        aria-hidden
      />

      {/* Panel — slides in from the right, macOS notification-center style */}
      <aside
        role="dialog"
        aria-label="Notifications"
        style={{ width }}
        className={cn(
          'fixed right-0 top-0 z-[61] flex h-full max-w-[calc(100vw-1rem)] flex-col border-l bg-background shadow-xl transition-transform duration-300 ease-out',
          panelOpen ? 'translate-x-0' : 'translate-x-full',
        )}
      >
        {/* Drag handle to resize the panel width */}
        <div
          onMouseDown={() => {
            dragging.current = true;
            document.body.style.cursor = 'col-resize';
            document.body.style.userSelect = 'none';
          }}
          title="Drag to resize"
          className="absolute left-0 top-0 z-10 h-full w-1.5 -translate-x-1/2 cursor-col-resize hover:bg-primary/30"
        />
        <div className="flex h-14 shrink-0 items-center justify-between border-b px-4">
          <div className="flex items-center gap-2">
            <Bell className="h-4 w-4 text-muted-foreground" />
            <span className="text-sm font-medium">Notifications</span>
          </div>
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={closePanel} aria-label="Close">
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Controls */}
        <div className="flex shrink-0 items-center gap-1 border-b px-2 py-1.5">
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs text-muted-foreground"
            onClick={markEverythingRead}
            disabled={!hasItems && unreadCount === 0}
          >
            <CheckCheck className="h-3.5 w-3.5" /> Mark all read
          </Button>
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs text-muted-foreground"
            onClick={clearAll}
            disabled={!items.some((i) => !i.active) && !feed.some((n) => n.read) && !hasActivities}
          >
            <Trash2 className="h-3.5 w-3.5" /> Clear all
          </Button>
          <div className="flex-1" />
          <Button
            variant="ghost"
            size="sm"
            className="h-8 gap-1.5 text-xs text-muted-foreground"
            onClick={() => setMuted(!muted)}
            title={muted ? 'Unmute pop-up notifications' : 'Mute pop-up notifications'}
          >
            {muted ? <VolumeX className="h-3.5 w-3.5" /> : <Volume2 className="h-3.5 w-3.5" />}
            {muted ? 'Muted' : 'Mute'}
          </Button>
        </div>

        {/* List */}
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {!hasItems && !hasFeed && !hasActivities ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center text-sm text-muted-foreground">
              <Bell className="h-8 w-8 opacity-30" />
              <span>No notifications</span>
            </div>
          ) : (
            <div className="flex flex-col gap-3">
              {hasActivities && (
                <div className="flex flex-col gap-2">
                  <div className="px-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {currentTermName || 'This term'}
                  </div>
                  {termActivities.map((a) => (
                    <div
                      key={a.id}
                      className={cn('rounded-lg border bg-card p-3 shadow-sm', !a.read && 'border-primary/40')}
                    >
                      <div className="flex items-start gap-2">
                        {activityIcon(a.kind)}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <div className="truncate text-sm font-medium">{a.title}</div>
                            {!a.read && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />}
                          </div>
                          {a.message && (
                            <div className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">{a.message}</div>
                          )}
                          <div className="mt-1 text-[11px] text-muted-foreground/70">{timeAgoMs(a.ts)}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {hasItems && (
              <div className="flex flex-col gap-2">
              {items.map((item) => (
                <div
                  key={`${item.kind}-${item.id}`}
                  className="rounded-lg border bg-card p-3 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-medium">{item.title}</div>
                      <div className="truncate text-xs text-muted-foreground">{item.subtitle}</div>
                    </div>
                    <div className="flex items-center gap-1.5 shrink-0">
                      {item.active ? (
                        <Loader2 className="h-4 w-4 animate-spin text-primary" />
                      ) : item.status === 'completed' ? (
                        <CheckCircle2 className="h-4 w-4 text-emerald-600" />
                      ) : item.status === 'failed' || item.status === 'completed_with_errors' ? (
                        <AlertTriangle className="h-4 w-4 text-amber-600" />
                      ) : null}
                      {collapsedIds.has(item.id) && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-muted-foreground"
                          onClick={() => restore(item.id)}
                          title="Show in the corner again"
                          aria-label="Show in the corner again"
                        >
                          <PanelRightOpen className="h-3.5 w-3.5" />
                        </Button>
                      )}
                      {!item.active && (
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-muted-foreground"
                          onClick={item.dismiss}
                          aria-label="Dismiss"
                        >
                          <X className="h-3.5 w-3.5" />
                        </Button>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 flex items-center gap-2">
                    <Progress value={item.percent} className="h-1.5 flex-1" />
                    <span className="w-16 shrink-0 text-right text-xs text-muted-foreground">
                      {item.statusLabel}
                    </span>
                  </div>
                  {item.error ? (
                    <div className="mt-2 rounded-md border border-destructive/30 bg-destructive/10 px-2 py-1 text-xs text-destructive">
                      {item.error}
                    </div>
                  ) : null}
                </div>
              ))}
              </div>
              )}

              {hasFeed && (
                <div className="flex flex-col gap-2">
                  {hasItems && (
                    <div className="sticky top-0 z-10 bg-background px-1 pb-1 pt-1 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                      Activity
                    </div>
                  )}
                  {feed.map((n) => (
                    <div
                      key={n.id}
                      className={cn(
                        'rounded-lg border bg-card p-3 shadow-sm',
                        !n.read && 'border-primary/40',
                      )}
                    >
                      <div className="flex items-start gap-2">
                        {feedIcon(n.level)}
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <div className="truncate text-sm font-medium">{n.title}</div>
                            {!n.read && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />}
                          </div>
                          {n.message && (
                            <div className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
                              {n.message}
                            </div>
                          )}
                          <div className="mt-1 text-[11px] text-muted-foreground/70">
                            {timeAgo(n.created_at)}
                          </div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      </aside>
    </>
  );
}
