import type { StudentWithCoursesCompleted } from '@/lib/api/extractor';
import type { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';

/** Coerce a loosely-typed (string | number) field to a finite number, or
 * undefined — the course record types numeric fields as `number | null`. */
const toNum = (v: unknown): number | undefined =>
  v != null && Number.isFinite(Number(v)) ? Number(v) : undefined;

export function mapStudentToTranscriptRecord(
  student: StudentWithCoursesCompleted,
  status?: string | null,
): TranscriptRecord {
  const idVal = student.student_id ?? student.id ?? student.db_id;
  return {
    id: String(idVal ?? ''),
    studentId: idVal != null ? String(idVal) : undefined,
    db_id: student.db_id,   // real student_details PK — used for FK writes
    sourceFile: student.source_file ?? undefined,
    status: status ?? 'completed',
    studentName: student.student_name,
    email: student.email ?? undefined,
    format: student.format ?? undefined,
    birthDate: student.birth_date ?? undefined,
    graduationDate: student.graduation_date ?? undefined,
    address: student.address ?? undefined,
    reviewed: student.reviewed ?? false,
    gpa: student.gpa != null ? String(student.gpa) : undefined,
    recalculated_gpa: student.recalculated_gpa ?? undefined,
    marks: student.marks ?? undefined,
    processedAt: student.processed_at ?? undefined,
    courses:
      student.courses?.map((c) => {
        return {
          id: c.id ?? c.crs_id,
          crs_id: c.crs_id || '-',
          name: c.name ?? c.crs_description ?? undefined,
          // The completed serialization returns the high school as `school`;
          // keep crs_hs populated so school-scoped transcript codes match.
          crs_hs: c.crs_hs ?? (c as any).school ?? (c as any).school_name ?? undefined,
          transcript_type: (c as any).transcript_type ?? (c as any).school ?? undefined,
          grade: c.grade ?? c.crs_letter_grade ?? undefined,
          letter_grade: c.letter_grade ?? c.grade ?? c.crs_letter_grade ?? undefined,
          crs_grade: c.grade_level ?? undefined,
          course_type: c.course_type ?? undefined,
          course_category: c.course_category ?? undefined,
          credits: c.credits != null ? String(c.credits) : undefined,
          crs_credit_completed: c.crs_credit_completed ?? c.credits_completed ?? undefined,
          credits_completed: c.credits_completed ?? c.crs_credit_completed ?? undefined,
          year: toNum(c.year),
          month: toNum(c.month),
          grade_level: toNum(c.grade_level),
          uc_doorway_course_id: toNum(c.uc_doorway_course_id),
          mapping_status: c.mapping_status ?? undefined,
          mapped_uc_course: c.mapped_uc_course ?? undefined,
          standardizedCode: c.mapped_uc_course?.crs_ag_category_letter ?? undefined,
          standardizedDescription: c.mapped_uc_course?.crs_ag_category_description ?? undefined,
        };
      }) ?? [],
  };
}
