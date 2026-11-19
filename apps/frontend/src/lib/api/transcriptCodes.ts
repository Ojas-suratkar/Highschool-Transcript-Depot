export type CodePosition = 'prefix' | 'suffix' | 'either';

export type CodeMeaning =
  | 'honors'
  | 'non_academic'
  | 'repeated'
  | 'college_prep'
  | 'ap'
  | 'dual_enrollment'
  | 'other';

export const MEANING_LABELS: Record<CodeMeaning, string> = {
  honors: 'Honors',
  non_academic: 'Non-Academic',
  repeated: 'Repeated',
  college_prep: 'College Prep',
  ap: 'AP (Advanced Placement)',
  dual_enrollment: 'Dual Enrollment',
  other: 'Other',
};

export const POSITION_LABELS: Record<CodePosition, string> = {
  prefix: 'Prefix',
  suffix: 'Suffix',
  either: 'Either',
};

export interface TranscriptCode {
  id: number;
  institution_id: number;
  code: string;
  position: CodePosition;
  meaning: CodeMeaning;
  label: string;
  school_name: string | null;
  affects_ag: boolean;
  strip_for_matching: boolean;
  created_at: string;
  updated_at: string;
}

export interface TranscriptCodeInput {
  code: string;
  position: CodePosition;
  meaning: CodeMeaning;
  label: string;
  school_name: string | null;
  affects_ag: boolean;
  strip_for_matching: boolean;
}

async function apiFetch(path: string, init?: RequestInit) {
  const token = typeof window !== 'undefined' ? localStorage.getItem('th_access_token') : null;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  if (token) {
    headers['Authorization'] = `Bearer ${token}`;
  }
  const res = await fetch(path, {
    ...init,
    headers,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

export async function listTranscriptTypes(): Promise<string[]> {
  try {
    return await apiFetch('/api/transcript-course-codes/transcript-types');
  } catch {
    return [];
  }
}

export async function listTranscriptCodes(): Promise<TranscriptCode[]> {
  try {
    return await apiFetch('/api/transcript-course-codes');
  } catch {
    return [];
  }
}

export async function createTranscriptCode(payload: TranscriptCodeInput): Promise<TranscriptCode> {
  return apiFetch('/api/transcript-course-codes', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function updateTranscriptCode(id: number, payload: TranscriptCodeInput): Promise<TranscriptCode> {
  return apiFetch(`/api/transcript-course-codes/${id}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}

export async function deleteTranscriptCode(id: number): Promise<void> {
  await apiFetch(`/api/transcript-course-codes/${id}`, { method: 'DELETE' });
}
