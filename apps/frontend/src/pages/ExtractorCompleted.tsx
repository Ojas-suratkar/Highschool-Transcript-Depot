import { useCallback, useMemo, useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { IconButton } from '@/components/shared/IconButton';
import { Avatar } from '@/components/shared/Avatar';
import { StandardTable, StdColumn } from '@/components/shared/StandardTable';
import { resolveFormat } from '@/lib/extractorFormat';
import { Eye } from 'lucide-react';
import TranscriptDetailDialog, {
  TranscriptRecord,
} from '@/components/dialogs/TranscriptDetailDialog';
import { fetchCompletedStudents, fetchStudentDetail } from '@/lib/api/extractor';
import { mapStudentToTranscriptRecord } from '@/lib/studentUtils';
import { useTerm } from '@/contexts/TermContext';
import { formatDateTimePST } from '@/lib/utils';
import { useStaleData } from '@/lib/useStaleData';

type CompletedInitialTab = 'personal' | 'courses' | 'standardization' | 'transcript';

type ReconciliationSummary = {
  status?: string | null;
  validation_type?: string | null;

  document_ai_course_count?: number | null;
  raw_document_ai_course_count?: number | null;
  course_details_count?: number | null;

  gemini_course_count?: number | null;
  raw_gemini_course_count?: number | null;
  gemini_course_details_count?: number | null;

  final_course_count?: number | null;
  actual_final_course_count?: number | null;
  final_course_details_count?: number | null;

  expected_final_course_count?: number | null;
  course_count_difference?: number | null;
  final_count_shortfall?: boolean | null;
  counts_match?: boolean | null;

  matched_count?: number | null;
  matched_course_count?: number | null;
  document_ai_only_count?: number | null;
  gemini_only_count?: number | null;

  auto_fixed_count?: number | null;
  auto_applied_count?: number | null;

  needs_review_count?: number | null;
  open_review_count?: number | null;

  review_reason_text?: string | null;
  review_reasons?: string[];
  course_math_explanation?: string | null;
  model?: string | null;
};

type CompletedTranscriptRecord = TranscriptRecord & {
  rowKey: string;
  serial?: number;
  fileName?: string | null;
  school?: string | null;

  reconciliation?: ReconciliationSummary | null;

  documentAiRawCount?: number | null;
  geminiRawCount?: number | null;
  finalCourseCount?: number | null;
  autoFixedCount?: number | null;
  needsReviewCount?: number | null;

  courseCount?: number;
  hasAutoFixedCourses?: boolean;
  autoFixedSummary?: string | null;
};

function firstNonEmpty<T>(...values: T[]): T | undefined {
  return values.find((value) => {
    if (value === null || value === undefined) return false;
    if (Array.isArray(value) && value.length === 0) return false;
    if (typeof value === 'string' && value.trim() === '') return false;
    return true;
  });
}

function normalizeString(value: unknown): string {
  return String(value ?? '')
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function getFileName(rawStudent: any, mappedTranscript: any): string | null {
  return (
    firstNonEmpty(
      rawStudent?.file_name,
      rawStudent?.fileName,
      rawStudent?.source_file_name,
      rawStudent?.transcript_file_name,
      rawStudent?.original_file_name,
      mappedTranscript?.fileName,
      mappedTranscript?.file_name,
    ) ?? null
  );
}

function getDatabaseFinalCourses(rawStudent: any): any[] {
  const possibleCourseArrays = [
    rawStudent?.final_course_details,
    rawStudent?.final_courses,
    rawStudent?.courses,
  ];

  for (const value of possibleCourseArrays) {
    if (Array.isArray(value)) {
      return value;
    }
  }

  return [];
}
function getReconciliationSummary(rawStudent: any): ReconciliationSummary | null {
  const nested =
    rawStudent?.reconciliation_summary ||
    rawStudent?.course_reconciliation ||
    rawStudent?.course_validation ||
    rawStudent?.validation_result ||
    null;

  const summary: ReconciliationSummary = {
    status:
      rawStudent?.reconciliation_status ||
      rawStudent?.validation_status ||
      nested?.status ||
      rawStudent?.process_status ||
      rawStudent?.file_status ||
      null,

    validation_type:
      rawStudent?.validation_type ||
      nested?.validation_type ||
      'course_reconciliation',

    document_ai_course_count:
      rawStudent?.document_ai_course_count ??
      rawStudent?.raw_document_ai_course_count ??
      rawStudent?.course_details_count ??
      nested?.document_ai_course_count ??
      nested?.raw_document_ai_course_count ??
      nested?.course_details_count ??
      null,

    raw_document_ai_course_count:
      rawStudent?.raw_document_ai_course_count ??
      rawStudent?.document_ai_course_count ??
      rawStudent?.course_details_count ??
      nested?.raw_document_ai_course_count ??
      nested?.document_ai_course_count ??
      nested?.course_details_count ??
      null,

    course_details_count:
      rawStudent?.course_details_count ??
      nested?.course_details_count ??
      null,

    gemini_course_count:
      rawStudent?.gemini_course_count ??
      rawStudent?.raw_gemini_course_count ??
      rawStudent?.gemini_course_details_count ??
      nested?.gemini_course_count ??
      nested?.raw_gemini_course_count ??
      nested?.gemini_course_details_count ??
      null,

    raw_gemini_course_count:
      rawStudent?.raw_gemini_course_count ??
      rawStudent?.gemini_course_count ??
      rawStudent?.gemini_course_details_count ??
      nested?.raw_gemini_course_count ??
      nested?.gemini_course_count ??
      nested?.gemini_course_details_count ??
      null,

    gemini_course_details_count:
      rawStudent?.gemini_course_details_count ??
      nested?.gemini_course_details_count ??
      null,

    final_course_count:
      rawStudent?.final_course_count ??
      rawStudent?.actual_final_course_count ??
      rawStudent?.final_course_details_count ??
      nested?.final_course_count ??
      nested?.actual_final_course_count ??
      nested?.final_course_details_count ??
      null,

    actual_final_course_count:
      rawStudent?.actual_final_course_count ??
      rawStudent?.final_course_count ??
      rawStudent?.final_course_details_count ??
      nested?.actual_final_course_count ??
      nested?.final_course_count ??
      nested?.final_course_details_count ??
      null,

    final_course_details_count:
      rawStudent?.final_course_details_count ??
      rawStudent?.final_course_count ??
      nested?.final_course_details_count ??
      nested?.final_course_count ??
      null,

    expected_final_course_count:
      rawStudent?.expected_final_course_count ??
      nested?.expected_final_course_count ??
      null,

    course_count_difference:
      rawStudent?.course_count_difference ??
      nested?.course_count_difference ??
      null,

    final_count_shortfall:
      rawStudent?.final_count_shortfall ??
      nested?.final_count_shortfall ??
      null,

    counts_match:
      rawStudent?.counts_match ??
      nested?.counts_match ??
      null,

    matched_count:
      rawStudent?.matched_count ??
      rawStudent?.matched_course_count ??
      nested?.matched_count ??
      nested?.matched_course_count ??
      null,

    matched_course_count:
      rawStudent?.matched_course_count ??
      rawStudent?.matched_count ??
      nested?.matched_course_count ??
      nested?.matched_count ??
      null,

    document_ai_only_count:
      rawStudent?.document_ai_only_count ??
      nested?.document_ai_only_count ??
      null,

    gemini_only_count:
      rawStudent?.gemini_only_count ??
      nested?.gemini_only_count ??
      null,

    auto_fixed_count:
      rawStudent?.auto_fixed_count ??
      rawStudent?.auto_applied_count ??
      nested?.auto_fixed_count ??
      nested?.auto_applied_count ??
      null,

    auto_applied_count:
      rawStudent?.auto_applied_count ??
      nested?.auto_applied_count ??
      null,

    needs_review_count:
      rawStudent?.needs_review_count ??
      nested?.needs_review_count ??
      null,

    open_review_count:
      rawStudent?.open_review_count ??
      nested?.open_review_count ??
      null,

    review_reason_text:
      rawStudent?.review_reason_text ??
      nested?.review_reason_text ??
      null,

    review_reasons:
      rawStudent?.review_reasons ??
      nested?.review_reasons ??
      [],

    course_math_explanation:
      rawStudent?.course_math_explanation ??
      nested?.course_math_explanation ??
      null,

    model:
      rawStudent?.model ??
      nested?.model ??
      null,
  };

  const hasAnySummary =
    summary.status ||
    summary.document_ai_course_count !== null ||
    summary.raw_document_ai_course_count !== null ||
    summary.gemini_course_count !== null ||
    summary.raw_gemini_course_count !== null ||
    summary.final_course_count !== null ||
    summary.final_course_details_count !== null ||
    summary.auto_fixed_count !== null ||
    summary.needs_review_count !== null ||
    (summary.review_reasons?.length ?? 0) > 0;

  return hasAnySummary ? summary : null;
}

function isAutoFixedCourse(course: any): boolean {
  const decision = normalizeString(
    firstNonEmpty(
      course?.decision,
      course?.match_decision,
      course?.final_decision,
      course?.resolution,
      course?.auto_action,
      course?.match_type,
      course?.match_status,
    ),
  );

  if (course?.auto_fixed === true) return true;
  if (course?.auto_applied === true) return true;
  if (course?.changed_by_gemini === true) return true;

  const fieldSources = course?.field_sources || course?.source_summary || course?.field_decisions;

  if (fieldSources && typeof fieldSources === 'object') {
    const usedGemini = Object.values(fieldSources).some((value) =>
      String(value ?? '').toLowerCase().includes('gemini'),
    );

    if (usedGemini) return true;
  }

  return (
    decision.includes('auto') ||
    decision.includes('gemini') ||
    decision.includes('corrected') ||
    decision.includes('filled') ||
    decision.includes('accepted')
  );
}

function getAutoFixedFields(course: any): string[] {
  const explicit = firstNonEmpty(
    course?.gemini_corrected_fields,
    course?.gemini_fields_used,
    course?.auto_fixed_fields,
  );

  if (Array.isArray(explicit)) {
    return explicit.map((field) => String(field)).filter(Boolean);
  }

  const fieldSources = course?.field_sources || course?.source_summary || course?.field_decisions;

  if (!fieldSources || typeof fieldSources !== 'object') {
    return [];
  }

  return Object.entries(fieldSources)
    .filter(([, source]) => String(source ?? '').toLowerCase().includes('gemini'))
    .map(([field]) => field);
}

function getAutoFixedSummary(courses: any[]): string | null {
  const autoFixedRows = courses.filter(isAutoFixedCourse);

  if (!autoFixedRows.length) return null;

  const fields = new Set<string>();

  autoFixedRows.forEach((course) => {
    getAutoFixedFields(course).forEach((field) => fields.add(field));
  });

  if (!fields.size) {
    return `${autoFixedRows.length} row(s) adjusted`;
  }

  return `${autoFixedRows.length} row(s): ${Array.from(fields).slice(0, 4).join(', ')}`;
}

// Build a lookup so each mapped course can find its raw-metadata twin.
//
// CRITICAL: keys MUST be namespaced. `final_course_detail_id` and
// `course_extraction_match_id` are drawn from overlapping integer ranges, so a
// bare-string map would let one course's match-id (e.g. "54301") clobber a
// different course's final-id ("54301") — which silently merged the wrong row
// (e.g. Algebra rendered with an English course's id + UC mapping). Namespacing
// (`id:`, `match:`, `crs:`, `name:`) keeps those spaces from colliding. Unique
// id keys overwrite freely; ambiguous crs/name keys are first-wins so two
// rows that share a course id/title don't collapse onto each other.
function buildCourseMetadataLookup(rawCourses: any[]): Map<string, any> {
  const lookup = new Map<string, any>();

  rawCourses.forEach((course) => {
    const idKeys = [
      course?.id,
      course?.final_course_detail_id,
      course?.final_course_id,
      course?.course_detail_id,
    ];
    idKeys.forEach((v) => {
      if (v != null && String(v)) lookup.set(`id:${String(v)}`, course);
    });

    const ambiguous: [string, any][] = [
      ['match', course?.course_extraction_match_id ?? course?.match_id],
      ['crs', course?.crs_id ?? course?.course_id],
      ['name', course?.name ?? course?.course_name ?? course?.crs_description],
    ];
    ambiguous.forEach(([ns, v]) => {
      const key = v != null && String(v) ? `${ns}:${String(v)}` : '';
      if (key && !lookup.has(key)) lookup.set(key, course);
    });
  });

  return lookup;
}

function mergeMappedCoursesWithRawMetadata(mappedCourses: any[], rawCourses: any[]) {
  const lookup = buildCourseMetadataLookup(rawCourses);

  if (!mappedCourses.length) {
    return rawCourses.map((course) => ({
      ...course,
      source_label:
        course.source_label ??
        course.extraction_source ??
        course.source ??
        'Final',
    }));
  }

  return mappedCourses.map((course) => {
    // Probe id-namespace first (unique, collision-free), then fall back to the
    // ambiguous keys. Must mirror buildCourseMetadataLookup's namespacing.
    const possibleKeys = [
      course?.id,
      course?.final_course_detail_id,
      course?.final_course_id,
      course?.course_detail_id,
    ]
      .map((v) => (v != null && String(v) ? `id:${String(v)}` : ''))
      .concat([
        course?.course_extraction_match_id != null || course?.match_id != null
          ? `match:${String(course?.course_extraction_match_id ?? course?.match_id)}`
          : '',
        course?.crs_id || course?.course_id
          ? `crs:${String(course?.crs_id ?? course?.course_id)}`
          : '',
        course?.name || course?.course_name || course?.crs_description
          ? `name:${String(course?.name ?? course?.course_name ?? course?.crs_description)}`
          : '',
      ])
      .filter(Boolean);

    const rawCourse =
      possibleKeys.map((key) => lookup.get(key)).find(Boolean) ?? null;

    if (!rawCourse) {
      return {
        ...course,
        source_label:
          course.source_label ??
          course.extraction_source ??
          course.source ??
          'Final',
        changed_by_gemini: course.changed_by_gemini ?? isAutoFixedCourse(course),
        gemini_corrected_fields:
          course.gemini_corrected_fields ?? getAutoFixedFields(course),
      };
    }

    const changedByGemini =
      Boolean(course.changed_by_gemini) ||
      Boolean(rawCourse.changed_by_gemini) ||
      isAutoFixedCourse(course) ||
      isAutoFixedCourse(rawCourse);

    const correctedFields = firstNonEmpty(
      course.gemini_corrected_fields,
      rawCourse.gemini_corrected_fields,
      course.gemini_fields_used,
      rawCourse.gemini_fields_used,
      getAutoFixedFields(rawCourse),
      getAutoFixedFields(course),
    );

    return {
      ...course,
      ...rawCourse,

      id: course.id ?? rawCourse.id,
      name:
        course.name ??
        course.course_name ??
        rawCourse.name ??
        rawCourse.course_name ??
        rawCourse.crs_description,
      grade:
        course.grade ??
        course.letter_grade ??
        rawCourse.grade ??
        rawCourse.letter_grade ??
        rawCourse.crs_letter_grade,

      credits:
        course.credits ??
        rawCourse.credits ??
        rawCourse.credits_completed ??
        rawCourse.credit_completed ??
        rawCourse.crs_credit_completed ??
        rawCourse.credits_attempted ??
        rawCourse.credit_attempted ??
        rawCourse.crs_credit_attempted,

      credits_completed:
        course.credits_completed ??
        rawCourse.credits_completed ??
        rawCourse.credit_completed ??
        rawCourse.crs_credit_completed,

      credits_attempted:
        course.credits_attempted ??
        rawCourse.credits_attempted ??
        rawCourse.credit_attempted ??
        rawCourse.crs_credit_attempted,

      grade_level:
        course.grade_level ??
        course.crs_grade ??
        rawCourse.grade_level ??
        rawCourse.crs_grade,

      crs_grade:
        course.crs_grade ??
        course.grade_level ??
        rawCourse.crs_grade ??
        rawCourse.grade_level,

      year:
        course.year ??
        course.crs_year ??
        rawCourse.year ??
        rawCourse.crs_year,

      crs_year:
        course.crs_year ??
        course.year ??
        rawCourse.crs_year ??
        rawCourse.year,

      month:
        course.month ??
        course.crs_month ??
        rawCourse.month ??
        rawCourse.crs_month,

      crs_month:
        course.crs_month ??
        course.month ??
        rawCourse.crs_month ??
        rawCourse.month,

      source_label:
        course.source_label ??
        rawCourse.source_label ??
        rawCourse.extraction_source ??
        rawCourse.source ??
        'Final',

      changed_by_gemini: changedByGemini,
      gemini_corrected_fields: correctedFields,
      field_sources:
        course.field_sources ??
        rawCourse.field_sources ??
        rawCourse.source_summary ??
        rawCourse.field_decisions ??
        null,

      document_ai_course_detail_id:
        course.document_ai_course_detail_id ??
        rawCourse.document_ai_course_detail_id ??
        rawCourse.doc_ai_course_detail_id ??
        null,

      gemini_course_detail_id:
        course.gemini_course_detail_id ??
        rawCourse.gemini_course_detail_id ??
        null,

      course_extraction_match_id:
        course.course_extraction_match_id ??
        rawCourse.course_extraction_match_id ??
        rawCourse.match_id ??
        null,

      needs_review:
        course.needs_review ??
        rawCourse.needs_review ??
        false,

      review_reason:
        course.review_reason ??
        rawCourse.review_reason ??
        null,

      decision:
        course.decision ??
        rawCourse.decision ??
        null,

      match_type:
        course.match_type ??
        rawCourse.match_type ??
        rawCourse.match_status ??
        null,

      match_score:
        course.match_score ??
        rawCourse.match_score ??
        null,
    };
  });
}

// The actual high school — distinct from `format` (which extractor was used).
// Prefer explicit fields from the record, else parse it from the file name
// (e.g. "Aguilar, Manuel_CABRILLO HIGH SCHOOL.pdf" → "Cabrillo High School").
function schoolFromFileName(fileName?: string | null): string {
  const base = String(fileName ?? '').replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  const raw = idx > 0 && idx < base.length - 1 ? base.slice(idx + 1).trim() : '';
  if (!raw) return '';
  const up = raw.toUpperCase();
  if (up === 'LBUSD' || up === 'CAMS') return up;
  return raw.replace(/\b\w/g, (c) => c.toUpperCase());
}

function resolveSchool(rawStudent: any, fileName?: string | null): string {
  return (
    rawStudent?.final_school ||
    rawStudent?.school ||
    rawStudent?.school_name ||
    schoolFromFileName(fileName) ||
    ''
  );
}

function buildCompletedTranscript(
  rawStudent: any,
  index: number,
): CompletedTranscriptRecord {
  const mapped = mapStudentToTranscriptRecord(
    rawStudent,
    'completed',
  ) as CompletedTranscriptRecord;

  const rawCourses = getDatabaseFinalCourses(rawStudent);
  const mappedCourses = Array.isArray(mapped?.courses) ? mapped.courses : [];
  const mergedCourses = mergeMappedCoursesWithRawMetadata(mappedCourses, rawCourses);

  const reconciliation = getReconciliationSummary(rawStudent);
  const autoFixedCount =
    reconciliation?.auto_fixed_count ??
    reconciliation?.auto_applied_count ??
    mergedCourses.filter(isAutoFixedCourse).length;

  const needsReviewCount =
    reconciliation?.needs_review_count ??
    reconciliation?.open_review_count ??
    mergedCourses.filter((course) => course?.needs_review === true).length;

  const finalCourseCount =
    reconciliation?.final_course_count ??
    reconciliation?.actual_final_course_count ??
    reconciliation?.final_course_details_count ??
    mergedCourses.length ??
    rawCourses.length;

  const rowKey = String(
    firstNonEmpty(
      rawStudent?.db_id,
      mapped?.db_id,
      rawStudent?.source_file,
      mapped?.sourceFile,
      rawStudent?.id,
      mapped?.id,
      rawStudent?.student_id,
      index,
    ),
  );

  return {
    ...mapped,
    id: rowKey,
    rowKey,
    serial: index + 1,
    status:
      mapped.status ||
      rawStudent?.process_status ||
      rawStudent?.file_status ||
      reconciliation?.status ||
      'completed',
    fileName: getFileName(rawStudent, mapped),
    school: resolveSchool(rawStudent, getFileName(rawStudent, mapped)),
    sourceFile: mapped.sourceFile ?? rawStudent?.source_file ?? undefined,
    courses: mergedCourses,
    courseCount: finalCourseCount ?? mergedCourses.length,
    finalCourseCount,
    documentAiRawCount:
      reconciliation?.raw_document_ai_course_count ??
      reconciliation?.document_ai_course_count ??
      null,
    geminiRawCount:
      reconciliation?.raw_gemini_course_count ??
      reconciliation?.gemini_course_count ??
      null,
    autoFixedCount,
    needsReviewCount,
    hasAutoFixedCourses: Boolean(autoFixedCount && autoFixedCount > 0),
    autoFixedSummary: getAutoFixedSummary(mergedCourses),
    reconciliation,
    validation_result: rawStudent?.validation_result ?? reconciliation ?? mapped.validation_result,
    course_validation: rawStudent?.course_validation ?? reconciliation ?? mapped.course_validation,
    validation_status:
      rawStudent?.validation_status ??
      reconciliation?.status ??
      rawStudent?.process_status ??
      rawStudent?.file_status ??
      mapped.validation_status,
  };
}

export default function ExtractorCompleted({ embedded = false }: { embedded?: boolean }) {
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [active, setActive] = useState<TranscriptRecord | null>(null);
  const [initialTab, setInitialTab] = useState<CompletedInitialTab>('personal');

  const { currentTerm, terms } = useTerm();

  const termName = terms.find((term) => term.id === currentTerm)?.term_name;

  const { data: rawStudents, refreshing } = useStaleData(
    `completed:${termName ?? ''}`,
    () => fetchCompletedStudents(termName),
    [termName],
    { refreshIntervalMs: 8000 },
  );

  const transcripts = useMemo<CompletedTranscriptRecord[]>(() => {
    if (!rawStudents) return [];

    return rawStudents
      .map((student: any, index: number) => buildCompletedTranscript(student, index))
      .filter(
        (transcript) =>
          transcript.studentName ||
          transcript.fileName ||
          (transcript.courses && transcript.courses.length),
      );
  }, [rawStudents]);

  // Search/sort/filter are handled by StandardTable; feed it the full list.

  const openDetail = useCallback(
    (rowKey: string, tab: CompletedInitialTab = 'personal') => {
      const transcript = transcripts.find((item) => item.rowKey === rowKey) || null;

      // Open immediately with the slim row; the list payload has no courses.
      setActive(transcript);
      setOpenKey(rowKey);
      setInitialTab(tab);

      // Fetch the full student (courses + reconciliation) on demand and merge it
      // in, keeping the row's identity (rowKey/serial).
      const dbId = transcript?.db_id;
      if (dbId == null) return;
      fetchStudentDetail(dbId)
        .then((full) => {
          const rebuilt = buildCompletedTranscript(full as any, 0);
          setActive((prev) =>
            prev && prev.rowKey === rowKey
              ? { ...rebuilt, rowKey: prev.rowKey, serial: prev.serial }
              : prev,
          );
        })
        .catch(() => {
          /* keep the slim view if the on-demand fetch fails */
        });
    },
    [transcripts],
  );

  const columns: StdColumn<CompletedTranscriptRecord>[] = useMemo(
    () => [
      {
        key: 'student',
        header: 'Student',
        value: (r) => r.studentName || `Unknown Student ${r.studentId ?? r.id}`,
        cell: (r) => {
          const name = r.studentName || `Unknown Student ${r.studentId ?? r.id}`;
          return (
            <div className="flex items-center gap-3">
              <Avatar name={name} />
              <div className="min-w-0">
                <div className="truncate font-semibold text-slate-900" title={name}>
                  {name}
                </div>
                <div className="truncate text-xs text-slate-400" title={String(r.studentId ?? r.id ?? '')}>
                  {r.studentId ?? r.id ?? '—'}
                  {r.processedAt ? ` · ${formatDateTimePST(new Date(r.processedAt))}` : ''}
                </div>
              </div>
            </div>
          );
        },
      },
      {
        key: 'school',
        header: 'School',
        value: (r) => r.school ?? '',
        cell: (r) => (
          <span className="block truncate text-slate-600" title={String(r.school ?? '')}>
            {r.school || '—'}
          </span>
        ),
      },
      {
        key: 'format',
        header: 'Format',
        value: (r) => resolveFormat(r.school, (r as any).format),
        filterable: true,
        cell: (r) => {
          const fmt = resolveFormat(r.school, (r as any).format);
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
        key: 'view',
        header: 'View',
        align: 'center',
        width: 80,
        sortable: false,
        cell: (r) => (
          <IconButton tooltip="View transcript details" onClick={() => openDetail(r.rowKey, 'personal')}>
            <Eye className="h-4 w-4" />
          </IconButton>
        ),
      },
    ],
    [openDetail],
  );

  return (
    <div className="w-full min-w-0 max-w-full overflow-hidden">
      <div className="w-full min-w-0 max-w-full space-y-6 overflow-hidden">
        {!embedded && (
          <PageHeader
            title="Completed"
            subtitle="Final reconciled transcript rows ready for downstream review"
          />
        )}

        {refreshing && transcripts.length === 0 ? (
          <div className="rounded-md border p-4 text-sm text-muted-foreground">
            Loading completed transcripts...
          </div>
        ) : (
          <StandardTable
            columns={columns}
            data={transcripts}
            rowKey={(r) => r.rowKey}
            flagId={(r) => r.rowKey}
            search
            searchPlaceholder="Search by name, ID, school, or file…"
            storageKey="extract:completed"
            emptyMessage="No completed transcripts found."
          />
        )}

        <TranscriptDetailDialog
          open={!!openKey}
          onOpenChange={(open) => {
            if (!open) {
              setOpenKey(null);
              setActive(null);
            }
          }}
          transcript={active}
          initialTab={initialTab}
        />
      </div>
    </div>
  );
}