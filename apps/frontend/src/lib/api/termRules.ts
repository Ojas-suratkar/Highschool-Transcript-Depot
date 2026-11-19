// Term rules: upload a handbook, review the Gemini-compiled rules, approve them.

export interface TermRule {
  id: string;
  type: string;
  area: string | null;
  title: string;
  params: Record<string, unknown>;
  source_quote: string;
  source_page: number | null;
  confidence: number;
  approved: boolean;
  relevant?: boolean; // A-G relevance (type gate + Gemini check); undefined = relevant
  relevance_reason?: string;
  // Deterministic-engine binding: when set, approving this rule auto-configures
  // the engine (criteria/toggles) and it is enforced in code, not by the LLM.
  engine_binding?: { id: string; label: string } | null;
}

export interface UnsupportedRule {
  title?: string;
  source_quote?: string;
  source_page?: number | null;
  reason?: string;
}

export interface RuleSet {
  id: number;
  year_intake: string;
  version: number;
  status: string; // processing | draft | approved | error
  error?: string | null;
  pages_total?: number | null;
  pages_done?: number | null;
  document_name: string | null;
  document_hash: string | null;
  document_gcs_path?: string | null;
  rules: TermRule[] | null;
  unsupported: UnsupportedRule[] | null;
  approved_by: string | null;
  updated_at: string;
}

async function apiFetch(path: string, init?: RequestInit) {
  const res = await fetch(path, {
    headers: init?.body instanceof FormData ? {} : { 'Content-Type': 'application/json' },
    ...init,
  });
  if (!res.ok) throw new Error((await res.text()) || `HTTP ${res.status}`);
  const text = await res.text();
  return text ? JSON.parse(text) : null;
}

export async function getTermRules(term: string): Promise<RuleSet | null> {
  return apiFetch(`/api/term-rules?term=${encodeURIComponent(term)}`);
}

export async function uploadTermRules(term: string, file: File): Promise<RuleSet> {
  const form = new FormData();
  form.append('file', file);
  return apiFetch(`/api/term-rules/upload?term=${encodeURIComponent(term)}`, {
    method: 'POST',
    body: form,
  });
}

export async function saveTermRules(rulesetId: number, rules: TermRule[]): Promise<RuleSet> {
  return apiFetch(`/api/term-rules/${rulesetId}/rules`, {
    method: 'PUT',
    body: JSON.stringify({ rules }),
  });
}

export async function approveTermRules(rulesetId: number): Promise<RuleSet> {
  return apiFetch(`/api/term-rules/${rulesetId}/approve`, { method: 'POST' });
}

export async function reprocessTermRules(rulesetId: number): Promise<RuleSet> {
  return apiFetch(`/api/term-rules/${rulesetId}/reprocess`, { method: 'POST' });
}

export interface AreaVerdict {
  area: string;
  satisfied: boolean;
  reason: string;
  cited_rule_ids?: string[];
  cited_courses?: string[];
}

export interface LearnedRule {
  title?: string;
  why_applied?: string;
  source?: string;
}

export interface Verdict {
  id: number;
  student_id: number;
  ruleset_version: number;
  decision: string | null;
  baseline_decision: string | null;
  reason: string | null;
  per_area: AreaVerdict[] | null;
  learned_rules: LearnedRule[] | null;
  overridden: boolean;
  override_decision: string | null;
  updated_at: string;
}

export async function getVerdict(studentId: number): Promise<Verdict | null> {
  return apiFetch(`/api/term-rules/verdict?student_id=${studentId}`);
}

export async function getVerdictHistory(studentId: number): Promise<Verdict[]> {
  return apiFetch(`/api/term-rules/verdict/history?student_id=${studentId}`);
}

export async function overrideVerdict(studentId: number, decision: string | null): Promise<Verdict> {
  return apiFetch(`/api/term-rules/verdict/override`, {
    method: 'POST',
    body: JSON.stringify({ student_id: studentId, decision }),
  });
}

export async function getLearnedRules(term: string): Promise<LearnedRule[]> {
  return apiFetch(`/api/term-rules/learned?term=${encodeURIComponent(term)}`);
}

export const RULE_TYPE_LABELS: Record<string, string> = {
  subject_requirement: 'Subject requirement',
  grade_rule: 'Grade rule',
  validation_rule: 'Validation',
  substitution_rule: 'Substitution / makeup',
  discipline_map: 'Discipline mapping',
  gpa_rule: 'GPA rule',
  index_formula: 'Index formula',
  final_audit: 'Final audit',
  other: 'Other',
};
