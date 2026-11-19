import {
  createContext,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';
import { toast } from 'sonner';

import {
  CloudFolderExtractionJobDTO,
  getCloudFolderExtractionJob,
  listActiveCloudFolderExtractionJobs,
  startCloudFolderExtractionJob,
  cancelCloudFolderExtractionJob,
} from '@/lib/api/cloudFolders';

const STORAGE_KEY = 'th_extraction_job_ids';
const ACTIVE_JOB_STATUSES = new Set(['queued', 'running']);
const MAX_POLL_FAILURES = 3;
const TERMINAL_JOB_STATUSES = new Set([
  'completed',
  'completed_with_errors',
  'failed',
  'cancelled',
]);

type StartJobInput = {
  id: string | number;
  label: string;
  /**
   * Optional selected term. Existing callers do not have to provide it.
   */
  termName?: string;

  /**
   * Explicit manual re-extraction controls.
   *
   * These are optional so every existing automatic/normal extraction caller
   * keeps the same behavior.
   */
  forceReextract?: boolean;
  selectedFileIds?: Array<number | string>;
};

type ExtractionJobsContextValue = {
  jobs: CloudFolderExtractionJobDTO[];
  startJob: (folder: StartJobInput) => Promise<CloudFolderExtractionJobDTO>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => Promise<void>;
  cancelAll: () => Promise<void>;
  isFolderExtracting: (folderId: string | number) => boolean;
};

const ExtractionJobsContext =
  createContext<ExtractionJobsContextValue | null>(null);

function readStoredJobIds(): string[] {
  if (typeof window === 'undefined') return [];

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw);

    return Array.isArray(parsed)
      ? parsed.filter((id): id is string => typeof id === 'string')
      : [];
  } catch {
    return [];
  }
}

function sortJobs(jobs: CloudFolderExtractionJobDTO[]) {
  return [...jobs].sort((a, b) => {
    const aActive = ACTIVE_JOB_STATUSES.has(a.status) ? 1 : 0;
    const bActive = ACTIVE_JOB_STATUSES.has(b.status) ? 1 : 0;

    if (aActive !== bActive) {
      return bActive - aActive;
    }

    return (
      new Date(b.started_at).getTime() - new Date(a.started_at).getTime()
    );
  });
}

export function ExtractionJobsProvider({
  children,
}: {
  children: ReactNode;
}) {
  const [jobs, setJobs] = useState<CloudFolderExtractionJobDTO[]>([]);

  /**
   * jobsRef is the authoritative in-memory snapshot used by async callbacks.
   *
   * Re-extract All starts several folders at the same time. The previous
   * implementation built every update from the render-time `jobs` array, so
   * concurrent startJob() calls could overwrite one another. Keeping this ref
   * in sync makes those updates concurrency-safe without changing the API.
   */
  const jobsRef = useRef<CloudFolderExtractionJobDTO[]>([]);

  const prevStatusesRef = useRef<Record<string, string>>({});
  const cancellingRef = useRef<Record<string, boolean>>({});
  const failureCountsRef = useRef<Record<string, number>>({});

  const persistJobIds = useCallback(
    (nextJobs: CloudFolderExtractionJobDTO[]) => {
      if (typeof window === 'undefined') return;

      // Never persist temp IDs — the backend does not know about them.
      const realIds = nextJobs
        .map((job) => job.id)
        .filter((id) => !id.startsWith('temp-'));

      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(realIds));
    },
    [],
  );

  const announceTransitions = useCallback(
    (nextJobs: CloudFolderExtractionJobDTO[]) => {
      const nextStatusMap: Record<string, string> = {};
      let reachedTerminal = false;

      for (const job of nextJobs) {
        nextStatusMap[job.id] = job.status;

        const previousStatus = prevStatusesRef.current[job.id];

        if (
          !previousStatus ||
          previousStatus === job.status ||
          !TERMINAL_JOB_STATUSES.has(job.status)
        ) {
          continue;
        }

        reachedTerminal = true;

        if (job.status === 'completed') {
          toast.success(`Extraction complete for ${job.folder_label}.`);
        } else if (job.status === 'completed_with_errors') {
          const failedDetail = job.details.find(
            (detail) => detail.status === 'failed',
          );

          toast.error(
            failedDetail?.reason
              ? `Extraction finished with issues: ${failedDetail.reason}`
              : `Extraction finished with issues for ${job.folder_label}.`,
          );
        } else if (job.status === 'failed') {
          toast.error(
            job.error || `Extraction failed for ${job.folder_label}.`,
          );
        }
      }

      prevStatusesRef.current = nextStatusMap;

      if (reachedTerminal && typeof window !== 'undefined') {
        // Existing global refresh signal.
        window.dispatchEvent(new CustomEvent('app-notify', { detail: {} }));

        // Extractor pages already listen for this event to refresh Auto Complete,
        // Human Review and Audit counts. Emitting it here makes the counts update
        // as soon as any extraction job finishes.
        window.dispatchEvent(new Event('transcript-extraction-complete'));
      }
    },
    [],
  );

  /**
   * Commit a complete jobs snapshot.
   *
   * All mutations flow through this helper so React state, localStorage,
   * transition notifications and jobsRef stay synchronized.
   */
  const commitJobs = useCallback(
    (nextJobs: CloudFolderExtractionJobDTO[]) => {
      const sorted = sortJobs(nextJobs);

      jobsRef.current = sorted;
      setJobs(sorted);
      persistJobIds(sorted);
      announceTransitions(sorted);
    },
    [announceTransitions, persistJobIds],
  );

  /**
   * Apply an update against the latest async-safe snapshot.
   */
  const updateJobs = useCallback(
    (
      updater: (
        currentJobs: CloudFolderExtractionJobDTO[],
      ) => CloudFolderExtractionJobDTO[],
    ) => {
      commitJobs(updater(jobsRef.current));
    },
    [commitJobs],
  );

  const replaceJobs = useCallback(
    (nextJobs: CloudFolderExtractionJobDTO[]) => {
      commitJobs(nextJobs);
    },
    [commitJobs],
  );

  const upsertJob = useCallback(
    (job: CloudFolderExtractionJobDTO) => {
      updateJobs((currentJobs) =>
        currentJobs.some((existingJob) => existingJob.id === job.id)
          ? currentJobs.map((existingJob) =>
              existingJob.id === job.id ? job : existingJob,
            )
          : [...currentJobs, job],
      );
    },
    [updateJobs],
  );

  useEffect(() => {
    const storedJobIds = readStoredJobIds();

    if (storedJobIds.length === 0) {
      return;
    }

    let cancelled = false;

    const hydrateJobs = async () => {
      const fetched = await Promise.all(
        storedJobIds.map(async (jobId) => {
          try {
            return await getCloudFolderExtractionJob(jobId);
          } catch {
            return null;
          }
        }),
      );

      if (!cancelled) {
        replaceJobs(
          fetched.filter(
            (job): job is CloudFolderExtractionJobDTO => job !== null,
          ),
        );
      }
    };

    void hydrateJobs();

    return () => {
      cancelled = true;
    };
  }, [replaceJobs]);

  /**
   * Discover extraction jobs that were created automatically by the backend
   * after uploads settle.
   *
   * This is read-only discovery. It never starts, restarts, cancels, or
   * otherwise changes backend extraction behavior. Discovered jobs are merged
   * into the existing frontend list so manual/selected jobs and completed cards
   * are preserved.
   */
  useEffect(() => {
    let cancelled = false;

    const discoverActiveJobs = async () => {
      try {
        const discovered = await listActiveCloudFolderExtractionJobs();

        if (cancelled || discovered.length === 0) {
          return;
        }

        updateJobs((currentJobs) => {
          const merged = new Map(
            currentJobs.map((job) => [job.id, job] as const),
          );

          for (const job of discovered) {
            merged.set(job.id, job);
          }

          return Array.from(merged.values());
        });
      } catch {
        // Discovery is best-effort. Existing known-job polling continues to
        // work even if this read-only endpoint is temporarily unavailable.
      }
    };

    void discoverActiveJobs();

    const interval = window.setInterval(() => {
      void discoverActiveJobs();
    }, 2000);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [updateJobs]);

  useEffect(() => {
    const activeJobs = jobs.filter((job) =>
      ACTIVE_JOB_STATUSES.has(job.status),
    );

    if (activeJobs.length === 0) {
      return;
    }

    const interval = window.setInterval(async () => {
      const snapshot = jobsRef.current;

      const refreshed = await Promise.all(
        snapshot.map(async (job) => {
          if (!ACTIVE_JOB_STATUSES.has(job.status)) {
            return job;
          }

          // Skip temp IDs — the backend does not know about them yet.
          if (job.id.startsWith('temp-')) {
            return job;
          }

          try {
            const updated = await getCloudFolderExtractionJob(job.id);
            failureCountsRef.current[job.id] = 0;
            return updated;
          } catch {
            // Treat 404/network failures as transient. With Cloud Run session
            // affinity a poll can briefly land on an instance that does not
            // hold the job. Only remove it after several consecutive failures.
            const failures =
              (failureCountsRef.current[job.id] ?? 0) + 1;

            failureCountsRef.current[job.id] = failures;

            if (failures >= MAX_POLL_FAILURES) {
              return null;
            }

            return job;
          }
        }),
      );

      replaceJobs(
        refreshed.filter(
          (job): job is CloudFolderExtractionJobDTO => job !== null,
        ),
      );
    }, 3000);

    return () => {
      window.clearInterval(interval);
    };
  }, [jobs, replaceJobs]);

  const startJob = useCallback(
    async (folder: StartJobInput): Promise<CloudFolderExtractionJobDTO> => {
      const tempId = `temp-${folder.id}-${Date.now()}-${Math.random()
        .toString(36)
        .slice(2, 8)}`;

      const placeholder: CloudFolderExtractionJobDTO = {
        id: tempId,
        folder_id: Number(folder.id),
        folder_label: folder.label,
        year_intake: folder.termName ?? folder.label,
        status: 'queued',
        percent_complete: 0,
        total_files: folder.selectedFileIds?.length ?? 0,
        processed_files: 0,
        skipped_files: 0,
        failed_files: 0,
        current_file:
          folder.selectedFileIds && folder.selectedFileIds.length > 0
            ? 'Preparing selected transcripts…'
            : 'Running classification…',
        details: [],
        error: null,
        started_at: new Date().toISOString(),
        finished_at: null,
      };

      upsertJob(placeholder);

      try {
        const job = await startCloudFolderExtractionJob(
          folder.id,
          folder.forceReextract || folder.selectedFileIds !== undefined
            ? {
                forceReextract: Boolean(folder.forceReextract),
                selectedFileIds: folder.selectedFileIds,
              }
            : undefined,
        );

        /**
         * Do not use the render-time `jobs` array here.
         *
         * Re-extract All can call startJob for many folders concurrently. Each
         * returned real job replaces only its own placeholder while preserving
         * every other job that was added in the meantime.
         */
        updateJobs((currentJobs) =>
          currentJobs
            .filter(
              (existingJob) =>
                existingJob.id !== tempId && existingJob.id !== job.id,
            )
            .concat(job),
        );

        if (ACTIVE_JOB_STATUSES.has(job.status)) {
          toast.success(`Started extraction for ${folder.label}.`);
        }

        return job;
      } catch (error) {
        updateJobs((currentJobs) =>
          currentJobs.filter((job) => job.id !== tempId),
        );

        throw error;
      }
    },
    [updateJobs, upsertJob],
  );

  const cancelJob = useCallback(
    async (jobId: string): Promise<void> => {
      const job = jobsRef.current.find((item) => item.id === jobId);

      if (
        !job ||
        TERMINAL_JOB_STATUSES.has(job.status) ||
        cancellingRef.current[jobId]
      ) {
        return;
      }

      cancellingRef.current[jobId] = true;

      try {
        // Optimistic cancel in the UI.
        updateJobs((currentJobs) =>
          currentJobs.map((item) =>
            item.id === jobId
              ? {
                  ...item,
                  status: 'cancelled',
                  error: 'Cancelled by user',
                  finished_at: new Date().toISOString(),
                  percent_complete: 0,
                }
              : item,
          ),
        );

        await cancelCloudFolderExtractionJob(jobId);
        toast.success('Extraction cancelled');
      } catch (error: any) {
        // Restore the previous job snapshot when the backend cancellation fails.
        upsertJob(job);
        toast.error(
          error?.message || 'Failed to cancel extraction job.',
        );
      } finally {
        cancellingRef.current[jobId] = false;
      }
    },
    [updateJobs, upsertJob],
  );

  const cancelAll = useCallback(async (): Promise<void> => {
    const activeJobs = jobsRef.current.filter((job) =>
      ACTIVE_JOB_STATUSES.has(job.status),
    );

    await Promise.all(activeJobs.map((job) => cancelJob(job.id)));
  }, [cancelJob]);

  const dismissJob = useCallback(
    (jobId: string) => {
      delete failureCountsRef.current[jobId];
      delete prevStatusesRef.current[jobId];

      updateJobs((currentJobs) =>
        currentJobs.filter((job) => job.id !== jobId),
      );
    },
    [updateJobs],
  );

  const value = useMemo<ExtractionJobsContextValue>(
    () => ({
      jobs,
      startJob,
      dismissJob,
      cancelJob,
      cancelAll,
      isFolderExtracting: (folderId) => {
        const numericFolderId = Number(folderId);

        return jobs.some(
          (job) =>
            job.folder_id === numericFolderId &&
            ACTIVE_JOB_STATUSES.has(job.status),
        );
      },
    }),
    [cancelAll, cancelJob, dismissJob, jobs, startJob],
  );

  return (
    <ExtractionJobsContext.Provider value={value}>
      {children}
    </ExtractionJobsContext.Provider>
  );
}

export function useExtractionJobs() {
  const context = useContext(ExtractionJobsContext);

  if (!context) {
    throw new Error(
      'useExtractionJobs must be used within an ExtractionJobsProvider.',
    );
  }

  return context;
}
