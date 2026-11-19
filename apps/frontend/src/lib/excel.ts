import * as XLSX from 'xlsx';

export interface ParsedSheet {
  /** Original file name, e.g. "fall-2025-targets.xlsx". */
  fileName: string;
  /** File size in bytes. */
  fileSize: number;
  /** Name of the sheet we read (first non-empty sheet). */
  sheetName: string;
  /** Header labels in original order. */
  headers: string[];
  /** Data rows as objects keyed by header label. */
  rows: Record<string, string>[];
}

/**
 * Parse an uploaded .xlsx / .xls / .csv file entirely in the browser.
 * Reads the first sheet, using the first row as headers.
 */
export async function parseSpreadsheet(file: File): Promise<ParsedSheet> {
  const buf = await file.arrayBuffer();
  const wb = XLSX.read(buf, { type: 'array' });
  const sheetName = wb.SheetNames[0];
  const ws = wb.Sheets[sheetName];
  if (!ws) {
    return { fileName: file.name, fileSize: file.size, sheetName: sheetName || '', headers: [], rows: [] };
  }

  // Grid form (array of arrays) so we can read the header row exactly as written.
  const grid = XLSX.utils.sheet_to_json<string[]>(ws, { header: 1, defval: '', blankrows: false });
  const headerRow = (grid[0] || []).map((h) => String(h ?? '').trim());
  const headers = headerRow.filter((h) => h.length > 0);

  const rows: Record<string, string>[] = [];
  for (let i = 1; i < grid.length; i++) {
    const cells = grid[i] || [];
    // Skip fully empty rows.
    if (cells.every((c) => String(c ?? '').trim() === '')) continue;
    const obj: Record<string, string> = {};
    headerRow.forEach((h, idx) => {
      if (!h) return;
      obj[h] = String(cells[idx] ?? '').trim();
    });
    rows.push(obj);
  }

  return { fileName: file.name, fileSize: file.size, sheetName, headers, rows };
}

const normalize = (s: string) => s.toLowerCase().replace(/[^a-z0-9]/g, '');

/**
 * Read a value from a parsed row by trying several candidate header names
 * (case/space/punctuation-insensitive, exact match first then "contains").
 */
export function pickField(row: Record<string, string>, candidates: string[]): string {
  const keys = Object.keys(row);
  for (const cand of candidates) {
    const c = normalize(cand);
    const k = keys.find((key) => normalize(key) === c);
    if (k && String(row[k]).trim() !== '') return String(row[k]).trim();
  }
  for (const cand of candidates) {
    const c = normalize(cand);
    const k = keys.find((key) => normalize(key).includes(c));
    if (k && String(row[k]).trim() !== '') return String(row[k]).trim();
  }
  return '';
}

/** Parse a numeric cell, stripping commas / % / currency symbols. */
export function pickNumber(row: Record<string, string>, candidates: string[]): number {
  const raw = pickField(row, candidates);
  if (!raw) return 0;
  const n = Number(raw.replace(/[^0-9.\-]/g, ''));
  return Number.isFinite(n) ? n : 0;
}

/** Human-readable file size, e.g. "12.4 KB". */
export function formatFileSize(bytes: number): string {
  if (!bytes) return '0 B';
  const units = ['B', 'KB', 'MB', 'GB'];
  const i = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const val = bytes / Math.pow(1024, i);
  return `${i === 0 ? val : val.toFixed(1)} ${units[i]}`;
}
