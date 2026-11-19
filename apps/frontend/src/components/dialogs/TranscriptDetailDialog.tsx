import { useState, useEffect, useMemo } from 'react';
import { Plus, Clock } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Avatar } from '@/components/shared/Avatar';
import { useAuth } from '@/contexts/AuthContext';
import { AdmissionReviewTabs } from './AdmissionReview';
import { type TranscriptCode, listTranscriptCodes } from '@/lib/api/transcriptCodes';
import { fetchStudentDetail } from '@/lib/api/extractor';

export type TranscriptTab =
  | 'personal'
  | 'courses'
  | 'standardization'
  | 'agRequirement'
  | 'gpaCalculation'
  | 'transcript'
  | 'notes';

type StaffNote = {
  id: number;
  author: string;
  role: string | null;
  body: string;
  created_at: string | null;
};

function formatNoteTime(iso: string | null): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    const day = d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    const time = d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
    return `${day} · ${time}`;
  } catch {
    return '';
  }
}

function NotesPanel({ noteKey }: { noteKey: string }) {
  const { user } = useAuth();
  const authorName =
    [user?.first_name, user?.last_name].filter(Boolean).join(' ').trim() ||
    user?.email ||
    'Staff';
  const authorRole = user?.role || '';

  const [notes, setNotes] = useState<StaffNote[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    let on = true;
    setLoaded(false);
    setComposing(false);
    setDraft('');
    fetch(`/api/extractor/student-notes/${encodeURIComponent(noteKey)}`)
      .then((r) => r.json())
      .then((d) => {
        if (on) {
          setNotes(Array.isArray(d.notes) ? d.notes : []);
          setLoaded(true);
        }
      })
      .catch(() => { if (on) setLoaded(true); });
    return () => { on = false; };
  }, [noteKey]);

  const addNote = async () => {
    const body = draft.trim();
    if (!body) return;
    setSaving(true);
    try {
      const res = await fetch(`/api/extractor/student-notes/${encodeURIComponent(noteKey)}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ body, author: authorName, role: authorRole }),
      });
      const created = await res.json();
      if (created && created.id != null) {
        setNotes((prev) => [created as StaffNote, ...prev]);
      }
      setDraft('');
      setComposing(false);
    } catch {
      /* ignore transient failures */
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex flex-1 min-h-0 flex-col rounded-md border bg-white">
      <div className="flex shrink-0 items-start justify-between gap-3 p-4">
        <div>
          <h4 className="text-lg font-medium">Staff Notes</h4>
          <p className="mt-1 text-sm text-muted-foreground">
            Staff notes are visible to all authorized staff across devices.
          </p>
        </div>
        {!composing && (
          <Button size="sm" className="gap-1.5" onClick={() => setComposing(true)}>
            <Plus className="h-4 w-4" /> Add Note
          </Button>
        )}
      </div>

      {composing && (
        <div className="shrink-0 border-t bg-slate-50/60 p-4">
          <div className="flex items-start gap-3">
            <Avatar name={authorName} className="h-9 w-9 shrink-0 text-xs" />
            <div className="min-w-0 flex-1 space-y-2">
              <textarea
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="Write a note for the team…"
                rows={3}
                className="w-full resize-none rounded-md border bg-white p-3 text-sm outline-none focus:ring-2 focus:ring-blue-200"
              />
              <div className="flex items-center gap-2">
                <Button size="sm" onClick={addNote} disabled={saving || !draft.trim()}>
                  {saving ? 'Posting…' : 'Post note'}
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => { setComposing(false); setDraft(''); }}
                  disabled={saving}
                >
                  Cancel
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-auto border-t p-4">
        {!loaded ? (
          <p className="text-sm text-muted-foreground">Loading…</p>
        ) : notes.length === 0 ? (
          <div className="flex h-full min-h-[200px] items-center justify-center text-center text-sm text-muted-foreground">
            No notes yet. Click “Add Note” to start the conversation.
          </div>
        ) : (
          <div className="space-y-3">
            {notes.map((n) => (
              <div key={n.id} className="rounded-lg border bg-white p-4 shadow-sm">
                <div className="flex gap-4">
                  <div className="flex w-44 shrink-0 items-start gap-3">
                    <Avatar name={n.author} className="h-10 w-10 shrink-0 text-sm" />
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-900">{n.author}</div>
                      {n.role ? <div className="truncate text-xs text-slate-500">{n.role}</div> : null}
                    </div>
                  </div>
                  <div className="min-w-0 flex-1 border-l pl-4">
                    <div className="flex items-center gap-1.5 text-xs text-slate-500">
                      <Clock className="h-3.5 w-3.5" />
                      {formatNoteTime(n.created_at)}
                    </div>
                    <p className="mt-1.5 whitespace-pre-wrap break-words text-sm text-slate-800">
                      {n.body}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export type TranscriptRecord = {
  id: string;
  studentId?: string | null;
  sourceFile?: number | string | null;
  status?: string;
  studentName?: string | null;
  email?: string | null;
  format?: string | null;
  birthDate?: string | null;
  graduationDate?: string | null;
  address?: string | null;
  courses?: Array<{
    id?: number | string | null;
    crs_id?: number | string | null;
    name?: string;
    crs_hs?: string | null;
    transcript_type?: string | null;
    grade?: string;
    letter_grade?: string | null;
    crs_letter_grade?: string | null;
    crs_grade?: string | number | null;
    credits?: string;
    crs_credit_completed?: string | number | null;
    credits_completed?: string | number | null;
    year?: number | null;
    month?: number | null;
    grade_level?: number | null;
    course_type?: string | null;
    course_category?: string | null;
    uc_doorway_course_id?: number | null;
    mapping_status?: string | null;
    standardizedCode?: string | null;
    standardizedDescription?: string | null;
    mapped_uc_course?: {
      id?: number | null;
      hs_id?: number | null;
      crs_hs?: string | null;
      crs_description?: string | null;
      crs_discipline?: string | null;
      crs_environment?: string | null;
      crs_honors?: string | null;
      crs_ag_category_letter?: string | null;
      crs_ag_category_description?: string | null;
      crs_grade?: string | null;
      crs_transcript_abbrevs?: string | null;
      crs_local_codes?: string | null;
      crs_academic_year?: string | null;
    } | null;
  }>;
  reviewed?: boolean | null;
  gpa?: string | null;
  recalculated_gpa?: number | null;
  marks?: string | null;
  notes?: string | null;
  processed?: number;
  processedAt?: string | null;
  serial?: number;
  [k: string]: any;
};

type TranscriptCourse = NonNullable<TranscriptRecord['courses']>[number];

// ── Universal filter constants (same for every file) ──────────────────────────

/** All known course-ID letter prefixes across the DB, sorted alphabetically. */
const UNIVERSAL_ID_PREFIXES = ['DAC', 'H', 'HP', 'IN', 'N', 'ON', 'P', 'PR', 'R', 'W'];

/** All standard letter grades. */
const UNIVERSAL_LETTER_GRADES = ['A+', 'A', 'A-', 'B+', 'B', 'B-', 'C+', 'C', 'C-', 'D', 'F'];

/** High school grade levels. */
const UNIVERSAL_HS_GRADES = ['8', '9', '10', '11', '12'];

/** All known course types (mapped from prefix). */
const UNIVERSAL_COURSE_TYPES = [
  'Regular',
  'Honors',
  'Independent Study',
  'Non-Academic',
  'Repeat',
  'Withdrawn',
];

/** All known course categories (A-G descriptions + type fallbacks). */

/** A-G requirement letters (D split into D1/D2, D for generic science). */
const AG_LETTERS = ['A', 'B', 'C', 'D', 'D1', 'D2', 'E', 'F', 'G'];

// ── Helpers ───────────────────────────────────────────────────────────────────


const COURSE_TYPE_MAP: Record<string, string> = {
  H: 'Honors',
  HP: 'Honors',
  N: 'Non-Academic',
  P: 'Regular',
  R: 'Repeat',
  PR: 'Repeat',
  IN: 'Independent Study',
  W: 'Withdrawn',
};

const MEANING_TYPE_LABEL: Record<string, string> = {
  honors: 'Honors',
  ap: 'AP / Honors',
  non_academic: 'Non-Academic',
  repeated: 'Repeat',
  college_prep: 'College Prep',
  dual_enrollment: 'Dual Enrollment',
  other: 'Regular',
};

/** Returns the normalized letter prefix from a course ID (skips leading symbols). */
function getCourseIdPrefix(course?: TranscriptCourse | null): string {
  const crsId = course?.crs_id;
  if (!crsId) return '';
  const match = String(crsId).trim().match(/^[^A-Za-z]*([A-Za-z]+)/);
  return match ? match[1].toUpperCase() : '';
}

/** Normalize school names so "mayfair_high_school" matches "Mayfair High School". */
function normSchool(v: string | null | undefined): string {
  return (v ?? '').trim().toLowerCase().replace(/[_-]+/g, ' ').replace(/\s+/g, ' ');
}

/** School-aware priority merge: school-specific codes beat institution-wide ones. */
function effectiveCodesForSchool(codes: TranscriptCode[], schoolName: string): TranscriptCode[] {
  const school = normSchool(schoolName);
  const wide: Map<string, TranscriptCode> = new Map();
  const specific: Map<string, TranscriptCode> = new Map();
  for (const c of codes) {
    const key = `${c.code.toLowerCase()}|${c.position}`;
    const entrySchool = normSchool(c.school_name);
    if (!entrySchool) wide.set(key, c);
    // Match when either name contains the other (handles "Mayfair High School"
    // vs "mayfair_high_school" and minor naming differences).
    else if (school && (entrySchool === school || school.includes(entrySchool) || entrySchool.includes(school))) {
      specific.set(key, c);
    }
  }
  return [...new Map([...wide, ...specific]).values()];
}

function getCourseType(course?: TranscriptCourse | null, configuredCodes?: TranscriptCode[]): string {
  const crsId = String(course?.crs_id ?? '').trim().toLowerCase();
  const school = String(
    course?.transcript_type
      ?? course?.crs_hs
      ?? (course as { school?: string })?.school
      ?? (course as { school_name?: string })?.school_name
      ?? '',
  ).trim();

  // Check configured transcript codes first (highest priority)
  if (configuredCodes?.length && crsId) {
    const effective = effectiveCodesForSchool(configuredCodes, school);
    // Sort longest code first to avoid partial matches
    const sorted = [...effective].sort((a, b) => b.code.length - a.code.length);
    for (const entry of sorted) {
      const code = entry.code.toLowerCase();
      const isPrefix = entry.position === 'prefix' || entry.position === 'either';
      const isSuffix = entry.position === 'suffix' || entry.position === 'either';
      if (isPrefix && (crsId.startsWith(code + ' ') || crsId.startsWith(code))) {
        return MEANING_TYPE_LABEL[entry.meaning] ?? 'Regular';
      }
      if (isSuffix && (crsId.endsWith(' ' + code) || crsId.endsWith(code))) {
        return MEANING_TYPE_LABEL[entry.meaning] ?? 'Regular';
      }
    }
  }

  // Fall back to stored course_type from extraction
  if (course?.course_type) {
    return course.course_type === 'CSU/UC a-g Course' ? 'Regular' : course.course_type;
  }

  // Last resort: course ID letter prefix map
  const prefix = getCourseIdPrefix(course);
  if (!prefix) return '—';
  return COURSE_TYPE_MAP[prefix] ?? 'Regular';
}


function getLabScienceSubCategory(c: TranscriptCourse): 'D1' | 'D2' | null {
  const discipline = (c?.mapped_uc_course?.crs_discipline ?? '').toLowerCase();

  // crs_discipline is the most reliable signal.
  // Note: engineering and computer science are NOT D2 — backend counts them as
  // science-extra (they contribute to total D but not to D1 or D2 individually).
  if (discipline.includes('biology') || discipline.includes('life science') || discipline.includes('anatomy') || discipline.includes('physiology')) return 'D1';
  if (
    discipline === 'chemistry' ||
    discipline.startsWith('chemistry/') ||
    discipline === 'physics' ||
    discipline.startsWith('physics/') ||
    discipline === 'earth and space sciences' ||
    discipline === 'earth science' ||
    discipline === 'geology' ||
    discipline === 'astronomy'
  ) return 'D2';

  // Fall back to course title keyword matching
  const title = (c?.mapped_uc_course?.crs_description ?? c?.name ?? '').toLowerCase();

  // biochem / biophysics are physical sciences despite the "bio" prefix
  if (/biochem|biophys/.test(title)) return 'D2';

  // D1 — Life Sciences (environmental science is D1 per backend, not D2)
  if (/\bbiol|\banatomy|\bphysiol|\bmarine|\becolog|\bbotan|\bzoolog|\bgenetic|\bmicrobiol|life science|environmental science|\borganism|\bagri\w*sci|\bbiotech|\bneurosci|\bpatholog|\bimmunol|virolog|bacteriol/.test(title)) return 'D1';

  // D2 — Physical Sciences
  // Excluded: engineering, computer sci, pltw — backend classifies those as science-extra
  if (/\bchem|\bphysics|\bearth\b|\bgeolog|\bgeosci|\bastro|\bocean|\bmeteor|\belectric|\bthermo|\bnuclear|\bquantum/.test(title)) return 'D2';

  return null;
}

function getAgDisplayLetter(c?: TranscriptCourse | null): string {
  const raw = (c?.mapped_uc_course?.crs_ag_category_letter ?? '').toUpperCase().trim();
  if (raw === 'D') {
    const sub = getLabScienceSubCategory(c!);
    if (sub) return sub; // 'D1' or 'D2'
    return 'D';
  }
  if (raw === 'G') {
    const agDesc = (c?.mapped_uc_course?.crs_ag_category_description ?? '').toLowerCase();
    if (agDesc.includes('science')) return 'D';
  }
  return raw;
}


function getCourseCreditsDisplay(course?: TranscriptCourse | null) {
  return course?.crs_credit_completed ?? course?.credits_completed ?? '—';
}

function getCourseGradeLabel(course?: TranscriptCourse | null) {
  return course?.letter_grade ?? course?.grade ?? '—';
}

function getHsGrade(course?: TranscriptCourse | null) {
  // The detail endpoint puts the HS grade level in `grade_level`; `crs_grade` is
  // often null, so reading it alone left the HS Grade column blank.
  return course?.grade_level ?? course?.crs_grade ?? '—';
}

// ── Compact column-header filter (select or text search) ─────────────────────

function ColFilter({
  value,
  onChange,
  options,
  placeholder = 'All',
  isSearch = false,
}: {
  value: string;
  onChange: (v: string) => void;
  options?: string[];
  placeholder?: string;
  isSearch?: boolean;
}) {
  const cls = 'w-full rounded border border-input bg-white px-1.5 py-0.5 text-[11px] leading-tight focus:outline-none focus:ring-1 focus:ring-ring';
  if (isSearch) {
    return <input value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} className={cls} />;
  }
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={cls}>
      <option value="">{placeholder}</option>
      {options?.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

// ── Standardization course table ──────────────────────────────────────────────

type StdFilters = {
  search: string; onSearch: (v: string) => void;
  prefix: string; onPrefix: (v: string) => void;
  grade: string; onGrade: (v: string) => void;
  agLetter: string; onAgLetter: (v: string) => void;
  honors: string; onHonors: (v: string) => void;
  academicYear: string; onAcademicYear: (v: string) => void;
  discipline: string; onDiscipline: (v: string) => void;
  mappingStatus: string; onMappingStatus: (v: string) => void;
  hsGrade: string; onHsGrade: (v: string) => void;
  category: string; onCategory: (v: string) => void;
};

// Column provenance in the Standardization table: some values are read straight
// from the student's transcript; others are standardized/derived from the UC
// Doorways catalog. We keep the same column titles but tag + tint the headers so
// the two sources are unmistakable.
const TX_HEAD = 'bg-blue-50/70 text-blue-700';
const UC_HEAD = 'bg-violet-50/70 text-violet-700';
function TxTag() {
  return (
    <span
      title="From the actual transcript"
      className="ml-1 rounded bg-blue-100 px-1 py-0.5 align-middle text-[8.5px] font-bold uppercase tracking-wide text-blue-700"
    >
      T
    </span>
  );
}
function UcTag() {
  return (
    <span
      title="Derived from the UC Doorways catalog"
      className="ml-1 rounded bg-violet-100 px-1 py-0.5 align-middle text-[8.5px] font-bold uppercase tracking-wide text-violet-700"
    >
      UC
    </span>
  );
}

function StandardizationCourseTable({
  courses,
  filters,
  allAcademicYears,
  allDisciplines,
  allMappingStatuses,
  configuredCodes,
}: {
  courses?: TranscriptRecord['courses'];
  filters: StdFilters;
  allAcademicYears: string[];
  allDisciplines: string[];
  allMappingStatuses: string[];
  configuredCodes: TranscriptCode[];
}) {
  const rows = courses || [];
  const f = filters;
  const [sc, setSc] = useState<{ k: string; d: 1 | -1 } | null>(null);
  const ts = (k: string) => setSc((p) => (p && p.k === k ? { k, d: p.d === 1 ? -1 : 1 } : { k, d: 1 }));
  const acc: Record<string, (c: any) => any> = {
    courseId: (c) => c?.crs_id || '', prefix: (c) => getCourseIdPrefix(c), course: (c) => c?.name || '',
    grade: (c) => getCourseGradeLabel(c), credits: (c) => getCourseCreditsDisplay(c), hsGrade: (c) => getHsGrade(c),
    type: (c) => getCourseType(c, configuredCodes), ag: (c) => getAgDisplayLetter(c),
    agDesc: (c) => c?.mapped_uc_course?.crs_ag_category_description ?? '', discipline: (c) => c?.mapped_uc_course?.crs_discipline ?? '',
    mapped: (c) => c?.mapped_uc_course?.crs_transcript_abbrevs ?? c?.name ?? '', honors: (c) => c?.mapped_uc_course?.crs_honors ?? '',
    mappedHs: (c) => c?.mapped_uc_course?.crs_hs ?? '', environment: (c) => c?.mapped_uc_course?.crs_environment ?? '',
    localCodes: (c) => c?.mapped_uc_course?.crs_local_codes ?? '', ucYear: (c) => c?.mapped_uc_course?.crs_academic_year ?? '',
    mappingStatus: (c) => c?.mapping_status ?? '',
  };
  const sorted = sc && acc[sc.k]
    ? [...rows].sort((a, b) => {
        const av = acc[sc.k](a) ?? '', bv = acc[sc.k](b) ?? '';
        const cmp = typeof av === 'number' && typeof bv === 'number' ? av - bv : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
        return sc.d === 1 ? cmp : -cmp;
      })
    : rows;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-blue-200" />
          <b className="text-blue-700">Transcript</b>
          <span className="text-muted-foreground">— read from the student’s transcript</span>
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-2.5 rounded-sm bg-violet-200" />
          <b className="text-violet-700">UC Doorways</b>
          <span className="text-muted-foreground">— standardized from the UC Doorways catalog</span>
        </span>
      </div>
      <div className="max-h-[52vh] overflow-x-auto overflow-y-auto rounded-md border">
        <table className="w-max min-w-full text-xs">
        <thead className="sticky top-0 z-10 bg-white text-left text-muted-foreground">
          <tr className="border-b">
            <th className="whitespace-nowrap px-2 py-1.5">#</th>
            <th onClick={() => ts('courseId')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${TX_HEAD}`}>Course ID<TxTag /></th>
            <th onClick={() => ts('prefix')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${TX_HEAD}`}>Prefix<TxTag /></th>
            <th onClick={() => ts('course')} className={`cursor-pointer min-w-[220px] px-2 py-1.5 ${TX_HEAD}`}>Course<TxTag /></th>
            <th onClick={() => ts('grade')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${TX_HEAD}`}>Grade<TxTag /></th>
            <th onClick={() => ts('credits')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${TX_HEAD}`}>Credits<TxTag /></th>
            <th onClick={() => ts('hsGrade')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${TX_HEAD}`}>HS Grade<TxTag /></th>
            <th onClick={() => ts('type')} className={`cursor-pointer min-w-[160px] px-2 py-1.5 ${UC_HEAD}`}>Type<UcTag /></th>
            <th onClick={() => ts('ag')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${UC_HEAD}`}>A-G<UcTag /></th>
            <th onClick={() => ts('agDesc')} className={`cursor-pointer min-w-[180px] px-2 py-1.5 ${UC_HEAD}`}>AG Description<UcTag /></th>
            <th onClick={() => ts('discipline')} className={`cursor-pointer min-w-[160px] px-2 py-1.5 ${UC_HEAD}`}>Discipline<UcTag /></th>
            <th onClick={() => ts('mapped')} className={`cursor-pointer min-w-[220px] px-2 py-1.5 ${UC_HEAD}`}>Mapped Course<UcTag /></th>
            <th onClick={() => ts('honors')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${UC_HEAD}`}>Honors<UcTag /></th>
            <th onClick={() => ts('mappedHs')} className={`cursor-pointer min-w-[160px] px-2 py-1.5 ${UC_HEAD}`}>Mapped HS<UcTag /></th>
            <th onClick={() => ts('environment')} className={`cursor-pointer min-w-[140px] px-2 py-1.5 ${UC_HEAD}`}>Environment<UcTag /></th>
            <th onClick={() => ts('localCodes')} className={`cursor-pointer min-w-[160px] px-2 py-1.5 ${UC_HEAD}`}>Local Codes<UcTag /></th>
            <th onClick={() => ts('ucYear')} className={`cursor-pointer whitespace-nowrap px-2 py-1.5 ${UC_HEAD}`}>UC Year<UcTag /></th>
            <th onClick={() => ts('mappingStatus')} className={`cursor-pointer min-w-[140px] px-2 py-1.5 ${UC_HEAD}`}>Mapping Status<UcTag /></th>
          </tr>
          <tr className="border-b bg-slate-50">
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.search} onChange={f.onSearch} isSearch placeholder="Search…" /></th>
            <th className="px-1 py-1"><ColFilter value={f.prefix} onChange={f.onPrefix} options={UNIVERSAL_ID_PREFIXES} /></th>
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.grade} onChange={f.onGrade} options={UNIVERSAL_LETTER_GRADES} /></th>
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.hsGrade} onChange={f.onHsGrade} options={UNIVERSAL_HS_GRADES} /></th>
            <th className="px-1 py-1"><ColFilter value={f.category} onChange={f.onCategory} options={UNIVERSAL_COURSE_TYPES} /></th>
            <th className="px-1 py-1"><ColFilter value={f.agLetter} onChange={f.onAgLetter} options={AG_LETTERS} /></th>
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.discipline} onChange={f.onDiscipline} options={allDisciplines} /></th>
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.honors} onChange={f.onHonors} options={['Yes', 'No']} /></th>
            <th className="px-1 py-1" />
            <th className="px-1 py-1" />
            <th className="px-1 py-1" />
            <th className="px-1 py-1"><ColFilter value={f.academicYear} onChange={f.onAcademicYear} options={allAcademicYears} /></th>
            <th className="px-1 py-1"><ColFilter value={f.mappingStatus} onChange={f.onMappingStatus} options={allMappingStatuses} /></th>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 ? (
            <tr>
              <td colSpan={18} className="px-3 py-8 text-center text-muted-foreground">
                No courses match the current filters.
              </td>
            </tr>
          ) : (
            sorted.map((c, i) => {
              const mapped = c?.mapped_uc_course;
              const prefix = getCourseIdPrefix(c);
              return (
                <tr key={i} className="align-top border-t bg-white hover:bg-slate-50">
                  <td className="whitespace-nowrap px-2 py-1.5">{i + 1}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{c?.crs_id || '—'}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{prefix || '—'}</td>
                  <td className="px-2 py-1.5">{c?.name || '—'}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{getCourseGradeLabel(c)}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{getCourseCreditsDisplay(c)}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{getHsGrade(c)}</td>
                  <td className="px-2 py-1.5">{getCourseType(c, configuredCodes)}</td>
                  <td className="whitespace-nowrap px-2 py-1.5">{getAgDisplayLetter(c) || '—'}</td>
                  <td className="px-2 py-1.5">{mapped?.crs_ag_category_description ?? '—'}</td>
                  <td className="px-2 py-1.5">{mapped?.crs_discipline ?? '—'}</td>
                  <td className="px-2 py-1.5">
                    {mapped
                      ? mapped.crs_transcript_abbrevs
                        ? mapped.crs_transcript_abbrevs.split('|').join(', ')
                        : c?.name ?? '—'
                      : '—'}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">{mapped?.crs_honors ?? '—'}</td>
                  <td className="px-2 py-1.5">{mapped?.crs_hs ?? '—'}</td>
                  <td className="px-2 py-1.5">{mapped?.crs_environment ?? '—'}</td>
                  <td className="px-2 py-1.5">
                    {mapped?.crs_local_codes ? mapped.crs_local_codes.split('|').join(', ') : '—'}
                  </td>
                  <td className="whitespace-nowrap px-2 py-1.5">{mapped?.crs_academic_year ?? '—'}</td>
                  <td className="px-2 py-1.5 text-muted-foreground">{c?.mapping_status ?? '—'}</td>
                </tr>
              );
            })
          )}
        </tbody>
      </table>
      </div>
    </div>
  );
}

// ── Main body ─────────────────────────────────────────────────────────────────

export function TranscriptDetailBody({
  transcript: transcriptProp,
  initialTab = 'personal',
  onDecisionSaved,
}: {
  transcript?: TranscriptRecord | null;
  initialTab?: TranscriptTab;
  onDecisionSaved?: (decision: string) => void;
}) {
  // The list endpoints are slim (no courses) for fast loads. If a record arrives
  // without courses, fetch the full student on demand and merge them in. Records
  // that already carry courses (e.g. the Completed page rebuilds them) skip this.
  const dbId = (transcriptProp as { db_id?: number | string } | null | undefined)?.db_id;
  const hasCourses = !!(transcriptProp?.courses && transcriptProp.courses.length);
  const [fetchedCourses, setFetchedCourses] = useState<TranscriptRecord['courses'] | null>(null);
  const [sortCol, setSortCol] = useState<{ key: string; dir: 1 | -1 } | null>(null);
  const toggleSort = (key: string) =>
    setSortCol((p) => (p && p.key === key ? { key, dir: p.dir === 1 ? -1 : 1 } : { key, dir: 1 }));
  const sortRows = <T,>(rows: T[], accessors: Record<string, (r: T) => any>): T[] => {
    if (!sortCol) return rows;
    const g = accessors[sortCol.key];
    if (!g) return rows;
    return [...rows].sort((a, b) => {
      const av = g(a) ?? '';
      const bv = g(b) ?? '';
      const cmp = typeof av === 'number' && typeof bv === 'number'
        ? av - bv
        : String(av).localeCompare(String(bv), undefined, { numeric: true, sensitivity: 'base' });
      return sortCol.dir === 1 ? cmp : -cmp;
    });
  };

  useEffect(() => {
    setFetchedCourses(null);
    if (hasCourses || dbId == null) return;
    let cancelled = false;
    fetchStudentDetail(dbId)
      .then((full) => {
        if (!cancelled) {
          const courses = (full as { courses?: TranscriptRecord['courses'] })?.courses;
          setFetchedCourses(Array.isArray(courses) ? courses : []);
        }
      })
      .catch(() => {
        if (!cancelled) setFetchedCourses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [dbId, hasCourses]);

  const transcript = useMemo<TranscriptRecord | null | undefined>(() => {
    if (hasCourses || !fetchedCourses) return transcriptProp;
    return { ...(transcriptProp as TranscriptRecord), courses: fetchedCourses };
  }, [transcriptProp, fetchedCourses, hasCourses]);

  // Courses are "settled" once either the record already carried them or the
  // on-demand fetch has returned. The A-G / GPA tabs must wait for this so they
  // don't compute on an empty course set (showing 0 units / empty GPA).
  const coursesSettled = hasCourses || fetchedCourses !== null || dbId == null;

  const [activeTab, setActiveTab] = useState<TranscriptTab>(initialTab);
  useEffect(() => setActiveTab(initialTab), [initialTab, transcript?.id]);

  const [configuredCodes, setConfiguredCodes] = useState<TranscriptCode[]>([]);
  useEffect(() => { listTranscriptCodes().then(setConfiguredCodes); }, []);

  // ── Shared filter state (visible in both Courses and Standardization tabs) ──
  const [courseSearch, setCourseSearch]   = useState('');
  const [filterPrefix, setFilterPrefix]   = useState('');
  const [filterType, setFilterType]       = useState('');
  const [filterGrade, setFilterGrade]     = useState('');
  const [filterYear, setFilterYear]       = useState('');
  const [filterMonth, setFilterMonth]     = useState('');

  const [filterAgLetter, setFilterAgLetter]         = useState('');

  // ── Standardization-only filter state ────────────────────────────────────
  const [filterMappingStatus, setFilterMappingStatus] = useState('');
  const [filterHonors, setFilterHonors]             = useState('');
  const [filterAcademicYear, setFilterAcademicYear] = useState('');
  const [filterDiscipline, setFilterDiscipline]     = useState('');
  const [filterStdHsGrade, setFilterStdHsGrade]     = useState('');
  const [filterStdCategory, setFilterStdCategory]   = useState('');

  useEffect(() => {
    setCourseSearch('');
    setFilterPrefix('');
    setFilterType('');
    setFilterGrade('');
    setFilterYear('');
    setFilterMonth('');
    setFilterAgLetter('');
    setFilterMappingStatus('');
    setFilterHonors('');
    setFilterAcademicYear('');
    setFilterDiscipline('');
    setFilterStdHsGrade('');
    setFilterStdCategory('');
  }, [transcript?.id]);

  // ── Dynamic options (per-file, for fields with no universal list) ─────────
  const allYears = useMemo(() => {
    const s = new Set((transcript?.courses ?? []).map((c) => c?.year).filter((v) => v != null));
    return Array.from(s as Set<number>).sort((a, b) => a - b).map(String);
  }, [transcript?.courses]);

  const allMonths = useMemo(() => {
    const s = new Set((transcript?.courses ?? []).map((c) => c?.month).filter((v) => v != null));
    return Array.from(s as Set<number>).sort((a, b) => a - b).map(String);
  }, [transcript?.courses]);

  const allMappingStatuses = useMemo(() => {
    const s = new Set((transcript?.courses ?? []).map((c) => c?.mapping_status).filter(Boolean));
    return Array.from(s as Set<string>).sort();
  }, [transcript?.courses]);

  const allAcademicYears = useMemo(() => {
    const s = new Set(
      (transcript?.courses ?? []).map((c) => c?.mapped_uc_course?.crs_academic_year).filter(Boolean),
    );
    return Array.from(s as Set<string>).sort();
  }, [transcript?.courses]);

  const allDisciplines = useMemo(() => {
    const s = new Set(
      (transcript?.courses ?? []).map((c) => c?.mapped_uc_course?.crs_discipline).filter(Boolean),
    );
    return Array.from(s as Set<string>).sort();
  }, [transcript?.courses]);

  // ── Filtered rows ─────────────────────────────────────────────────────────

  const filteredCourses = useMemo(() => {
    return (transcript?.courses ?? []).filter((c) => {
      const q = courseSearch.trim().toLowerCase();
      if (q && !String(c?.crs_id ?? '').toLowerCase().includes(q) && !String(c?.name ?? '').toLowerCase().includes(q)) return false;
      if (filterPrefix && getCourseIdPrefix(c) !== filterPrefix) return false;
      if (filterType && getCourseType(c, configuredCodes) !== filterType) return false;
      if (filterGrade && (c?.letter_grade ?? c?.grade) !== filterGrade) return false;
      if (filterYear && String(c?.year ?? '') !== filterYear) return false;
      if (filterMonth && String(c?.month ?? '') !== filterMonth) return false;
      if (filterAgLetter && getAgDisplayLetter(c) !== filterAgLetter) return false;
      return true;
    });
  }, [transcript?.courses, courseSearch, filterPrefix, filterType, filterGrade, filterYear, filterMonth, filterAgLetter]);

  const filteredStdCourses = useMemo(() => {
    return filteredCourses.filter((c) => {
      if (filterMappingStatus && c?.mapping_status !== filterMappingStatus) return false;
      if (filterHonors && (c?.mapped_uc_course?.crs_honors ?? '') !== filterHonors) return false;
      if (filterAcademicYear && (c?.mapped_uc_course?.crs_academic_year ?? '') !== filterAcademicYear) return false;
      if (filterDiscipline && (c?.mapped_uc_course?.crs_discipline ?? '') !== filterDiscipline) return false;
      if (filterStdHsGrade && String(c?.grade_level ?? c?.crs_grade ?? '') !== filterStdHsGrade) return false;
      if (filterStdCategory && getCourseType(c, configuredCodes) !== filterStdCategory) return false;
      return true;
    });
  }, [filteredCourses, filterMappingStatus, filterHonors, filterAcademicYear, filterDiscipline, filterStdHsGrade, filterStdCategory]);

  const hasSharedFilters = !!(courseSearch || filterPrefix || filterType || filterGrade || filterYear || filterMonth || filterAgLetter);
  const hasStdFilters    = !!(hasSharedFilters || filterMappingStatus || filterHonors || filterAcademicYear || filterDiscipline || filterStdHsGrade || filterStdCategory);

  const clearSharedFilters = () => {
    setCourseSearch(''); setFilterPrefix(''); setFilterType('');
    setFilterGrade(''); setFilterYear(''); setFilterMonth('');
    setFilterAgLetter('');
  };
  const clearAllFilters = () => {
    clearSharedFilters();
    setFilterMappingStatus(''); setFilterHonors('');
    setFilterAcademicYear(''); setFilterDiscipline('');
    setFilterStdHsGrade(''); setFilterStdCategory('');
  };

  const displayStudentId = transcript?.studentId ?? transcript?.id ?? '—';


  return (
    <div className="thd-revamp flex min-h-0 flex-1 flex-col">
      <div className="mt-3 shrink-0">
        <div className="thd-tabs">
          {(['personal', 'courses', 'standardization', 'agRequirement', 'gpaCalculation', 'transcript', 'notes'] as TranscriptTab[]).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              data-active={activeTab === tab}
              className="thd-tab"
            >
              {tab === 'personal' ? 'Personal Data'
                : tab === 'courses' ? 'Courses'
                : tab === 'standardization' ? 'Standardization'
                : tab === 'agRequirement' ? 'A/G Requirement'
                : tab === 'gpaCalculation' ? 'GPA Calculation'
                : tab === 'transcript' ? 'Transcript'
                : 'Staff Notes'}
            </button>
          ))}
        </div>
      </div>

      <div key={activeTab} className="thd-tabpane mt-4 flex min-h-0 flex-1 flex-col">

        {/* ── Personal ── */}
        {activeTab === 'personal' && (
          <div className="flex-1 min-h-0 overflow-y-auto rounded-md border bg-white pr-1 shadow-sm">
            <div className="p-4">
              <h4 className="text-lg font-medium">Personal Information</h4>
            </div>
            <div className="divide-y border-t">
              <div className="grid grid-cols-1 gap-3 px-4 py-4 text-sm md:grid-cols-4 md:items-center">
                <div className="text-muted-foreground">Name</div>
                <div className="font-medium text-foreground">{transcript?.studentName || '—'}</div>
                <div className="text-muted-foreground">Dob</div>
                <div className="font-medium text-foreground">{transcript?.birthDate || '—'}</div>
              </div>
              <div className="grid grid-cols-1 gap-3 px-4 py-4 text-sm md:grid-cols-4 md:items-center">
                <div className="text-muted-foreground">Student Id</div>
                <div className="font-medium text-foreground">{displayStudentId}</div>
                <div className="text-muted-foreground">School</div>
                <div className="font-medium text-foreground">{transcript?.format || '—'}</div>
              </div>
              <div className="grid grid-cols-1 gap-3 px-4 py-4 text-sm md:grid-cols-4 md:items-center">
                <div className="text-muted-foreground">Graduation Date</div>
                <div className="font-medium text-foreground">{transcript?.graduationDate || '—'}</div>
                <div className="text-muted-foreground">Address</div>
                <div className="font-medium text-foreground">{transcript?.address || '—'}</div>
              </div>
            </div>
          </div>
        )}

        {/* ── Courses ── */}
        {activeTab === 'courses' && (
          <div className="flex flex-1 min-h-0 flex-col rounded-md border bg-white p-4">
            <div className="mb-2 flex shrink-0 items-center justify-between">
              <h4 className="text-md font-medium">Courses</h4>
              {hasSharedFilters && (
                <Button variant="ghost" size="sm" className="text-xs text-muted-foreground" onClick={clearSharedFilters}>
                  Clear filters
                </Button>
              )}
            </div>
            <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px]">
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-blue-200" />
                <b className="text-blue-700">Transcript</b>
                <span className="text-muted-foreground">— read from the student’s transcript</span>
              </span>
              <span className="inline-flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-sm bg-violet-200" />
                <b className="text-violet-700">UC Doorways</b>
                <span className="text-muted-foreground">— derived from the UC Doorways catalog</span>
              </span>
            </div>
            <div className="flex-1 min-h-0 overflow-auto rounded-md border">
              <table className="w-full table-fixed text-xs">
                <colgroup>
                  <col style={{ width: '5%' }} />
                  <col style={{ width: '13%' }} />
                  <col style={{ width: '11%' }} />
                  <col style={{ width: '24%' }} />
                  <col style={{ width: '10%' }} />
                  <col style={{ width: '10%' }} />
                  <col style={{ width: '9%' }} />
                  <col style={{ width: '9%' }} />
                  <col style={{ width: '9%' }} />
                </colgroup>
                <thead className="sticky top-0 z-10 bg-white text-left text-muted-foreground">
                  <tr className="border-b">
                    <th className="px-2 py-1.5">#</th>
                    <th onClick={() => toggleSort('courseId')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Course ID<TxTag /></th>
                    <th onClick={() => toggleSort('prefix')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Prefix<TxTag /></th>
                    <th onClick={() => toggleSort('course')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Course<TxTag /></th>
                    <th onClick={() => toggleSort('grade')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Grade<TxTag /></th>
                    <th onClick={() => toggleSort('credits')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Credits<TxTag /></th>
                    <th onClick={() => toggleSort('year')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Year<TxTag /></th>
                    <th onClick={() => toggleSort('month')} className={`cursor-pointer px-2 py-1.5 ${TX_HEAD}`}>Month<TxTag /></th>
                    <th onClick={() => toggleSort('type')} className={`cursor-pointer px-2 py-1.5 ${UC_HEAD}`}>Type<UcTag /></th>
                  </tr>
                  <tr className="border-b bg-slate-50">
                    <th className="px-1 py-1" />
                    <th className="px-1 py-1"><ColFilter value={courseSearch} onChange={setCourseSearch} isSearch placeholder="Search…" /></th>
                    <th className="px-1 py-1"><ColFilter value={filterPrefix} onChange={setFilterPrefix} options={UNIVERSAL_ID_PREFIXES} /></th>
                    <th className="px-1 py-1" />
                    <th className="px-1 py-1"><ColFilter value={filterGrade} onChange={setFilterGrade} options={UNIVERSAL_LETTER_GRADES} /></th>
                    <th className="px-1 py-1" />
                    <th className="px-1 py-1"><ColFilter value={filterYear} onChange={setFilterYear} options={allYears} /></th>
                    <th className="px-1 py-1"><ColFilter value={filterMonth} onChange={setFilterMonth} options={allMonths} /></th>
                    <th className="px-1 py-1"><ColFilter value={filterType} onChange={setFilterType} options={UNIVERSAL_COURSE_TYPES} /></th>
                  </tr>
                </thead>
                <tbody>
                  {filteredCourses.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="px-3 py-4 text-center text-muted-foreground">
                        No courses match the current filters.
                      </td>
                    </tr>
                  ) : (
                    sortRows(filteredCourses ?? [], {
                      courseId: (c: any) => c?.crs_id || '',
                      prefix: (c: any) => getCourseIdPrefix(c),
                      course: (c: any) => c?.name || '',
                      grade: (c: any) => getCourseGradeLabel(c),
                      credits: (c: any) => getCourseCreditsDisplay(c),
                      year: (c: any) => c?.year ?? '',
                      month: (c: any) => c?.month ?? '',
                      type: (c: any) => getCourseType(c, configuredCodes),
                    }).map((c, i) => {
                      const prefix = getCourseIdPrefix(c);
                      return (
                        <tr key={i} className="border-t bg-white hover:bg-slate-50">
                          <td className="px-2 py-1.5">{i + 1}</td>
                          <td className="truncate px-2 py-1.5">{c?.crs_id || '—'}</td>
                          <td className="px-2 py-1.5">{prefix || '—'}</td>
                          <td className="truncate px-2 py-1.5">{c.name || '—'}</td>
                          <td className="px-2 py-1.5">{getCourseGradeLabel(c)}</td>
                          <td className="px-2 py-1.5">{getCourseCreditsDisplay(c)}</td>
                          <td className="px-2 py-1.5">{c?.year ?? '—'}</td>
                          <td className="px-2 py-1.5">{c?.month ?? '—'}</td>
                          <td className="truncate px-2 py-1.5">{getCourseType(c, configuredCodes)}</td>
                        </tr>
                      );
                    })
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {/* ── Standardization ── */}
        {activeTab === 'standardization' && (
          <div className="flex flex-1 min-h-0 flex-col">
            <div className="flex min-h-0 flex-1 flex-col rounded-md border bg-white p-4">
              <div className="mb-2 flex shrink-0 items-center justify-between">
                <h5 className="text-sm text-muted-foreground">Courses with Mapping Details</h5>
                {hasStdFilters && (
                  <Button variant="ghost" size="sm" className="text-xs text-muted-foreground" onClick={clearAllFilters}>
                    Clear filters
                  </Button>
                )}
              </div>
              <StandardizationCourseTable
                courses={filteredStdCourses}
                filters={{
                  search: courseSearch, onSearch: setCourseSearch,
                  prefix: filterPrefix, onPrefix: setFilterPrefix,
                  grade: filterGrade, onGrade: setFilterGrade,
                  agLetter: filterAgLetter, onAgLetter: setFilterAgLetter,
                  honors: filterHonors, onHonors: setFilterHonors,
                  academicYear: filterAcademicYear, onAcademicYear: setFilterAcademicYear,
                  discipline: filterDiscipline, onDiscipline: setFilterDiscipline,
                  mappingStatus: filterMappingStatus, onMappingStatus: setFilterMappingStatus,
                  hsGrade: filterStdHsGrade, onHsGrade: setFilterStdHsGrade,
                  category: filterStdCategory, onCategory: setFilterStdCategory,
                }}
                allAcademicYears={allAcademicYears}
                allDisciplines={allDisciplines}
                allMappingStatuses={allMappingStatuses}
                configuredCodes={configuredCodes}
              />
            </div>
          </div>
        )}

        {(activeTab === 'agRequirement' || activeTab === 'gpaCalculation') && (
          // The A-G / GPA review is computed once when AdmissionReviewTabs mounts,
          // keyed on the student id. Because the list pages are slim (courses fetched
          // asynchronously after open), mounting before the fetch settles would
          // compute on an empty course set — showing 0 units / empty GPA forever.
          // Wait until courses are loaded so it computes on the real data.
          coursesSettled ? (
            <AdmissionReviewTabs transcript={transcript} mode={activeTab} onDecisionSaved={onDecisionSaved} />
          ) : (
            <div className="flex flex-1 items-center justify-center p-8 text-sm text-muted-foreground">
              Loading courses…
            </div>
          )
        )}

        {activeTab === 'transcript' && (
          <div className="flex flex-1 min-h-0 flex-col rounded-md border bg-white">
            <div className="shrink-0 p-4">
              <h4 className="text-lg font-medium">Transcript PDF</h4>
              <p className="mt-1 text-sm text-muted-foreground">Original upload from storage.</p>
            </div>
            {transcript?.sourceFile ? (
              <div className="flex-1 min-h-0 border-t">
                <iframe
                  title="Transcript PDF"
                  src={`/api/extractor/files/${transcript.sourceFile}/pdf#zoom=page-width`}
                  className="h-full w-full border-0"
                />
              </div>
            ) : (
              <div className="border-t p-4 text-sm text-muted-foreground">
                No source file available for this record.
              </div>
            )}
          </div>
        )}

        {activeTab === 'notes' && (
          <NotesPanel
            noteKey={`student:${transcript?.studentId ?? transcript?.id ?? transcript?.sourceFile ?? 'x'}`}
          />
        )}
      </div>
    </div>
  );
}

export default function TranscriptDetailDialog({
  open,
  onOpenChange,
  transcript,
  initialTab = 'personal',
  onDecisionSaved,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript?: TranscriptRecord | null;
  initialTab?: TranscriptTab;
  onDecisionSaved?: (decision: string) => void;
}) {
  const displayStudentId = transcript?.studentId ?? transcript?.id ?? '—';
  const [tab, setTab] = useState<TranscriptTab>(initialTab);

  useEffect(() => {
    setTab(initialTab);
  }, [initialTab, transcript?.id]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex h-[97vh] max-h-[97vh] !w-[95vw] !max-w-[1500px] flex-col p-0 sm:rounded-lg">
        <DialogHeader className="shrink-0 border-b px-6 py-4 pr-14">
          <DialogTitle>
            Transcript: {transcript?.studentName || displayStudentId || 'Unknown'}
          </DialogTitle>
          <div className="mt-2">
            <p className="text-sm text-muted-foreground">Student ID: {displayStudentId}</p>
          </div>
        </DialogHeader>

        <div className="flex min-h-0 flex-1 flex-col px-6 py-4">
          <TranscriptDetailBody transcript={transcript} initialTab={tab} onDecisionSaved={onDecisionSaved} />
        </div>

        <DialogFooter className="shrink-0 border-t px-6 py-4">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
