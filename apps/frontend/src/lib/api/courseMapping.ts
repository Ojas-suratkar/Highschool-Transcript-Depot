// Course -> A-G mapping overrides (institution-level). Search the UC Doorways
// catalog, then reassign a course's A-G category or add a new one.

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json();
}

export interface CourseHit {
  course_name: string;
  ag_letter: string | null;
  ag_description: string | null;
  discipline: string | null;
  occurrences: number;
}

export interface CourseOverride {
  id: number;
  course_name: string;
  discipline: string | null;
  original_ag: string | null;
  target_ag: string;
  is_new: boolean;
  enabled: boolean;
  updated_at: string;
}

export interface OverrideInput {
  course_name: string;
  discipline?: string | null;
  original_ag?: string | null;
  target_ag: string;
  is_new?: boolean;
}

export const AG_TARGETS: Array<{ value: string; label: string }> = [
  { value: 'a', label: 'A — History / Social Science' },
  { value: 'b', label: 'B — English' },
  { value: 'c', label: 'C — Mathematics' },
  { value: 'd1', label: 'D1 — Biological Science' },
  { value: 'd2', label: 'D2 — Physical Science' },
  { value: 'd', label: 'D — Science (extra)' },
  { value: 'e', label: 'E — Language Other Than English' },
  { value: 'f', label: 'F — Visual & Performing Arts' },
  { value: 'g', label: 'G — College-Prep Elective' },
  { value: 'exclude', label: 'Exclude from A-G' },
];

export function agLabel(value: string | null | undefined): string {
  if (!value) return '—';
  const hit = AG_TARGETS.find((t) => t.value === value.toLowerCase());
  return hit ? hit.label : value.toUpperCase();
}

export async function searchUcCourses(q: string, limit = 30): Promise<CourseHit[]> {
  return apiFetch(`/api/course-mapping/search?q=${encodeURIComponent(q)}&limit=${limit}`);
}

export async function listCourseOverrides(): Promise<CourseOverride[]> {
  return apiFetch('/api/course-mapping/overrides');
}

export async function upsertCourseOverride(payload: OverrideInput): Promise<CourseOverride> {
  return apiFetch('/api/course-mapping/overrides', {
    method: 'POST',
    body: JSON.stringify(payload),
  });
}

export async function deleteCourseOverride(id: number): Promise<void> {
  await apiFetch(`/api/course-mapping/overrides/${id}`, { method: 'DELETE' });
}
