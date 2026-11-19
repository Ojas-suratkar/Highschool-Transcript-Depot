import { AlertTriangle, CheckCircle2, Loader2, PanelRightOpen, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useUploadJobs } from '@/contexts/UploadJobsContext';
import { useNotifications } from '@/contexts/NotificationsContext';

function statusLabel(status: string) {
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

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`;
}

export function UploadJobDock() {
  const { jobs, dismissJob, cancelJob } = useUploadJobs();
  const { collapse, collapsedIds } = useNotifications();

  // Collapsed jobs leave the corner but stay listed in the side panel.
  const visible = jobs.filter((job) => !collapsedIds.has(String(job.id)));
  if (visible.length === 0) return null;

  return (
    <>
      {visible.slice(0, 3).map((job) => {
        const isActive = job.status === 'uploading';
        const barColor =
          job.status === 'completed'
            ? 'var(--ok)'
            : job.status === 'failed' || job.status === 'completed_with_errors'
              ? 'var(--warn)'
              : 'var(--blue)';
        return (
          <div
            key={job.id}
            className="pointer-events-auto rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-4 shadow-[var(--sh-pop)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--blue-t)] text-[var(--blue)]">
                  {isActive ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : job.status === 'completed' ? (
                    <CheckCircle2 className="h-4 w-4 text-[var(--ok)]" />
                  ) : (
                    <AlertTriangle className="h-4 w-4 text-[var(--warn)]" />
                  )}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-[13px] font-semibold text-[var(--ink)]">
                    {job.programName || job.folderLabel}
                  </div>
                  <div className="text-[11px] text-[var(--ink-3)]">
                    {statusLabel(job.status)} · {job.totalFiles} file{job.totalFiles === 1 ? '' : 's'}
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-[var(--ink-3)] hover:bg-[var(--panel-2)] hover:text-[var(--ink)]"
                onClick={() => collapse(String(job.id))}
                title="Hide — the upload keeps running"
                aria-label="Hide"
              >
                <PanelRightOpen className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--panel-3)]">
              <div
                className="h-full rounded-full transition-[width] duration-300"
                style={{ width: `${job.percentComplete}%`, background: barColor }}
              />
            </div>

            <div className="mt-2 flex items-center justify-between text-[12px]">
              <span className="truncate text-[var(--ink-2)]">
                {isActive
                  ? job.currentFile
                    ? `Sending ${job.currentFile}`
                    : 'Preparing files'
                  : `${job.uploadedFiles} uploaded · ${job.failedFiles} failed`}
              </span>
              <span className="shrink-0 font-semibold tabular-nums text-[var(--ink)]">{job.percentComplete}%</span>
            </div>

            {job.error ? (
              <div className="mt-2 rounded-md border border-red-200 bg-[var(--danger-t)] px-2.5 py-1.5 text-[11px] text-[var(--danger)]">
                {job.error}
              </div>
            ) : null}

            <div className="mt-3 flex items-center justify-between">
              <span className="text-[11px] text-[var(--ink-3)]">
                {formatBytes(job.uploadedBytes)} / {formatBytes(job.totalBytes)} ·{' '}
                {job.uploadedFiles + job.failedFiles} of {job.totalFiles} finished
              </span>
              {isActive ? (
                <Button variant="outline" size="sm" className="h-7 px-3" onClick={() => cancelJob(job.id)}>
                  Cancel
                </Button>
              ) : (
                <Button
                  variant="ghost"
                  size="sm"
                  className="h-7 gap-1 px-2 text-[var(--ink-3)]"
                  onClick={() => dismissJob(job.id)}
                >
                  <X className="h-3.5 w-3.5" /> Dismiss
                </Button>
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}
