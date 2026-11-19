export type TranscriptSchoolTypeStatus =
  | "needs_setup"
  | "in_setup"
  | "ready"
  | "existing"
  | "failed"
  | "held";

export interface TranscriptSchoolTypeSample {
  id: number;
  file_name: string;
  blob_name?: string | null;
  gcs_uri: string;
  semester?: string | null;
  detected_school_name?: string | null;
  created_at?: string | null;
}

export interface TranscriptSchoolType {
  id: number;
  display_name: string;
  normalized_name?: string | null;
  classifier_label: string;
  status: TranscriptSchoolTypeStatus;
  sample_count: number;
  required_sample_count: number;
  cluster_confidence?: number | null;
  gcs_raw_prefix?: string | null;
  gcs_training_prefix?: string | null;
  document_ai_processor_id?: string | null;
  document_ai_processor_version_id?: string | null;
  import_operation_name?: string | null;
  training_operation_name?: string | null;
  deploy_operation_name?: string | null;
  extractor_profile?: string | null;
  error_message?: string | null;
  samples?: TranscriptSchoolTypeSample[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TranscriptClassifierRoute {
  id: number;
  classifier_label: string;
  display_name: string;
  extractor_profile: string;
  status: "active" | "inactive";
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ClassifierTrainingResult {
  queued?: boolean;
  processed?: number;
  in_progress?: number;
  ready?: number;
  failed?: number;
  skipped?: number;
  message?: string;
  details?: unknown;
  [key: string]: unknown;
}

export interface ClassifierTrainingRunResponse {
  status: string;
  result: ClassifierTrainingResult;
  school_type?: TranscriptSchoolType | null;
}

export interface ExtractorSetupRunResponse {
  status: string;
  message?: string;
  result?: Record<string, unknown>;
  school_type?: TranscriptSchoolType | null;
}

export interface MoveSchoolTypeToExistingResponse {
  status: string;
  message?: string;
  school_type?: TranscriptSchoolType | null;
  route?: TranscriptClassifierRoute | null;
}

// Same-origin by default: the app serves its API under /api behind the same
// host (Cloud Run), so an empty base is correct in every environment. The env
// vars remain as overrides for local split-port development.
const API_BASE =
  import.meta.env.VITE_API_BASE_URL ||
  import.meta.env.VITE_API_URL ||
  "";

async function apiJson<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
  });

  const text = await response.text();

  let data: any = null;

  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }

  if (!response.ok) {
    const message =
      data?.detail ||
      data?.message ||
      data ||
      `Request failed with status ${response.status}`;

    throw new Error(String(message));
  }

  return data as T;
}

export function transcriptDetectorFileUrl(blobName: string): string {
  return `${API_BASE}/api/transcript-detector/new/file?blob_name=${encodeURIComponent(
    blobName
  )}`;
}

export async function getClassifierSchoolTypes(
  status?: TranscriptSchoolTypeStatus
): Promise<TranscriptSchoolType[]> {
  const query = status ? `?status=${encodeURIComponent(status)}` : "";

  return apiJson<TranscriptSchoolType[]>(
    `/api/classifier-training/school-types${query}`
  );
}

export async function getNeedsSetupSchoolTypes(): Promise<
  TranscriptSchoolType[]
> {
  return getClassifierSchoolTypes("needs_setup");
}

export async function getInSetupSchoolTypes(): Promise<TranscriptSchoolType[]> {
  return getClassifierSchoolTypes("in_setup");
}

export async function getReadySchoolTypes(): Promise<TranscriptSchoolType[]> {
  return getClassifierSchoolTypes("ready");
}

export async function getExistingSchoolTypes(): Promise<TranscriptSchoolType[]> {
  return getClassifierSchoolTypes("existing");
}

export async function getFailedSchoolTypes(): Promise<TranscriptSchoolType[]> {
  return getClassifierSchoolTypes("failed");
}

export async function getClassifierRoutes(): Promise<
  TranscriptClassifierRoute[]
> {
  return apiJson<TranscriptClassifierRoute[]>(
    "/api/classifier-training/routes"
  );
}

export async function startSchoolTypeSetup(
  schoolTypeId: number
): Promise<ClassifierTrainingRunResponse> {
  return apiJson<ClassifierTrainingRunResponse>(
    `/api/classifier-training/school-types/${schoolTypeId}/start`,
    {
      method: "POST",
    }
  );
}

/**
 * Runs the actual classifier setup worker for rows currently in setup.
 *
 * Backend:
 * POST /api/classifier-training/run-ready
 *
 * Used by the In Setup page classifier button.
 */
export async function runClassifierSetup(): Promise<
  ClassifierTrainingRunResponse
> {
  return apiJson<ClassifierTrainingRunResponse>(
    "/api/classifier-training/run-ready",
    {
      method: "POST",
    }
  );
}

/**
 * Backward-compatible alias.
 * Existing code can keep importing runReadySchoolTypeSetup.
 */
export async function runReadySchoolTypeSetup(): Promise<
  ClassifierTrainingRunResponse
> {
  return runClassifierSetup();
}

/**
 * Starts extractor setup for one transcript type.
 *
 * Backend expected:
 * POST /api/classifier-training/school-types/{schoolTypeId}/start-extractor
 *
 * Used by the In Setup page extractor button.
 */
export async function startExtractorSetup(
  schoolTypeId: number
): Promise<ExtractorSetupRunResponse> {
  return apiJson<ExtractorSetupRunResponse>(
    `/api/classifier-training/school-types/${schoolTypeId}/start-extractor`,
    {
      method: "POST",
    }
  );
}

/**
 * Moves a fully ready transcript type to Existing.
 *
 * Backend expected:
 * POST /api/classifier-training/school-types/{schoolTypeId}/move-to-existing
 *
 * This should activate the transcript type globally for all semesters.
 */
export async function moveSchoolTypeToExisting(
  schoolTypeId: number
): Promise<MoveSchoolTypeToExistingResponse> {
  return apiJson<MoveSchoolTypeToExistingResponse>(
    `/api/classifier-training/school-types/${schoolTypeId}/move-to-existing`,
    {
      method: "POST",
    }
  );
}
