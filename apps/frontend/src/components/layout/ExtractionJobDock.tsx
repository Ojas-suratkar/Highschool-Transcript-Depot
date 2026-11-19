import { AlertTriangle, CheckCircle2, Clock, Loader2, PanelRightOpen, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';
import { useNotifications } from '@/contexts/NotificationsContext';

function formatEta(seconds: number): string {
  if (seconds < 60) return `~${seconds}s`;
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  if (s === 0) return `~${m}m`;
  return `~${m}m ${s}s`;
}

function statusLabel(status: string) {
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

export function ExtractionJobDock() {
  const { jobs, dismissJob, cancelJob } = useExtractionJobs();
  const { collapse, collapsedIds } = useNotifications();

  const visibleJobs = jobs.filter((job) => !collapsedIds.has(String(job.id)));
  if (visibleJobs.length === 0) return null;

  return (
    <>
      {visibleJobs.slice(0, 3).map((job) => {
        const failedDetail = job.details.find((detail) => detail.status === 'failed');
        const isActive = job.status === 'queued' || job.status === 'running';
        const barColor =
          job.status === 'completed'
            ? 'var(--ok)'
            : job.status === 'failed' || job.status === 'completed_with_errors'
              ? 'var(--warn)'
              : 'var(--green)';
        return (
          <div
            key={job.id}
            className="pointer-events-auto rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-4 shadow-[var(--sh-pop)]"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex min-w-0 items-center gap-2.5">
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-[var(--green-t)] text-[var(--green)]">
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
                    {job.program_name || job.folder_label}
                  </div>
                  <div className="text-[11px] text-[var(--ink-3)]">
                    {statusLabel(job.status)} · {job.total_files || 0} file{job.total_files === 1 ? '' : 's'}
                  </div>
                </div>
              </div>
              <button
                type="button"
                className="grid h-7 w-7 shrink-0 place-items-center rounded-md text-[var(--ink-3)] hover:bg-[var(--panel-2)] hover:text-[var(--ink)]"
                onClick={() => collapse(String(job.id))}
                title="Hide — the job keeps running"
                aria-label="Hide"
              >
                <PanelRightOpen className="h-4 w-4" />
              </button>
            </div>

            <div className="mt-3 h-2 overflow-hidden rounded-full bg-[var(--panel-3)]">
              <div
                className="h-full rounded-full transition-[width] duration-300"
                style={{ width: `${job.percent_complete}%`, background: barColor }}
              />
            </div>

            {isActive && ((job.to_classify ?? 0) > 0 || (job.to_extract ?? 0) > 0) ? (
              <div className="mt-2 space-y-1">
                <div className="flex items-center justify-between text-[11px] text-[var(--ink-3)]">
                  <div className="flex items-center gap-3">
                    {(job.to_classify ?? 0) > 0 && (
                      <span>Classify: {job.classified_files ?? 0}/{job.to_classify}</span>
                    )}
                    {(job.to_extract ?? 0) > 0 && (
                      <span>Extract: {job.extracted_files ?? 0}/{job.to_extract}</span>
                    )}
                  </div>
                  {job.eta_seconds != null && job.eta_seconds > 0 && (
                    <div className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      <span>{formatEta(job.eta_seconds)} left</span>
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-2 text-[12px] text-[var(--ink-2)]">
                  <span className="truncate">
                    {job.current_file ? `Working on ${job.current_file}` : 'Processing files…'}
                  </span>
                  <span className="ml-auto shrink-0 font-semibold tabular-nums text-[var(--ink)]">
                    {job.percent_complete}%
                  </span>
                </div>
              </div>
            ) : (
              <div className="mt-2 flex items-center justify-between text-[12px]">
                <span className="truncate text-[var(--ink-2)]">
                  {isActive
                    ? job.current_file
                      ? `Working on ${job.current_file}`
                      : 'Preparing files'
                    : `${job.processed_files} processed · ${job.skipped_files} skipped · ${job.failed_files} failed`}
                </span>
                <span className="shrink-0 font-semibold tabular-nums text-[var(--ink)]">{job.percent_complete}%</span>
              </div>
            )}

            {failedDetail?.reason ? (
              <div className="mt-2 rounded-md border border-amber-200 bg-[var(--warn-t)] px-2.5 py-1.5 text-[11px] text-[var(--warn)]">
                Latest issue: {failedDetail.reason}
              </div>
            ) : null}

            {job.error ? (
              <div className="mt-2 rounded-md border border-red-200 bg-[var(--danger-t)] px-2.5 py-1.5 text-[11px] text-[var(--danger)]">
                {job.error}
              </div>
            ) : null}

            <div className="mt-3 flex justify-end">
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
