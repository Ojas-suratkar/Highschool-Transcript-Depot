import { createContext, ReactNode, useContext, useMemo, useRef, useState } from 'react';
import { toast } from 'sonner';
import { deleteUploadedObjects } from '@/lib/api/cloudFolders';

export type UploadJob = {
  id: string;
  folderId: number;
  folderLabel: string;
  programName?: string | null;
  yearIntake?: string | null;
  status: 'uploading' | 'completed' | 'completed_with_errors' | 'failed' | 'cancelled';
  percentComplete: number;
  totalFiles: number;
  uploadedFiles: number;
  failedFiles: number;
  uploadedObjects: string[];
  currentFile?: string | null;
  totalBytes: number;
  uploadedBytes: number;
  error?: string | null;
  startedAt: string;
  finishedAt?: string | null;
};

type StartUploadInput = {
  folderId: string | number;
  folderLabel: string;
  programName?: string | null;
  yearIntake?: string | null;
  files: File[];
  buildFormData?: (file: File) => FormData;
  onComplete?: () => void | Promise<void>;
};

type UploadJobsContextValue = {
  jobs: UploadJob[];
  startUpload: (input: StartUploadInput) => Promise<UploadJob>;
  dismissJob: (jobId: string) => void;
  cancelJob: (jobId: string) => void;
  cancelAll: () => void;
  isFolderUploading: (folderId: string | number) => boolean;
};

const UploadJobsContext = createContext<UploadJobsContextValue | null>(null);

function createJobId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return `upload-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatErrorMessage(responseText: string, status: number) {
  const text = responseText.trim();
  return text || `Upload failed with status ${status}`;
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

function uploadFileWithProgress(
  folderId: number,
  formData: FormData,
  onProgress: (loaded: number) => void,
  onXhr?: (xhr: XMLHttpRequest) => void,
  shouldCancel?: () => boolean,
) {
  return new Promise<{ object?: string }>((resolve, reject) => {
    const token = localStorage.getItem('th_access_token');
    if (!token) {
      reject(new Error('You need to log in again before uploading.'));
      return;
    }

    const xhr = new XMLHttpRequest();
    if (onXhr) onXhr(xhr);
    xhr.open('POST', `/api/cloud-folder-locations/${folderId}/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(event.loaded);
      }
      if (shouldCancel && shouldCancel()) {
        xhr.abort();
      }
    };

    xhr.onerror = () => reject(new Error('Network error while uploading the file.'));
    xhr.onabort = () => {
      const err: any = new Error('Upload cancelled');
      err.code = 'cancelled';
      reject(err);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText || '{}');
          resolve({ object: data.object });
        } catch {
          resolve({});
        }
        return;
      }
      reject(new Error(formatErrorMessage(xhr.responseText, xhr.status)));
    };

    xhr.send(formData);
  });
}

export function UploadJobsProvider({ children }: { children: ReactNode }) {
  const [jobs, setJobs] = useState<UploadJob[]>([]);
  const activeXhrs = useRef<Record<string, Set<XMLHttpRequest>>>({});
  const cancelFlags = useRef<Record<string, boolean>>({});

  const upsertJob = (jobId: string, updater: (current: UploadJob) => UploadJob) => {
    setJobs((currentJobs) =>
      currentJobs.map((job) => (job.id === jobId ? updater(job) : job))
    );
  };

  const value = useMemo<UploadJobsContextValue>(() => ({
    jobs: [...jobs].sort((a, b) => {
      const aActive = a.status === 'uploading' ? 1 : 0;
      const bActive = b.status === 'uploading' ? 1 : 0;
      if (aActive !== bActive) return bActive - aActive;
      return new Date(b.startedAt).getTime() - new Date(a.startedAt).getTime();
    }),
    startUpload: async ({
      folderId,
      folderLabel,
      programName,
      yearIntake,
      files,
      buildFormData,
      onComplete,
    }) => {
      const numericFolderId = Number(folderId);
      const activeExistingJob = jobs.find(
        (job) => job.folderId === numericFolderId && job.status === 'uploading'
      );
      if (activeExistingJob) {
        return activeExistingJob;
      }

      const totalBytes = files.reduce((sum, file) => sum + file.size, 0);
      const jobId = createJobId();
      const baseJob: UploadJob = {
        id: jobId,
        folderId: numericFolderId,
        folderLabel,
        programName,
        yearIntake,
        status: 'uploading',
        percentComplete: 0,
        totalFiles: files.length,
        uploadedFiles: 0,
        failedFiles: 0,
        uploadedObjects: [],
        currentFile: files[0]?.name ?? null,
        totalBytes,
        uploadedBytes: 0,
        error: null,
        startedAt: new Date().toISOString(),
        finishedAt: null,
      };

      setJobs((currentJobs) => [baseJob, ...currentJobs]);

      let uploadedFiles = 0;
      let failedFiles = 0;
      let completedBytes = 0;

      let firstError: string | null = null;
      let wasCancelled = false;
      const uploadedObjects: string[] = [];

      // Track in-flight bytes per file so the progress bar stays smooth while
      // several files upload at once.
      const inflightBytes: Record<number, number> = {};
      activeXhrs.current[jobId] = new Set();

      const recomputeProgress = () => {
        const inflightTotal = Object.values(inflightBytes).reduce((a, b) => a + b, 0);
        const uploadedBytes = Math.min(totalBytes || Infinity, completedBytes + inflightTotal);
        const percentComplete = totalBytes > 0
          ? Math.min(100, Math.round((uploadedBytes / totalBytes) * 100))
          : 0;
        upsertJob(jobId, (job) => ({
          ...job,
          uploadedBytes,
          uploadedFiles,
          failedFiles,
          percentComplete,
        }));
      };

      const uploadOne = async (file: File, fileIndex: number): Promise<void> => {
        if (cancelFlags.current[jobId]) {
          wasCancelled = true;
          return;
        }

        upsertJob(jobId, (job) => ({
          ...job,
          currentFile: file.name,
        }));

        inflightBytes[fileIndex] = 0;

        try {
          // Retry each file up to 5 attempts. Transient network errors / timeouts
          // previously dropped files silently (uploaded count < selected count).
          const MAX_ATTEMPTS = 5;
          let result: { object?: string } | undefined;
          let lastError: any = null;

          for (let attempt = 1; attempt <= MAX_ATTEMPTS; attempt += 1) {
            if (cancelFlags.current[jobId]) {
              const err: any = new Error('Upload cancelled');
              err.code = 'cancelled';
              throw err;
            }
            // Rebuild FormData per attempt — a consumed stream cannot be re-sent.
            const attemptFormData = buildFormData ? buildFormData(file) : new FormData();
            if (!buildFormData) attemptFormData.append('file', file);
            try {
              result = await uploadFileWithProgress(
                numericFolderId,
                attemptFormData,
                (loaded) => {
                  inflightBytes[fileIndex] = Math.min(loaded, file.size);
                  recomputeProgress();
                },
                (xhr) => {
                  (activeXhrs.current[jobId] ||= new Set()).add(xhr);
                },
                () => !!cancelFlags.current[jobId],
              );
              lastError = null;
              break; // success
            } catch (attemptError: any) {
              lastError = attemptError;
              if (attemptError?.code === 'cancelled') throw attemptError;
              if (attempt < MAX_ATTEMPTS) {
                await sleep(500 * attempt); // backoff: 0.5s, 1s
              }
            }
          }

          if (lastError) throw lastError;

          const uploadedObject = result?.object;
          if (uploadedObject) {
            uploadedObjects.push(uploadedObject);
            upsertJob(jobId, (job) => ({
              ...job,
              uploadedObjects: [...job.uploadedObjects, uploadedObject],
            }));
          }
          uploadedFiles += 1;
        } catch (error: any) {
          if (error?.code === 'cancelled') {
            wasCancelled = true;
          } else {
            failedFiles += 1;
            if (!firstError) {
              firstError = error?.message || `Failed to upload ${file.name}`;
            }
          }
        } finally {
          delete inflightBytes[fileIndex];
          completedBytes += file.size;
          recomputeProgress();
        }
      };

      // Upload files concurrently with a bounded pool instead of one-at-a-time.
      // Browsers cap connections per host (~6), so a small pool maximizes
      // throughput without overwhelming the network or the server.
      const UPLOAD_CONCURRENCY = Math.max(
        1,
        Math.min(
          Number(import.meta.env.VITE_UPLOAD_CONCURRENCY) || 5,
          files.length,
        ),
      );
      let nextIndex = 0;
      const worker = async (): Promise<void> => {
        while (true) {
          if (cancelFlags.current[jobId]) {
            wasCancelled = true;
            return;
          }
          const i = nextIndex;
          nextIndex += 1;
          if (i >= files.length) return;
          await uploadOne(files[i], i);
        }
      };
      await Promise.all(
        Array.from({ length: UPLOAD_CONCURRENCY }, () => worker()),
      );

      activeXhrs.current[jobId] = new Set();
      const finalStatus: UploadJob['status'] = wasCancelled
        ? 'cancelled'
        : failedFiles === 0
          ? 'completed'
          : uploadedFiles > 0
            ? 'completed_with_errors'
            : 'failed';

      const finalJob: UploadJob = {
        ...baseJob,
        status: finalStatus,
        percentComplete: 100,
        uploadedFiles,
        failedFiles,
        currentFile: null,
        uploadedBytes: totalBytes,
        error: wasCancelled ? 'Cancelled by user' : firstError,
        finishedAt: new Date().toISOString(),
        uploadedObjects,
      };

      setJobs((currentJobs) =>
        currentJobs.map((job) => (job.id === jobId ? finalJob : job))
      );

      if (finalStatus === 'completed') {
        toast.success(`Uploaded ${uploadedFiles} file${uploadedFiles === 1 ? '' : 's'} to ${programName || folderLabel}.`);
      } else if (finalStatus === 'completed_with_errors') {
        toast.error(firstError || `Some files failed while uploading to ${programName || folderLabel}.`);
      } else if (finalStatus === 'cancelled') {
        toast.warning(`Upload to ${programName || folderLabel} was cancelled.`);
      } else {
        toast.error(firstError || `Upload failed for ${programName || folderLabel}.`);
      }

      if (onComplete) {
        await onComplete();
      }

      return finalJob;
    },
    dismissJob: (jobId) => {
      setJobs((currentJobs) => currentJobs.filter((job) => job.id !== jobId));
    },
    cancelJob: (jobId) => {
      cancelFlags.current[jobId] = true;
      activeXhrs.current[jobId]?.forEach((xhr) => {
        if (xhr.readyState !== XMLHttpRequest.DONE) {
          try {
            xhr.abort();
          } catch {}
        }
      });
      const job = jobs.find((j) => j.id === jobId);
      upsertJob(jobId, (job) => ({
        ...job,
        status: job.status === 'uploading' ? 'cancelled' : job.status,
        error: job.error || (job.status === 'uploading' ? 'Cancelled by user' : job.error),
        finishedAt: new Date().toISOString(),
      }));
      if (job && job.uploadedObjects.length > 0) {
        void deleteUploadedObjects(job.folderId, job.uploadedObjects).catch(() => {
          /* ignore rollback errors */
        });
      }
    },
    cancelAll: () => {
      const active = jobs.filter((job) => job.status === 'uploading');
      active.forEach((job) => {
        cancelFlags.current[job.id] = true;
        activeXhrs.current[job.id]?.forEach((xhr) => {
          if (xhr.readyState !== XMLHttpRequest.DONE) {
            try {
              xhr.abort();
            } catch {}
          }
        });
        upsertJob(job.id, (j) => ({
          ...j,
          status: 'cancelled',
          error: 'Cancelled by user',
          finishedAt: new Date().toISOString(),
        }));
        if (job.uploadedObjects.length > 0) {
          void deleteUploadedObjects(job.folderId, job.uploadedObjects).catch(() => {});
        }
      });
    },
    isFolderUploading: (folderId) => {
      const numericFolderId = Number(folderId);
      return jobs.some((job) => job.folderId === numericFolderId && job.status === 'uploading');
    },
  }), [jobs]);

  return (
    <UploadJobsContext.Provider value={value}>
      {children}
    </UploadJobsContext.Provider>
  );
}

export function useUploadJobs() {
  const context = useContext(UploadJobsContext);
  if (!context) {
    throw new Error('useUploadJobs must be used within an UploadJobsProvider.');
  }
  return context;
}
