// src/lib/api/cloudFolders.ts

import { apiFetch } from '../utils.ts';

export type CloudFolderDTO = {
  id: string;
  label: string;
  // url: string;
  year_intake: string;
  last_polled: string | null;
  updated_at: string;
  source_type?: string | null;
  source_uri?: string | null;
  last_poll_status?: string | null;
};

export type CloudFolderFileDTO = {
  name: string;
  path: string;
  kind: string;
  size_bytes?: number | null;
  updated_at?: string | null;
};

export type CloudFolderExtractResponse = {
  ok: boolean;
  processed_files: number;
  skipped_files: number;
  failed_files: number;
  details: Array<{
    file_name: string;
    status: string;
    reason?: string;
    students?: number;
    courses?: number;
  }>;
};

export type CloudFolderExtractionJobDTO = {
  id: string;
  folder_id: number;
  folder_label: string;
  program_name?: string | null;
  year_intake: string;
  status: string;
  percent_complete: number;
  total_files: number;
  processed_files: number;
  skipped_files: number;
  failed_files: number;
  current_file?: string | null;
  details: Array<{
    file_name: string;
    status: string;
    reason?: string;
    students?: number;
    courses?: number;
  }>;
  error?: string | null;
  started_at: string;
  finished_at?: string | null;
  to_classify?: number;
  classified_files?: number;
  to_extract?: number;
  extracted_files?: number;
  eta_seconds?: number | null;
};

/**
 * Optional controls for a manual extraction job.
 *
 * Normal extraction callers can keep calling:
 * startCloudFolderExtractionJob(folderId)
 *
 * Selected transcript re-extraction should call:
 * startCloudFolderExtractionJob(folderId, {
 *   forceReextract: true,
 *   selectedFileIds: [123, 456],
 * })
 *
 * selectedFileIds are ExtractionFileDetails IDs, not student IDs.
 */
export type StartCloudFolderExtractionJobOptions = {
  forceReextract?: boolean;
  selectedFileIds?: Array<number | string>;
};

function normalizeSelectedFileIds(
  values?: Array<number | string>,
): number[] {
  if (!values?.length) {
    return [];
  }

  return Array.from(
    new Set(
      values
        .map((value) => Number(value))
        .filter(
          (value) =>
            Number.isInteger(value) &&
            Number.isFinite(value) &&
            value > 0,
        ),
    ),
  );
}

export function listCloudFolders(termId?: string) {
  const qs = termId
    ? `?year_intake=${encodeURIComponent(termId)}`
    : '';

  return apiFetch<CloudFolderDTO[]>(
    `/api/cloud-folder-locations${qs}`,
  );
}

export function createCloudFolder(payload: {
  label: string;
  year_intake: string;
  user_id?: string;
  institution_id?: number;
  program_name?: string;
  source_type?: string;
  source_uri?: string;
}) {
  // program_name retained for backward compatibility; ignored by backend.
  return apiFetch<CloudFolderDTO>(`/api/cloud-folder-locations`, {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export function updateCloudFolder(
  id: string | number,
  payload: {
    label: string;
    year_intake: string;
    program_name?: string;
    source_type?: string;
    source_uri?: string;
  },
) {
  const sid = String(id);

  return apiFetch<CloudFolderDTO>(`/api/cloud-folder-locations/${sid}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export function deleteCloudFolder(id: string | number) {
  const sid = String(id);

  return apiFetch(`/api/cloud-folder-locations/${sid}`, {
    method: 'DELETE',
  });
}

export function listCloudFolderFiles(
  id: string | number,
  path?: string,
) {
  const sid = String(id);
  const qs = path ? `?path=${encodeURIComponent(path)}` : '';

  return apiFetch<CloudFolderFileDTO[]>(
    `/api/cloud-folder-locations/${sid}/files${qs}`,
    {
      method: 'GET',
    },
  );
}

export function extractCloudFolder(id: string | number) {
  const sid = String(id);

  return apiFetch(`/api/cloud-folder-locations/${sid}/extract`, {
    method: 'POST',
  });
}

/**
 * Start a cloud-folder extraction job.
 *
 * Important safety behavior:
 *
 * - No options -> existing normal guarded extraction behavior.
 *
 * - selectedFileIds -> backend extracts only those ExtractionFileDetails rows.
 *
 * - forceReextract is sent only when explicitly requested.
 *
 * The backend validates that every selected file belongs to the logged-in
 * institution and to the selected folder's term.
 */
export function startCloudFolderExtractionJob(
  id: string | number,
  options?: StartCloudFolderExtractionJobOptions,
): Promise<CloudFolderExtractionJobDTO> {
  const sid = String(id);
  const selectedFileIds = normalizeSelectedFileIds(
    options?.selectedFileIds,
  );

  // Preserve the existing request exactly for all old callers.
  if (!options) {
    return apiFetch<CloudFolderExtractionJobDTO>(
      `/api/cloud-folder-locations/${sid}/extract-jobs`,
      {
        method: 'POST',
      },
    );
  }

  const forceReextract = Boolean(options.forceReextract);

  /**
   * A caller that supplies selectedFileIds but every value is invalid should
   * fail on the client rather than accidentally sending an empty selection.
   * This prevents a checkbox-driven "selected only" action from falling back
   * to a term-wide forced re-extraction.
   */
  if (
    options.selectedFileIds !== undefined &&
    options.selectedFileIds.length > 0 &&
    selectedFileIds.length === 0
  ) {
    return Promise.reject(
      new Error(
        'No valid transcript file IDs were selected for re-extraction.',
      ),
    );
  }

  return apiFetch<CloudFolderExtractionJobDTO>(
    `/api/cloud-folder-locations/${sid}/extract-jobs`,
    {
      method: 'POST',
      body: JSON.stringify({
        force_reextract: forceReextract,
        selected_file_ids: selectedFileIds,
      }),
    },
  );
}

/**
 * Explicit helper for checkbox-driven re-extraction.
 *
 * It refuses an empty selection so the UI can never accidentally turn
 * "Re-extract Selected" into "Re-extract the whole term".
 */
export function startSelectedCloudFolderReExtractionJob(
  id: string | number,
  selectedFileIds: Array<number | string>,
): Promise<CloudFolderExtractionJobDTO> {
  const normalized = normalizeSelectedFileIds(selectedFileIds);

  if (normalized.length === 0) {
    return Promise.reject(
      new Error('Select at least one transcript to re-extract.'),
    );
  }

  return startCloudFolderExtractionJob(id, {
    forceReextract: true,
    selectedFileIds: normalized,
  });
}

export function pollCloudFolder(id: string | number) {
  const sid = String(id);

  return apiFetch(`/api/cloud-folder-locations/${sid}/poll`, {
    method: 'POST',
  });
}

/**
 * Read-only discovery helper for extraction jobs that were created
 * automatically by the backend after uploads settle.
 *
 * This does not create, restart, cancel, or otherwise modify an extraction job.
 */
export function listActiveCloudFolderExtractionJobs(): Promise<
  CloudFolderExtractionJobDTO[]
> {
  return apiFetch<CloudFolderExtractionJobDTO[]>(
    '/api/cloud-folder-locations/extract-jobs/active',
    {
      method: 'GET',
    },
  );
}

export function getCloudFolderExtractionJob(
  jobId: string,
): Promise<CloudFolderExtractionJobDTO> {
  return apiFetch<CloudFolderExtractionJobDTO>(
    `/api/cloud-folder-locations/extract-jobs/${jobId}`,
    {
      method: 'GET',
    },
  );
}

export function deleteUploadedObjects(
  folderId: string | number,
  objects: string[],
) {
  const sid = String(folderId);

  return apiFetch<{ deleted: number }>(
    `/api/cloud-folder-locations/${sid}/delete-objects`,
    {
      method: 'POST',
      body: JSON.stringify({ objects }),
    },
  );
}

export function deleteFileFromFolder(
  folderId: string | number,
  path: string,
) {
  const sid = String(folderId);

  return apiFetch<{
    deleted_objects: number;
    deleted_records: number;
  }>(
    `/api/cloud-folder-locations/${sid}/delete-file`,
    {
      method: 'POST',
      body: JSON.stringify({ path }),
    },
  );
}

export function deleteFolderPath(
  folderId: string | number,
  path: string,
) {
  const sid = String(folderId);

  return apiFetch<{
    deleted_objects: number;
    deleted_records: number;
  }>(
    `/api/cloud-folder-locations/${sid}/delete-folder`,
    {
      method: 'POST',
      body: JSON.stringify({ path }),
    },
  );
}

export function purgeCloudFolder(id: string | number) {
  const sid = String(id);

  return apiFetch<{
    ok: boolean;
    deleted_objects: number;
    deleted_records: number;
  }>(
    `/api/cloud-folder-locations/${sid}/purge`,
    {
      method: 'DELETE',
    },
  );
}

export function cancelCloudFolderExtractionJob(
  jobId: string,
): Promise<CloudFolderExtractionJobDTO> {
  return apiFetch<CloudFolderExtractionJobDTO>(
    `/api/cloud-folder-locations/extract-jobs/${jobId}/cancel`,
    {
      method: 'POST',
    },
  );
}

// Classification pipeline progress
export type PipelineStatus = {
  last_run_status: string;
  is_running: boolean;
  current_job_id: string | null;
  queued_jobs: string[];
  queue_length: number;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  last_finished_job_id: string | null;
  progress_stage: string | null;
  progress_percent: number;
};

export function fetchPipelineStatus() {
  return apiFetch(`/api/pipeline/status`, {
    method: 'GET',
  });
}

export function cancelPipeline() {
  return apiFetch<{ ok: boolean; message?: string }>(
    `/api/pipeline/cancel`,
    {
      method: 'POST',
    },
  );
}
