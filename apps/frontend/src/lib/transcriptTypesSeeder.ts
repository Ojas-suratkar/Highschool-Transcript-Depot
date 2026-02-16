// Simple seeder for demo transcript types
const STORAGE_KEY = 'transcriptTypes_v1';

export interface SeedType {
  id: string;
  name: string;
  status: 'Needs Setup' | 'In Setup' | 'Ready';
  count?: number;
  analyzing?: number;
  processed?: number;
  lastUpdated?: string;
  readySince?: string;
}

const DEFAULT_SEED: SeedType[] = [
  { id: 't1', name: 'Example High School - Unknown Format', status: 'Needs Setup', count: 5 },
  { id: 't4', name: 'Community College - Strange Layout', status: 'Needs Setup', count: 2 },
  { id: 't5', name: 'Roosevelt Academy - Handwritten Grades', status: 'Needs Setup', count: 3 },
  { id: 't6', name: 'Valley Technical - Multi-column', status: 'Needs Setup', count: 7 },
  { id: 't7', name: 'International - Foreign language headers', status: 'Needs Setup', count: 4 },

  { id: 't10', name: 'Metro High - Banner headers', status: 'In Setup', analyzing: 6, lastUpdated: new Date().toISOString() },
  { id: 't11', name: 'Suburban HS - scanned PDFs', status: 'In Setup', analyzing: 9, lastUpdated: new Date().toISOString() },
  { id: 't12', name: 'International College - different transcript order', status: 'In Setup', analyzing: 3, lastUpdated: new Date().toISOString() },

  { id: 't20', name: 'Lincoln District - Common layout', status: 'Ready', processed: 120, readySince: new Date().toISOString() },
  { id: 't21', name: 'State College - Standard format', status: 'Ready', processed: 80, readySince: new Date().toISOString() },
  { id: 't22', name: 'Online University - PDF export', status: 'Ready', processed: 45, readySince: new Date().toISOString() },
];

export function seedTranscriptTypesIfMissing(minimum = 3) {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_SEED));
      return;
    }
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed) || parsed.length < minimum) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_SEED));
      return;
    }
  } catch (e) {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_SEED));
  }
}

// Force-seed N items per status (default 10 each). This will replace any existing storage.
export function seedTranscriptTypes(force = false, perStatus = 10) {
  if (!force) return;
  const makeNeeds = (n: number) =>
    Array.from({ length: n }).map((_, i) => ({
      id: `needs-${i + 1}`,
      name: `Needs Setup Sample ${i + 1}`,
      status: 'Needs Setup' as const,
      count: Math.floor(Math.random() * 10) + 1,
    }));

  const makeInSetup = (n: number) =>
    Array.from({ length: n }).map((_, i) => ({
      id: `in-${i + 1}`,
      name: `In Setup Sample ${i + 1}`,
      status: 'In Setup' as const,
      analyzing: +(Math.random() * 9 + 1).toFixed(2),
      lastUpdated: new Date().toISOString(),
    }));

  const makeReady = (n: number) =>
    Array.from({ length: n }).map((_, i) => ({
      id: `ready-${i + 1}`,
      name: `Ready Sample ${i + 1}`,
      status: 'Ready' as const,
      processed: Math.floor(Math.random() * 300) + 20,
      readySince: new Date().toISOString(),
    }));

  const combined = [...makeNeeds(perStatus), ...makeInSetup(perStatus), ...makeReady(perStatus)];
  localStorage.setItem(STORAGE_KEY, JSON.stringify(combined));
}

export default seedTranscriptTypesIfMissing;
