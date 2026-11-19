import { useCallback, useMemo, useRef, useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Avatar } from '@/components/shared/Avatar';
import { StandardTable, StdColumn } from '@/components/shared/StandardTable';
import { resolveFormat } from '@/lib/extractorFormat';
import { emitNotification } from '@/lib/notify';
import { Button } from '@/components/ui/button';
import {
  fetchNeedsReviewStudents,
  fetchStudentDetail,
  StudentWithCourses,
  updateStudentAndCourses,
  createStudentForFile,
  reviewFinalCourse,
  resolveCourseExtractionMatch,
} from '@/lib/api/extractor';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Label } from '@/components/ui/label';
import { Input } from '@/components/ui/input';
import { toast } from 'sonner';
import { useTerm } from '@/contexts/TermContext';
import {
  Plus,
  Trash2,
  AlertTriangle,
  AlertCircle,
  CheckCircle2,
  Sparkles,
  ShieldCheck,
  Wand2,
  ArrowRightCircle,
  Filter,
  ChevronDown,
  UserRound,
  ListChecks,
} from 'lucide-react';
import { useStaleData } from '@/lib/useStaleData';

// Run async tasks with bounded concurrency. Saving a reviewed file used to fire
// ~2 sequential API calls per course (10-30s for big transcripts); running them
// in parallel batches makes "Move to Completed" near-instant.
async function runWithConcurrency<T>(
  items: T[],
  limit: number,
  worker: (item: T) => Promise<void>,
): Promise<void> {
  let index = 0;
  const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (index < items.length) {
      const current = index++;
      await worker(items[current]);
    }
  });
  await Promise.all(runners);
}

type CourseSource =
  | 'Document AI'
  | 'Gemini'
  | 'Document AI + Gemini'
  | 'Manual'
  | 'Reconciled'
  | string;

type DbFinalSource = 'merged' | 'document_ai' | 'gemini' | 'manual';

type ReconciliationSummary = {
  status?: string | null;
  validation_type?: string | null;

  document_ai_course_count?: number | null;
  document_ai_raw_course_count?: number | null;
  raw_document_ai_course_count?: number | null;

  gemini_course_count?: number | null;
  gemini_raw_course_count?: number | null;
  raw_gemini_course_count?: number | null;

  final_course_count?: number | null;
  final_course_details_count?: number | null;

  matched_course_count?: number | null;
  matched_count?: number | null;

  document_ai_only_count?: number | null;
  gemini_only_count?: number | null;

  suppressed_document_ai_duplicate_count?: number | null;
  suppressed_gemini_duplicate_count?: number | null;

  auto_fixed_count?: number | null;
  auto_applied_count?: number | null;

  needs_review_count?: number | null;
  unresolved_count?: number | null;
  unresolved_review_count?: number | null;

  removed_course_count?: number | null;

  review_reasons?: string[];
  warnings?: string[];

  model?: string | null;
};

type FieldDifference = {
  document_ai?: unknown;
  gemini?: unknown;
  final?: unknown;
  selected?: unknown;
  [key: string]: unknown;
};

type CourseFormRow = {
  id: number;
  finalCourseId?: number | null;
  matchId?: number | null;

  name: string;
  grade: string;
  credits: string;

  courseId: string;
  creditsAttempted: string;
  creditsCompleted: string;

  gradeLevel: string;
  month: string;
  year: string;
  school: string;

  sectionName?: string | null;
  termName?: string | null;
  academicYear?: string | null;

  source?: CourseSource | null;
  extractionSource?: CourseSource | null;
  fieldSource?: unknown;

  needsReview: boolean;
  reviewed: boolean;
  reviewReason?: string | null;

  matchStatus?: string | null;
  matchDecision?: string | null;
  matchConfidence?: string | null;

  courseIdMatch?: boolean | null;
  courseIdSource?: string | null;
  courseIdDifference?: FieldDifference | null;

  isAutoFixed: boolean;
  isManual: boolean;
  isRemoved: boolean;
  extraResolution: 'keep' | 'remove' | null;
};

type CourseReviewFilter = 'all' | 'needs_review' | 'done';

function isCourseOpenForReview(course: CourseFormRow): boolean {
  return (
    !course.isRemoved &&
    course.needsReview &&
    !course.reviewed &&
    course.extraResolution !== 'keep'
  );
}

type Row = {
  id: string;
  studentId: string;
  serial: number;
  studentName: string | null | undefined;
  fileName: string | null | undefined;
  school: string | null;
  format: string | null;
  status: string | null;
  isFileOnly?: boolean;
  sourceFileId?: number;

  reconciliation?: ReconciliationSummary | null;

  documentAiCount?: number | null;
  geminiCount?: number | null;
  finalCount?: number | null;
  autoFixedCount?: number | null;
  needsReviewCount: number;
};

// The actual high school — distinct from `format` (which extractor was used).
function schoolFromFileName(fileName?: string | null): string {
  const base = String(fileName ?? '').replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  const raw = idx > 0 && idx < base.length - 1 ? base.slice(idx + 1).trim() : '';
  if (!raw) return '';
  const up = raw.toUpperCase();
  if (up === 'LBUSD' || up === 'CAMS') return up;
  return raw.replace(/\b\w/g, (c) => c.toUpperCase());
}

function firstNonEmpty<T>(...values: T[]): T | undefined {
  return values.find((value) => {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value) && value.length === 0) return false;
    if (typeof value === 'string' && value.trim() === '') return false;
    return true;
  });
}

function toNumberOrNull(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function normalizeStatus(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

function normalizeString(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function toInputDate(value: unknown): string {
  if (!value) return '';

  const text = String(value);

  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    return text.slice(0, 10);
  }

  return '';
}

function objectFromUnknown(value: unknown): Record<string, any> | null {
  if (!value) return null;

  if (typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, any>;
  }

  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        return parsed as Record<string, any>;
      }
    } catch {
      return null;
    }
  }

  return null;
}

function normalizeFinalSourceForApi(source?: CourseSource | null): DbFinalSource {
  const text = String(source ?? '')
    .trim()
    .toLowerCase()
    .replace(/[-\s]+/g, '_');

  if (!text) return 'merged';

  if (
    (text.includes('document') && text.includes('gemini')) ||
    (text.includes('doc_ai') && text.includes('gemini')) ||
    text.includes('both') ||
    text.includes('merged') ||
    text.includes('reconciled')
  ) {
    return 'merged';
  }

  if (text.includes('manual') || text.includes('user')) return 'manual';
  if (text.includes('gemini')) return 'gemini';

  if (
    text.includes('document') ||
    text.includes('doc_ai') ||
    text.includes('docai')
  ) {
    return 'document_ai';
  }

  return 'merged';
}

function getDisplaySource(course: any): CourseSource {
  const raw = firstNonEmpty(
    course?.source,
    course?.source_label,
    course?.final_source,
    course?.extraction_source,
    course?.extractionSource,
    course?.selected_source,
    course?.trusted_source,
    course?.suggested_by,
  );

  if (!raw) {
    if (course?.added_by_gemini || course?.is_gemini_added) return 'Gemini';
    if (course?.is_manual || course?.manual_entry) return 'Manual';
    return 'Document AI';
  }

  const text = String(raw).trim();

  if (/document.*gemini|gemini.*document|both|matched|reconciled|merged/i.test(text)) {
    return 'Document AI + Gemini';
  }

  if (/gemini/i.test(text)) return 'Gemini';
  if (/manual/i.test(text)) return 'Manual';
  if (/document/i.test(text) || /doc ai/i.test(text) || /docai/i.test(text)) {
    return 'Document AI';
  }

  return text;
}

function getSourceBadgeClass(source?: string | null): string {
  if (source === 'Gemini') {
    return 'bg-purple-100 text-purple-700';
  }

  if (source === 'Manual') {
    return 'bg-blue-100 text-blue-700';
  }

  if (source === 'Document AI + Gemini' || source === 'Reconciled') {
    return 'bg-emerald-100 text-emerald-700';
  }

  return 'bg-slate-100 text-slate-700';
}

function getReconciliationSummary(student: any): ReconciliationSummary | null {
  const nested =
    student?.reconciliation_summary ||
    student?.course_reconciliation ||
    student?.course_validation ||
    student?.validation_result ||
    null;

  const summary: ReconciliationSummary = {
    status:
      student?.reconciliation_status ||
      student?.validation_status ||
      nested?.status ||
      null,

    validation_type:
      student?.validation_type ||
      nested?.validation_type ||
      'course_reconciliation',

    document_ai_course_count:
      student?.document_ai_course_count ??
      student?.document_ai_raw_course_count ??
      student?.raw_document_ai_course_count ??
      nested?.document_ai_course_count ??
      nested?.document_ai_raw_course_count ??
      nested?.raw_document_ai_course_count ??
      null,

    document_ai_raw_course_count:
      student?.document_ai_raw_course_count ??
      student?.raw_document_ai_course_count ??
      nested?.document_ai_raw_course_count ??
      nested?.raw_document_ai_course_count ??
      nested?.document_ai_course_count ??
      null,

    raw_document_ai_course_count:
      student?.raw_document_ai_course_count ??
      nested?.raw_document_ai_course_count ??
      null,

    gemini_course_count:
      student?.gemini_course_count ??
      student?.gemini_raw_course_count ??
      student?.raw_gemini_course_count ??
      nested?.gemini_course_count ??
      nested?.gemini_raw_course_count ??
      nested?.raw_gemini_course_count ??
      null,

    gemini_raw_course_count:
      student?.gemini_raw_course_count ??
      student?.raw_gemini_course_count ??
      nested?.gemini_raw_course_count ??
      nested?.raw_gemini_course_count ??
      nested?.gemini_course_count ??
      null,

    raw_gemini_course_count:
      student?.raw_gemini_course_count ??
      nested?.raw_gemini_course_count ??
      null,

    final_course_count:
      student?.final_course_count ??
      student?.final_course_details_count ??
      nested?.final_course_count ??
      nested?.final_course_details_count ??
      null,

    final_course_details_count:
      student?.final_course_details_count ??
      student?.final_course_count ??
      nested?.final_course_details_count ??
      nested?.final_course_count ??
      null,

    matched_course_count:
      student?.matched_course_count ??
      student?.matched_count ??
      nested?.matched_course_count ??
      nested?.matched_count ??
      null,

    matched_count:
      student?.matched_count ??
      nested?.matched_count ??
      null,

    document_ai_only_count:
      student?.document_ai_only_count ??
      nested?.document_ai_only_count ??
      null,

    gemini_only_count:
      student?.gemini_only_count ??
      nested?.gemini_only_count ??
      null,

    suppressed_document_ai_duplicate_count:
      student?.suppressed_document_ai_duplicate_count ??
      nested?.suppressed_document_ai_duplicate_count ??
      null,

    suppressed_gemini_duplicate_count:
      student?.suppressed_gemini_duplicate_count ??
      nested?.suppressed_gemini_duplicate_count ??
      null,

    auto_fixed_count:
      student?.auto_fixed_count ??
      student?.auto_applied_count ??
      nested?.auto_fixed_count ??
      nested?.auto_applied_count ??
      null,

    auto_applied_count:
      student?.auto_applied_count ??
      nested?.auto_applied_count ??
      null,

    needs_review_count:
      student?.needs_review_count ??
      student?.unresolved_count ??
      student?.unresolved_review_count ??
      nested?.needs_review_count ??
      nested?.unresolved_count ??
      nested?.unresolved_review_count ??
      null,

    unresolved_count:
      student?.unresolved_count ??
      nested?.unresolved_count ??
      null,

    unresolved_review_count:
      student?.unresolved_review_count ??
      nested?.unresolved_review_count ??
      null,

    removed_course_count:
      student?.removed_course_count ??
      nested?.removed_course_count ??
      null,

    review_reasons:
      student?.review_reasons ??
      nested?.review_reasons ??
      [],

    warnings:
      student?.warnings ??
      nested?.warnings ??
      [],

    model:
      student?.model ??
      nested?.model ??
      null,
  };

  const hasAnySummary =
    summary.status ||
    summary.document_ai_course_count !== null ||
    summary.gemini_course_count !== null ||
    summary.final_course_count !== null ||
    summary.needs_review_count !== null ||
    summary.auto_fixed_count !== null ||
    (summary.review_reasons?.length ?? 0) > 0 ||
    (summary.warnings?.length ?? 0) > 0;

  return hasAnySummary ? summary : null;
}

function getFinalCourses(student: any): any[] {
  const courses = firstNonEmpty(
    student?.final_courses,
    student?.final_course_details,
    student?.trusted_courses,
    student?.courses,
  );

  return Array.isArray(courses) ? courses : [];
}

function getCourseName(course: any): string {
  return String(
    firstNonEmpty(
      course?.course_name,
      course?.name,
      course?.crs_description,
      course?.final_course_name,
      course?.document_ai_course_name,
      course?.gemini_course_name,
    ) ?? '',
  );
}

function getCourseGrade(course: any): string {
  return String(
    firstNonEmpty(
      course?.letter_grade,
      course?.grade,
      course?.crs_letter_grade,
      course?.final_grade,
      course?.document_ai_grade,
      course?.gemini_grade,
    ) ?? '',
  );
}

function getCourseCreditsCompleted(course: any): string {
  return String(
    firstNonEmpty(
      course?.credit_completed,
      course?.credits_completed,
      course?.crs_credit_completed,
      course?.credits,
      course?.credit_attempted,
      course?.credits_attempted,
      course?.final_credit_completed,
      course?.gemini_credit_completed,
      course?.document_ai_credit_completed,
    ) ?? '',
  );
}

function getCourseCreditsAttempted(course: any): string {
  return String(
    firstNonEmpty(
      course?.credit_attempted,
      course?.credits_attempted,
      course?.crs_credit_attempted,
      course?.credits,
      course?.credit_completed,
      course?.credits_completed,
      course?.final_credit_attempted,
      course?.gemini_credit_attempted,
      course?.document_ai_credit_attempted,
    ) ?? '',
  );
}

function getCourseId(course: any): string {
  return String(
    firstNonEmpty(
      course?.course_id,
      course?.crs_id,
      course?.course_id_raw,
      course?.final_course_id_raw,
      course?.final_crs_id,
      course?.document_ai_course_id,
      course?.gemini_course_id,
      course?.course_number,
    ) ?? '',
  );
}

function getCourseGradeLevel(course: any): string {
  return String(
    firstNonEmpty(
      course?.grade_level,
      course?.crs_grade,
      course?.final_grade_level,
      course?.document_ai_grade_level,
      course?.gemini_grade_level,
    ) ?? '',
  );
}

function getCourseMonth(course: any): string {
  return String(
    firstNonEmpty(
      course?.month,
      course?.crs_month,
      course?.final_month,
      course?.document_ai_month,
      course?.gemini_month,
    ) ?? '',
  );
}

function getCourseYear(course: any): string {
  return String(
    firstNonEmpty(
      course?.year,
      course?.crs_year,
      course?.academic_year,
      course?.final_year,
      course?.document_ai_year,
      course?.gemini_year,
    ) ?? '',
  );
}

function getCourseSchool(course: any): string {
  return String(
    firstNonEmpty(
      course?.school,
      course?.school_name,
      course?.crs_hs,
      course?.final_school,
      course?.document_ai_school,
      course?.gemini_school,
    ) ?? '',
  );
}

function getFinalCourseId(course: any): number | null {
  return toNumberOrNull(
    firstNonEmpty(
      course?.final_course_id,
      course?.final_course_detail_id,
      course?.id,
    ),
  );
}

function getMatchId(course: any): number | null {
  return toNumberOrNull(
    firstNonEmpty(
      course?.match_id,
      course?.course_extraction_match_id,
      course?.validation_match_id,
      course?.reconciliation_match_id,
    ),
  );
}

function getCourseIdDifference(course: any): FieldDifference | null {
  const diffs = objectFromUnknown(
    firstNonEmpty(
      course?.field_differences,
      course?.fieldDifferences,
      course?.match_field_differences,
    ),
  );

  if (!diffs) return null;

  const value =
    diffs.course_id ||
    diffs.crs_id ||
    diffs.course_number ||
    diffs.id ||
    null;

  return value && typeof value === 'object' ? value : null;
}

function getCourseIdMatch(course: any): boolean | null {
  const explicit = firstNonEmpty(
    course?.course_id_match,
    course?.crs_id_match,
    course?.match_course_id,
  );

  if (typeof explicit === 'boolean') return explicit;

  const diff = getCourseIdDifference(course);
  if (diff) return false;

  const reviewReason = normalizeString(
    firstNonEmpty(
      course?.review_reason,
      course?.reason,
      course?.match_reason,
    ),
  );

  if (
    reviewReason.includes('course id') ||
    reviewReason.includes('course number') ||
    reviewReason.includes('crs id')
  ) {
    return false;
  }

  return null;
}

function getCourseIdSource(course: any): string | null {
  const direct = firstNonEmpty(
    course?.selected_course_id_source,
    course?.crs_id_source,
    course?.course_id_source,
  );

  if (direct) return String(direct);

  const fieldSources = objectFromUnknown(
    firstNonEmpty(
      course?.field_sources,
      course?.field_decisions,
    ),
  );

  const source = firstNonEmpty(
    fieldSources?.course_id,
    fieldSources?.crs_id,
    fieldSources?.course_number,
  );

  return source ? String(source) : null;
}

function isCourseNeedsReview(course: any): boolean {
  const status = normalizeStatus(
    firstNonEmpty(
      course?.review_status,
      course?.status,
      course?.match_status,
      course?.final_status,
    ),
  );

  if (course?.needs_review === true) return true;
  if (course?.review_required === true) return true;
  if (course?.reviewed_by_user === false && status.includes('needs_review')) {
    return true;
  }

  return status.includes('needs_review') || status.includes('unresolved');
}

function isCourseAutoFixed(course: any): boolean {
  const decision = normalizeStatus(
    firstNonEmpty(
      course?.decision,
      course?.match_decision,
      course?.auto_action,
      course?.resolution,
      course?.final_decision,
      course?.resolution_reason,
    ),
  );

  if (course?.auto_applied === true) return true;
  if (course?.auto_fixed === true) return true;

  return (
    decision.includes('auto') ||
    decision.includes('gemini_filled') ||
    decision.includes('corrected') ||
    decision.includes('accepted_document_ai_extra') ||
    decision.includes('accepted_gemini_only') ||
    decision.includes('accepted_document_ai_only')
  );
}

function isDocumentAiOnlyReview(course: CourseFormRow): boolean {
  const source = String(course.source ?? '');
  const decision = normalizeStatus(course.matchDecision);
  const status = normalizeStatus(course.matchStatus);

  return (
    source === 'Document AI' &&
    course.needsReview &&
    (decision.includes('document_ai_only') ||
      decision.includes('extra') ||
      decision.includes('doc_ai_only') ||
      status.includes('document_ai_only') ||
      status.includes('extra'))
  );
}

function isCourseResolved(course: CourseFormRow): boolean {
  if (course.isRemoved) return true;
  if (!course.needsReview) return true;
  return course.reviewed || course.extraResolution === 'keep';
}

function mapCourseToFormRow(course: any): CourseFormRow {
  const source = getDisplaySource(course);
  const finalCourseId = getFinalCourseId(course);
  const matchId = getMatchId(course);
  const needsReview = isCourseNeedsReview(course);
  const isAutoFixed = isCourseAutoFixed(course);

  const creditsCompleted = getCourseCreditsCompleted(course);
  const creditsAttempted = getCourseCreditsAttempted(course);

  const courseIdMatch = getCourseIdMatch(course);
  const courseIdDifference = getCourseIdDifference(course);
  const courseIdSource = getCourseIdSource(course);

  return {
    id: finalCourseId ?? Number(course?.id || 0),
    finalCourseId,
    matchId,

    name: getCourseName(course),
    grade: getCourseGrade(course),
    credits: creditsCompleted || creditsAttempted,

    creditsAttempted,
    creditsCompleted,

    courseId: getCourseId(course),
    gradeLevel: getCourseGradeLevel(course),
    month: getCourseMonth(course),
    year: getCourseYear(course),
    school: getCourseSchool(course),

    sectionName: course?.section_name ?? null,
    termName: course?.term_name ?? null,
    academicYear:
      course?.academic_year !== null && course?.academic_year !== undefined
        ? String(course.academic_year)
        : null,

    source,
    extractionSource:
      course?.extraction_source ||
      course?.extractionSource ||
      course?.final_source ||
      source,
    fieldSource:
      course?.field_source ||
      course?.field_sources ||
      course?.field_decisions ||
      course?.source_notes ||
      null,

    needsReview,
    reviewed:
      course?.reviewed_by_user === true ||
      course?.reviewed === true ||
      (!needsReview && normalizeStatus(course?.status) !== 'needs_review'),
    reviewReason:
      course?.review_reason ||
      course?.needs_review_reason ||
      course?.reason ||
      course?.match_reason ||
      null,

    matchStatus:
      course?.match_status ||
      course?.status ||
      course?.review_status ||
      course?.match_type ||
      null,
    matchDecision:
      course?.match_decision ||
      course?.decision ||
      course?.auto_action ||
      course?.resolution ||
      course?.resolution_reason ||
      course?.match_type ||
      null,
    matchConfidence:
      course?.match_confidence !== null && course?.match_confidence !== undefined
        ? String(course.match_confidence)
        : course?.confidence !== null && course?.confidence !== undefined
          ? String(course.confidence)
          : course?.gemini_confidence !== null && course?.gemini_confidence !== undefined
            ? String(course.gemini_confidence)
            : course?.match_score !== null && course?.match_score !== undefined
              ? String(course.match_score)
              : null,

    courseIdMatch,
    courseIdSource,
    courseIdDifference,

    isAutoFixed,
    isManual: source === 'Manual',
    isRemoved: false,
    extraResolution: null,
  };
}

function makeManualCourseRow(): CourseFormRow {
  return {
    id: 0,
    finalCourseId: null,
    matchId: null,

    name: '',
    grade: '',
    credits: '',

    creditsAttempted: '',
    creditsCompleted: '',

    courseId: '',
    gradeLevel: '',
    month: '',
    year: '',
    school: '',

    sectionName: null,
    termName: null,
    academicYear: null,

    source: 'Manual',
    extractionSource: 'Manual',
    fieldSource: null,

    needsReview: false,
    reviewed: true,
    reviewReason: null,

    matchStatus: null,
    matchDecision: null,
    matchConfidence: null,

    courseIdMatch: null,
    courseIdSource: 'manual',
    courseIdDifference: null,

    isAutoFixed: false,
    isManual: true,
    isRemoved: false,
    extraResolution: null,
  };
}

function getReadableStatus(row: Row): string {
  if (row.isFileOnly) {
    return 'File needs review';
  }

  if (row.needsReviewCount > 0) {
    return 'Needs review';
  }

  if (normalizeStatus(row.status).includes('completed')) {
    return 'Completed';
  }

  return row.status ?? 'Needs manual review';
}

function buildCoursePayload(
  course: CourseFormRow,
  options?: {
    markReviewed?: boolean;
    action?: string;
    resolution?: string;
  },
) {
  const courseId = course.courseId.trim();
  const shouldMarkReviewed = options?.markReviewed === true;
  const resolved = shouldMarkReviewed || isCourseResolved(course);

  const payload: Record<string, unknown> = {
    id: (course.finalCourseId ?? course.id) || undefined,
    final_course_id: course.finalCourseId ?? undefined,
    final_course_detail_id: course.finalCourseId ?? undefined,
    match_id: course.matchId ?? undefined,

    course_name: course.name.trim(),
    name: course.name.trim(),

    letter_grade: course.grade.trim(),
    grade: course.grade.trim(),

    credits: course.credits.trim(),
    credit_completed: course.creditsCompleted || course.credits.trim(),
    credits_completed: course.creditsCompleted || course.credits.trim(),
    credit_attempted: course.creditsAttempted || course.credits.trim(),
    credits_attempted: course.creditsAttempted || course.credits.trim(),

    course_id: courseId || undefined,
    crs_id: courseId || undefined,

    grade_level: course.gradeLevel || undefined,
    year: course.year || undefined,

    // Month is editable from the Needs Review table and saved to final_course_details.
    // It is optional unless the backend specifically keeps the row in Needs Review for month.
    month: course.month || undefined,

    school: course.school || undefined,

    section_name: course.sectionName || undefined,
    term_name: course.termName || undefined,
    academic_year: course.academicYear || undefined,

    source: course.source || undefined,
    extraction_source: course.extractionSource || course.source || undefined,
    final_source: normalizeFinalSourceForApi(course.source || course.extractionSource),

    needs_review: resolved ? false : course.needsReview,
    review_status: resolved ? 'reviewed' : course.needsReview ? 'needs_review' : 'auto_resolved',
    reviewed_by_user: resolved,
  };

  if (shouldMarkReviewed) {
    payload.mark_reviewed = true;
    payload.action = options?.action || 'review';
    payload.resolution = options?.resolution || 'accept_final';
  }

  return payload;
}

function courseRowKey(course: CourseFormRow, idx: number): string {
  return `${course.finalCourseId ?? 'no-final'}:${course.matchId ?? 'no-match'}:${course.id}:${idx}`;
}

function courseIdMismatchLabel(course: CourseFormRow): string | null {
  if (course.courseIdMatch !== false && !course.courseIdDifference) return null;

  const docValue = firstNonEmpty(
    course.courseIdDifference?.document_ai,
    course.courseIdDifference?.['Document AI'],
  );

  const geminiValue = firstNonEmpty(
    course.courseIdDifference?.gemini,
    course.courseIdDifference?.Gemini,
  );

  if (docValue || geminiValue) {
    return `ID mismatch: Doc AI ${docValue ?? '—'} / Gemini ${geminiValue ?? '—'}`;
  }

  return 'Course ID mismatch';
}

async function completeFileIfReady(fileId: number) {
  const response = await fetch(`/api/extractor/files/${fileId}/complete`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
  });

  let body: any = null;

  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (!response.ok) {
    const message =
      body?.detail?.message ||
      body?.detail ||
      body?.message ||
      'File still has unresolved or incomplete final rows.';

    throw new Error(
      typeof message === 'string'
        ? message
        : 'File still has unresolved or incomplete final rows.',
    );
  }

  return body;
}

export default function ExtractorNeedsReview({ embedded = false }: { embedded?: boolean }) {
  const [activeStudent, setActiveStudent] = useState<StudentWithCourses | null>(null);
  // Tracks the student currently being reviewed so a slow on-open course fetch
  // can't apply to a different student opened in the meantime.
  const reviewFetchKeyRef = useRef<string | null>(null);

  const [form, setForm] = useState({
    studentName: '',
    format: '',
    address: '',
    birthDate: '',
    graduationDate: '',
    gpa: '',
  });

  const [courseForm, setCourseForm] = useState<CourseFormRow[]>([]);
  // Default to the rows that actually need attention; the rest are one filter away.
  const [courseReviewFilter, setCourseReviewFilter] = useState<CourseReviewFilter>('needs_review');
  const [studentInfoOpen, setStudentInfoOpen] = useState(false);
  // True while the on-open detail fetch (slim list -> full courses) is in flight.
  const [loadingCourses, setLoadingCourses] = useState(false);
  const [removedRows, setRemovedRows] = useState<CourseFormRow[]>([]);
  const [saving, setSaving] = useState(false);
  const [movingToCompleted, setMovingToCompleted] = useState(false);
  const [savingRowKeys, setSavingRowKeys] = useState<Set<string>>(new Set());

  const { currentTerm, terms } = useTerm();
  const [refreshSeed, setRefreshSeed] = useState(0);

  const termName = terms.find((term) => term.id === currentTerm)?.term_name;

  const { data: rawStudents, refreshing } = useStaleData(
    `needs-review:${termName ?? ''}:${refreshSeed}`,
    () => fetchNeedsReviewStudents(termName),
    [termName, refreshSeed],
    // Auto-refresh continuously, but pause while a review is open so live
    // updates can't disrupt the form the user is editing.
    { refreshIntervalMs: activeStudent ? 0 : 8000 },
  );

  const setRowSaving = useCallback((key: string, isSaving: boolean) => {
    setSavingRowKeys((prev) => {
      const next = new Set(prev);

      if (isSaving) {
        next.add(key);
      } else {
        next.delete(key);
      }

      return next;
    });
  }, []);

  const refreshRows = useCallback(() => {
    setRefreshSeed((n) => n + 1);
  }, []);


  const finalCourseCountInForm = useMemo(
    () => courseForm.filter((course) => !course.isRemoved).length,
    [courseForm],
  );

  const needsReviewCourseCountInForm = useMemo(
    () =>
      courseForm.filter(
        (course) =>
          !course.isRemoved &&
          course.needsReview &&
          !course.reviewed &&
          course.extraResolution !== 'keep',
      ).length,
    [courseForm],
  );

  const reviewedCourseCountInForm = useMemo(
    () =>
      courseForm.filter(
        (course) =>
          !course.isRemoved &&
          (course.reviewed || !course.needsReview || course.extraResolution === 'keep'),
      ).length,
    [courseForm],
  );

  const doneCourseCountInForm = useMemo(
    () =>
      courseForm.filter(
        (course) => !course.isRemoved && !isCourseOpenForReview(course),
      ).length,
    [courseForm],
  );

  const filteredCourseRows = useMemo(
    () =>
      courseForm
        .map((course, idx) => ({ course, idx }))
        .filter(({ course }) => {
          if (course.isRemoved) return false;

          if (courseReviewFilter === 'needs_review') {
            return isCourseOpenForReview(course);
          }

          if (courseReviewFilter === 'done') {
            return !isCourseOpenForReview(course);
          }

          return true;
        }),
    [courseForm, courseReviewFilter],
  );

  const rows: Row[] = useMemo(() => {
    if (!rawStudents) return [];

    return rawStudents.map((student: any, idx) => {
      const reconciliation = getReconciliationSummary(student);
      const finalCourses = getFinalCourses(student);
      const unresolvedFromCourses = finalCourses.filter(isCourseNeedsReview).length;

      const finalCount =
        reconciliation?.final_course_count ??
        reconciliation?.final_course_details_count ??
        finalCourses.length ??
        null;

      const needsReviewCount =
        reconciliation?.needs_review_count ??
        reconciliation?.unresolved_review_count ??
        reconciliation?.unresolved_count ??
        unresolvedFromCourses;

      return {
        id: student.is_file_only
          ? `file-${student.source_file}`
          : String(student.db_id ?? student.id ?? ''),
        studentId: student.is_file_only
          ? `file-${student.source_file}`
          : String(student.student_id ?? student.id ?? ''),
        serial: idx + 1,
        studentName: student.student_name,
        fileName: student.file_name ?? null,
        school:
          student.final_school ||
          student.school ||
          student.school_name ||
          schoolFromFileName(student.file_name) ||
          null,
        format: student.format ?? null,
        status:
          student.process_status ||
          student.file_status ||
          student.review_reason ||
          reconciliation?.status ||
          'needs_manual_review',
        isFileOnly: student.is_file_only ?? false,
        sourceFileId: student.source_file ?? undefined,
        reconciliation,
        documentAiCount:
          reconciliation?.document_ai_raw_course_count ??
          reconciliation?.document_ai_course_count ??
          student.document_ai_course_count ??
          null,
        geminiCount:
          reconciliation?.gemini_raw_course_count ??
          reconciliation?.gemini_course_count ??
          student.gemini_course_count ??
          null,
        finalCount,
        autoFixedCount:
          reconciliation?.auto_fixed_count ??
          reconciliation?.auto_applied_count ??
          null,
        needsReviewCount: needsReviewCount ?? 0,
      };
    });
  }, [rawStudents]);

  const resetReviewState = useCallback(() => {
    setRemovedRows([]);
    setSavingRowKeys(new Set());
    setMovingToCompleted(false);
    setCourseReviewFilter('needs_review');
  }, []);

  const openReview = useCallback(
    (row: Row) => {
      resetReviewState();

      if (row.isFileOnly) {
        const target = rawStudents?.find(
          (student: any) => Number(student.source_file) === Number(row.sourceFileId),
        );

        const fallbackStudent = {
          id: `file-${row.sourceFileId}`,
          student_name: row.studentName ?? '',
          file_name: row.fileName ?? '',
          source_file: row.sourceFileId,
          is_file_only: true,
          reconciliation_summary: row.reconciliation,
          final_courses: [],
        };

        const selectedStudent = (target || fallbackStudent) as StudentWithCourses;
        const finalCourses = getFinalCourses(selectedStudent as any);

        setActiveStudent(selectedStudent);

        setForm({
          studentName: '',
          format: '',
          address: '',
          birthDate: '',
          graduationDate: '',
          gpa: '',
        });

        setCourseForm(finalCourses.map(mapCourseToFormRow));
        return;
      }

      const target = rawStudents?.find((student: any) => {
        const candidateId = String(student.db_id ?? student.id ?? '');
        return candidateId === row.id;
      });

      if (!target) {
        toast.error('Unable to load student for review');
        return;
      }

      const finalCourses = getFinalCourses(target);

      setActiveStudent(target);

      setForm({
        studentName: target.student_name || '',
        format: target.format || '',
        address: (target as any).address || '',
        birthDate: toInputDate(target.birth_date),
        graduationDate: toInputDate(target.graduation_date),
        gpa: target.gpa ? String(target.gpa) : '',
      });

      setCourseForm(finalCourses.map(mapCourseToFormRow));

      // The /needs-review list payload is slim (no courses) for fast loads, so
      // fetch the full student on open and fill in the course rows for review.
      const dbId = (target as any).db_id ?? (target as any).id;
      if (dbId != null && finalCourses.length === 0) {
        const fetchKey = String(dbId);
        reviewFetchKeyRef.current = fetchKey;
        setLoadingCourses(true);
        fetchStudentDetail(dbId)
          .then((full) => {
            if (reviewFetchKeyRef.current !== fetchKey) return; // a newer student was opened
            const fullCourses = getFinalCourses(full as any);
            setActiveStudent((prev) =>
              prev ? ({ ...(prev as any), courses: (full as any).courses } as StudentWithCourses) : prev,
            );
            setCourseForm(fullCourses.map(mapCourseToFormRow));
            setLoadingCourses(false);
          })
          .catch(() => {
            if (reviewFetchKeyRef.current === fetchKey) {
              setLoadingCourses(false);
              toast.error('Failed to load courses for review');
            }
          });
      }
    },
    [rawStudents, resetReviewState],
  );

  const updateCourseRow = useCallback(
    (idx: number, patch: Partial<CourseFormRow>) => {
      setCourseForm((prev) =>
        prev.map((course, i) => {
          if (i !== idx) return course;

          return {
            ...course,
            ...patch,
          };
        }),
      );
    },
    [],
  );

  const persistReviewedCourse = useCallback(
    async (
      course: CourseFormRow,
      payloadOverrides: Record<string, unknown> = {},
    ) => {
      const payload = {
        ...buildCoursePayload(course, {
          markReviewed: true,
          action: String(payloadOverrides.action || 'review'),
          resolution: String(payloadOverrides.resolution || 'accept_final'),
        }),
        ...payloadOverrides,
      };

      if (course.finalCourseId) {
        await reviewFinalCourse(course.finalCourseId, payload);
      }

      if (course.matchId) {
        await resolveCourseExtractionMatch(course.matchId, {
          action: String(payloadOverrides.action || 'accept_final'),
          resolution: String(payloadOverrides.resolution || 'accept_final'),
          final_course_id: course.finalCourseId ?? undefined,
          final_course: payload,
          mark_reviewed: true,
          reviewed_by_user: true,
          needs_review: false,
          final_source: normalizeFinalSourceForApi(course.source || course.extractionSource),
        });
      }
    },
    [],
  );

  const markCourseReviewed = useCallback(
    async (idx: number) => {
      const course = courseForm[idx];

      if (!course) return;

      // Course ID is intentionally NOT required — some formats (e.g. St. Anthony)
      // have no course IDs, so a reviewer can mark the row reviewed as-is.
      if (
        !course.name.trim() ||
        !course.gradeLevel.trim() ||
        !course.year.trim() ||
        !course.grade.trim() ||
        !course.credits.trim()
      ) {
        toast.error(
          'Course name, grade year, year, grade, and credits are required before marking reviewed',
        );
        return;
      }

      const updatedCourse: CourseFormRow = {
        ...course,
        reviewed: true,
        needsReview: false,
        extraResolution: course.extraResolution === null ? 'keep' : course.extraResolution,
      };

      const key = courseRowKey(course, idx);
      setRowSaving(key, true);

      try {
        if (course.finalCourseId || course.matchId) {
          await persistReviewedCourse(updatedCourse, {
            action: 'review',
            resolution: 'accept_final',
          });
        }

        updateCourseRow(idx, {
          reviewed: true,
          needsReview: false,
          extraResolution: course.extraResolution === null ? 'keep' : course.extraResolution,
          reviewReason: null,
          courseIdMatch: course.courseIdMatch === false ? true : course.courseIdMatch,
        });

        toast.success('Course marked reviewed and saved');
      } catch (error: any) {
        toast.error(error?.message || 'Could not mark course reviewed');
      } finally {
        setRowSaving(key, false);
      }
    },
    [courseForm, persistReviewedCourse, setRowSaving, updateCourseRow],
  );

  const markExtraCourseKeep = useCallback(
    async (idx: number) => {
      const course = courseForm[idx];

      if (!course) return;

      if (
        !course.courseId.trim() ||
        !course.name.trim() ||
        !course.gradeLevel.trim() ||
        !course.year.trim() ||
        !course.grade.trim() ||
        !course.credits.trim()
      ) {
        toast.error(
          'Course ID, course name, grade year, year, grade, and credits are required before keeping this row',
        );
        return;
      }

      const updatedCourse: CourseFormRow = {
        ...course,
        extraResolution: 'keep',
        reviewed: true,
        needsReview: false,
      };

      const key = courseRowKey(course, idx);
      setRowSaving(key, true);

      try {
        if (course.finalCourseId || course.matchId) {
          await persistReviewedCourse(updatedCourse, {
            action: 'keep',
            resolution: 'keep',
          });
        }

        updateCourseRow(idx, {
          extraResolution: 'keep',
          reviewed: true,
          needsReview: false,
          reviewReason: null,
        });

        toast.success('Kept row and saved review');
      } catch (error: any) {
        toast.error(error?.message || 'Could not keep row');
      } finally {
        setRowSaving(key, false);
      }
    },
    [courseForm, persistReviewedCourse, setRowSaving, updateCourseRow],
  );

  const markExtraCourseRemove = useCallback(
    async (idx: number) => {
      const course = courseForm[idx];

      if (!course) return;

      const key = courseRowKey(course, idx);
      setRowSaving(key, true);

      try {
        if (course.matchId) {
          await resolveCourseExtractionMatch(course.matchId, {
            action: 'remove',
            resolution: 'remove',
            final_course_id: course.finalCourseId ?? undefined,
            reviewed_by_user: true,
            needs_review: false,
            review_status: 'removed',
          });
        } else if (course.finalCourseId) {
          await reviewFinalCourse(course.finalCourseId, {
            action: 'remove',
            resolution: 'remove',
            final_course_id: course.finalCourseId,
            needs_review: false,
            reviewed_by_user: true,
            review_status: 'removed',
          });
        } else {
          setRemovedRows((prev) => [
            ...prev,
            { ...course, isRemoved: true, extraResolution: 'remove' },
          ]);
        }

        setCourseForm((prev) => prev.filter((_, i) => i !== idx));
        toast.success('Removed row and saved review');
      } catch (error: any) {
        toast.error(error?.message || 'Could not remove row');
      } finally {
        setRowSaving(key, false);
      }
    },
    [courseForm, setRowSaving],
  );

  const removeUnsavedCourse = useCallback((idx: number) => {
    setCourseForm((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const columns: StdColumn<Row>[] = useMemo(
    () => [
      {
        key: 'student',
        header: 'Student',
        value: (row) => row.studentName || `Unknown Student ${row.studentId ?? row.id}`,
        cell: (row) => {
          const displayName = row.studentName || `Unknown Student ${row.studentId ?? row.id}`;
          return (
            <div className="flex items-center gap-3">
              <Avatar name={displayName} />
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-900" title={displayName}>
                  {displayName}
                </div>
                <div className="truncate text-xs text-slate-400" title={String(row.studentId ?? row.id ?? '')}>
                  {row.studentId ?? row.id ?? '—'}
                </div>
              </div>
            </div>
          );
        },
      },
      {
        key: 'school',
        header: 'School',
        value: (row) => row.school ?? '',
        cell: (row) => (
          <span className="block truncate text-slate-600" title={String(row.school ?? '')}>
            {row.school || '—'}
          </span>
        ),
      },
      {
        key: 'format',
        header: 'Format',
        value: (row) => resolveFormat(row.school, row.format),
        filterable: true,
        cell: (row) => {
          const fmt = resolveFormat(row.school, row.format);
          return fmt && fmt !== '—' ? (
            <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-200">
              {fmt}
            </span>
          ) : (
            <span className="text-slate-400">—</span>
          );
        },
      },
      {
        key: 'status',
        header: 'Status',
        value: (row) => getReadableStatus(row),
        sortValue: (row) => row.needsReviewCount ?? 0,
        cell: (row) => (
          (row.needsReviewCount ?? 0) > 0 ? (
            <span className="inline-flex items-center gap-1 rounded bg-red-50 px-1.5 py-0.5 text-xs font-medium text-red-700 border border-red-200">
              <AlertCircle className="h-3 w-3 shrink-0" />
              {row.needsReviewCount} Need Review
            </span>
          ) : (
            <span className="text-xs text-slate-400">—</span>
          )
        ),
      },
      {
        key: 'review',
        header: 'Review',
        align: 'center',
        width: 120,
        sortable: false,
        cell: (row) => (
          <Button variant="secondary" size="sm" onClick={() => openReview(row)}>
            Review
          </Button>
        ),
      },
    ],
    [openReview],
  );

  const requiredCoursesFilled = courseForm.every((course) => {
    if (course.isRemoved) return true;

    return (
      course.name.trim() &&
      course.gradeLevel.trim() &&
      course.year.trim() &&
      course.grade.trim() &&
      course.credits.trim()
    );
  });

  const allReviewRowsResolved = courseForm.every((course) => isCourseResolved(course));

  const hasRowSaving = savingRowKeys.size > 0;

  const canSave =
    form.studentName.trim() !== '' &&
    requiredCoursesFilled &&
    !hasRowSaving;

  const canMoveToCompleted =
    Boolean(activeStudent) &&
    canSave &&
    allReviewRowsResolved &&
    needsReviewCourseCountInForm === 0 &&
    !saving &&
    !movingToCompleted &&
    !hasRowSaving;

  const saveReviewChanges = async (options?: { moveToCompleted?: boolean }) => {
    if (!activeStudent || !canSave) return;

    if (options?.moveToCompleted && needsReviewCourseCountInForm > 0) {
      toast.error(`Resolve ${needsReviewCourseCountInForm} row(s) before moving to Completed`);
      return;
    }

    if (options?.moveToCompleted && !allReviewRowsResolved) {
      toast.error('Resolve all review rows before moving to Completed');
      return;
    }

    if (options?.moveToCompleted) {
      setMovingToCompleted(true);
    } else {
      setSaving(true);
    }

    try {
      const activeStudentId =
        activeStudent.db_id ??
        activeStudent.student_id ??
        activeStudent.id ??
        '';

      const activeSourceFile = activeStudent.source_file;

      const activeRows = courseForm.filter((course) => !course.isRemoved);
      const manualRows = activeRows.filter((course) => course.id === 0 || course.isManual);

      const studentPayload = {
        student_name: form.studentName.trim(),
        format: form.format.trim(),
        address: form.address.trim() || undefined,
        birth_date: form.birthDate || undefined,
        graduation_date: form.graduationDate || undefined,
        gpa: form.gpa || undefined,
        courses: manualRows.map((course) =>
          buildCoursePayload(course, {
            markReviewed: isCourseResolved(course),
            action: isCourseResolved(course) ? 'review' : undefined,
            resolution: isCourseResolved(course) ? 'accept_final' : undefined,
          }),
        ),
      };

      if (activeStudent.is_file_only && activeSourceFile) {
        await createStudentForFile(activeSourceFile, studentPayload);
      } else {
        await updateStudentAndCourses(activeStudentId, studentPayload);
      }

      // Persist all active course rows in parallel batches (was sequential,
      // which made big transcripts take 10-30s to move to Completed).
      await runWithConcurrency(activeRows, 24, async (course) => {
        const rowResolved = isCourseResolved(course);

        const payload = buildCoursePayload(course, {
          markReviewed: rowResolved,
          action: rowResolved ? 'review' : undefined,
          resolution: rowResolved ? 'accept_final' : undefined,
        });

        if (course.finalCourseId) {
          await reviewFinalCourse(course.finalCourseId, payload, true);
        }

        if (rowResolved && course.matchId) {
          await resolveCourseExtractionMatch(course.matchId, {
            action: 'accept_final',
            resolution: 'accept_final',
            final_course_id: course.finalCourseId ?? undefined,
            final_course: payload,
            mark_reviewed: true,
            needs_review: false,
            reviewed_by_user: true,
            final_source: normalizeFinalSourceForApi(course.source || course.extractionSource),
          }, true);
        }
      });

      await runWithConcurrency(removedRows, 24, async (course) => {
        if (course.matchId) {
          await resolveCourseExtractionMatch(course.matchId, {
            action: 'remove',
            resolution: 'remove',
            final_course_id: course.finalCourseId ?? undefined,
            needs_review: false,
            reviewed_by_user: true,
            review_status: 'removed',
          }, true);
        } else if (course.finalCourseId) {
          await reviewFinalCourse(course.finalCourseId, {
            action: 'remove',
            resolution: 'remove',
            needs_review: false,
            reviewed_by_user: true,
            review_status: 'removed',
          }, true);
        }
      });

      if (options?.moveToCompleted) {
        if (!activeSourceFile) {
          throw new Error('Cannot move to Completed because source_file is missing.');
        }

        await completeFileIfReady(Number(activeSourceFile));
      }

      toast.success(
        options?.moveToCompleted
          ? 'Moved to Completed'
          : 'Saved review changes',
      );
      emitNotification({
        kind: 'success',
        title: options?.moveToCompleted ? 'Moved to Completed' : 'Review saved',
        message: (activeStudent as any)?.student_name || (activeStudent as any)?.file_name || undefined,
      });

      setActiveStudent(null);
      resetReviewState();
      refreshRows();
    } catch (error: any) {
      toast.error(error?.message || 'Save failed');
    } finally {
      setSaving(false);
      setMovingToCompleted(false);
    }
  };

  const handleSave = async () => {
    await saveReviewChanges();
  };

  const handleMoveToCompleted = async () => {
    await saveReviewChanges({ moveToCompleted: true });
  };

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Needs Review"
          subtitle="Final reconciled transcript rows that require manual review"
        />
      )}

      {refreshing && rows.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Loading transcripts…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-md border p-6 text-center text-muted-foreground">
          No transcripts require review right now.
        </div>
      ) : (
        <StandardTable
          columns={columns}
          data={rows}
          rowKey={(r) => r.id}
          flagId={(r) => r.id}
          search
          searchPlaceholder="Search students, schools, files…"
          storageKey="extract:needs-review"
          emptyMessage="No transcripts require review right now."
        />
      )}

      <Dialog
        open={!!activeStudent}
        onOpenChange={(open) => {
          if (!open) {
            setActiveStudent(null);
            resetReviewState();
          }
        }}
      >
        <DialogContent className="!w-[1500px] !max-w-[98vw] max-h-[94vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle>Review Transcript</DialogTitle>

            <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
              <span>
                Student: <b className="text-slate-700">{form.studentName || activeStudent?.student_name || '—'}</b>
              </span>
              <span>
                School: <b className="text-slate-700">{form.format || '—'}</b>
              </span>
              <span>ID: {activeStudent?.student_id ?? activeStudent?.id ?? '—'}</span>
            </div>
          </DialogHeader>

          <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 lg:grid-cols-12">
            <div className="lg:col-span-6 rounded-md border bg-slate-50/70 min-h-[520px] overflow-hidden">
              {activeStudent?.source_file ? (
                <iframe
                  title="Transcript PDF"
                  src={`/api/extractor/files/${activeStudent.source_file}/pdf`}
                  className="h-[calc(94vh-180px)] min-h-[520px] w-full border-0"
                />
              ) : (
                <div className="flex h-[520px] items-center justify-center px-4 py-6 text-center text-sm text-muted-foreground">
                  PDF preview not available for this student.
                </div>
              )}
            </div>

            <div className="lg:col-span-6 min-h-0 max-h-[calc(94vh-180px)] overflow-y-auto pr-1 space-y-4">
              <div className="rounded-md border border-slate-200 bg-white shadow-sm">
                {/* Collapsible — collapsed by default so the transcript + editor get the space. */}
                <div className="flex items-center justify-between gap-3 px-3 py-2.5">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                    <Wand2 className="h-4 w-4 text-emerald-600" />
                    Course Summary
                  </div>
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-semibold tabular-nums text-slate-800">
                      {reviewedCourseCountInForm}/{finalCourseCountInForm} reviewed
                    </span>
                    {needsReviewCourseCountInForm > 0 && (
                      <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                        {needsReviewCourseCountInForm} Need Review
                      </span>
                    )}
                  </div>
                </div>
              </div>

              <div className="rounded-md border border-slate-200 bg-white shadow-sm">
                <button
                  type="button"
                  onClick={() => setStudentInfoOpen((o) => !o)}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2.5 text-left"
                >
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-800">
                    <UserRound className="h-4 w-4 text-blue-600" />
                    Student Details
                  </div>
                  <ChevronDown
                    className={`h-4 w-4 shrink-0 text-slate-400 transition-transform ${studentInfoOpen ? 'rotate-180' : ''}`}
                  />
                </button>
                {studentInfoOpen && (
                <div className="grid grid-cols-2 gap-3 border-t border-slate-100 p-3">
                <div>
                  <Label>Student Name</Label>
                  <Input
                    value={form.studentName}
                    onChange={(event) =>
                      setForm({ ...form, studentName: event.target.value })
                    }
                  />
                </div>

                <div>
                  <Label>School</Label>
                  <Input
                    value={form.format}
                    onChange={(event) =>
                      setForm({ ...form, format: event.target.value })
                    }
                  />
                </div>

                <div>
                  <Label>Birth Date</Label>
                  <Input
                    type="date"
                    value={form.birthDate}
                    onChange={(event) =>
                      setForm({ ...form, birthDate: event.target.value })
                    }
                  />
                </div>

                <div>
                  <Label>Graduation Date</Label>
                  <Input
                    type="date"
                    value={form.graduationDate}
                    onChange={(event) =>
                      setForm({ ...form, graduationDate: event.target.value })
                    }
                  />
                </div>

                <div className="col-span-2">
                  <Label>Address</Label>
                  <Input
                    value={form.address}
                    onChange={(event) =>
                      setForm({ ...form, address: event.target.value })
                    }
                  />
                </div>

                <div className="col-span-2">
                  <Label>GPA</Label>
                  <Input
                    value={form.gpa}
                    onChange={(event) =>
                      setForm({ ...form, gpa: event.target.value })
                    }
                  />
                </div>
                </div>
                )}
              </div>

              <div className="space-y-2">
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <ListChecks className="h-4 w-4 text-violet-600" />
                    <h4 className="text-sm font-medium">Review Courses</h4>
                  </div>

                  <div className="flex flex-wrap items-center justify-end gap-2">
                    <div className="inline-flex items-center gap-1.5 rounded-md border bg-white px-2 py-1 text-xs text-slate-700 shadow-sm">
                      <Filter className="h-3.5 w-3.5 text-muted-foreground" />
                      <span className="font-medium">Filter</span>
                      <select
                        value={courseReviewFilter}
                        onChange={(event) =>
                          setCourseReviewFilter(event.target.value as CourseReviewFilter)
                        }
                        className="h-7 rounded border-0 bg-transparent px-1 text-xs font-medium outline-none focus:ring-0"
                        aria-label="Filter final courses"
                      >
                        <option value="all">All ({finalCourseCountInForm})</option>
                        <option value="needs_review">
                          Only needs review ({needsReviewCourseCountInForm})
                        </option>
                        <option value="done">Done ({doneCourseCountInForm})</option>
                      </select>
                    </div>

                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() =>
                        setCourseForm((prev) => [
                          ...prev,
                          makeManualCourseRow(),
                        ])
                      }
                    >
                      <Plus className="h-3.5 w-3.5 mr-1" />
                      Add Course
                    </Button>
                  </div>
                </div>

                <div className="rounded-md border bg-white">
                  <div className="max-h-[calc(94vh-250px)] space-y-3 overflow-y-auto p-3 [&_input]:h-9 [&_input]:text-sm">
                        {filteredCourseRows.map(({ course, idx }) => {
                          const needsReview = course.needsReview && !course.reviewed;
                          const isAutoFixed = course.isAutoFixed;
                          const isExtraReview = isDocumentAiOnlyReview(course);
                          const rowKey = courseRowKey(course, idx);
                          const rowSaving = savingRowKeys.has(rowKey);
                          const idMismatchLabel = courseIdMismatchLabel(course);

                          const cardTint = needsReview
                            ? 'border-amber-200 bg-amber-50/50'
                            : isAutoFixed
                              ? 'border-emerald-200 bg-emerald-50/40'
                              : course.isManual
                                ? 'border-blue-200 bg-blue-50/30'
                                : 'border-slate-200 bg-white';
                          const fieldCls = (bad?: boolean) =>
                            bad ? 'border-amber-300 bg-white font-medium' : 'bg-slate-50';
                          const labelCls = 'mb-1 block text-[11px] font-medium text-slate-500';

                          return (
                            <div
                              key={`${course.finalCourseId ?? course.id}-${idx}-${course.name}`}
                              className={`rounded-lg border p-3 shadow-sm ${cardTint}`}
                            >
                              {/* Row 1 — Course ID + Name + actions on one line */}
                              <div className="flex flex-wrap items-start gap-3">
                                <div className="w-28">
                                  <label className={labelCls}>Course ID</label>
                                  <Input
                                    value={course.courseId}
                                    placeholder="Course ID"
                                    className={fieldCls(Boolean(idMismatchLabel) || needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        courseId: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || Boolean(idMismatchLabel),
                                      })
                                    }
                                  />
                                </div>
                                <div className="min-w-[200px] flex-1">
                                  <label className={labelCls}>Course Name</label>
                                  <Input
                                    value={course.name}
                                    placeholder="Course name"
                                    className={fieldCls(needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        name: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                  <div className="hidden">
                                    {idMismatchLabel && (
                                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                                        <AlertTriangle className="h-3 w-3" />
                                        {idMismatchLabel}
                                      </span>
                                    )}
                                    {needsReview && (
                                      <span className="inline-flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-[10px] font-semibold text-amber-800">
                                        <AlertTriangle className="h-3 w-3" />
                                        Need Review
                                      </span>
                                    )}
                                    {isAutoFixed && (
                                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                                        <Sparkles className="h-3 w-3" />
                                        Auto-fixed
                                      </span>
                                    )}
                                    {course.reviewed && (
                                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                                        <CheckCircle2 className="h-3 w-3" />
                                        Reviewed
                                      </span>
                                    )}
                                    {course.source && (
                                      <span
                                        className={`rounded-full px-2 py-0.5 text-[10px] font-semibold ${getSourceBadgeClass(
                                          course.source,
                                        )}`}
                                      >
                                        Source: {course.source}
                                      </span>
                                    )}
                                    {course.extraResolution === 'keep' && (
                                      <span className="inline-flex items-center gap-1 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-semibold text-emerald-700">
                                        <ShieldCheck className="h-3 w-3" />
                                        Keep confirmed
                                      </span>
                                    )}
                                    {course.sectionName && (
                                      <span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-muted-foreground">
                                        {course.sectionName}
                                      </span>
                                    )}
                                    {course.matchConfidence && (
                                      <span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-muted-foreground">
                                        Confidence: {course.matchConfidence}
                                      </span>
                                    )}
                                    {course.reviewReason && (
                                      <span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-muted-foreground">
                                        {course.reviewReason}
                                      </span>
                                    )}
                                    {course.courseIdSource && (
                                      <span className="rounded-full bg-white px-2 py-0.5 text-[10px] text-muted-foreground">
                                        ID source: {course.courseIdSource}
                                      </span>
                                    )}
                                  </div>
                                </div>
                                <div className="flex flex-wrap items-center gap-2 pt-[22px]">
                                  {needsReview && (
                                    <Button
                                      type="button"
                                      size="sm"
                                      className="bg-amber-500 text-white shadow-sm hover:bg-amber-600"
                                      disabled={rowSaving || saving || movingToCompleted}
                                      onClick={() => markCourseReviewed(idx)}
                                    >
                                      {rowSaving ? 'Saving…' : 'Mark reviewed'}
                                    </Button>
                                  )}
                                  {isExtraReview && course.extraResolution !== 'keep' && (
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="outline"
                                      disabled={rowSaving || saving || movingToCompleted}
                                      onClick={() => markExtraCourseKeep(idx)}
                                    >
                                      Keep
                                    </Button>
                                  )}
                                  {isExtraReview && (
                                    <Button
                                      type="button"
                                      size="sm"
                                      variant="destructive"
                                      disabled={rowSaving || saving || movingToCompleted}
                                      onClick={() => markExtraCourseRemove(idx)}
                                    >
                                      Remove
                                    </Button>
                                  )}
                                  {course.id === 0 && (
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="text-destructive hover:text-destructive"
                                      disabled={rowSaving || saving || movingToCompleted}
                                      onClick={() => removeUnsavedCourse(idx)}
                                      title="Remove this course"
                                      aria-label="Remove this course"
                                    >
                                      <Trash2 className="mr-1 h-3.5 w-3.5" />
                                      Remove
                                    </Button>
                                  )}
                                </div>
                              </div>

                              {/* Row 2 — term & grade fields */}
                              <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
                                <div>
                                  <label className={labelCls}>Grade Yr</label>
                                  <Input
                                    value={course.gradeLevel}
                                    placeholder="9–12"
                                    className={fieldCls(needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        gradeLevel: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                </div>
                                <div>
                                  <label className={labelCls}>Month</label>
                                  <Input
                                    value={course.month}
                                    placeholder="MM"
                                    className={fieldCls(needsReview && !course.month.trim())}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        month: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                </div>
                                <div>
                                  <label className={labelCls}>Year</label>
                                  <Input
                                    value={course.year}
                                    placeholder="YYYY"
                                    className={fieldCls(needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        year: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                </div>
                                <div>
                                  <label className={labelCls}>Grade</label>
                                  <Input
                                    value={course.grade}
                                    placeholder="Grade"
                                    className={fieldCls(needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        grade: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                </div>
                                <div>
                                  <label className={labelCls}>Credits</label>
                                  <Input
                                    value={course.credits}
                                    placeholder="Credits"
                                    className={fieldCls(needsReview)}
                                    onChange={(event) =>
                                      updateCourseRow(idx, {
                                        credits: event.target.value,
                                        creditsCompleted: event.target.value,
                                        reviewed: false,
                                        needsReview: course.needsReview || needsReview,
                                      })
                                    }
                                  />
                                </div>
                              </div>
                            </div>
                          );
                        })}

                        {filteredCourseRows.length === 0 && (
                          <div className="px-3 py-8 text-center text-xs text-muted-foreground">
                            {loadingCourses
                              ? 'Loading courses…'
                              : courseReviewFilter === 'all'
                                ? 'No final courses found. Click "Add Course" to add one.'
                                : 'No courses match the selected filter.'}
                          </div>
                        )}
                  </div>
                </div>

                <div className="flex items-center justify-between gap-3 text-xs text-muted-foreground">
                  <span>
                    Course ID, course name, grade year, year, grade, and credits are required. Month is optional but can be filled manually.
                    {needsReviewCourseCountInForm > 0
                      ? ` Resolve ${needsReviewCourseCountInForm} row(s) before moving to Completed.`
                      : ' All open review rows are resolved.'}
                  </span>

                  <span>
                    Reviewed rows: {reviewedCourseCountInForm}/{finalCourseCountInForm}
                  </span>
                </div>
              </div>
            </div>
          </div>

          <DialogFooter className="gap-2 pt-3">
            <div className="mr-auto text-xs text-muted-foreground">
              {needsReviewCourseCountInForm > 0 ? (
                <span>
                  Resolve {needsReviewCourseCountInForm} row(s), then Move to Completed.
                </span>
              ) : (
                <span className="text-emerald-700">
                  All review rows are resolved. You can move this file to Completed.
                </span>
              )}
            </div>

            <Button
              variant="outline"
              onClick={() => {
                setActiveStudent(null);
                resetReviewState();
              }}
              disabled={saving || movingToCompleted || hasRowSaving}
            >
              Cancel
            </Button>

            <Button
              variant="secondary"
              onClick={handleSave}
              disabled={!canSave || saving || movingToCompleted || hasRowSaving}
            >
              {saving ? 'Saving…' : 'Save Review'}
            </Button>

            <Button
              onClick={handleMoveToCompleted}
              disabled={!canMoveToCompleted}
              className="gap-1"
            >
              <ArrowRightCircle className="h-4 w-4" />
              {movingToCompleted ? 'Moving…' : 'Move to Completed'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}