export interface AgCriteria {
  id: number;
  institution_id: number;
  year_intake: string;
  a_required: number;
  b_required: number;
  c_required: number;
  d1_required: number;
  d2_required: number;
  d_required: number;
  e_required: number;
  f_required: number;
  g_required: number;
  min_gpa_cumulative: number | null;
  min_gpa_english: number | null;
  min_gpa_math: number | null;
  min_gpa_science: number | null;
  min_csulb_score: number | null;
  min_stem_score: number | null;
  california_resident_min_gpa: number | null;
  non_resident_min_gpa: number | null;
  non_resident_csulb_score: number | null;
  ag_hs_grades: number[] | null;
  gpa_hs_grades: number[] | null;
  gpa_cumulative_hs_grades: number[] | null;
  rule_config: AgRuleConfig | null;
  updated_at: string;
}

// Strict handbook A-G rule toggles (all default off = current behavior).
export interface AgRuleConfig {
  strict_c_math_slots?: boolean;
  strict_a_history_anchor?: boolean;
  strict_f_same_discipline?: boolean;
}

export type AgCriteriaInput = Omit<AgCriteria, 'id' | 'institution_id' | 'updated_at'>;

export const DEFAULT_AG_CRITERIA: Omit<AgCriteriaInput, 'year_intake'> = {
  a_required: 4,
  b_required: 8,
  c_required: 6,
  d1_required: 2,
  d2_required: 2,
  d_required: 4,
  e_required: 4,
  f_required: 2,
  g_required: 2,
  min_gpa_cumulative: 3.0,
  min_gpa_english: 3.0,
  min_gpa_math: 3.0,
  min_gpa_science: 3.0,
  min_csulb_score: 3200,
  min_stem_score: 3600,
  california_resident_min_gpa: 2.5,
  non_resident_min_gpa: 3.0,
  non_resident_csulb_score: 3500,
  ag_hs_grades: [8, 9, 10, 11, 12],
  gpa_hs_grades: [9, 10, 11, 12],
  gpa_cumulative_hs_grades: [10, 11, 12],
  rule_config: {
    strict_c_math_slots: false,
    strict_a_history_anchor: false,
    strict_f_same_discipline: false,
  },
};

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

export async function listAgCriteria(): Promise<AgCriteria[]> {
  return apiFetch('/api/institution-ag-criteria');
}

export async function getAgCriteriaForTerm(yearIntake: string): Promise<AgCriteria | null> {
  try {
    return await apiFetch(`/api/institution-ag-criteria/${encodeURIComponent(yearIntake)}`);
  } catch {
    return null;
  }
}

export async function upsertAgCriteria(payload: AgCriteriaInput): Promise<AgCriteria> {
  return apiFetch('/api/institution-ag-criteria', {
    method: 'PUT',
    body: JSON.stringify(payload),
  });
}
