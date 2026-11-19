import { apiFetch } from "../utils.ts";
export type TermDTO = {
  id: number;
  term_name: string;
  term: "spring" | "summer" | "fall" | "winter";
  year: number;
  institution_id: number;
  is_current: boolean;
};

export type CreateTermPayload = {
  term_name: string;
  term: "spring" | "summer" | "fall" | "winter";
  year: number;
  institution_id: number;
  created_by_user_id: string; // UUID
};

export function listTerms(institutionId: number) {
  return apiFetch<TermDTO[]>(`/api/academic-terms?institution_id=${institutionId}`);
}

export function createTerm(payload: CreateTermPayload) {
    console.log(payload)
  return apiFetch<TermDTO>(`/api/academic-terms`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function deleteTerm(termId: number | string) {
  return apiFetch<{ deleted: boolean; term_name: string }>(
    `/api/academic-terms/${termId}`,
    { method: "DELETE" }
  );
}
