import { apiFetch } from "../utils.ts";

export type PrereqPayload = { course_name: string; min_gpa?: string };

export type CreateProgramPayload = {
  program_name: string;
  year_intake: string;
  prerequisites?: PrereqPayload[];
};

export type ProgramSummaryDTO = {
  id: number;
  program_name: string;
  year_intake: string;
  prereq_count: number;
};

export async function createProgram(payload: CreateProgramPayload) {
  return apiFetch<{ ok: boolean; created: boolean; id: number }>(`/api/program-criteria`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function updateProgram(programId: number, payload: CreateProgramPayload) {
  return apiFetch<{ ok: boolean; id: number }>(`/api/program-criteria/${programId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function deleteProgram(programId: number) {
  return apiFetch<{ ok: boolean }>(`/api/program-criteria/${programId}`, {
    method: "DELETE",
  });
}

export async function createProgramVersion(programId: number, notes?: string) {
  return apiFetch<{ ok: boolean; id: number }>(`/api/program-criteria/${programId}/versions`, {
    method: 'POST',
    body: JSON.stringify({ notes }),
  });
}

export async function listPrograms() {
  return apiFetch<ProgramSummaryDTO[]>(`/api/program-criteria`, { method: 'GET' });
}

export async function listProgramPrereqs(programId: number) {
  return apiFetch<PrereqPayload[]>(`/api/program-criteria/${programId}/prereqs`, {
    method: "GET",
  });
}
