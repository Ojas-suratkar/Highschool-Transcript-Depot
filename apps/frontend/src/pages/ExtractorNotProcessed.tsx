import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CheckCircle2,
  ChevronDown,
  X,
  Eye,
  FileSearch,
  Plus,
  UserRound,
  RotateCcw,
  Save,
  Trash2,
  Undo2,
} from 'lucide-react';
import { toast } from 'sonner';

import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Avatar } from '@/components/shared/Avatar';
import { StandardTable } from '@/components/shared/StandardTable';
import type { StdColumn } from '@/components/shared/StandardTable';
import { emitNotification } from '@/lib/notify';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import {
  completeExtractionFile,
  createStudentForFile,
  fetchAuditReviewStudents,
  fetchStudentDetail,
  getTranscriptPdfUrl,
  rerunFile,
  reviewFinalCourse,
  updateStudentAndCourses,
} from '@/lib/api/extractor';
import type {
  FinalCourseDetail,
  ReviewStudentCoursePayload,
  ReviewStudentPayload,
  StudentWithCourses,
} from '@/lib/api/extractor';
import { useTerm } from '@/contexts/TermContext';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';
import { listCloudFolders } from '@/lib/api/cloudFolders';
import { useStaleData } from '@/lib/useStaleData';

type AuditRow = {
  id: string;
  fileId: number;
  studentDbId: number | string | null;
  studentName: string;
  fileName: string;
  schoolName: string;
  formatName: string;
  courseCount: number;
  status: string | null;
  reviewReason?: string | null;
  source: StudentWithCourses;
};

type EditableCourse = ReviewStudentCoursePayload & {
  localKey: string;
  removed?: boolean;
};

type AuditDraft = {
  studentId: number | string | '';
  studentName: string;
  schoolName: string;
  address: string;
  phoneNumber: string;
  gender: string;
  birthDate: string;
  stateId: number | string | '';
  counselorName: string;
  currentGradeLevel: number | string | '';
  totalUnitsEarned: number | string | '';
  enterDate: string;
  graduationDate: string;
  gpa: number | string | '';
  academicGpa: number | string | '';
  universityGpa: number | string | '';
  courses: EditableCourse[];
};

const inputClassName =
  'h-9 w-full rounded-md border border-slate-200 bg-white px-3 text-sm text-slate-800 outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100';

/**
 * File 2 now accepts `?light=true` for Gemini-only Save Review requests.
 *
 * Keep this cast local so this TSX continues to compile even before the API
 * helper file is updated with the optional third argument. JavaScript safely
 * ignores an extra argument until file 4 starts forwarding it.
 */
const updateStudentAndCoursesFast = updateStudentAndCourses as unknown as (
  studentId: number | string,
  payload: ReviewStudentPayload,
  light?: boolean,
) => Promise<StudentWithCourses>;

function toText(value: unknown): string {
  return value === null || value === undefined ? '' : String(value);
}

function newLocalKey(): string {
  return `new-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function getStudentDbId(student: StudentWithCourses): number | string | null {
  return student.db_id ?? student.id ?? null;
}

function getCourseRows(student: StudentWithCourses | null): FinalCourseDetail[] {
  if (!student) return [];

  return (
    student.courses ??
    student.final_courses ??
    student.final_course_details ??
    student.trusted_courses ??
    []
  );
}

function getCourseNumericIds(course: {
  id?: unknown;
  final_course_id?: unknown;
  final_course_detail_id?: unknown;
  new_transcript_course_id?: unknown;
}): number[] {
  return [
    course.id,
    course.final_course_id,
    course.final_course_detail_id,
    course.new_transcript_course_id,
  ]
    .map((value) => Number(value))
    .filter((value) => Number.isFinite(value) && value !== 0);
}

function sameCourse(
  apiCourse: FinalCourseDetail,
  editableCourse: EditableCourse,
): boolean {
  const apiIds = new Set(getCourseNumericIds(apiCourse));
  const editableIds = getCourseNumericIds(editableCourse);

  if (editableIds.some((id) => apiIds.has(id))) {
    return true;
  }

  // Unsaved rows do not have a DB ID yet. They are handled by Save Review,
  // so do not guess a match based only on course name/grade/year.
  return false;
}

function patchStudentCourseReviewed(
  student: StudentWithCourses,
  editableCourse: EditableCourse,
): StudentWithCourses {
  const patchRows = (
    rows: FinalCourseDetail[] | undefined,
  ): FinalCourseDetail[] | undefined =>
    rows?.map((row) =>
      sameCourse(row, editableCourse)
        ? ({
            ...row,
            reviewed_by_user: true,
            reviewed: true,
            mark_reviewed: true,
            needs_review: false,
            review_status: 'reviewed',
          } as FinalCourseDetail)
        : row,
    );

  return {
    ...student,
    courses: patchRows(student.courses),
    final_courses: patchRows(student.final_courses),
    final_course_details: patchRows(student.final_course_details),
    trusted_courses: patchRows(student.trusted_courses),
  } as StudentWithCourses;
}

function mapStudentsToRows(students: StudentWithCourses[]): AuditRow[] {
  return students
    .filter((student) => {
      const isNewTranscript =
        student.is_new_transcript_type === true ||
        student.storage_source === 'new_transcript_tables' ||
        student.validation_type === 'gemini_only_new_transcript';
      const fileId = Number(student.source_file);

      return isNewTranscript && Number.isInteger(fileId) && fileId > 0;
    })
    .map((student) => {
      const fileId = Number(student.source_file);
      const studentDbId = getStudentDbId(student);
      const loadedCourseCount = getCourseRows(student).length;
      const reportedCourseCount =
        student.final_course_count ?? student.gemini_course_count;
      const courseCount =
        loadedCourseCount > 0
          ? loadedCourseCount
          : Number(reportedCourseCount ?? 0);

      return {
        id: `${fileId}:${String(studentDbId ?? 'file-only')}`,
        fileId,
        studentDbId,
        studentName: student.student_name || student.file_name || 'Unknown Student',
        fileName: student.file_name || `File ${fileId}`,
        schoolName: student.school_name || student.format || 'Unknown School',
        formatName:
          student.format ||
          student.validation_type ||
          'Gemini-only',
        courseCount,
        status:
          student.process_status ||
          student.file_status ||
          student.effective_status ||
          'needs_review_audit',
        reviewReason: student.review_reason_text || student.review_reason || null,
        source: student,
      };
    });
}

function toFiniteNumber(value: unknown): number | undefined {
  if (value === null || value === undefined || value === '') return undefined;

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function hasRequiredText(value: unknown): boolean {
  const normalized = String(value ?? '').trim().toLowerCase();

  return (
    normalized.length > 0 &&
    ![
      'unknown',
      'unknown student',
      'student unknown',
      'unknown school',
      'school unknown',
      'unknown course',
      'course unknown',
      'not available',
      'unavailable',
      'n/a',
      'na',
      'none',
      '-',
      '--',
    ].includes(normalized)
  );
}

function getMissingCourseFields(course: EditableCourse): string[] {
  const missing: string[] = [];

  const courseName = course.course_name || course.name;
  const grade = course.grade || course.letter_grade;
  const school = course.school || course.school_name;
  const gradeLevel = toFiniteNumber(course.grade_level);
  const year = toFiniteNumber(course.year);
  const credits =
    toFiniteNumber(course.credits_completed) ??
    toFiniteNumber(course.credits_attempted);

  if (!hasRequiredText(courseName)) missing.push('Course Name');
  if (!hasRequiredText(grade)) missing.push('Grade');
  if (!hasRequiredText(school)) missing.push('School');
  if (gradeLevel === undefined) missing.push('Grade Yr');
  if (year === undefined) missing.push('Year');
  if (credits === undefined) missing.push('Credits');

  // Course ID and Month are intentionally optional for new transcript layouts.
  return missing;
}

function formatMissingFieldsForUser(fields: string[]): string {
  if (fields.length === 0) return '';
  if (fields.length === 1) return fields[0];
  if (fields.length === 2) return `${fields[0]} and ${fields[1]}`;

  return `${fields.slice(0, -1).join(', ')}, and ${fields[fields.length - 1]}`;
}

function getReadableApiErrorMessage(
  error: any,
  fallback: string,
): string {
  const inspect = (value: unknown): string | null => {
    if (!value) return null;

    if (typeof value === 'object') {
      const objectValue = value as Record<string, unknown>;
      return (
        inspect(objectValue.message) ||
        inspect(objectValue.detail) ||
        null
      );
    }

    if (typeof value !== 'string') return null;

    const trimmed = value.trim();
    if (!trimmed) return null;

    if (
      (trimmed.startsWith('{') && trimmed.endsWith('}')) ||
      (trimmed.startsWith('[') && trimmed.endsWith(']'))
    ) {
      try {
        return inspect(JSON.parse(trimmed)) || trimmed;
      } catch {
        return trimmed;
      }
    }

    return trimmed;
  };

  return (
    inspect(error?.detail) ||
    inspect(error?.message) ||
    inspect(error) ||
    fallback
  );
}

function buildDraft(student: StudentWithCourses): AuditDraft {
  const courses = getCourseRows(student).map((course, index) => {
    const publicId = toFiniteNumber(course.id);
    const finalCourseId = toFiniteNumber(course.final_course_id);
    const finalCourseDetailId =
      toFiniteNumber(course.final_course_detail_id) ??
      finalCourseId ??
      publicId;

    return {
    id: publicId,
    final_course_id: finalCourseId,
    final_course_detail_id: finalCourseDetailId,
    new_transcript_course_id:
      course.new_transcript_course_id === null ||
      course.new_transcript_course_id === undefined
        ? undefined
        : Number(course.new_transcript_course_id),
    is_new_transcript_type: true,
    storage_source: 'new_transcript_course_details',
    course_id: toText(course.course_id ?? course.crs_id),
    crs_id: toText(course.crs_id ?? course.course_id),
    course_name: toText(course.course_name ?? course.name ?? course.crs_description),
    name: toText(course.name ?? course.course_name ?? course.crs_description),
    grade: toText(course.grade ?? course.letter_grade ?? course.crs_letter_grade),
    letter_grade: toText(course.letter_grade ?? course.grade ?? course.crs_letter_grade),
    credits_attempted: toText(
      course.credits_attempted ?? course.credit_attempted ?? course.crs_credit_attempted,
    ),
    credits_completed: toText(
      course.credits_completed ??
        course.credit_completed ??
        course.crs_credit_completed ??
        course.credits,
    ),
    grade_level: toText(course.grade_level ?? course.crs_grade),
    month: toText(course.month ?? course.crs_month),
    year: toText(course.year ?? course.crs_year),
    school: toText(course.school ?? course.school_name ?? course.crs_hs),
    school_name: toText(course.school_name ?? course.school ?? course.crs_hs),
    term_gpa: toText(course.term_gpa ?? course.crs_term_gpa),
    reviewed_by_user: Boolean(
      course.reviewed_by_user ??
        course.reviewed ??
        course.review_status === 'reviewed',
    ),
    mark_reviewed: Boolean(
      course.reviewed_by_user ??
        course.reviewed ??
        course.review_status === 'reviewed',
    ),
    review_status:
      course.review_status ??
      (course.reviewed_by_user || course.reviewed ? 'reviewed' : 'needs_review'),
    needs_review: !Boolean(
      course.reviewed_by_user ??
        course.reviewed ??
        course.review_status === 'reviewed',
    ),
    localKey: `course-${String(course.id ?? index)}`,
    };
  });

  return {
    studentId: student.student_id ?? '',
    studentName: student.student_name ?? '',
    schoolName: student.school_name ?? student.format ?? '',
    address: student.address ?? '',
    phoneNumber: toText(student.phone_number),
    gender: toText(student.gender),
    birthDate: student.birth_date ?? '',
    stateId: toText(student.state_id),
    counselorName: toText(student.counselor_name),
    currentGradeLevel: toText(
      student.grade_level ?? student.current_grade_level,
    ),
    totalUnitsEarned: toText(student.total_units_earned),
    enterDate: toText(student.enter_date),
    graduationDate: student.graduation_date ?? '',
    gpa: student.gpa ?? '',
    academicGpa: toText(student.academic_gpa),
    universityGpa: toText(student.university_gpa),
    courses,
  };
}

function Field({
  label,
  value,
  onChange,
  type = 'text',
  placeholder,
}: {
  label: string;
  value: string | number;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="space-y-1.5">
      <span className="block text-xs font-medium text-slate-600">{label}</span>
      <input
        className={inputClassName}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event: { target: { value: string } }) =>
          onChange(event.target.value)
        }
      />
    </label>
  );
}

function AutoGrowTextArea({
  value,
  onChange,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  ariaLabel: string;
}) {
  const textAreaRef = useRef<HTMLTextAreaElement | null>(null);

  useEffect(() => {
    const element = textAreaRef.current;
    if (!element) return;

    element.style.height = '0px';
    element.style.height = `${Math.max(38, element.scrollHeight)}px`;
  }, [value]);

  return (
    <textarea
      ref={textAreaRef}
      aria-label={ariaLabel}
      rows={1}
      value={value}
      title={value}
      className={`${inputClassName} h-auto min-h-9 resize-none overflow-hidden whitespace-pre-wrap break-words py-2 leading-4`}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

export default function ExtractorNotProcessed({
  embedded = false,
}: {
  embedded?: boolean;
}) {
  const [preview, setPreview] = useState<{
    open: boolean;
    label?: string;
    url?: string;
  }>({ open: false });
  const [rerunning, setRerunning] = useState<Record<string, boolean>>({});
  const [refreshSeed, setRefreshSeed] = useState(0);
  const [selectedTranscriptFileIds, setSelectedTranscriptFileIds] = useState<
    Set<number>
  >(new Set());
  const [startingSelectedReextract, setStartingSelectedReextract] =
    useState(false);

  const [selectedRow, setSelectedRow] = useState<AuditRow | null>(null);
  const [selectedDetail, setSelectedDetail] = useState<StudentWithCourses | null>(null);
  const [draft, setDraft] = useState<AuditDraft | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [saving, setSaving] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [creatingStudent, setCreatingStudent] = useState(false);
  const [reviewingCourseKeys, setReviewingCourseKeys] = useState<Set<string>>(
    new Set(),
  );
  const [selectedCourseKeys, setSelectedCourseKeys] = useState<Set<string>>(
    new Set(),
  );
  const [courseFilter, setCourseFilter] = useState<
    'needs_review' | 'reviewed' | 'all'
  >('needs_review');

  const detailRequestSequence = useRef(0);
  const detailCacheRef = useRef<Map<string, StudentWithCourses>>(new Map());
  const detailRequestCacheRef = useRef<
    Map<string, Promise<StudentWithCourses>>
  >(new Map());
  const coursePaneRef = useRef<HTMLDivElement | null>(null);

  const { currentTerm, terms } = useTerm();
  const termName = terms.find((term) => term.id === currentTerm)?.term_name;
  const { startJob, isFolderExtracting } = useExtractionJobs();

  const { data: rawStudents, refreshing } = useStaleData<StudentWithCourses[]>(
    `human-review-audit:${termName ?? ''}:${refreshSeed}`,
    () => fetchAuditReviewStudents(termName),
    [termName, refreshSeed],
  );

  const rows = useMemo(
    () => mapStudentsToRows(rawStudents ?? []),
    [rawStudents],
  );

  const visibleCourses = useMemo(
    () => draft?.courses.filter((course) => !course.removed) ?? [],
    [draft],
  );

  const filteredCourses = useMemo(() => {
    if (courseFilter === 'reviewed') {
      return visibleCourses.filter((course) => Boolean(course.reviewed_by_user));
    }

    if (courseFilter === 'all') {
      return visibleCourses;
    }

    return visibleCourses.filter((course) => !Boolean(course.reviewed_by_user));
  }, [courseFilter, visibleCourses]);

  const removedCourses = useMemo(
    () => draft?.courses.filter((course) => course.removed) ?? [],
    [draft],
  );

  const reviewedCourseCount = useMemo(
    () =>
      visibleCourses.filter((course) => Boolean(course.reviewed_by_user)).length,
    [visibleCourses],
  );

  const unreviewedCourseCount = Math.max(
    visibleCourses.length - reviewedCourseCount,
    0,
  );

  const incompleteCourseIssues = useMemo(
    () =>
      visibleCourses
        .map((course, index) => ({
          index,
          course,
          missing: getMissingCourseFields(course),
        }))
        .filter((item) => item.missing.length > 0),
    [visibleCourses],
  );

  const incompleteCourseCount = incompleteCourseIssues.length;

  const studentMissingRequiredFields = useMemo(() => {
    if (!draft) return [] as string[];

    const missing: string[] = [];
    if (!hasRequiredText(draft.studentName)) missing.push('Student Name');
    if (!hasRequiredText(draft.schoolName)) missing.push('School');
    return missing;
  }, [draft]);

  const refreshPage = () => setRefreshSeed((value) => value + 1);

  useEffect(() => {
    const currentFileIds = new Set(rows.map((row) => row.fileId));

    setSelectedTranscriptFileIds((current) => {
      const next = new Set(
        Array.from(current).filter((fileId) => currentFileIds.has(fileId)),
      );

      if (
        next.size === current.size &&
        Array.from(next).every((fileId) => current.has(fileId))
      ) {
        return current;
      }

      return next;
    });
  }, [rows]);

  const allVisibleTranscriptsSelected =
    rows.length > 0 &&
    rows.every((row) => selectedTranscriptFileIds.has(row.fileId));

  const toggleTranscriptSelection = (fileId: number) => {
    setSelectedTranscriptFileIds((current) => {
      const next = new Set(current);

      if (next.has(fileId)) {
        next.delete(fileId);
      } else {
        next.add(fileId);
      }

      return next;
    });
  };

  const toggleAllTranscripts = () => {
    setSelectedTranscriptFileIds((current) => {
      if (
        rows.length > 0 &&
        rows.every((row) => current.has(row.fileId))
      ) {
        return new Set();
      }

      return new Set(rows.map((row) => row.fileId));
    });
  };

  const handleReextractSelectedTranscripts = async () => {
    const selectedFileIds = Array.from(selectedTranscriptFileIds);

    if (selectedFileIds.length === 0) {
      toast.info('Select at least one transcript to re-extract.');
      return;
    }

    if (!termName) {
      toast.error('Select a term before starting re-extraction.');
      return;
    }

    setStartingSelectedReextract(true);

    try {
      const folders = await listCloudFolders(termName);
      const folder =
        folders.find((item) => item.year_intake === termName) ??
        folders[0];

      if (!folder) {
        throw new Error(
          `No extraction folder was found for ${termName}.`,
        );
      }

      if (isFolderExtracting(folder.id)) {
        throw new Error(
          `An extraction job is already running for ${termName}. Stop or wait for it before starting another re-extraction.`,
        );
      }

      await startJob({
        id: folder.id,
        label: folder.label,
        termName,
        forceReextract: true,
        selectedFileIds,
      });

      toast.success(
        `Started re-extraction for ${selectedFileIds.length} selected transcript${
          selectedFileIds.length === 1 ? '' : 's'
        }.`,
      );

      emitNotification({
        kind: 'info',
        title: 'Selected re-extraction started',
        message: `${selectedFileIds.length} transcript${
          selectedFileIds.length === 1 ? '' : 's'
        } selected in ${termName}.`,
        term: termName,
      });

      setSelectedTranscriptFileIds(new Set());
    } catch (error: any) {
      toast.error(
        error?.message || 'Unable to start selected transcript re-extraction',
      );
    } finally {
      setStartingSelectedReextract(false);
    }
  };

  const closeAuditModal = () => {
    detailRequestSequence.current += 1;
    setSelectedRow(null);
    setSelectedDetail(null);
    setDraft(null);
    setSelectedCourseKeys(new Set());
    setCourseFilter('needs_review');
    setReviewingCourseKeys(new Set());
    setLoadingDetail(false);
  };

  useEffect(() => {
    if (!selectedRow) return undefined;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !saving && !completing) {
        closeAuditModal();
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [selectedRow, saving, completing]);

  const getOrFetchStudentDetail = (
    studentDbId: number | string,
  ): Promise<StudentWithCourses> => {
    const cacheKey = String(studentDbId);
    const cached = detailCacheRef.current.get(cacheKey);

    if (cached) {
      return Promise.resolve(cached);
    }

    const existingRequest = detailRequestCacheRef.current.get(cacheKey);
    if (existingRequest) {
      return existingRequest;
    }

    const request = fetchStudentDetail(studentDbId)
      .then((detail) => {
        detailCacheRef.current.set(cacheKey, detail);
        return detail;
      })
      .finally(() => {
        detailRequestCacheRef.current.delete(cacheKey);
      });

    detailRequestCacheRef.current.set(cacheKey, request);
    return request;
  };

  // Start loading detail rows quietly after the selected-year audit list
  // appears. With the small audit list this makes Review open almost instantly,
  // while keeping the initial table responsive.
  useEffect(() => {
    let cancelled = false;

    const candidates = rows
      .filter((row) => row.studentDbId !== null)
      .filter((row) => getCourseRows(row.source).length === 0)
      .filter(
        (row) =>
          !detailCacheRef.current.has(String(row.studentDbId)),
      );

    const prefetch = async () => {
      const queue = [...candidates];
      const workerCount = Math.min(4, queue.length);

      const workers = Array.from(
        { length: workerCount },
        async () => {
          while (!cancelled) {
            const nextRow = queue.shift();
            if (!nextRow || nextRow.studentDbId === null) return;

            try {
              await getOrFetchStudentDetail(nextRow.studentDbId);
            } catch {
              // Review click will retry and show the normal user-facing error.
            }
          }
        },
      );

      await Promise.allSettled(workers);
    };

    void prefetch();

    return () => {
      cancelled = true;
    };
  }, [rows]);

  useEffect(() => {
    const refreshVisibleData = () => refreshPage();
    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') {
        refreshVisibleData();
      }
    };

    window.addEventListener('focus', refreshVisibleData);
    window.addEventListener(
      'transcript-extraction-complete',
      refreshVisibleData as EventListener,
    );
    document.addEventListener('visibilitychange', refreshWhenVisible);

    return () => {
      window.removeEventListener('focus', refreshVisibleData);
      window.removeEventListener(
        'transcript-extraction-complete',
        refreshVisibleData as EventListener,
      );
      document.removeEventListener('visibilitychange', refreshWhenVisible);
    };
  }, [termName]);

  useEffect(() => {
    window.dispatchEvent(
      new CustomEvent('extract-audit-count-updated', {
        detail: {
          termName: termName ?? null,
          count: rows.length,
        },
      }),
    );
  }, [rows.length, termName]);

  const handleRerun = async (row: AuditRow) => {
    setRerunning((previous) => ({ ...previous, [row.id]: true }));

    try {
      const result = await rerunFile(row.fileId);
      toast.success(
        `Re-run complete: ${result.students} student(s), ${result.courses} course(s) extracted.`,
      );
      emitNotification({
        kind: 'success',
        title: 'Re-run complete',
        message: `${row.fileName || `File ${row.fileId}`} · ${result.students} student(s), ${result.courses} course(s)`,
      });

      detailCacheRef.current.delete(String(row.studentDbId ?? ''));
      detailRequestCacheRef.current.delete(String(row.studentDbId ?? ''));

      if (selectedRow?.id === row.id) {
        closeAuditModal();
      }

      refreshPage();
    } catch (error: any) {
      toast.error(error?.message || 'Re-run failed');
    } finally {
      setRerunning((previous) => ({ ...previous, [row.id]: false }));
    }
  };

  const handleOpenAudit = async (row: AuditRow) => {
    const requestSequence = detailRequestSequence.current + 1;
    detailRequestSequence.current = requestSequence;

    setSelectedRow(row);
    setSelectedCourseKeys(new Set());
    setCourseFilter('needs_review');

    if (row.studentDbId === null) {
      setSelectedDetail(null);
      setDraft(null);
      setLoadingDetail(false);
      return;
    }

    const cacheKey = String(row.studentDbId);
    const immediateDetail =
      detailCacheRef.current.get(cacheKey) ?? row.source;

    // Open immediately using data already loaded for the selected term.
    // The optimized Audit list endpoint now includes the course rows, so in
    // the normal path no second student-detail request is needed.
    const immediateCourses = getCourseRows(immediateDetail);
    setSelectedDetail(immediateDetail);
    setDraft(buildDraft(immediateDetail));
    setLoadingDetail(immediateCourses.length === 0);

    if (immediateCourses.length > 0) {
      detailCacheRef.current.set(cacheKey, immediateDetail);
      setLoadingDetail(false);
      return;
    }

    try {
      const detail = await getOrFetchStudentDetail(row.studentDbId);

      if (detailRequestSequence.current !== requestSequence) return;

      detailCacheRef.current.set(cacheKey, detail);
      setSelectedDetail(detail);
      setDraft(buildDraft(detail));
      setLoadingDetail(false);
    } catch (error: any) {
      if (getCourseRows(immediateDetail).length === 0) {
        toast.error(error?.message || 'Unable to refresh transcript details');
      }
      setLoadingDetail(false);
    } finally {
      if (detailRequestSequence.current === requestSequence) {
        setLoadingDetail(false);
      }
    }
  };

  const updateStudentField = <K extends keyof AuditDraft>(
    field: K,
    value: AuditDraft[K],
  ) => {
    setDraft((current) => (current ? { ...current, [field]: value } : current));
  };

  const updateCourseField = (
    localKey: string,
    field: keyof EditableCourse,
    value: string,
  ) => {
    setDraft((current) => {
      if (!current) return current;

      return {
        ...current,
        courses: current.courses.map((course) =>
          course.localKey === localKey
            ? {
                ...course,
                [field]: value,
                // Any edit means the row needs another human check.
                // Save Review persists this unreviewed state.
                reviewed_by_user: false,
                mark_reviewed: false,
                needs_review: true,
                review_status: 'needs_review',
              }
            : course,
        ),
      };
    });
  };

  const markCourseReviewed = async (course: EditableCourse) => {
    if (course.reviewed_by_user) return;

    const missingFields = getMissingCourseFields(course);

    if (missingFields.length > 0) {
      toast.error(
        `This course is not ready to be marked reviewed yet. Please add ${formatMissingFieldsForUser(
          missingFields,
        )}.`,
      );
      return;
    }

    const persistedCourseId =
      toFiniteNumber(course.id) ??
      toFiniteNumber(course.final_course_detail_id) ??
      toFiniteNumber(course.final_course_id);

    const setCourseReviewedLocally = (reviewed: boolean) => {
      setDraft((current) => {
        if (!current) return current;

        return {
          ...current,
          courses: current.courses.map((item) =>
            item.localKey === course.localKey
              ? {
                  ...item,
                  reviewed_by_user: reviewed,
                  mark_reviewed: reviewed,
                  needs_review: !reviewed,
                  review_status: reviewed ? 'reviewed' : 'needs_review',
                }
              : item,
          ),
        };
      });
    };

    const patchCachedReviewState = (reviewed: boolean) => {
      if (
        selectedRow?.studentDbId === null ||
        selectedRow?.studentDbId === undefined
      ) {
        return;
      }

      const cacheKey = String(selectedRow.studentDbId);
      const cachedStudent =
        detailCacheRef.current.get(cacheKey) ?? selectedDetail;

      if (!cachedStudent) return;

      if (reviewed) {
        const patchedStudent = patchStudentCourseReviewed(
          cachedStudent,
          course,
        );

        detailCacheRef.current.set(cacheKey, patchedStudent);
        setSelectedDetail(patchedStudent);
        setSelectedRow((current) =>
          current
            ? {
                ...current,
                source: patchedStudent,
              }
            : current,
        );
        return;
      }

      // Roll back only the review flags if the backend rejects the optimistic save.
      const rollbackStudent = {
        ...cachedStudent,
        courses: (cachedStudent.courses ?? []).map((item: any) => {
          const itemId =
            toFiniteNumber(item.id) ??
            toFiniteNumber(item.final_course_detail_id) ??
            toFiniteNumber(item.final_course_id) ??
            toFiniteNumber(item.new_transcript_course_id);

          const courseId =
            toFiniteNumber(course.id) ??
            toFiniteNumber(course.final_course_detail_id) ??
            toFiniteNumber(course.final_course_id) ??
            toFiniteNumber(course.new_transcript_course_id);

          const samePersistedRow =
            itemId !== undefined &&
            courseId !== undefined &&
            itemId === courseId;

          const sameLocalRow =
            toText(item.localKey) !== '' &&
            toText(item.localKey) === toText(course.localKey);

          if (!samePersistedRow && !sameLocalRow) return item;

          return {
            ...item,
            reviewed_by_user: false,
            mark_reviewed: false,
            needs_review: true,
            review_status: 'needs_review',
          };
        }),
      };

      detailCacheRef.current.set(cacheKey, rollbackStudent);
      setSelectedDetail(rollbackStudent);
      setSelectedRow((current) =>
        current
          ? {
              ...current,
              source: rollbackStudent,
            }
          : current,
      );
    };

    // New unsaved rows are local until Save Review creates them.
    if (persistedCourseId === undefined || persistedCourseId === 0) {
      setCourseReviewedLocally(true);
      toast.success('Course marked as reviewed.');
      return;
    }

    // Optimistic UI:
    // move the row out of Needs Review immediately instead of keeping the user
    // waiting on the network request. The backend write still happens below
    // and we roll the row back if that write fails.
    setCourseReviewedLocally(true);
    patchCachedReviewState(true);

    setReviewingCourseKeys((current) => {
      const next = new Set(current);
      next.add(course.localKey);
      return next;
    });

    try {
      await reviewFinalCourse(
        persistedCourseId,
        {
          id: course.id,
          final_course_id: course.final_course_id,
          final_course_detail_id: course.final_course_detail_id,
          new_transcript_course_id: course.new_transcript_course_id,
          is_new_transcript_type: true,
          storage_source: 'new_transcript_course_details',
          course_id: course.course_id,
          crs_id: course.crs_id,
          course_name: course.course_name,
          name: course.name,
          grade: course.grade,
          letter_grade: course.letter_grade,
          credits_attempted: course.credits_attempted,
          credits_completed: course.credits_completed,
          grade_level: course.grade_level,
          month: course.month,
          year: course.year,
          school: course.school,
          school_name: course.school_name,
          term_gpa: course.term_gpa,
          action: 'review',
          reviewed_by_user: true,
          mark_reviewed: true,
          needs_review: false,
          review_status: 'reviewed',
        },
        true,
      );

      toast.success('Course marked as reviewed.');
    } catch (error: any) {
      setCourseReviewedLocally(false);
      patchCachedReviewState(false);

      toast.error(
        getReadableApiErrorMessage(
          error,
          'This course could not be marked reviewed. Please try again.',
        ),
      );
    } finally {
      setReviewingCourseKeys((current) => {
        const next = new Set(current);
        next.delete(course.localKey);
        return next;
      });
    }
  };

  const addCourse = () => {
    setCourseFilter('needs_review');

    setDraft((current) => {
      if (!current) return current;

      const course: EditableCourse = {
        is_new_transcript_type: true,
        storage_source: 'new_transcript_course_details',
        localKey: newLocalKey(),
        course_id: '',
        crs_id: '',
        course_name: '',
        name: '',
        grade: '',
        letter_grade: '',
        credits_attempted: '',
        credits_completed: '',
        grade_level: '',
        month: '',
        year: '',
        school: current.schoolName,
        school_name: current.schoolName,
        term_gpa: '',
        reviewed_by_user: false,
        mark_reviewed: false,
        review_status: 'needs_review',
        needs_review: true,
      };

      return {
        ...current,
        courses: [course, ...current.courses],
      };
    });

    requestAnimationFrame(() => {
      coursePaneRef.current?.scrollTo({
        top: 0,
        behavior: 'smooth',
      });
    });
  };

  const toggleCourseSelection = (localKey: string) => {
    setSelectedCourseKeys((current) => {
      const next = new Set(current);
      if (next.has(localKey)) {
        next.delete(localKey);
      } else {
        next.add(localKey);
      }
      return next;
    });
  };

  const toggleAllVisibleCourses = () => {
    setSelectedCourseKeys((current) => {
      const visibleKeys = filteredCourses.map((course) => course.localKey);
      const allSelected =
        visibleKeys.length > 0 &&
        visibleKeys.every((localKey) => current.has(localKey));

      const next = new Set(current);

      if (allSelected) {
        visibleKeys.forEach((localKey) => next.delete(localKey));
        return next;
      }

      visibleKeys.forEach((localKey) => next.add(localKey));
      return next;
    });
  };

  const deleteSelectedCourses = () => {
    if (selectedCourseKeys.size === 0) return;

    setDraft((current) => {
      if (!current) return current;

      return {
        ...current,
        courses: current.courses.map((course) =>
          selectedCourseKeys.has(course.localKey)
            ? { ...course, removed: true }
            : course,
        ),
      };
    });

    toast.success(
      `${selectedCourseKeys.size} course row${
        selectedCourseKeys.size === 1 ? '' : 's'
      } selected for removal.`,
    );
    setSelectedCourseKeys(new Set());
  };

  const restoreCourse = (localKey: string) => {
    setDraft((current) => {
      if (!current) return current;

      return {
        ...current,
        courses: current.courses.map((course) =>
          course.localKey === localKey
            ? { ...course, removed: false }
            : course,
        ),
      };
    });
  };

  const hasPersistedCourseId = (course: EditableCourse): boolean =>
    [
      course.new_transcript_course_id,
      course.final_course_detail_id,
      course.final_course_id,
      course.id,
    ].some(
      (value) =>
        typeof value === 'number' &&
        Number.isFinite(value) &&
        value !== 0,
    );

  const handleCreateStudent = async () => {
    if (!selectedRow) return;

    setCreatingStudent(true);

    try {
      const created = await createStudentForFile(selectedRow.fileId, {
        is_new_transcript_type: true,
        storage_source: 'new_transcript_tables',
        student_name:
          selectedRow.studentName === 'Unknown Student'
            ? ''
            : selectedRow.studentName,
        name:
          selectedRow.studentName === 'Unknown Student'
            ? ''
            : selectedRow.studentName,
        school_name:
          selectedRow.schoolName === 'Unknown School'
            ? ''
            : selectedRow.schoolName,
        school:
          selectedRow.schoolName === 'Unknown School'
            ? ''
            : selectedRow.schoolName,
        format:
          selectedRow.schoolName === 'Unknown School'
            ? ''
            : selectedRow.schoolName,
        courses: [],
      });

      const studentDbId = getStudentDbId(created);
      if (studentDbId === null) {
        throw new Error('The backend did not return the created student ID.');
      }

      const updatedRow: AuditRow = {
        ...selectedRow,
        studentDbId,
        studentName: created.student_name || selectedRow.studentName,
        schoolName:
          created.school_name || created.format || selectedRow.schoolName,
        source: created,
      };

      setSelectedRow(updatedRow);
      setSelectedDetail(created);
      setDraft(buildDraft(created));
      detailCacheRef.current.set(String(studentDbId), created);
      toast.success('Student record created. Add or verify the transcript fields.');
      refreshPage();
    } catch (error: any) {
      toast.error(error?.message || 'Unable to create the student record');
    } finally {
      setCreatingStudent(false);
    }
  };

  const buildSavePayload = (): ReviewStudentPayload | null => {
    if (!draft) return null;

    const courses: ReviewStudentCoursePayload[] = draft.courses
      .filter((course) => !(course.removed && !hasPersistedCourseId(course)))
      .map((course) => ({
        id: course.id,
        final_course_id: course.final_course_id,
        final_course_detail_id: course.final_course_detail_id,
        new_transcript_course_id: course.new_transcript_course_id,
        is_new_transcript_type: true,
        storage_source: 'new_transcript_course_details',
        course_id: course.course_id,
        crs_id: course.crs_id,
        course_name: course.course_name,
        name: course.name,
        grade: course.grade,
        letter_grade: course.letter_grade,
        credits_attempted: course.credits_attempted,
        credits_completed: course.credits_completed,
        grade_level: course.grade_level,
        month: course.month,
        year: course.year,
        school: course.school,
        school_name: course.school_name,
        term_gpa: course.term_gpa,
        reviewed_by_user: Boolean(course.reviewed_by_user),
        mark_reviewed: Boolean(course.reviewed_by_user),
        needs_review: !Boolean(course.reviewed_by_user),
        review_status: course.reviewed_by_user ? 'reviewed' : 'needs_review',
        action: course.removed ? 'remove' : 'review',
      }));

    return {
      is_new_transcript_type: true,
      storage_source: 'new_transcript_tables',
      student_id: draft.studentId,
      student_name: draft.studentName,
      name: draft.studentName,
      format: draft.schoolName,
      school: draft.schoolName,
      school_name: draft.schoolName,
      address: draft.address,
      phone_number: draft.phoneNumber,
      gender: draft.gender,
      birth_date: draft.birthDate,
      state_id: draft.stateId,
      counselor_name: draft.counselorName,
      grade_level: draft.currentGradeLevel,
      total_units_earned: draft.totalUnitsEarned,
      enter_date: draft.enterDate,
      graduation_date: draft.graduationDate,
      gpa: draft.gpa,
      academic_gpa: draft.academicGpa,
      university_gpa: draft.universityGpa,
      courses,
    };
  };

  const persistDraft = async ({
    showSuccessToast = true,
    refreshAfterSave = true,
  }: {
    showSuccessToast?: boolean;
    refreshAfterSave?: boolean;
  } = {}): Promise<StudentWithCourses | null> => {
    if (!selectedRow || selectedRow.studentDbId === null || !draft) {
      toast.error('This transcript does not have an extracted student row yet.');
      return null;
    }

    const payload = buildSavePayload();
    if (!payload) return null;

    const savingRowId = selectedRow.id;
    const savingStudentId = selectedRow.studentDbId;
    const draftAtSave = draft;
    const detailAtSave = selectedDetail ?? selectedRow.source;

    // New rows need the full response once so we receive their generated DB IDs.
    // Existing rows can use the much faster light=true backend response.
    const hasNewActiveCourse = draftAtSave.courses.some(
      (course) => !course.removed && !hasPersistedCourseId(course),
    );
    const useLightResponse = !hasNewActiveCourse;

    setSaving(true);

    try {
      const updated = await updateStudentAndCoursesFast(
        savingStudentId,
        payload,
        useLightResponse,
      );

      if (selectedRow?.id !== savingRowId) {
        return updated;
      }

      const responseCourses = getCourseRows(updated);
      let nextDetail: StudentWithCourses;

      if (responseCourses.length > 0 || !useLightResponse) {
        // Full backend response: use the authoritative rows/IDs.
        nextDetail = updated;
        setDraft(buildDraft(updated));
      } else {
        // light=true intentionally returns only a tiny status response. Keep the
        // current verified/editable rows in memory rather than rebuilding the
        // modal from an empty response.
        const activeCourses = draftAtSave.courses
          .filter((course) => !course.removed)
          .map(
            (course) =>
              ({
                ...course,
                reviewed_by_user: Boolean(course.reviewed_by_user),
                reviewed: Boolean(course.reviewed_by_user),
                mark_reviewed: Boolean(course.reviewed_by_user),
                needs_review: !Boolean(course.reviewed_by_user),
                review_status: course.reviewed_by_user
                  ? 'reviewed'
                  : 'needs_review',
              }) as FinalCourseDetail,
          );

        nextDetail = {
          ...detailAtSave,
          student_id: draftAtSave.studentId,
          student_name: draftAtSave.studentName,
          school_name: draftAtSave.schoolName,
          format: draftAtSave.schoolName,
          address: draftAtSave.address,
          phone_number: draftAtSave.phoneNumber,
          gender: draftAtSave.gender,
          birth_date: draftAtSave.birthDate,
          state_id: draftAtSave.stateId,
          counselor_name: draftAtSave.counselorName,
          grade_level: draftAtSave.currentGradeLevel,
          current_grade_level: draftAtSave.currentGradeLevel,
          total_units_earned: draftAtSave.totalUnitsEarned,
          enter_date: draftAtSave.enterDate,
          graduation_date: draftAtSave.graduationDate,
          gpa: draftAtSave.gpa,
          academic_gpa: draftAtSave.academicGpa,
          university_gpa: draftAtSave.universityGpa,
          courses: activeCourses,
          final_courses: activeCourses,
          final_course_details: activeCourses,
          trusted_courses: activeCourses,
          final_course_count: activeCourses.length,
          gemini_course_count: activeCourses.length,
          process_status:
            updated.process_status ??
            detailAtSave.process_status ??
            'needs_review_audit',
          file_status:
            updated.file_status ??
            detailAtSave.file_status ??
            'needs_review_audit',
          effective_status:
            updated.effective_status ??
            detailAtSave.effective_status ??
            'needs_review_audit',
        } as StudentWithCourses;
      }

      setSelectedDetail(nextDetail);
      setSelectedCourseKeys(new Set());
      detailCacheRef.current.set(String(savingStudentId), nextDetail);
      setSelectedRow((current) =>
        current && current.id === savingRowId
          ? {
              ...current,
              studentName:
                nextDetail.student_name || current.studentName,
              schoolName:
                nextDetail.school_name ||
                nextDetail.format ||
                current.schoolName,
              formatName:
                nextDetail.format ||
                nextDetail.school_name ||
                current.formatName,
              courseCount: getCourseRows(nextDetail).length,
              source: nextDetail,
            }
          : current,
      );

      if (showSuccessToast) {
        toast.success('Audit changes saved.');
      }

      // Normal Save Review refreshes the table/counts in the background.
      // Move to Completed skips this intermediate fetch and refreshes once after
      // completion, which removes a noticeable delay.
      if (refreshAfterSave) {
        refreshPage();
      }

      return nextDetail;
    } catch (error: any) {
      toast.error(error?.message || 'Unable to save audit changes');
      return null;
    } finally {
      setSaving(false);
    }
  };

  const handleMoveToCompleted = async () => {
    if (!selectedRow) return;

    if (unreviewedCourseCount > 0) {
      toast.error(
        `Mark all ${unreviewedCourseCount} remaining course row${
          unreviewedCourseCount === 1 ? '' : 's'
        } as reviewed before moving to Auto Complete.`,
      );
      return;
    }

    if (studentMissingRequiredFields.length > 0) {
      toast.error(
        `Complete the required student field${
          studentMissingRequiredFields.length === 1 ? '' : 's'
        }: ${studentMissingRequiredFields.join(', ')}.`,
      );
      return;
    }

    if (incompleteCourseCount > 0) {
      const firstIssue = incompleteCourseIssues[0];
      const courseLabel =
        String(
          firstIssue.course.course_name ||
            firstIssue.course.name ||
            `Course ${firstIssue.index + 1}`,
        ).trim() || `Course ${firstIssue.index + 1}`;

      toast.error(
        `${incompleteCourseCount} course row${
          incompleteCourseCount === 1 ? ' is' : 's are'
        } still incomplete. ${courseLabel} needs: ${firstIssue.missing.join(
          ', ',
        )}.`,
      );
      return;
    }

    setCompleting(true);

    try {
      const completedRow = selectedRow;
      const saved = await persistDraft({
        showSuccessToast: false,
        refreshAfterSave: false,
      });
      if (!saved) return;

      const result = await completeExtractionFile(completedRow.fileId);

      if (result.process_status !== 'completed') {
        toast.error('This transcript still has incomplete required fields.');
        return;
      }

      toast.success('Transcript moved to Auto Complete.');

      if (completedRow.studentDbId !== null) {
        const completedCacheKey = String(completedRow.studentDbId);
        detailCacheRef.current.delete(completedCacheKey);
        detailRequestCacheRef.current.delete(completedCacheKey);
      }

      setSelectedRow(null);
      setSelectedDetail(null);
      setDraft(null);
      setSelectedCourseKeys(new Set());
      setReviewingCourseKeys(new Set());
      refreshPage();

      // Refresh Auto Complete / Human Review / Audit counts immediately.
      window.dispatchEvent(new Event('transcript-extraction-complete'));
    } catch (error: any) {
      toast.error(
        getReadableApiErrorMessage(
          error,
          'Unable to move transcript to Auto Complete.',
        ),
      );
    } finally {
      setCompleting(false);
    }
  };

  const columns: StdColumn<AuditRow>[] = [
    {
      key: 'selectTranscript',
      header: 'Select',
      align: 'center',
      width: 76,
      sortable: false,
      cell: (row) => (
        <input
          type="checkbox"
          aria-label={`Select ${row.studentName || row.fileName} for re-extraction`}
          className="h-4 w-4 cursor-pointer rounded border-slate-300 text-blue-600 focus:ring-blue-500"
          checked={selectedTranscriptFileIds.has(row.fileId)}
          onChange={() => toggleTranscriptSelection(row.fileId)}
          onClick={(event) => event.stopPropagation()}
        />
      ),
    },
    {
      key: 'student',
      header: 'Student',
      value: (row) => `${row.studentName} ${row.fileName}`,
      cell: (row) => (
        <div className="flex min-w-0 items-center gap-3">
          <Avatar name={row.studentName || row.fileName} />
          <div className="min-w-0">
            <div
              className="truncate font-medium text-slate-800"
              title={row.studentName}
            >
              {row.studentName}
            </div>
            <div
              className="truncate text-xs text-slate-400"
              title={row.fileName}
            >
              {row.fileName}
            </div>
          </div>
        </div>
      ),
    },
    {
      key: 'school',
      header: 'School',
      value: (row) => row.schoolName,
      cell: (row) => (
        <div
          className="truncate text-sm text-slate-700"
          title={row.schoolName}
        >
          {row.schoolName}
        </div>
      ),
    },
    {
      key: 'format',
      header: 'Format',
      value: (row) => row.formatName,
      cell: (row) => (
        <span
          className="inline-flex max-w-full items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-200"
          title={row.formatName}
        >
          <span className="truncate">{row.formatName}</span>
        </span>
      ),
    },
    {
      key: 'courseCount',
      header: 'Extracted Course',
      align: 'center',
      width: 150,
      value: (row) => row.courseCount,
      sortValue: (row) => row.courseCount,
      cell: (row) => (
        <span className="inline-flex min-w-10 items-center justify-center rounded-full bg-slate-100 px-2.5 py-1 text-sm font-semibold tabular-nums text-slate-700">
          {row.courseCount}
        </span>
      ),
    },
    {
      key: 'review',
      header: 'Review',
      align: 'center',
      width: 120,
      sortable: false,
      cell: (row) => (
        <Button
          size="sm"
          variant="secondary"
          onMouseEnter={() => {
            if (
              row.studentDbId !== null &&
              getCourseRows(row.source).length === 0
            ) {
              void getOrFetchStudentDetail(row.studentDbId).catch(() => undefined);
            }
          }}
          onFocus={() => {
            if (
              row.studentDbId !== null &&
              getCourseRows(row.source).length === 0
            ) {
              void getOrFetchStudentDetail(row.studentDbId).catch(() => undefined);
            }
          }}
          onClick={() => handleOpenAudit(row)}
        >
          <FileSearch className="mr-1 h-3.5 w-3.5" />
          Review
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      {!embedded && (
        <PageHeader
          title="Human Review with Audit"
          subtitle="Review Gemini-only transcripts against the original PDF"
        />
      )}

      {refreshing && rows.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Loading backlog…
        </div>
      ) : rows.length === 0 ? (
        <div className="rounded-md border p-8 text-center text-muted-foreground">
          No transcripts are waiting in the backlog.
        </div>
      ) : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-3 py-2 shadow-sm">
            <div className="flex flex-wrap items-center gap-2">
              <label className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-700">
                <input
                  type="checkbox"
                  aria-label="Select all transcripts"
                  className="h-4 w-4 cursor-pointer rounded border-slate-300 text-blue-600 focus:ring-blue-500"
                  checked={allVisibleTranscriptsSelected}
                  onChange={toggleAllTranscripts}
                />
                Select all
              </label>

              <span className="text-xs text-slate-500">
                {selectedTranscriptFileIds.size} selected
              </span>
            </div>

            <Button
              type="button"
              size="sm"
              disabled={
                selectedTranscriptFileIds.size === 0 ||
                startingSelectedReextract
              }
              onClick={() => void handleReextractSelectedTranscripts()}
              className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-700"
            >
              <RotateCcw
                className={`h-4 w-4 ${
                  startingSelectedReextract ? 'animate-spin' : ''
                }`}
              />
              {startingSelectedReextract
                ? 'Starting…'
                : `Re-extract Selected${
                    selectedTranscriptFileIds.size > 0
                      ? ` (${selectedTranscriptFileIds.size})`
                      : ''
                  }`}
            </Button>
          </div>

          <StandardTable
            columns={columns}
            data={rows}
            rowKey={(row: AuditRow) => row.id}
            flagId={(row: AuditRow) => row.id}
            search
            searchPlaceholder="Search files…"
            storageKey="extract:not-processed"
            emptyMessage="No transcripts are waiting in the backlog."
          />
        </div>
      )}

      {selectedRow && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-slate-950/65 p-2 backdrop-blur-[1px] sm:p-4">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="audit-review-title"
            className="flex h-[calc(100vh-16px)] w-full max-w-[1510px] flex-col overflow-hidden rounded-xl bg-white shadow-2xl sm:h-[calc(100vh-32px)]"
          >
            <header className="relative grid shrink-0 grid-cols-1 border-b border-slate-200 lg:grid-cols-[minmax(480px,1fr)_minmax(620px,1fr)]">
              <div className="min-w-0 px-5 py-4 sm:px-7">
                <h2
                  id="audit-review-title"
                  className="text-xl font-semibold text-slate-950"
                >
                  Review Transcript
                </h2>
                <p className="mt-1 flex flex-wrap items-center gap-x-5 gap-y-1 text-sm text-slate-500">
                  <span>
                    Student:{' '}
                    <span className="font-semibold text-slate-700">
                      {draft?.studentName || selectedRow.studentName || '—'}
                    </span>
                  </span>
                  <span>
                    School:{' '}
                    <span className="font-semibold text-slate-700">
                      {draft?.schoolName || selectedRow.schoolName || '—'}
                    </span>
                  </span>
                  <span>
                    ID:{' '}
                    <span className="font-medium text-slate-600">
                      {toText(draft?.studentId) || '—'}
                    </span>
                  </span>
                </p>
              </div>

              <div className="min-w-0 px-3 py-3 pr-14">
                {selectedDetail && draft && unreviewedCourseCount > 0 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-2.5 text-amber-900">
                    <div className="text-sm font-semibold">
                      Why this transcript needs review
                    </div>
                    <p className="mt-0.5 text-sm leading-5">
                      {unreviewedCourseCount} course entr
                      {unreviewedCourseCount === 1 ? 'y' : 'ies'} could not be fully
                      verified automatically and require
                      {unreviewedCourseCount === 1 ? 's' : ''} an admission staff review
                      before the transcript can be finalized.
                    </p>
                  </div>
                )}
              </div>

              <button
                type="button"
                aria-label="Close transcript review"
                className="absolute right-4 top-4 rounded-md p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={saving || completing}
                onClick={closeAuditModal}
              >
                <X className="h-5 w-5" />
              </button>
            </header>

            <div className="min-h-0 flex-1 overflow-hidden">
              {selectedRow.studentDbId === null ? (
                <div className="flex h-full items-center justify-center p-8 text-center">
                  <div>
                    <p className="text-sm text-slate-600">
                      This file does not have an extracted student row yet.
                    </p>
                    <div className="mt-4 flex flex-wrap justify-center gap-2">
                      <Button
                        disabled={creatingStudent || !!rerunning[selectedRow.id]}
                        onClick={handleCreateStudent}
                      >
                        <Plus className="mr-1.5 h-4 w-4" />
                        {creatingStudent ? 'Creating…' : 'Create Student Record'}
                      </Button>
                      <Button
                        variant="secondary"
                        disabled={creatingStudent || !!rerunning[selectedRow.id]}
                        onClick={() => handleRerun(selectedRow)}
                      >
                        <RotateCcw className="mr-1.5 h-4 w-4" />
                        Re-run Extraction
                      </Button>
                    </div>
                  </div>
                </div>
              ) : !selectedDetail || !draft ? (
                <div className="flex h-full items-center justify-center p-8 text-center text-sm text-slate-500">
                  Transcript details could not be loaded.
                </div>
              ) : (
                <div className="grid h-full min-h-0 grid-cols-1 lg:grid-cols-[minmax(480px,1fr)_minmax(620px,1fr)]">
                  {/* PDF - left side, matching the Human Review split layout */}
                  <div className="min-h-0 border-b border-slate-200 bg-slate-50 p-3 lg:border-b-0 lg:border-r">
                    <div className="flex h-full min-h-[480px] flex-col overflow-hidden rounded-lg border border-slate-300 bg-white shadow-sm">
                      <div className="flex shrink-0 items-center justify-between border-b border-slate-200 bg-white px-3 py-2 text-xs text-slate-500">
                        <span className="truncate">{selectedRow.fileName}</span>
                        <Button
                          variant="secondary"
                          size="sm"
                          onClick={() =>
                            setPreview({
                              open: true,
                              url: getTranscriptPdfUrl(selectedRow.fileId),
                              label: `${selectedRow.studentName} (${selectedRow.fileName})`,
                            })
                          }
                        >
                          <Eye className="mr-1.5 h-3.5 w-3.5" />
                          Open PDF
                        </Button>
                      </div>

                      <iframe
                        loading="eager"
                        title={`Transcript PDF for ${selectedRow.studentName}`}
                        src={`${getTranscriptPdfUrl(
                          selectedRow.fileId,
                        )}#view=Fit&toolbar=1&navpanes=0`}
                        className="min-h-0 flex-1 bg-white"
                      />
                    </div>
                  </div>

                  {/* Review - right side, styled like the Human Review page */}
                  <div
                    ref={coursePaneRef}
                    className="min-h-0 min-w-0 overflow-y-auto bg-white p-3"
                  >
                    <div className="space-y-3">
                      {/* Collapsible Student Details - same interaction as Human Review */}
                      <details className="group overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
                        <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 hover:bg-slate-50">
                          <div className="flex items-center gap-2">
                            <UserRound className="h-4 w-4 text-blue-600" />
                            <div>
                              <div className="font-medium text-slate-900">
                                Student Details
                              </div>
                              <div className="text-xs text-slate-500">
                                Expand to verify or edit student fields.
                              </div>
                            </div>
                          </div>
                          <ChevronDown className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180" />
                        </summary>

                        <div className="grid grid-cols-1 gap-3 border-t border-slate-200 bg-slate-50/60 p-4 md:grid-cols-2 xl:grid-cols-3">
                          <Field
                            label="Student ID"
                            value={draft.studentId}
                            onChange={(value) => updateStudentField('studentId', value)}
                          />
                          <Field
                            label="Student Name"
                            value={draft.studentName}
                            onChange={(value) => updateStudentField('studentName', value)}
                          />
                          <Field
                            label="School"
                            value={draft.schoolName}
                            onChange={(value) => updateStudentField('schoolName', value)}
                          />
                          <Field
                            label="State ID"
                            value={draft.stateId}
                            onChange={(value) => updateStudentField('stateId', value)}
                          />
                          <Field
                            label="Phone Number"
                            value={draft.phoneNumber}
                            onChange={(value) => updateStudentField('phoneNumber', value)}
                          />
                          <Field
                            label="Gender"
                            value={draft.gender}
                            onChange={(value) => updateStudentField('gender', value)}
                          />
                          <Field
                            label="Counselor Name"
                            value={draft.counselorName}
                            onChange={(value) => updateStudentField('counselorName', value)}
                          />
                          <Field
                            label="Current Grade Level"
                            type="number"
                            value={draft.currentGradeLevel}
                            onChange={(value) =>
                              updateStudentField('currentGradeLevel', value)
                            }
                          />
                          <Field
                            label="Total Units Earned"
                            type="number"
                            value={draft.totalUnitsEarned}
                            onChange={(value) =>
                              updateStudentField('totalUnitsEarned', value)
                            }
                          />
                          <Field
                            label="Overall GPA"
                            type="number"
                            value={draft.gpa}
                            onChange={(value) => updateStudentField('gpa', value)}
                          />
                          <Field
                            label="Academic GPA"
                            type="number"
                            value={draft.academicGpa}
                            onChange={(value) => updateStudentField('academicGpa', value)}
                          />
                          <Field
                            label="University GPA"
                            type="number"
                            value={draft.universityGpa}
                            onChange={(value) => updateStudentField('universityGpa', value)}
                          />
                          <Field
                            label="Birth Date"
                            type="date"
                            value={draft.birthDate}
                            onChange={(value) => updateStudentField('birthDate', value)}
                          />
                          <Field
                            label="Enter Date"
                            type="date"
                            value={draft.enterDate}
                            onChange={(value) => updateStudentField('enterDate', value)}
                          />
                          <Field
                            label="Graduation Date"
                            type="date"
                            value={draft.graduationDate}
                            onChange={(value) =>
                              updateStudentField('graduationDate', value)
                            }
                          />
                          <div className="md:col-span-2 xl:col-span-3">
                            <Field
                              label="Address"
                              value={draft.address}
                              onChange={(value) => updateStudentField('address', value)}
                            />
                          </div>
                        </div>
                      </details>

                      {/* Review Courses toolbar */}
                      <div className="flex flex-wrap items-center justify-between gap-3 pt-1">
                        <div className="flex flex-wrap items-center gap-3">
                          <div className="font-medium text-slate-900">
                            Review Courses
                          </div>

                          <div className="inline-flex overflow-hidden rounded-md border border-slate-200 bg-white">
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedCourseKeys(new Set());
                                setCourseFilter('needs_review');
                              }}
                              className={`px-3 py-1.5 text-xs font-medium transition ${
                                courseFilter === 'needs_review'
                                  ? 'bg-amber-100 text-amber-900'
                                  : 'text-slate-600 hover:bg-slate-50'
                              }`}
                            >
                              Needs Review ({unreviewedCourseCount})
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedCourseKeys(new Set());
                                setCourseFilter('reviewed');
                              }}
                              className={`border-l border-slate-200 px-3 py-1.5 text-xs font-medium transition ${
                                courseFilter === 'reviewed'
                                  ? 'bg-emerald-100 text-emerald-800'
                                  : 'text-slate-600 hover:bg-slate-50'
                              }`}
                            >
                              Reviewed ({reviewedCourseCount})
                            </button>
                            <button
                              type="button"
                              onClick={() => {
                                setSelectedCourseKeys(new Set());
                                setCourseFilter('all');
                              }}
                              className={`border-l border-slate-200 px-3 py-1.5 text-xs font-medium transition ${
                                courseFilter === 'all'
                                  ? 'bg-slate-100 text-slate-900'
                                  : 'text-slate-600 hover:bg-slate-50'
                              }`}
                            >
                              All ({visibleCourses.length})
                            </button>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center gap-2">
                          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-slate-200 bg-white px-3 py-2 text-xs font-medium text-slate-600">
                            <input
                              aria-label="Select all visible course rows"
                              type="checkbox"
                              className="h-4 w-4 cursor-pointer rounded border-slate-300"
                              checked={
                                filteredCourses.length > 0 &&
                                filteredCourses.every((course) =>
                                  selectedCourseKeys.has(course.localKey),
                                )
                              }
                              onChange={toggleAllVisibleCourses}
                            />
                            Select all
                          </label>

                          <Button
                            size="sm"
                            variant="destructive"
                            disabled={selectedCourseKeys.size === 0}
                            onClick={deleteSelectedCourses}
                          >
                            <Trash2 className="mr-1.5 h-4 w-4" />
                            Delete Selected
                            {selectedCourseKeys.size > 0
                              ? ` (${selectedCourseKeys.size})`
                              : ''}
                          </Button>

                          <Button size="sm" variant="secondary" onClick={addCourse}>
                            <Plus className="mr-1.5 h-4 w-4" />
                            Add Course
                          </Button>
                        </div>
                      </div>

                      {/* Human-Review-style editable course cards */}
                      {loadingDetail && visibleCourses.length === 0 ? (
                        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
                          Loading course rows…
                        </div>
                      ) : visibleCourses.length === 0 ? (
                        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
                          No course rows are available. Use Add Course to create one.
                        </div>
                      ) : filteredCourses.length === 0 ? (
                        <div className="rounded-lg border border-slate-200 bg-white p-8 text-center text-sm text-slate-500">
                          {courseFilter === 'needs_review'
                            ? 'All course rows have been reviewed.'
                            : courseFilter === 'reviewed'
                              ? 'No course rows have been reviewed yet.'
                              : 'No course rows are available.'}
                        </div>
                      ) : (
                        <div className="space-y-3 pb-3">
                          {filteredCourses.map((course, index) => {
                            const selected = selectedCourseKeys.has(course.localKey);

                            return (
                              <div
                                key={course.localKey}
                                className={`rounded-xl border p-3 shadow-sm transition ${
                                  selected
                                    ? 'border-red-300 bg-red-50/40'
                                    : course.reviewed_by_user
                                      ? 'border-emerald-300 bg-emerald-50/55'
                                      : 'border-amber-200 bg-amber-50/35'
                                }`}
                              >
                                <div className="grid grid-cols-[minmax(90px,0.8fr)_minmax(220px,2.2fr)_36px] gap-3">
                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Course ID
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} ID`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      placeholder="Course ID"
                                      value={toText(course.course_id || course.crs_id)}
                                      onChange={(event) => {
                                        updateCourseField(
                                          course.localKey,
                                          'course_id',
                                          event.target.value,
                                        );
                                        updateCourseField(
                                          course.localKey,
                                          'crs_id',
                                          event.target.value,
                                        );
                                      }}
                                    />
                                  </label>

                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Course Name
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} name`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      placeholder="Course Name"
                                      value={toText(course.course_name || course.name)}
                                      onChange={(event) => {
                                        updateCourseField(
                                          course.localKey,
                                          'course_name',
                                          event.target.value,
                                        );
                                        updateCourseField(
                                          course.localKey,
                                          'name',
                                          event.target.value,
                                        );
                                      }}
                                    />
                                  </label>

                                  <label
                                    className="flex cursor-pointer items-center justify-center"
                                    title="Select row for deletion"
                                  >
                                    <input
                                      aria-label={`Select course ${index + 1} for deletion`}
                                      type="checkbox"
                                      className="h-4 w-4 cursor-pointer rounded border-slate-300"
                                      checked={selected}
                                      onChange={() =>
                                        toggleCourseSelection(course.localKey)
                                      }
                                    />
                                  </label>
                                </div>

                                <div className="mt-3 grid grid-cols-5 gap-3">
                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Grade Yr
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} grade level`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      type="number"
                                      value={toText(course.grade_level)}
                                      onChange={(event) =>
                                        updateCourseField(
                                          course.localKey,
                                          'grade_level',
                                          event.target.value,
                                        )
                                      }
                                    />
                                  </label>

                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Month
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} month`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      type="number"
                                      placeholder="MM"
                                      value={toText(course.month)}
                                      onChange={(event) =>
                                        updateCourseField(
                                          course.localKey,
                                          'month',
                                          event.target.value,
                                        )
                                      }
                                    />
                                  </label>

                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Year
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} year`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100 [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none`}
                                      type="number"
                                      value={toText(course.year)}
                                      onChange={(event) =>
                                        updateCourseField(
                                          course.localKey,
                                          'year',
                                          event.target.value,
                                        )
                                      }
                                    />
                                  </label>

                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Grade
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} grade`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      value={toText(course.grade || course.letter_grade)}
                                      onChange={(event) => {
                                        updateCourseField(
                                          course.localKey,
                                          'grade',
                                          event.target.value,
                                        );
                                        updateCourseField(
                                          course.localKey,
                                          'letter_grade',
                                          event.target.value,
                                        );
                                      }}
                                    />
                                  </label>

                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      Credits
                                    </span>
                                    <input
                                      aria-label={`Course ${index + 1} credits`}
                                      className={`${inputClassName} border-amber-300 focus:border-amber-500 focus:ring-amber-100`}
                                      type="number"
                                      value={toText(course.credits_completed)}
                                      onChange={(event) => {
                                        updateCourseField(
                                          course.localKey,
                                          'credits_completed',
                                          event.target.value,
                                        );
                                        updateCourseField(
                                          course.localKey,
                                          'credits_attempted',
                                          event.target.value,
                                        );
                                      }}
                                    />
                                  </label>
                                </div>

                                <div className="mt-3 grid grid-cols-[minmax(0,1fr)_170px] items-end gap-3">
                                  <label className="space-y-1">
                                    <span className="block text-xs font-medium text-slate-500">
                                      School
                                    </span>
                                    <AutoGrowTextArea
                                      ariaLabel={`Course ${index + 1} school`}
                                      value={toText(
                                        course.school || course.school_name,
                                      )}
                                      onChange={(value) => {
                                        updateCourseField(
                                          course.localKey,
                                          'school',
                                          value,
                                        );
                                        updateCourseField(
                                          course.localKey,
                                          'school_name',
                                          value,
                                        );
                                      }}
                                    />
                                  </label>

                                  <div className="space-y-1">
                                    <Button
                                      type="button"
                                      disabled={
                                        Boolean(course.reviewed_by_user) ||
                                        reviewingCourseKeys.has(course.localKey)
                                      }
                                      onClick={() => void markCourseReviewed(course)}
                                      className={
                                        course.reviewed_by_user
                                          ? 'h-9 w-full bg-emerald-600 text-white hover:bg-emerald-600'
                                          : 'h-9 w-full bg-amber-500 text-white hover:bg-amber-600'
                                      }
                                    >
                                      <CheckCircle2 className="mr-1.5 h-4 w-4" />
                                      {course.reviewed_by_user
                                        ? 'Reviewed'
                                        : reviewingCourseKeys.has(course.localKey)
                                          ? 'Saving…'
                                          : 'Mark as reviewed'}
                                    </Button>

                                    {!course.reviewed_by_user &&
                                      getMissingCourseFields(course).length > 0 && (
                                        <p className="text-xs leading-4 text-amber-700">
                                          Add{' '}
                                          {formatMissingFieldsForUser(
                                            getMissingCourseFields(course),
                                          )}{' '}
                                          before marking reviewed.
                                        </p>
                                      )}
                                  </div>
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}

                      {removedCourses.length > 0 && (
                        <details className="group overflow-hidden rounded-lg border border-red-200 bg-red-50">
                          <summary className="flex cursor-pointer list-none items-center justify-between px-4 py-3 text-sm font-medium text-red-800">
                            <span>
                              Removed Courses ({removedCourses.length}) — saved after Save Review
                            </span>
                            <ChevronDown className="h-4 w-4 transition-transform group-open:rotate-180" />
                          </summary>
                          <div className="space-y-2 border-t border-red-200 p-3">
                            {removedCourses.map((course) => (
                              <div
                                key={course.localKey}
                                className="flex items-center justify-between gap-3 rounded-md bg-white px-3 py-2"
                              >
                                <span className="truncate text-sm text-slate-700">
                                  {toText(course.course_name || course.name) ||
                                    'Untitled Course'}
                                </span>
                                <Button
                                  size="sm"
                                  variant="secondary"
                                  onClick={() => restoreCourse(course.localKey)}
                                >
                                  <Undo2 className="mr-1.5 h-4 w-4" />
                                  Restore
                                </Button>
                              </div>
                            ))}
                          </div>
                        </details>
                      )}
                    </div>
                  </div>
                </div>
              )}
            </div>

            <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-slate-200 bg-white px-5 py-4 sm:px-7">
              <div className="text-xs text-slate-500">
                <div>
                  Review and correct all required fields, then move the transcript
                  to Auto Complete.
                </div>
                <div className="mt-1 font-medium text-slate-600">
                  Reviewed: {reviewedCourseCount}/{visibleCourses.length}
                  {unreviewedCourseCount > 0
                    ? ` • ${unreviewedCourseCount} still need review`
                    : ' • All active rows reviewed'}
                  {incompleteCourseCount > 0
                    ? ` • ${incompleteCourseCount} incomplete row${
                        incompleteCourseCount === 1 ? '' : 's'
                      }`
                    : ''}
                  {removedCourses.length > 0
                    ? ` • Removed in draft: ${removedCourses.length}`
                    : ''}
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="secondary"
                  disabled={saving || completing}
                  onClick={closeAuditModal}
                >
                  Cancel
                </Button>
                <Button
                  variant="secondary"
                  disabled={
                    saving ||
                    completing ||
                    !draft ||
                    selectedRow.studentDbId === null
                  }
                  onClick={() => void persistDraft()}
                >
                  <Save className="mr-1.5 h-4 w-4" />
                  {saving ? 'Saving…' : 'Save Review'}
                </Button>
                <Button
                  disabled={
                    saving ||
                    completing ||
                    !draft ||
                    selectedRow.studentDbId === null ||
                    unreviewedCourseCount > 0 ||
                    incompleteCourseCount > 0 ||
                    studentMissingRequiredFields.length > 0
                  }
                  onClick={handleMoveToCompleted}
                  title={
                    incompleteCourseCount > 0
                      ? `${incompleteCourseCount} course row${
                          incompleteCourseCount === 1 ? '' : 's'
                        } still have required fields missing.`
                      : studentMissingRequiredFields.length > 0
                        ? `Required student fields missing: ${studentMissingRequiredFields.join(
                            ', ',
                          )}`
                        : undefined
                  }
                >
                  <CheckCircle2 className="mr-1.5 h-4 w-4" />
                  {completing ? 'Moving…' : 'Move to Auto Complete'}
                </Button>
              </div>
            </footer>
          </div>
        </div>
      )}

      <PdfPreviewDialog
        open={preview.open}
        onOpenChange={(open: boolean) =>
          setPreview((current) => ({ ...current, open }))
        }
        url={preview.url}
        idLabel={preview.label}
      />
    </div>
  );
}
