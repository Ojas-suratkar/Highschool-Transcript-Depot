import { apiFetch } from "../utils.ts";


export function listProgramNames(institutionId: number, yearIntake: string) {
  const qs = `?institution_id=${institutionId}&year_intake=${encodeURIComponent(yearIntake)}`;
  return apiFetch<string[]>(`/api/program-criteria/program-names${qs}`);
}