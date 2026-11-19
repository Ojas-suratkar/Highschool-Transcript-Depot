import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

type DateInput = string | number | Date | null | undefined;

const PST_TIMEZONE = 'America/Los_Angeles';

export function formatDatePST(value: DateInput, options?: Intl.DateTimeFormatOptions) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat('en-US', {
    timeZone: PST_TIMEZONE,
    dateStyle: 'medium',
    ...(options || {}),
  }).format(date);
}

export function formatDateTimePST(value: DateInput, options?: Intl.DateTimeFormatOptions) {
  if (!value) return '';
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat('en-US', {
    timeZone: PST_TIMEZONE,
    dateStyle: 'short',
    timeStyle: 'short',
    ...(options || {}),
  }).format(date);
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const token = typeof window !== 'undefined' ? localStorage.getItem('th_access_token') : null;
  const defaultHeaders: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> ?? {}),
  };
  if (token) {
    defaultHeaders['Authorization'] = `Bearer ${token}`;
  }

  const res = await fetch(path, {
    headers: defaultHeaders,
    ...init,
  });

  // Read body once to handle empty responses safely
  const raw = await res.text().catch(() => "");

  if (!res.ok) {
    throw new Error(raw || `Request failed: ${res.status}`);
  }
  if (res.status === 204 || raw.trim() === "") return undefined as T;
  try {
    return JSON.parse(raw) as T;
  } catch {
    throw new Error("Unexpected response format");
  }
}
