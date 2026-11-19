export interface StudentAgSummary {
  id: number;
  student_id: number;
  a_calc: number; b_calc: number; c_calc: number;
  d1_calc: number; d2_calc: number; d_calc: number;
  e_calc: number; f_calc: number; g_calc: number;
  a_override: number | null; b_override: number | null; c_override: number | null;
  d1_override: number | null; d2_override: number | null; d_override: number | null;
  e_override: number | null; f_override: number | null; g_override: number | null;
  gpa_extracted: number | null;
  gpa_cumulative: number | null;
  gpa_english: number | null;
  gpa_math: number | null;
  gpa_science: number | null;
  stem_score: number | null;
  csulb_score: number | null;
  gpa_cumulative_override: number | null;
  gpa_english_override: number | null;
  gpa_math_override: number | null;
  gpa_science_override: number | null;
  stem_score_override: number | null;
  csulb_score_override: number | null;
  course_overrides: Record<string, any> | null;
  admission_decision: string | null;
  year_intake: string | null;
  reviewed: boolean;
  updated_at: string;
}

export interface AgOverrides {
  a?: number | null; b?: number | null; c?: number | null;
  d1?: number | null; d2?: number | null; d?: number | null;
  e?: number | null; f?: number | null; g?: number | null;
}

export interface AdmissionResultPayload {
  student_id: number;
  year_intake?: string | null;
  admission_decision?: string | null;
  ag_overrides?: AgOverrides | null;
  gpa_cumulative?: number | null;
  gpa_english?: number | null;
  gpa_math?: number | null;
  gpa_science?: number | null;
  stem_score?: number | null;
  csulb_score?: number | null;
  gpa_extracted?: number | null;
  course_overrides?: Record<string, any> | null;
  reviewed?: boolean | null;
}

import { apiFetch as sharedFetch } from '@/lib/utils';

export async function getStudentAgSummary(studentId: number): Promise<StudentAgSummary | null> {
  try {
    return await sharedFetch<StudentAgSummary>(`/api/student-ag-summary/${studentId}`);
  } catch {
    return null;
  }
}

export async function saveAdmissionResult(payload: AdmissionResultPayload): Promise<StudentAgSummary> {
  return sharedFetch<StudentAgSummary>('/api/student-ag-summary/save-admission-result', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function recomputeAgSummary(studentId: number): Promise<StudentAgSummary> {
  return sharedFetch<StudentAgSummary>(`/api/student-ag-summary/recompute/${studentId}`, { method: 'POST' });
}

export async function batchCalculateAdmission(
  term: string,
  force = false,
  background = false,
): Promise<{ processed: number; scheduled?: boolean }> {
  try {
    const qs = `${force ? '&force=true' : ''}${background ? '&background=true' : ''}`;
    return await sharedFetch<{ processed: number; scheduled?: boolean }>(
      `/api/admission/batch-calculate?term=${encodeURIComponent(term)}${qs}`,
      { method: 'POST' },
    );
  } catch {
    return { processed: 0 };
  }
}
