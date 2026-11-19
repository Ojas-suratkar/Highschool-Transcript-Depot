import { useState, useEffect, useMemo, useRef, type Dispatch, type SetStateAction } from 'react';
import AiAuditPanel from './AiAuditPanel';
import { useTerm } from '@/contexts/TermContext';
import { Loader2, Check, AlertTriangle } from 'lucide-react';
import type { Verdict } from '@/lib/api/termRules';
import { toast } from 'sonner';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { calculateAdmissionReview } from '@/lib/api/admission';
import { emitNotification } from '@/lib/notify';
import { getAgCriteriaForTerm } from '@/lib/api/institutionAgCriteria';
import { getStudentAgSummary, saveAdmissionResult } from '@/lib/api/studentAgSummary';
import type { TranscriptRecord } from './TranscriptDetailDialog';

type TranscriptCourse = NonNullable<TranscriptRecord['courses']>[number];

type AgKey = 'a' | 'b' | 'c' | 'd1' | 'd2' | 'd' | 'e' | 'f' | 'g';
type AgRequirementKey = AgKey;
type BasicGrade = 'A' | 'B' | 'C' | 'D' | 'F';
type CourseAssignment = {
  courseKey: string;
  agKey: AgKey | '';
  removed?: boolean;
};
type AdmissionSubjectEntry = {
  name?: string;
  count?: number;
  original_ag?: string | null;
  final_ag?: string | null;
  moved_from?: string | null;
  label?: string;
};
type AdmissionAgRow = {
  key: AgRequirementKey;
  label: string;
  required: number;
  actual: number;
  def: number;
  subject_counts?: Record<string, number>;
  subjects?: AdmissionSubjectEntry[];
};
type AdmissionCourseAssignment = {
  course_key?: string;
  course_id?: string;
  course_name?: string;
  original_ag?: string | null;
  final_ag?: string | null;
  removed?: boolean;
  manual?: boolean;
  moved_from?: string | null;
  counted?: boolean;
  reason?: string;
};
type AdmissionDecisionStatus = 'admitted' | 'denied' | 'waitlisted';
type AdmissionDecision = {
  recommended_decision?: AdmissionDecisionStatus;
  ag_satisfied_ignoring_g?: boolean;
  minimum_gpa_satisfied?: boolean;
  g_is_optional?: boolean;
  g_deficit_ignored?: number;
  cumulative_gpa?: number | null;
  minimum_gpa_required?: number;
  reason?: string;
  ag_deficits_ignoring_g?: Array<{
    key?: string;
    label?: string;
    def?: number;
  }>;
};
type GpaBucketKey = 'cumulative' | 'math' | 'english' | 'science';
type GpaBucketEdit = {
  grade_counts?: Partial<Record<BasicGrade, number>>;
  honors_count?: number;
};
type GpaBucketEdits = Partial<Record<GpaBucketKey, GpaBucketEdit>>;
type BackendGpaBucket = {
  label: string;
  grade_counts?: Partial<Record<BasicGrade, number>>;
  grade_points?: Partial<Record<BasicGrade, number>>;
  honors_count?: number;
  honors_bonus_points?: number;
  honors_max_semesters?: number;
  honors_max_10th_grade_semesters?: number;
  total_semesters?: number;
  total_points?: number;
  gpa?: number | null;
};
type AdmissionReviewResponse = {
  student?: Record<string, any>;
  ag_review?: {
    rows?: AdmissionAgRow[];
    totals?: {
      required?: number;
      actual?: number;
      def?: number;
    };
    manual_mappings?: Array<{
      course_id: string;
      target_ag: string;
    }>;
    course_assignments?: AdmissionCourseAssignment[];
  };
  gpa_calculation?: {
    buckets?: {
      cumulative?: BackendGpaBucket;
      math?: BackendGpaBucket;
      english?: BackendGpaBucket;
      science?: BackendGpaBucket;
    };
    score_summary?: {
      csulb_score?: number | null;
      cumulative_gpa?: number | null;
      english_gpa?: number | null;
      math_gpa?: number | null;
      science_gpa?: number | null;
      stem_score?: number | null;
      stem_index?: number | null;
      csulb_score_multiplier?: number;
      california_resident_min_gpa?: number;
      csulb_threshold?: number;
      stem_threshold?: number;
    };
  };
  admission_decision?: AdmissionDecision;
  final_audit?: FinalAudit;
  config?: Record<string, any>;
};

export type FinalAuditOutcome =
  | 'clear_admit'
  | 'clear_admit_lbusd_promise'
  | 'failed_audit_rescinded';

export type FinalAudit = {
  outcome?: FinalAuditOutcome;
  label?: string;
  student_status?: string;
  reason?: string;
  checks?: {
    ag_completion?: boolean;
    gpa_minimum?: boolean;
    csulb_index?: boolean;
    stem_index?: boolean;
    hs_graduation?: boolean;
  };
  inputs?: {
    residency?: string;
    residency_was_provided?: boolean;
    is_stem_major?: boolean;
    lbusd_promise?: boolean;
    applied_min_gpa?: number;
    applied_csulb_index_min?: number;
    stem_index_min?: number;
    graduation_required_by?: string | null;
  };
};

const AG_TYPES: Array<{ key: AgKey; label: string; short: string }> = [
  { key: 'a', label: 'History / Social Science', short: 'A' },
  { key: 'b', label: 'English', short: 'B' },
  { key: 'c', label: 'Mathematics', short: 'C' },
  { key: 'd1', label: 'Bio', short: 'D1' },
  { key: 'd2', label: 'Phys', short: 'D2' },
  { key: 'd', label: 'Extra Science', short: 'D' },
  { key: 'e', label: 'Language Other than English', short: 'E' },
  { key: 'f', label: 'Visual & Performing Arts', short: 'F' },
  { key: 'g', label: 'College-Preparatory Elective', short: 'G' },
];
const DEFAULT_AG_REQUIRED: Record<AgRequirementKey, number> = {
  a: 4,
  b: 8,
  c: 6,
  d1: 2,
  d2: 2,
  d: 4,
  e: 4,
  f: 2,
  g: 2,
};
const DEFAULT_GRADE_POINTS: Record<BasicGrade, number> = {
  A: 4,
  B: 3,
  C: 2,
  D: 1,
  F: 0,
};
function cleanText(value: unknown) {
  return String(value ?? '').trim();
}
function lowerText(value: unknown) {
  return cleanText(value).toLowerCase();
}
function toNumber(value: unknown, fallback = 0) {
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
}
function formatCount(value: number | null | undefined) {
  const safeValue = toNumber(value, 0);
  if (Number.isInteger(safeValue)) return String(safeValue);
  return safeValue.toFixed(3).replace(/\.?0+$/, '');
}
function getCourseKey(course: TranscriptCourse, index: number) {
  const explicitId = cleanText(course.id);
  if (explicitId) return explicitId;
  return `${course.crs_id ?? 'course'}-${course.name ?? 'unknown'}-${index}`;
}
function normalizeCourseAgKey(value: unknown): AgKey | '' {
  const key = lowerText(value);
  if (key === 'a') return 'a';
  if (key === 'b') return 'b';
  if (key === 'c') return 'c';
  if (key === 'd1') return 'd1';
  if (key === 'd2') return 'd2';
  if (key === 'd') return 'd';
  if (key === 'e') return 'e';
  if (key === 'f') return 'f';
  if (key === 'g') return 'g';
  return '';
}
function normalizeRequirementKey(value: unknown): AgRequirementKey | '' {
  return normalizeCourseAgKey(value);
}
function getCourseGradeLabel(course?: TranscriptCourse | null) {
  return course?.letter_grade ?? course?.grade ?? course?.crs_letter_grade ?? '—';
}
function getCourseCreditsDisplay(course?: TranscriptCourse | null) {
  return course?.crs_credit_completed ?? course?.credits_completed ?? course?.credits ?? '—';
}
function getOriginalAgKey(course?: TranscriptCourse | null): AgKey | '' {
  const explicit = lowerText(
    course?.mapped_uc_course?.crs_ag_category_letter ??
      course?.standardizedCode
  );
  if (explicit === 'a') return 'a';
  if (explicit === 'b') return 'b';
  if (explicit === 'c') return 'c';
  if (explicit === 'd1') return 'd1';
  if (explicit === 'd2') return 'd2';
  if (explicit === 'd') return 'd';
  if (explicit === 'e') return 'e';
  if (explicit === 'f') return 'f';
  if (explicit === 'g') return 'g';
  return '';
}
function getAgShort(key: AgRequirementKey | '') {
  if (!key) return '—';
  return AG_TYPES.find((item) => item.key === key)?.short ?? key.toUpperCase();
}
function getAgBadgeClass(key: AgRequirementKey | '') {
  if (key === 'a') return 'border-blue-300 bg-blue-50 text-blue-700';
  if (key === 'b') return 'border-emerald-300 bg-emerald-50 text-emerald-700';
  if (key === 'c') return 'border-purple-300 bg-purple-50 text-purple-700';
  if (key === 'd1') return 'border-orange-300 bg-orange-50 text-orange-700';
  if (key === 'd2') return 'border-amber-300 bg-amber-50 text-amber-700';
  if (key === 'd') return 'border-yellow-300 bg-yellow-50 text-yellow-800';
  if (key === 'e') return 'border-pink-300 bg-pink-50 text-pink-700';
  if (key === 'f') return 'border-indigo-300 bg-indigo-50 text-indigo-700';
  if (key === 'g') return 'border-slate-300 bg-slate-50 text-slate-700';
  return 'border-slate-200 bg-slate-50 text-slate-600';
}
function getAgMoveBadgeClass(originalKey: AgRequirementKey | '', currentKey: AgRequirementKey | '') {
  if (originalKey === 'g' && currentKey && currentKey !== 'g') {
    return 'border-yellow-300 bg-yellow-50 text-yellow-800';
  }
  return getAgBadgeClass(currentKey);
}
function getAgDisplayLabel(originalKey: AgRequirementKey | '', currentKey: AgRequirementKey | '') {
  const original = getAgShort(originalKey);
  const current = getAgShort(currentKey);
  if (originalKey === 'g' && currentKey && currentKey !== 'g') {
    return `${original} → ${current}`;
  }
  if (originalKey === 'd' && (currentKey === 'd1' || currentKey === 'd2')) {
    return `${current} - D`;
  }
  return current;
}
function getAgRowLabel(key: AgRequirementKey) {
  if (key === 'a') return 'History / Social Science (A)';
  if (key === 'b') return 'English (B)';
  if (key === 'c') return 'Mathematics (C)';
  if (key === 'd1') return 'Bio (D1)';
  if (key === 'd2') return 'Phys (D2)';
  if (key === 'd') return 'Laboratory Science (D) = D1 + D2';
  if (key === 'e') return 'Language Other than English (E)';
  if (key === 'f') return 'Visual & Performing Arts (F)';
  return 'College-Preparatory Elective (G)';
}
function getGradeCount(bucket: BackendGpaBucket | undefined, grade: BasicGrade) {
  return toNumber(bucket?.grade_counts?.[grade], 0);
}
function getEditedGradeCount(
  bucket: BackendGpaBucket | undefined,
  edit: GpaBucketEdit | undefined,
  grade: BasicGrade
) {
  const editedValue = edit?.grade_counts?.[grade];
  if (editedValue != null) return toNumber(editedValue, 0);
  return getGradeCount(bucket, grade);
}
function getEditedHonorsCount(
  bucket: BackendGpaBucket | undefined,
  edit: GpaBucketEdit | undefined
) {
  if (edit?.honors_count != null) return toNumber(edit.honors_count, 0);
  return toNumber(bucket?.honors_count, 0);
}
function getEditedBucketSemesters(
  bucket: BackendGpaBucket | undefined,
  edit: GpaBucketEdit | undefined
) {
  const grades: BasicGrade[] = ['A', 'B', 'C', 'D', 'F'];
  return grades.reduce(
    (sum, grade) => sum + getEditedGradeCount(bucket, edit, grade),
    0
  );
}
function getEditedBucketTotalPoints(
  bucket: BackendGpaBucket | undefined,
  edit: GpaBucketEdit | undefined,
  gradePoints: Record<BasicGrade, number>,
  honorsBonus: number
) {
  if (!bucket) return 0;
  const gradeTotal =
    getEditedGradeCount(bucket, edit, 'A') * gradePoints.A +
    getEditedGradeCount(bucket, edit, 'B') * gradePoints.B +
    getEditedGradeCount(bucket, edit, 'C') * gradePoints.C +
    getEditedGradeCount(bucket, edit, 'D') * gradePoints.D +
    getEditedGradeCount(bucket, edit, 'F') * gradePoints.F;
  const honorsTotal = getEditedHonorsCount(bucket, edit) * honorsBonus;
  return gradeTotal + honorsTotal;
}
function getEditedBucketGpa(
  bucket: BackendGpaBucket | undefined,
  edit: GpaBucketEdit | undefined,
  gradePoints: Record<BasicGrade, number>,
  honorsBonus: number
) {
  const semesters = getEditedBucketSemesters(bucket, edit);
  if (!bucket || semesters <= 0) return null;
  return Number(
    (getEditedBucketTotalPoints(bucket, edit, gradePoints, honorsBonus) / semesters).toFixed(3)
  );
}
function normalizeDecisionStatus(value: unknown): AdmissionDecisionStatus | null {
  const decision = lowerText(value);
  if (decision === 'admitted') return 'admitted';
  if (decision === 'denied') return 'denied';
  if (decision === 'waitlisted') return 'waitlisted';
  return null;
}
function getAgDeficitsIgnoringG(admissionReview: AdmissionReviewResponse | null) {
  const decisionDeficits = admissionReview?.admission_decision?.ag_deficits_ignoring_g;
  if (decisionDeficits && decisionDeficits.length > 0) {
    return decisionDeficits
      .map((item) => ({
        key: cleanText(item.key),
        label: cleanText(item.label),
        def: toNumber(item.def, 0),
      }))
      .filter((item) => item.key !== 'g' && item.def > 0);
  }
  const decisionKeys = new Set(['a', 'b', 'c', 'd', 'e', 'f']);
  return (admissionReview?.ag_review?.rows ?? [])
    .filter((row) => decisionKeys.has(row.key))
    .filter((row) => toNumber(row.def, 0) > 0)
    .map((row) => ({
      key: row.key,
      label: row.label || getAgRowLabel(row.key),
      def: toNumber(row.def, 0),
    }));
}
function getGDeficit(admissionReview: AdmissionReviewResponse | null) {
  const backendGDef = admissionReview?.admission_decision?.g_deficit_ignored;
  if (backendGDef != null) return Math.max(toNumber(backendGDef, 0), 0);
  const gRow = (admissionReview?.ag_review?.rows ?? []).find((row) => row.key === 'g');
  return Math.max(toNumber(gRow?.def, 0), 0);
}
function getGMissingText(admissionReview: AdmissionReviewResponse | null) {
  const gDeficit = getGDeficit(admissionReview);
  if (gDeficit <= 0) return '';
  return ` G missing: deficit ${formatCount(gDeficit)}.`;
}
function buildAdmissionReasonFallback({
  admissionReview,
  selectedDecision,
  cumulativeGpa,
  minimumGpa,
}: {
  admissionReview: AdmissionReviewResponse | null;
  selectedDecision: AdmissionDecisionStatus;
  cumulativeGpa: number | null;
  minimumGpa: number;
}) {
  const deficits = getAgDeficitsIgnoringG(admissionReview);
  const agSatisfied = deficits.length === 0;
  const gpaSatisfied = cumulativeGpa != null && cumulativeGpa >= minimumGpa;
  const gMissingText = getGMissingText(admissionReview);
  if (selectedDecision === 'admitted') {
    if (agSatisfied && gpaSatisfied) {
      return `Admitted: A-G requirements are satisfied. Minimum GPA is achieved: cumulative GPA ${cumulativeGpa} is at or above ${minimumGpa}.${gMissingText}`;
    }
    const blockers: string[] = [];
    if (!agSatisfied) {
      const deficitText = deficits
        .map((item) => `${item.label || item.key} deficit ${formatCount(item.def)}`)
        .join('; ');
      blockers.push(`A-G requirements are not fully satisfied: ${deficitText}.`);
    }
    if (!gpaSatisfied) {
      blockers.push(
        cumulativeGpa == null
          ? `Minimum GPA is not satisfied because cumulative GPA is unavailable. Required minimum GPA is ${minimumGpa}.`
          : `Minimum GPA is not satisfied: cumulative GPA ${cumulativeGpa} is below ${minimumGpa}.`
      );
    }
    return `Admitted was selected manually, but review is needed. ${blockers.join(' ')}${gMissingText}`;
  }
  const reasons: string[] = [];
  if (!agSatisfied) {
    const deficitText = deficits
      .map((item) => `${item.label || item.key} deficit ${formatCount(item.def)}`)
      .join('; ');
    reasons.push(`A-G requirements are not satisfied: ${deficitText}.`);
  }
  if (!gpaSatisfied) {
    reasons.push(
      cumulativeGpa == null
        ? `Minimum GPA is not satisfied because cumulative GPA is unavailable. Required minimum GPA is ${minimumGpa}.`
        : `Minimum GPA is not satisfied: cumulative GPA ${cumulativeGpa} is below ${minimumGpa}.`
    );
  }
  if (selectedDecision === 'waitlisted') {
    return reasons.length > 0
      ? `Waitlisted: ${reasons.join(' ')}${gMissingText}`
      : `Waitlisted manually. A-G requirements are satisfied and minimum GPA is achieved.${gMissingText}`;
  }
  return reasons.length > 0
    ? `Denied: ${reasons.join(' ')}${gMissingText}`
    : `Denied was selected manually, but A-G requirements are satisfied and minimum GPA is achieved.${gMissingText}`;
}

function CourseEditDialog({
  open,
  onOpenChange,
  agKey,
  courses,
  assignments,
  setAssignments,
  admissionCourseAssignments,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  agKey: AgRequirementKey;
  courses: TranscriptRecord['courses'];
  assignments: Record<string, CourseAssignment>;
  setAssignments: (value: Record<string, CourseAssignment>) => void;
  admissionCourseAssignments?: AdmissionCourseAssignment[];
}) {
  const [editingCourseKey, setEditingCourseKey] = useState<string | null>(null);
  const [editAgKey, setEditAgKey] = useState<AgKey>(agKey);
  const [rowAgKeys, setRowAgKeys] = useState<Record<string, AgKey>>({});
  useEffect(() => {
    setEditAgKey(agKey);
    setRowAgKeys({});
  }, [agKey]);
  const backendAssignmentByKey = useMemo(() => {
    const map: Record<string, AdmissionCourseAssignment> = {};
    for (const assignment of admissionCourseAssignments ?? []) {
      if (assignment.course_key) map[assignment.course_key] = assignment;
      if (assignment.course_id) map[assignment.course_id] = assignment;
    }
    return map;
  }, [admissionCourseAssignments]);
  const mappedCourses = (courses ?? []).map((course, index) => {
    const courseKey = getCourseKey(course, index);
    const backendAssignment =
      backendAssignmentByKey[courseKey] ??
      backendAssignmentByKey[cleanText(course.crs_id)] ??
      backendAssignmentByKey[cleanText(course.id)];
    const manualAssignment = assignments[courseKey];
    const originalAg =
      normalizeRequirementKey(backendAssignment?.original_ag) ||
      getOriginalAgKey(course);
    const backendFinalAg = normalizeCourseAgKey(backendAssignment?.final_ag);
    const backendCounted = backendAssignment?.counted === true;
    const currentAg = manualAssignment?.removed
      ? ''
      : manualAssignment?.agKey || (backendCounted ? backendFinalAg : '');
    return {
      course,
      index,
      courseKey,
      currentAg,
      originalAg,
      removed: manualAssignment?.removed || backendAssignment?.removed || false,
      backendCounted,
    };
  });
  const activeCourses = mappedCourses.filter((item) => {
    if (item.removed || !item.currentAg) return false;
    if (agKey === 'd') {
      return item.currentAg === 'd1' || item.currentAg === 'd2' || item.currentAg === 'd';
    }
    return item.currentAg === agKey;
  });
  const availableCourses = mappedCourses.filter((item) => {
    if (agKey === 'd') {
      return item.currentAg !== 'd1' && item.currentAg !== 'd2' && item.currentAg !== 'd';
    }
    return item.currentAg !== agKey;
  });
  const startEdit = (courseKey: string, currentAg: AgKey | '') => {
    setEditingCourseKey(courseKey);
    setEditAgKey((currentAg || agKey) as AgKey);
  };
  const saveEdit = (courseKey: string) => {
    setAssignments({
      ...assignments,
      [courseKey]: {
        courseKey,
        agKey: editAgKey,
        removed: false,
      },
    });
    setEditingCourseKey(null);
  };
  const removeCourse = (courseKey: string) => {
    setAssignments({
      ...assignments,
      [courseKey]: {
        courseKey,
        agKey: '',
        removed: true,
      },
    });
  };
  const addCourse = (courseKey: string) => {
    const targetKey = rowAgKeys[courseKey] ?? agKey;
    setAssignments({
      ...assignments,
      [courseKey]: {
        courseKey,
        agKey: targetKey,
        removed: false,
      },
    });
    setRowAgKeys((prev) => { const next = { ...prev }; delete next[courseKey]; return next; });
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="flex max-h-[90vh] flex-col !w-[88vw] !max-w-[1400px] p-0">
        <DialogHeader className="shrink-0 border-b px-6 py-4 pr-14">
          <DialogTitle>{getAgRowLabel(agKey)}</DialogTitle>
        </DialogHeader>
        <div className="flex-1 min-h-0 space-y-4 overflow-y-auto px-6 py-4">
          <div className="overflow-x-auto rounded-md border">
            <table className="w-full min-w-[1100px] text-sm">
              <thead className="sticky top-0 z-10 bg-slate-100">
                <tr className="text-left">
                  <th className="px-3 py-2">CRS ID</th>
                  <th className="px-3 py-2">Name</th>
                  <th className="px-3 py-2">Grade</th>
                  <th className="px-3 py-2">Credits</th>
                  <th className="px-3 py-2">Year</th>
                  <th className="px-3 py-2">Month</th>
                  <th className="px-3 py-2">Current A/G</th>
                  <th className="px-3 py-2">Edit</th>
                  <th className="px-3 py-2">Remove</th>
                </tr>
              </thead>
              <tbody>
                {activeCourses.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="px-3 py-8 text-center text-muted-foreground">
                      No courses currently mapped to this A/G category.
                    </td>
                  </tr>
                ) : activeCourses.map(({ course, courseKey, currentAg, originalAg }) => (
                  <tr key={courseKey} className="border-t bg-white">
                    <td className="px-3 py-2">{course.crs_id ?? course.id ?? '—'}</td>
                    <td className="px-3 py-2">{course.name ?? '—'}</td>
                    <td className="px-3 py-2">{getCourseGradeLabel(course)}</td>
                    <td className="px-3 py-2">{getCourseCreditsDisplay(course)}</td>
                    <td className="px-3 py-2">{course.year ?? '—'}</td>
                    <td className="px-3 py-2">{course.month ?? '—'}</td>
                    <td className="px-3 py-2">
                      {editingCourseKey === courseKey ? (
                        <select
                          value={editAgKey}
                          onChange={(event) => setEditAgKey(event.target.value as AgKey)}
                          className="h-9 rounded-md border border-input bg-background px-2 text-sm"
                        >
                          {AG_TYPES.map((type) => (
                            <option key={type.key} value={type.key}>
                              {type.short} - {type.label}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <span
                          className={`inline-flex rounded-md border px-2 py-1 text-xs font-semibold ${getAgMoveBadgeClass(
                            originalAg,
                            currentAg
                          )}`}
                        >
                          {getAgDisplayLabel(originalAg, currentAg)}
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {editingCourseKey === courseKey ? (
                        <div className="flex gap-2">
                          <Button size="sm" onClick={() => saveEdit(courseKey)}>
                            Save
                          </Button>
                          <Button size="sm" variant="outline" onClick={() => setEditingCourseKey(null)}>
                            Cancel
                          </Button>
                        </div>
                      ) : (
                        <Button size="sm" variant="outline" onClick={() => startEdit(courseKey, currentAg)}>
                          Edit
                        </Button>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Button
                        size="sm"
                        className="bg-red-500 text-white hover:bg-red-600"
                        onClick={() => removeCourse(courseKey)}
                      >
                        Remove
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="rounded-md border bg-slate-50 p-4">
            <h4 className="mb-3 text-base font-semibold">Add Course Mapping</h4>
            {availableCourses.length === 0 ? (
              <p className="text-sm text-muted-foreground">All courses are already mapped to this category.</p>
            ) : (
              <div className="overflow-x-auto rounded-md border bg-white">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-slate-100">
                    <tr className="text-left text-xs font-semibold text-slate-600">
                      <th className="px-3 py-2">Course Name</th>
                      <th className="px-3 py-2">CRS ID</th>
                      <th className="px-3 py-2">Grade</th>
                      <th className="px-3 py-2">Year</th>
                      <th className="px-3 py-2">Current A/G</th>
                      <th className="px-3 py-2">Map To</th>
                      <th className="px-3 py-2"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {availableCourses.map(({ course, courseKey, currentAg, removed }) => (
                      <tr key={courseKey} className={`border-t ${removed ? 'bg-red-50' : 'bg-white hover:bg-slate-50'}`}>
                        <td className="px-3 py-2 font-medium">
                          {removed && (
                            <span className="mr-1.5 rounded bg-red-100 px-1.5 py-0.5 text-xs font-semibold text-red-600">Removed</span>
                          )}
                          {course.name ?? '—'}
                        </td>
                        <td className="px-3 py-2 text-muted-foreground">{course.crs_id ?? course.id ?? '—'}</td>
                        <td className="px-3 py-2">{getCourseGradeLabel(course)}</td>
                        <td className="px-3 py-2">{course.year ?? '—'}</td>
                        <td className="px-3 py-2">
                          <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs font-semibold">
                            {currentAg ? currentAg.toUpperCase() : '—'}
                          </span>
                        </td>
                        <td className="px-3 py-2">
                          <select
                            value={rowAgKeys[courseKey] ?? agKey}
                            onChange={(e) => setRowAgKeys((prev) => ({ ...prev, [courseKey]: e.target.value as AgKey }))}
                            className="h-8 rounded-md border border-input bg-background px-2 text-xs"
                          >
                            {AG_TYPES.map((type) => (
                              <option key={type.key} value={type.key}>{type.short} — {type.label}</option>
                            ))}
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <Button size="sm" onClick={() => addCourse(courseKey)}>Add</Button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
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
export function AgRequirementTab({
  admissionReview,
  transcript,
  assignments,
  setAssignments,
  agRequired,
  setAgRequired,
  onAssignmentsSaved,
  loading,
  selectedAdmissionDecision,
}: {
  admissionReview: AdmissionReviewResponse | null;
  transcript?: TranscriptRecord | null;
  assignments: Record<string, CourseAssignment>;
  setAssignments: (value: Record<string, CourseAssignment>) => void;
  agRequired: Record<AgRequirementKey, number>;
  setAgRequired: (value: Record<AgRequirementKey, number>) => void;
  onAssignmentsSaved?: () => void;
  loading: boolean;
  selectedAdmissionDecision: AdmissionDecisionStatus | null;
}) {
  const [openAgKey, setOpenAgKey] = useState<AgRequirementKey | null>(null);
  const rows: AdmissionAgRow[] = useMemo(() => {
    const backendRows = admissionReview?.ag_review?.rows ?? [];
    if (backendRows.length > 0) {
      return backendRows
        .map((row) => {
          const key = normalizeRequirementKey(row.key);
          if (!key) return null;
          const required = agRequired[key] ?? row.required ?? DEFAULT_AG_REQUIRED[key];
          const actual = toNumber(row.actual, 0);
          const def = toNumber(row.def, 0);
          return {
            ...row,
            key,
            label: row.label || getAgRowLabel(key),
            required,
            actual,
            def,
          };
        })
        .filter(Boolean) as AdmissionAgRow[];
    }
    return (['a', 'b', 'c', 'd1', 'd2', 'd', 'e', 'f', 'g'] as AgRequirementKey[]).map((key) => ({
      key,
      label: getAgRowLabel(key),
      required: agRequired[key],
      actual: 0,
      def: agRequired[key],
      subjects: [],
      subject_counts: {},
    }));
  }, [admissionReview, agRequired]);
  const decisionBadgeClass =
    selectedAdmissionDecision === 'admitted'
      ? 'bg-green-100 text-green-800 border-green-300'
      : selectedAdmissionDecision === 'denied'
        ? 'bg-red-100 text-red-800 border-red-300'
        : selectedAdmissionDecision === 'waitlisted'
          ? 'bg-amber-100 text-amber-800 border-amber-300'
          : 'bg-slate-100 text-slate-500 border-slate-300';

  return (
    <div className="flex-1 min-h-0 overflow-y-auto rounded-md border bg-white p-3">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <h3 className="text-lg font-semibold">College Preparatory Semesters</h3>
          {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
        </div>
        <span className={`inline-flex items-center rounded-full border px-3 py-0.5 text-xs font-bold ${decisionBadgeClass}`}>
          {selectedAdmissionDecision === 'admitted' ? 'Admitted'
            : selectedAdmissionDecision === 'denied' ? 'Denied'
            : selectedAdmissionDecision === 'waitlisted' ? 'Waitlisted'
            : 'Pending'}
        </span>
      </div>

      {/* At-a-glance summary: how many areas are satisfied vs. short. */}
      {(() => {
        const deficient = rows.filter((r) => r.def > 0).length;
        const short = rows.reduce((s, r) => s + (r.def > 0 ? r.def : 0), 0);
        const met = rows.length - deficient;
        return (
          <div className="mb-3 flex flex-wrap items-center gap-2 text-xs">
            <span className="inline-flex items-center rounded-full bg-emerald-100 px-2.5 py-0.5 font-semibold text-emerald-800">
              {met} of {rows.length} areas met
            </span>
            {deficient > 0 && (
              <span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 font-semibold text-red-800">
                {deficient} area{deficient === 1 ? '' : 's'} short · {short} semester{short === 1 ? '' : 's'} needed
              </span>
            )}
          </div>
        );
      })()}

      <div className="overflow-hidden rounded-md border">
        <table className="w-full table-fixed text-xs">
          <thead className="bg-slate-100 text-left">
            <tr>
              <th className="w-[42%] px-3 py-2">College Preparatory Semesters</th>
              <th className="w-[13%] px-2 py-2 text-center">Required</th>
              <th className="w-[13%] px-2 py-2 text-center">Actual</th>
              <th className="w-[10%] px-2 py-2 text-center">DEF</th>
              <th className="w-[22%] px-2 py-2 text-center">Subject Count</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.key} className="border-t align-middle">
                <td className="px-3 py-2 font-semibold leading-tight">
                  {row.label || getAgRowLabel(row.key)}
                </td>
                <td className="px-2 py-2 text-center">
                  <Input
                    type="number"
                    value={agRequired[row.key] ?? row.required}
                    onChange={(event) =>
                      setAgRequired({
                        ...agRequired,
                        [row.key]: toNumber(event.target.value, 0),
                      })
                    }
                    className="mx-auto h-8 w-20 text-center text-xs"
                  />
                </td>
                <td className="px-2 py-2 text-center">
                  <Input
                    type="number"
                    value={formatCount(row.actual)}
                    readOnly
                    className={`mx-auto h-8 w-20 bg-slate-50 text-center text-xs font-semibold ${
                      row.def > 0 ? 'text-red-600' : 'text-green-600'
                    }`}
                  />
                </td>
                <td
                  className={
                    row.def > 0
                      ? 'px-2 py-2 text-center font-bold text-red-600'
                      : 'px-2 py-2 text-center font-bold text-green-600'
                  }
                >
                  {formatCount(row.def)}
                </td>
                <td className="px-2 py-2 text-center">
                  <button
                    className="text-xs font-semibold text-blue-600 underline"
                    onClick={() => setOpenAgKey(row.key)}
                  >
                    View / Edit Courses
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {openAgKey && (
        <CourseEditDialog
          open={Boolean(openAgKey)}
          onOpenChange={(open) => {
            if (!open) {
              setOpenAgKey(null);
              onAssignmentsSaved?.();
            }
          }}
          agKey={openAgKey}
          courses={transcript?.courses ?? []}
          assignments={assignments}
          setAssignments={setAssignments}
          admissionCourseAssignments={admissionReview?.ag_review?.course_assignments ?? []}
        />
      )}
    </div>
  );
}
function GpaCalcBox({
  bucketKey,
  bucket,
  bucketEdits,
  setBucketEdits,
  gradePoints,
  setGradePoints,
  honorsBonus,
  setHonorsBonus,
}: {
  bucketKey: GpaBucketKey;
  bucket?: BackendGpaBucket;
  bucketEdits: GpaBucketEdits;
  setBucketEdits: Dispatch<SetStateAction<GpaBucketEdits>>;
  gradePoints: Record<BasicGrade, number>;
  setGradePoints: (value: Record<BasicGrade, number>) => void;
  honorsBonus: number;
  setHonorsBonus: (value: number) => void;
}) {
  const grades: BasicGrade[] = ['A', 'B', 'C', 'D', 'F'];
  const bucketEdit = bucketEdits[bucketKey];
  const updateGradePoint = (grade: BasicGrade, value: string) => {
    setGradePoints({
      ...gradePoints,
      [grade]: toNumber(value, 0),
    });
  };
  const updateSemesterCount = (grade: BasicGrade, value: string) => {
    const nextValue = Math.max(toNumber(value, 0), 0);
    setBucketEdits((previous) => ({
      ...previous,
      [bucketKey]: {
        ...(previous[bucketKey] ?? {}),
        grade_counts: {
          ...(previous[bucketKey]?.grade_counts ?? {}),
          [grade]: nextValue,
        },
      },
    }));
  };
  const updateHonorsCount = (value: string) => {
    const nextValue = Math.max(toNumber(value, 0), 0);
    setBucketEdits((previous) => ({
      ...previous,
      [bucketKey]: {
        ...(previous[bucketKey] ?? {}),
        honors_count: nextValue,
      },
    }));
  };
  const totalSemesters = getEditedBucketSemesters(bucket, bucketEdit);
  const totalPoints = getEditedBucketTotalPoints(bucket, bucketEdit, gradePoints, honorsBonus);
  const calculatedGpa = getEditedBucketGpa(bucket, bucketEdit, gradePoints, honorsBonus);
  const honorsCount = getEditedHonorsCount(bucket, bucketEdit);
  // Drop the word "Calc"/"Calculation" from the card title (e.g. "Cumulative
  // GPA Calc" → "Cumulative GPA").
  const cardTitle = (bucket?.label ?? 'GPA').replace(/\s*calc(ulation)?\b/gi, '').trim() || 'GPA';
  return (
    <div className="rounded-md border bg-white p-3 shadow-sm">
      <h5 className="mb-2 text-sm font-semibold">{cardTitle}</h5>
      <div className="overflow-hidden rounded-md border">
        <table className="w-full text-xs">
          <thead className="bg-slate-50 text-muted-foreground">
            <tr>
              <th className="px-2 py-1.5 text-left">Grade</th>
              <th className="px-2 py-1.5 text-center">Sem</th>
              <th className="px-2 py-1.5 text-center">Point</th>
              <th className="px-2 py-1.5 text-center">Pts</th>
            </tr>
          </thead>
          <tbody>
            {grades.map((grade) => {
              const semesters = getEditedGradeCount(bucket, bucketEdit, grade);
              const points = semesters * gradePoints[grade];
              return (
                <tr key={grade} className="border-t">
                  <td className="px-2 py-1.5 font-medium">{grade}</td>
                  <td className="px-2 py-1.5 text-center">
                    <Input
                      type="number"
                      min={0}
                      step={1}
                      value={semesters}
                      onChange={(event) => updateSemesterCount(grade, event.target.value)}
                      className="mx-auto h-7 w-16 text-center text-xs"
                    />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    <Input
                      type="number"
                      value={gradePoints[grade]}
                      onChange={(event) => updateGradePoint(grade, event.target.value)}
                      className="mx-auto h-7 w-16 text-center text-xs"
                    />
                  </td>
                  <td className="px-2 py-1.5 text-center">
                    {semesters ? formatCount(points) : ''}
                  </td>
                </tr>
              );
            })}
            <tr className="border-t">
              <td className="px-2 py-1.5 font-medium">Honors / AP</td>
              <td className="px-2 py-1.5 text-center">
                <Input
                  type="number"
                  min={0}
                  step={1}
                  value={honorsCount}
                  onChange={(event) => updateHonorsCount(event.target.value)}
                  className="mx-auto h-7 w-16 text-center text-xs"
                />
              </td>
              <td className="px-2 py-1.5 text-center">
                <Input
                  type="number"
                  value={honorsBonus}
                  onChange={(event) => setHonorsBonus(toNumber(event.target.value, 0))}
                  className="mx-auto h-7 w-16 text-center text-xs"
                />
              </td>
              <td className="px-2 py-1.5 text-center">
                {honorsCount ? formatCount(honorsCount * honorsBonus) : ''}
              </td>
            </tr>
            <tr className="border-t bg-slate-50 font-semibold">
              <td className="px-2 py-1.5">Total</td>
              <td className="px-2 py-1.5 text-center">{formatCount(totalSemesters)}</td>
              <td className="px-2 py-1.5 text-center">—</td>
              <td className="px-2 py-1.5 text-center">{formatCount(totalPoints)}</td>
            </tr>
            <tr className="border-t bg-slate-50 font-semibold">
              <td className="px-2 py-1.5">GPA</td>
              <td className="px-2 py-1.5 text-center" colSpan={3}>
                {calculatedGpa ?? '—'}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  );
}
export function GpaCalculationTab({
  admissionReview,
  gradePoints,
  setGradePoints,
  honorsBonus,
  setHonorsBonus,
  californiaResidentMinGpa,
  gpaBucketEdits,
  setGpaBucketEdits,
  selectedAdmissionDecision,
  onDecisionSave,
  loading,
  isSaving,
  studentDbId,
}: {
  studentDbId?: number | null;
  admissionReview: AdmissionReviewResponse | null;
  gradePoints: Record<BasicGrade, number>;
  setGradePoints: (value: Record<BasicGrade, number>) => void;
  honorsBonus: number;
  setHonorsBonus: (value: number) => void;
  honorsMaxSemesters: number;
  setHonorsMaxSemesters: (value: number) => void;
  honorsMax10thGradeSemesters: number;
  setHonorsMax10thGradeSemesters: (value: number) => void;
  csulbScoreMultiplier: number;
  setCsulbScoreMultiplier: (value: number) => void;
  californiaResidentMinGpa: number;
  setCaliforniaResidentMinGpa: (value: number) => void;
  csulbThreshold: number;
  setCsulbThreshold: (value: number) => void;
  stemThreshold: number;
  setStemThreshold: (value: number) => void;
  gpaBucketEdits: GpaBucketEdits;
  setGpaBucketEdits: Dispatch<SetStateAction<GpaBucketEdits>>;
  selectedAdmissionDecision: AdmissionDecisionStatus | null;
  onDecisionSave: (decision: AdmissionDecisionStatus | null) => Promise<void>;
  loading: boolean;
  isSaving?: boolean;
}) {
  const buckets = admissionReview?.gpa_calculation?.buckets ?? {};
  const backendDecision = admissionReview?.admission_decision;
  // Handbook verdict is reported up by AiAuditPanel so this card can show ONE
  // decision plus a single "checks agree / disagree" line, instead of three
  // competing verdict badges.
  const [handbookVerdict, setHandbookVerdict] = useState<Verdict | null>(null);
  const [showChecks, setShowChecks] = useState(false);
  const cumulativeGpa = getEditedBucketGpa(
    buckets.cumulative,
    gpaBucketEdits.cumulative,
    gradePoints,
    honorsBonus
  );
  const englishGpa = getEditedBucketGpa(
    buckets.english,
    gpaBucketEdits.english,
    gradePoints,
    honorsBonus
  );
  const mathGpa = getEditedBucketGpa(
    buckets.math,
    gpaBucketEdits.math,
    gradePoints,
    honorsBonus
  );
  const scienceGpa = getEditedBucketGpa(
    buckets.science,
    gpaBucketEdits.science,
    gradePoints,
    honorsBonus
  );
  // Index formulas moved to the score dashboard tiles (score_summary values);
  // the live-edit bucket GPAs above still drive the backend recalculation.
  void cumulativeGpa; void englishGpa; void mathGpa; void scienceGpa;
  const agDeficitsIgnoringG = getAgDeficitsIgnoringG(admissionReview);
  const agSatisfiedIgnoringG = agDeficitsIgnoringG.length === 0;
  const minimumGpa = toNumber(
    backendDecision?.minimum_gpa_required,
    californiaResidentMinGpa
  );
  const minimumGpaSatisfied = cumulativeGpa != null && cumulativeGpa >= minimumGpa;
  // The recommended decision follows the Final Audit when present; otherwise it
  // falls back to the A-F + GPA pre-check.
  const finalAudit = admissionReview?.final_audit;
  const fallbackRecommendedDecision: AdmissionDecisionStatus = finalAudit
    ? finalAudit.outcome === 'failed_audit_rescinded'
      ? 'denied'
      : 'admitted'
    : agSatisfiedIgnoringG && minimumGpaSatisfied
      ? 'admitted'
      : 'denied';
  const recommendedDecision =
    normalizeDecisionStatus(backendDecision?.recommended_decision) ??
    fallbackRecommendedDecision;
  const activeDecision = selectedAdmissionDecision ?? recommendedDecision;
  const decisionReason = buildAdmissionReasonFallback({
    admissionReview,
    selectedDecision: activeDecision,
    cumulativeGpa,
    minimumGpa,
  });

  // Until the review API has returned, always show "Calculating…" — never a
  // provisional/stored decision that would flip once the real result lands.
  const computingDecision = loading || !admissionReview;

  const decisionCardClass =
    activeDecision === 'admitted'
      ? 'border-green-200 bg-green-50'
      : activeDecision === 'denied'
        ? 'border-red-200 bg-red-50'
        : activeDecision === 'waitlisted'
          ? 'border-amber-200 bg-amber-50'
          : 'border-slate-200 bg-white';

  // ── The two automated checks, expressed relative to the current decision ──
  // Neither renders its own headline verdict any more; they either agree with
  // the decision above or they don't, and that is the only thing surfaced.
  const decLabel = (d: AdmissionDecisionStatus | null | undefined) =>
    d === 'admitted' ? 'Admit' : d === 'denied' ? 'Deny' : d === 'waitlisted' ? 'Waitlist' : '—';
  const requirementsDecision: AdmissionDecisionStatus | null = finalAudit
    ? finalAudit.outcome === 'failed_audit_rescinded'
      ? 'denied'
      : 'admitted'
    : null;
  const handbookDecision = normalizeDecisionStatus(
    handbookVerdict?.overridden ? handbookVerdict?.override_decision : handbookVerdict?.decision
  );
  const checkList: Array<{ key: string; label: string; decision: AdmissionDecisionStatus }> = [];
  if (requirementsDecision) checkList.push({ key: 'req', label: 'Requirements', decision: requirementsDecision });
  if (handbookDecision) checkList.push({ key: 'hb', label: 'Handbook', decision: handbookDecision });
  const disagreeing = checkList.filter((c) => c.decision !== activeDecision);
  const allAgree = checkList.length > 0 && disagreeing.length === 0;
  const checksSummary = allAgree
    ? checkList.length === 1
      ? 'Checks agree'
      : 'Both checks agree'
    : disagreeing.map((c) => `${c.label} suggests ${decLabel(c.decision)}`).join(' · ');
  const decisionTextClass =
    activeDecision === 'admitted'
      ? 'text-green-700'
      : activeDecision === 'denied'
        ? 'text-red-700'
        : activeDecision === 'waitlisted'
          ? 'text-amber-700'
          : 'text-slate-600';

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 overflow-y-auto">

      {/* ── Score dashboard (order-2: verdict reads first, evidence second) ── */}
      {!computingDecision && (() => {
        const ss = admissionReview?.gpa_calculation?.score_summary ?? {};
        const fai = admissionReview?.final_audit?.inputs ?? {};
        const californiaResidentMinGpa = fai.applied_min_gpa ?? 2.5;
        const csulbThreshold = fai.applied_csulb_index_min ?? 3200;
        const stemThreshold = fai.stem_index_min ?? 0;
        const fmt = (v: number | null | undefined, d = 2) => (v == null ? '—' : Number(v).toFixed(d));
        const tiles: Array<{ label: string; value: string; target?: string; ok?: boolean | null; pct?: number }> = [
          { label: 'Cumulative GPA', value: fmt(ss.cumulative_gpa), target: `min ${fmt(californiaResidentMinGpa)}`,
            ok: ss.cumulative_gpa == null ? null : Number(ss.cumulative_gpa) >= (californiaResidentMinGpa ?? 0),
            pct: ss.cumulative_gpa == null ? 0 : Math.min(100, (Number(ss.cumulative_gpa) / 4) * 100) },
          { label: 'English GPA', value: fmt(ss.english_gpa), pct: ss.english_gpa == null ? 0 : Math.min(100, (Number(ss.english_gpa) / 4) * 100) },
          { label: 'Math GPA', value: fmt(ss.math_gpa), pct: ss.math_gpa == null ? 0 : Math.min(100, (Number(ss.math_gpa) / 4) * 100) },
          { label: 'Science GPA', value: fmt(ss.science_gpa), pct: ss.science_gpa == null ? 0 : Math.min(100, (Number(ss.science_gpa) / 4) * 100) },
          { label: 'CSULB Index', value: fmt(ss.csulb_score, 0), target: `min ${csulbThreshold}`,
            ok: ss.csulb_score == null ? null : Number(ss.csulb_score) >= (csulbThreshold ?? 0),
            pct: ss.csulb_score == null ? 0 : Math.min(100, (Number(ss.csulb_score) / Math.max(csulbThreshold || 1, 1)) * 100) },
          { label: 'STEM Index', value: fmt(ss.stem_index, 0), target: stemThreshold ? `min ${stemThreshold}` : 'not gated',
            ok: !stemThreshold ? null : ss.stem_index == null ? null : Number(ss.stem_index) >= stemThreshold,
            pct: ss.stem_index == null ? 0 : Math.min(100, (Number(ss.stem_index) / Math.max(stemThreshold || 3600, 1)) * 100) },
        ];
        return (
          <div className="order-2 grid shrink-0 grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
            {tiles.map((t) => (
              <div key={t.label} className={`flex h-full flex-col rounded-lg border p-2.5 ${t.ok === false ? 'border-red-200 bg-red-50/60' : t.ok ? 'border-emerald-200 bg-emerald-50/60' : 'border-slate-200 bg-white'}`}>
                <div className="flex items-baseline justify-between gap-1">
                  <span className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{t.label}</span>
                  {t.ok != null && (
                    <span className={`text-[10px] font-bold ${t.ok ? 'text-emerald-600' : 'text-red-600'}`}>{t.ok ? 'MET' : 'BELOW'}</span>
                  )}
                </div>
                <div className={`mt-0.5 text-xl font-bold tabular-nums ${t.ok === false ? 'text-red-700' : 'text-slate-800'}`}>{t.value}</div>
                {/* Reserve the target line height even when absent so the bar
                    below aligns across every card (not above/below its peers). */}
                <div className="text-[10px] text-slate-400">{t.target ?? ' '}</div>
                <div className="mt-auto h-1 overflow-hidden rounded-full bg-slate-100">
                  <div className={`h-full rounded-full ${t.ok === false ? 'bg-red-400' : t.ok ? 'bg-emerald-500' : 'bg-slate-400'}`} style={{ width: `${t.pct ?? 0}%` }} />
                </div>
              </div>
            ))}
          </div>
        );
      })()}

      {/* ── Admission Decision (decision + Final Audit, clubbed) ── */}
      {/* Until the review is computed, show "Calculating…" instead of a
          provisional fallback decision (which would briefly read Denied before
          flipping to the real result). */}
      <div className={`order-1 shrink-0 overflow-hidden rounded-lg border ${computingDecision ? 'border-slate-200 bg-slate-50' : decisionCardClass}`}>
        <div className="p-4">
          {computingDecision ? (
            <span className="inline-flex items-center gap-2 text-sm font-semibold text-slate-500">
              <Loader2 className="h-4 w-4 animate-spin" /> Calculating…
            </span>
          ) : (
            <>
              {/* What the decision is */}
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <span className={`text-2xl font-bold leading-none ${decisionTextClass}`}>
                  {activeDecision === 'admitted' ? 'Admitted'
                    : activeDecision === 'denied' ? 'Denied'
                    : activeDecision === 'waitlisted' ? 'Waitlisted'
                    : 'Pending'}
                </span>
                {isSaving && <Loader2 className="h-3.5 w-3.5 animate-spin text-slate-400" />}
              </div>

              {/* Why */}
              <p className="mt-2 text-sm leading-relaxed text-slate-700">
                {(decisionReason || '').replace(/^(Admitted|Denied|Waitlisted):\s*/i, '')}
              </p>

              {/* Change it — status above is a state, these are actions */}
              <div className="mt-3 inline-flex rounded-lg border border-slate-300 bg-white p-0.5">
                {([['admitted', 'Admit'], ['denied', 'Deny'], ['waitlisted', 'Waitlist']] as Array<[AdmissionDecisionStatus, string]>).map(([d, label]) => (
                  <button
                    key={d}
                    type="button"
                    disabled={isSaving || loading}
                    onClick={() => onDecisionSave(d)}
                    aria-pressed={activeDecision === d}
                    className={`rounded-md px-3.5 py-1.5 text-xs font-semibold transition-colors disabled:opacity-50 ${
                      activeDecision === d
                        ? d === 'admitted'
                          ? 'bg-green-600 text-white'
                          : d === 'denied'
                            ? 'bg-red-600 text-white'
                            : 'bg-amber-500 text-white'
                        : 'text-slate-600 hover:bg-slate-100'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>

        {/* One quiet line: do the checks agree? Detail only on request.
            The expandable area stays mounted (hidden) so the handbook verdict
            still loads and can feed the line above. */}
        <div className="border-t border-black/5 bg-white/60">
          {!computingDecision && checkList.length > 0 && (
            <button
              type="button"
              onClick={() => setShowChecks((v) => !v)}
              className="flex w-full items-center gap-1.5 px-4 py-2 text-left"
            >
              {allAgree
                ? <Check className="h-3.5 w-3.5 shrink-0 text-emerald-600" />
                : <AlertTriangle className="h-3.5 w-3.5 shrink-0 text-amber-600" />}
              <span className={`truncate text-xs ${allAgree ? 'text-slate-500' : 'font-medium text-amber-800'}`}>
                {checksSummary}
              </span>
              <span className="ml-auto shrink-0 text-[11px] text-slate-500">
                {showChecks ? 'Hide' : 'Why?'}
              </span>
            </button>
          )}

          <div className={showChecks ? 'space-y-2.5 border-t border-black/5 px-4 pb-3 pt-2.5' : 'hidden'}>
            {finalAudit && (() => {
              const c = finalAudit.checks ?? {};
              const items: Array<[string, boolean | undefined]> = [
                ['A-G', c.ag_completion],
                ['GPA', c.gpa_minimum],
                ['CSULB', c.csulb_index],
                ['STEM', c.stem_index],
                ['Graduation', c.hs_graduation],
              ];
              return (
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1.5">
                  <span className="w-20 shrink-0 text-[11px] font-medium text-slate-500">Requirements</span>
                  <div className="flex flex-wrap gap-1.5">
                    {items.map(([label, ok]) => (
                      <span
                        key={label}
                        className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                          ok ? 'bg-green-100 text-green-800' : 'bg-red-100 text-red-800'
                        }`}
                      >
                        {ok ? '✓' : '✗'} {label}
                      </span>
                    ))}
                  </div>
                </div>
              );
            })()}

            {studentDbId != null && (
              <div className="flex flex-wrap items-baseline gap-x-3">
                <span className="w-20 shrink-0 text-[11px] font-medium text-slate-500">Handbook</span>
                <div className="min-w-0 flex-1">
                  {!handbookDecision && (
                    <p className="text-[11px] text-slate-400">None for this term.</p>
                  )}
                  <AiAuditPanel
                    studentId={studentDbId}
                    embedded
                    onVerdictChange={setHandbookVerdict}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      <div className="order-3 flex shrink-0 items-center gap-2 px-0.5">
        <h4 className="text-sm font-semibold text-slate-700">GPA breakdown</h4>
        <span className="text-[11px] text-slate-400">per-course points behind each GPA above — edit grades/honors to recalculate live</span>
        {loading && <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />}
      </div>
      <div className="order-4 grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <GpaCalcBox
          bucketKey="cumulative"
          bucket={buckets.cumulative}
          bucketEdits={gpaBucketEdits}
          setBucketEdits={setGpaBucketEdits}
          gradePoints={gradePoints}
          setGradePoints={setGradePoints}
          honorsBonus={honorsBonus}
          setHonorsBonus={setHonorsBonus}
        />
        <GpaCalcBox
          bucketKey="math"
          bucket={buckets.math}
          bucketEdits={gpaBucketEdits}
          setBucketEdits={setGpaBucketEdits}
          gradePoints={gradePoints}
          setGradePoints={setGradePoints}
          honorsBonus={honorsBonus}
          setHonorsBonus={setHonorsBonus}
        />
        <GpaCalcBox
          bucketKey="english"
          bucket={buckets.english}
          bucketEdits={gpaBucketEdits}
          setBucketEdits={setGpaBucketEdits}
          gradePoints={gradePoints}
          setGradePoints={setGradePoints}
          honorsBonus={honorsBonus}
          setHonorsBonus={setHonorsBonus}
        />
        <GpaCalcBox
          bucketKey="science"
          bucket={buckets.science}
          bucketEdits={gpaBucketEdits}
          setBucketEdits={setGpaBucketEdits}
          gradePoints={gradePoints}
          setGradePoints={setGradePoints}
          honorsBonus={honorsBonus}
          setHonorsBonus={setHonorsBonus}
        />
      </div>
      {/* (Calculated Score table removed — the score dashboard tiles at the top
          present the same numbers with thresholds and pass/fail state.) */}
    </div>
  );
}

// ── Public wrapper ────────────────────────────────────────────────────────────
// Manages all admission-review state and renders the requested tab. Keeping a
// single instance mounted while the user toggles between 'agRequirement' and
// 'gpaCalculation' preserves edits and avoids re-fetching the backend.

export type AdmissionReviewMode = 'agRequirement' | 'gpaCalculation';

export function AdmissionReviewTabs({
  transcript,
  mode,
  onDecisionSaved,
}: {
  transcript?: TranscriptRecord | null;
  mode: AdmissionReviewMode;
  onDecisionSaved?: (decision: AdmissionDecisionStatus) => void;
}) {
  const { currentTerm, terms } = useTerm();
  const yearIntake = terms.find((t) => t.id === currentTerm)?.term_name ?? null;
  const [assignments, setAssignments] = useState<Record<string, CourseAssignment>>({});
  const [agRequired, setAgRequired] = useState<Record<AgRequirementKey, number>>({ ...DEFAULT_AG_REQUIRED });
  const [gradePoints, setGradePoints] = useState<Record<BasicGrade, number>>({ ...DEFAULT_GRADE_POINTS });
  const [honorsBonus, setHonorsBonus] = useState(1);
  const [honorsMaxSemesters, setHonorsMaxSemesters] = useState(8);
  const [honorsMax10thGradeSemesters, setHonorsMax10thGradeSemesters] = useState(2);
  const [csulbScoreMultiplier, setCsulbScoreMultiplier] = useState(800);
  const [californiaResidentMinGpa, setCaliforniaResidentMinGpa] = useState(2.5);
  const [csulbThreshold, setCsulbThreshold] = useState(3200);
  const [stemThreshold, setStemThreshold] = useState(0);
  const [agHsGrades, setAgHsGrades] = useState<number[]>([8, 9, 10, 11, 12]);
  const [gpaHsGrades, setGpaHsGrades] = useState<number[]>([8, 9, 10, 11, 12]);
  const [gpaBucketEdits, setGpaBucketEdits] = useState<GpaBucketEdits>({});
  const [selectedAdmissionDecision, setSelectedAdmissionDecision] = useState<AdmissionDecisionStatus | null>(null);
  const [admissionReview, setAdmissionReview] = useState<AdmissionReviewResponse | null>(null);
  const [admissionLoading, setAdmissionLoading] = useState(false);
  // True for the whole init sequence (criteria load -> calc -> stored-override
  // patch -> settle). The decision badge stays "Calculating…" until this clears,
  // so it reveals only the final settled decision and never flips mid-init.
  const [isInitializing, setIsInitializing] = useState(true);
  const [admissionError, setAdmissionError] = useState<string | null>(null);
  const [isSaving, setIsSaving] = useState(false);

  // Track whether the user has explicitly chosen a decision (vs auto-recommended)
  const userOverrodeDecisionRef = useRef(false);
  // Prevent auto-saves from firing during initial load
  const isInitializedRef = useRef(false);
  // Debounce timer for GPA edits
  const gpaDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const assignDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Signature of the inputs the last calculation ran on, so the recompute effect
  // can skip a redundant pass (notably the one that would otherwise fire right
  // after init seeds these states — the source of the decision "flip").
  const computeSigRef = useRef<string>('');
  // Stable ref to latest save function (avoids stale closure in debounce)
  const saveStateRef = useRef<() => Promise<void>>(async () => {});

  const getManualMappingsPayload = (sourceAssignments = assignments) =>
    Object.values(sourceAssignments)
      .filter((assignment) => assignment.agKey || assignment.removed)
      .map((assignment) => ({
        course_id: assignment.courseKey,
        target_ag: assignment.removed ? 'removed' : assignment.agKey,
      }));

  const runAdmissionCalculation = async (
    overrides?: Partial<{
      assignments: Record<string, CourseAssignment>;
      agRequired: Record<AgRequirementKey, number>;
      gradePoints: Record<BasicGrade, number>;
      honorsBonus: number;
      honorsMaxSemesters: number;
      honorsMax10thGradeSemesters: number;
      csulbScoreMultiplier: number;
      californiaResidentMinGpa: number;
      csulbThreshold: number;
      stemThreshold: number;
      agHsGrades: number[];
      gpaHsGrades: number[];
    }>
  ) => {
    if (!transcript) return;
    const nextAssignments = overrides?.assignments ?? assignments;
    const nextAgRequired = overrides?.agRequired ?? agRequired;
    const nextGradePoints = overrides?.gradePoints ?? gradePoints;
    const nextHonorsBonus = overrides?.honorsBonus ?? honorsBonus;
    const nextHonorsMaxSemesters = overrides?.honorsMaxSemesters ?? honorsMaxSemesters;
    const nextHonorsMax10thGradeSemesters = overrides?.honorsMax10thGradeSemesters ?? honorsMax10thGradeSemesters;
    const nextCsulbScoreMultiplier = overrides?.csulbScoreMultiplier ?? csulbScoreMultiplier;
    const nextCaliforniaResidentMinGpa = overrides?.californiaResidentMinGpa ?? californiaResidentMinGpa;
    const nextCsulbThreshold = overrides?.csulbThreshold ?? csulbThreshold;
    const nextStemThreshold = overrides?.stemThreshold ?? stemThreshold;
    const nextAgHsGrades = overrides?.agHsGrades ?? agHsGrades;
    const nextGpaHsGrades = overrides?.gpaHsGrades ?? gpaHsGrades;
    try {
      setAdmissionLoading(true);
      setAdmissionError(null);
      const result = await calculateAdmissionReview({
        student: transcript,
        year_intake: yearIntake ?? undefined,
        config: {
          ag_required: nextAgRequired,
          grade_points: nextGradePoints,
          honors_bonus_points: nextHonorsBonus,
          honors_max_semesters: nextHonorsMaxSemesters,
          honors_max_10th_grade_semesters: nextHonorsMax10thGradeSemesters,
          csulb_score_multiplier: nextCsulbScoreMultiplier,
          california_resident_min_gpa: nextCaliforniaResidentMinGpa,
          csulb_threshold: nextCsulbThreshold,
          stem_threshold: nextStemThreshold,
          ag_hs_grades: nextAgHsGrades,
          gpa_hs_grades: nextGpaHsGrades,
        },
        manual_mappings: getManualMappingsPayload(nextAssignments),
      });
      setAdmissionReview(result);
      // Auto-update and auto-save recommended decision unless user explicitly chose one
      if (!userOverrodeDecisionRef.current && result) {
        const rec = normalizeDecisionStatus(result.admission_decision?.recommended_decision);
        if (rec) {
          setSelectedAdmissionDecision(rec);
          // Persist the recommendation silently (reviewed=false — not yet human-confirmed)
          void saveCurrentState(result, rec, true, false);
        }
      }
      return result;
    } catch (error) {
      setAdmissionError(error instanceof Error ? error.message : 'Failed to calculate admission review');
      return null;
    } finally {
      setAdmissionLoading(false);
    }
  };

  // ── Persist current state to backend (no extra recalculation) ──
  const saveCurrentState = async (
    overrideResult?: AdmissionReviewResponse | null,
    overrideDecision?: AdmissionDecisionStatus | null,
    silent = false,
    reviewed?: boolean,
  ) => {
    const studentId = Number(transcript?.db_id ?? transcript?.id);
    if (!studentId) return;
    setIsSaving(true);
    try {
      const sourceResult = overrideResult !== undefined ? overrideResult : admissionReview;
      const agOverrides: Partial<Record<AgKey, number>> = {};
      for (const row of sourceResult?.ag_review?.rows ?? []) {
        const key = normalizeRequirementKey(row.key);
        if (key) agOverrides[key] = toNumber(row.actual, 0);
      }
      const sourceBuckets = sourceResult?.gpa_calculation?.buckets ?? {};
      const cumGpa  = getEditedBucketGpa(sourceBuckets.cumulative, gpaBucketEdits.cumulative, gradePoints, honorsBonus);
      const engGpa  = getEditedBucketGpa(sourceBuckets.english,    gpaBucketEdits.english,    gradePoints, honorsBonus);
      const mathGpa = getEditedBucketGpa(sourceBuckets.math,       gpaBucketEdits.math,       gradePoints, honorsBonus);
      const sciGpa  = getEditedBucketGpa(sourceBuckets.science,    gpaBucketEdits.science,    gradePoints, honorsBonus);
      // CSULB Index = cum*200 + eng*500 + math*500; STEM Index = math*600 + sci*600.
      const csulbScore = cumGpa  != null ? Math.round(cumGpa * 200 + (engGpa ?? 0) * 500 + (mathGpa ?? 0) * 500) : null;
      const stemScore  = mathGpa != null && sciGpa != null ? Math.round(mathGpa * 600 + sciGpa * 600) : null;
      const courseOverridesLog: Record<string, any> = {};
      for (const [key, assignment] of Object.entries(assignments)) {
        if (assignment.agKey || assignment.removed) {
          courseOverridesLog[key] = { agKey: assignment.agKey, removed: assignment.removed ?? false };
        }
      }
      const decision = overrideDecision !== undefined ? overrideDecision : selectedAdmissionDecision;
      await saveAdmissionResult({
        student_id: studentId,
        year_intake: yearIntake ?? undefined,
        admission_decision: decision ?? undefined,
        ag_overrides: agOverrides,
        gpa_extracted: transcript?.gpa != null ? Number(transcript.gpa) : undefined,
        gpa_cumulative: cumGpa,
        gpa_english: engGpa,
        gpa_math: mathGpa,
        gpa_science: sciGpa,
        csulb_score: csulbScore,
        stem_score: stemScore,
        course_overrides: Object.keys(courseOverridesLog).length > 0 ? courseOverridesLog : null,
        reviewed: reviewed,
      });
      if (!silent) toast.success('Saved');
    } catch (err: any) {
      toast.error(err?.message || 'Failed to save');
    } finally {
      setIsSaving(false);
    }
  };

  // Keep saveStateRef fresh so debounce timer always calls the latest version
  saveStateRef.current = () => saveCurrentState(admissionReview, undefined, true);

  // Auto-save GPA edits (debounced 1.5 s, silent)
  useEffect(() => {
    if (!isInitializedRef.current) return;
    if (gpaDebounceRef.current) clearTimeout(gpaDebounceRef.current);
    gpaDebounceRef.current = setTimeout(() => { void saveStateRef.current(); }, 1500);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [gpaBucketEdits, gradePoints, honorsBonus]);

  // Auto-recalculate + silent save when A-G course assignments change
  const handleAssignmentsSaved = async () => {
    if (!isInitializedRef.current) return;
    const result = await runAdmissionCalculation();
    if (result) await saveCurrentState(result, undefined, true);
  };

  // Recompute A-G units + GPA immediately whenever anything that drives the
  // calculation changes — course assignments (add/remove/remap in View/Edit
  // Courses) or any institution-criteria-derived value the user edits in the
  // dialog (A-G required counts, HS grade levels, GPA points/honors, CSULB/STEM
  // thresholds, resident GPA). Both tabs update live without closing the modal.
  // Debounced to coalesce rapid edits.
  useEffect(() => {
    if (!isInitializedRef.current) return;
    const sig = JSON.stringify([
      assignments, agRequired, agHsGrades, gpaHsGrades,
      gradePoints, honorsBonus, csulbThreshold, stemThreshold, californiaResidentMinGpa,
    ]);
    // Inputs unchanged since the last calc (e.g. the effect firing right after
    // init seeded these states) — don't recompute, which prevents the flip.
    if (sig === computeSigRef.current) return;
    computeSigRef.current = sig;
    if (assignDebounceRef.current) clearTimeout(assignDebounceRef.current);
    assignDebounceRef.current = setTimeout(() => { void handleAssignmentsSaved(); }, 350);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    assignments,
    agRequired,
    agHsGrades,
    gpaHsGrades,
    gradePoints,
    honorsBonus,
    csulbThreshold,
    stemThreshold,
    californiaResidentMinGpa,
  ]);

  // Decision button clicked — save as reviewed=true, then notify parent
  const handleDecisionSave = async (decision: AdmissionDecisionStatus | null) => {
    userOverrodeDecisionRef.current = true;
    setSelectedAdmissionDecision(decision);
    await saveCurrentState(admissionReview, decision, true, true);
    const label = decision === 'admitted' ? 'Admitted' : decision === 'denied' ? 'Denied' : decision === 'waitlisted' ? 'Waitlisted' : 'Cleared';
    toast.success(`Decision set to ${label}`);
    emitNotification({
      kind: decision === 'admitted' ? 'success' : decision === 'denied' ? 'error' : 'warn',
      title: `Decision recorded — ${label}`,
      message: transcript?.studentName
        ? `${transcript.studentName}${yearIntake ? ` · ${yearIntake}` : ''}`
        : undefined,
      term: yearIntake ?? undefined,
    });
    if (decision) onDecisionSaved?.(decision);
  };

  useEffect(() => {
    isInitializedRef.current = false;
    userOverrodeDecisionRef.current = false;
    setIsInitializing(true);
    const resetAssignments: Record<string, CourseAssignment> = {};
    const resetGradePoints = { ...DEFAULT_GRADE_POINTS };
    setAssignments(resetAssignments);
    setGradePoints(resetGradePoints);
    setHonorsBonus(1);
    setHonorsMaxSemesters(8);
    setHonorsMax10thGradeSemesters(2);
    setCsulbScoreMultiplier(800);
    setCaliforniaResidentMinGpa(2.5);
    setCsulbThreshold(3200);
    setStemThreshold(0);
    setAgHsGrades([8, 9, 10, 11, 12]);
    setGpaHsGrades([8, 9, 10, 11, 12]);
    setGpaBucketEdits({});
    setSelectedAdmissionDecision(null);
    setAdmissionReview(null);
    setAdmissionError(null);

    const initAndCalculate = async () => {
      const dbStudentId = Number(transcript?.db_id ?? transcript?.id);

      let nextAgRequired = { ...DEFAULT_AG_REQUIRED };
      let nextCaliforniaResidentMinGpa = 2.5;
      let nextAgHsGrades: number[] = [8, 9, 10, 11, 12];
      let nextGpaHsGrades: number[] = [8, 9, 10, 11, 12];
      // CSULB / STEM admit thresholds (Index = GPA × 800) come from the
      // institution criteria; fall back to 3200 / 0 only when none is saved.
      let nextCsulbThreshold = 3200;
      let nextStemThreshold = 0;

      // Load criteria and stored summary in parallel
      const [, storedSummary] = await Promise.all([
        (() => {
          if (!yearIntake) return Promise.resolve();
          return getAgCriteriaForTerm(yearIntake)
            .then((criteria) => {
              if (!criteria) return;
              nextAgRequired = {
                a: criteria.a_required, b: criteria.b_required,
                c: criteria.c_required, d1: criteria.d1_required,
                d2: criteria.d2_required, d: criteria.d_required,
                e: criteria.e_required, f: criteria.f_required,
                g: criteria.g_required,
              };
              nextCaliforniaResidentMinGpa = criteria.california_resident_min_gpa ?? 2.5;
              nextAgHsGrades = criteria.ag_hs_grades ?? [8, 9, 10, 11, 12];
              nextGpaHsGrades = criteria.gpa_hs_grades ?? [8, 9, 10, 11, 12];
              nextCsulbThreshold = criteria.min_csulb_score ?? 3200;
              nextStemThreshold = criteria.min_stem_score ?? 0;
              setCaliforniaResidentMinGpa(nextCaliforniaResidentMinGpa);
              setAgHsGrades(nextAgHsGrades);
              setGpaHsGrades(nextGpaHsGrades);
              setCsulbThreshold(nextCsulbThreshold);
              setStemThreshold(nextStemThreshold);
            })
            .catch(() => {});
        })(),
        dbStudentId
          ? getStudentAgSummary(dbStudentId).catch((): null => null)
          : Promise.resolve(null),
      ] as const);

      setAgRequired(nextAgRequired);

      if (storedSummary?.admission_decision) {
        const stored = normalizeDecisionStatus(storedSummary.admission_decision);
        setSelectedAdmissionDecision(stored);
        if (stored) userOverrodeDecisionRef.current = true;
      }

      const result = await runAdmissionCalculation({
        assignments: resetAssignments,
        agRequired: nextAgRequired,
        gradePoints: resetGradePoints,
        honorsBonus: 1,
        honorsMaxSemesters: 8,
        honorsMax10thGradeSemesters: 2,
        csulbScoreMultiplier: 800,
        californiaResidentMinGpa: nextCaliforniaResidentMinGpa,
        csulbThreshold: nextCsulbThreshold,
        stemThreshold: nextStemThreshold,
        agHsGrades: nextAgHsGrades,
        gpaHsGrades: nextGpaHsGrades,
      });

      if (storedSummary && result) {
        const overrideMap: Record<string, number | null | undefined> = {
          a:  storedSummary.a_override,  b:  storedSummary.b_override,
          c:  storedSummary.c_override,  d1: storedSummary.d1_override,
          d2: storedSummary.d2_override, d:  storedSummary.d_override,
          e:  storedSummary.e_override,  f:  storedSummary.f_override,
          g:  storedSummary.g_override,
        };
        const patchedRows = result.ag_review?.rows?.map((row: AdmissionAgRow) => {
          const key = normalizeRequirementKey(row.key);
          const ov = key ? overrideMap[key] : undefined;
          return ov != null ? { ...row, actual: ov } : row;
        });
        const ss = result.gpa_calculation?.score_summary;
        const patchedScoreSummary = ss ? {
          ...ss,
          cumulative_gpa: storedSummary.gpa_cumulative_override ?? ss.cumulative_gpa,
          english_gpa:    storedSummary.gpa_english_override    ?? ss.english_gpa,
          math_gpa:       storedSummary.gpa_math_override       ?? ss.math_gpa,
          science_gpa:    storedSummary.gpa_science_override    ?? ss.science_gpa,
          csulb_score:    storedSummary.csulb_score_override    ?? ss.csulb_score,
          stem_score:     storedSummary.stem_score_override     ?? ss.stem_score,
        } : ss;
        setAdmissionReview({
          ...result,
          ...(patchedRows && { ag_review: { ...result.ag_review, rows: patchedRows } }),
          ...(patchedScoreSummary && { gpa_calculation: { ...result.gpa_calculation, score_summary: patchedScoreSummary } }),
        });
      }

      // Record what we just computed on, so the recompute effect (which fires
      // because init set these states) recognises the inputs are unchanged and
      // skips a redundant second calc — which is what caused the decision flip.
      computeSigRef.current = JSON.stringify([
        resetAssignments, nextAgRequired, nextAgHsGrades, nextGpaHsGrades,
        resetGradePoints, 1, nextCsulbThreshold, nextStemThreshold, nextCaliforniaResidentMinGpa,
      ]);
      isInitializedRef.current = true;
      setIsInitializing(false);
    };
    void initAndCalculate().catch(() => { isInitializedRef.current = true; setIsInitializing(false); });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [transcript?.id]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {admissionError && (
        <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {admissionError}
        </div>
      )}
      {mode === 'agRequirement' && (
        <AgRequirementTab
          admissionReview={admissionReview}
          transcript={transcript}
          assignments={assignments}
          setAssignments={setAssignments}
          agRequired={agRequired}
          setAgRequired={setAgRequired}
          onAssignmentsSaved={handleAssignmentsSaved}
          loading={admissionLoading || isInitializing}
          selectedAdmissionDecision={selectedAdmissionDecision}
        />
      )}
      {mode === 'gpaCalculation' && (
        <GpaCalculationTab
          admissionReview={admissionReview}
          gradePoints={gradePoints}
          setGradePoints={setGradePoints}
          honorsBonus={honorsBonus}
          setHonorsBonus={setHonorsBonus}
          honorsMaxSemesters={honorsMaxSemesters}
          setHonorsMaxSemesters={setHonorsMaxSemesters}
          honorsMax10thGradeSemesters={honorsMax10thGradeSemesters}
          setHonorsMax10thGradeSemesters={setHonorsMax10thGradeSemesters}
          csulbScoreMultiplier={csulbScoreMultiplier}
          setCsulbScoreMultiplier={setCsulbScoreMultiplier}
          californiaResidentMinGpa={californiaResidentMinGpa}
          setCaliforniaResidentMinGpa={setCaliforniaResidentMinGpa}
          csulbThreshold={csulbThreshold}
          setCsulbThreshold={setCsulbThreshold}
          stemThreshold={stemThreshold}
          setStemThreshold={setStemThreshold}
          gpaBucketEdits={gpaBucketEdits}
          setGpaBucketEdits={setGpaBucketEdits}
          selectedAdmissionDecision={selectedAdmissionDecision}
          onDecisionSave={handleDecisionSave}
          loading={admissionLoading || isInitializing}
          isSaving={isSaving}
          studentDbId={transcript?.db_id != null ? Number(transcript.db_id) : null}
        />
      )}
    </div>
  );
}
