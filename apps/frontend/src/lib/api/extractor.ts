import { apiFetch } from '@/lib/utils';

/**
 * Clean 4-table transcript extraction contract:
 *
 * course_details = raw Document AI rows
 * gemini_course_details = raw Gemini rows
 * course_extraction_matches = row-by-row comparison decisions
 * final_course_details = trusted final rows used by frontend/admission
 *
 * Important:
 * - Frontend should display final_course_details rows as the main course list.
 * - Raw Document AI / Gemini counts are supporting/debug counts only.
 * - Do not call old /validation-matches endpoints.
 *
 * Gemini-only new transcript types are stored separately in:
 * new_transcript_student_details
 * new_transcript_course_details
 *
 * The backend exposes those rows through the same extractor endpoints and marks
 * them with is_new_transcript_type=true and storage_source='new_transcript_tables'.
 * Their API IDs may be negative so they cannot collide with IDs from the existing
 * trusted transcript tables. Keep those IDs unchanged when calling the API.
 */

export type JsonObject = Record<string, unknown>;

export type ApiId = number | string;
export type NullableApiId = ApiId | null;

export type ExtractorReviewBucket =
  | 'auto_complete'
  | 'human_review'
  | 'human_review_with_audit'
  | string;

export type CourseSource =
  | 'Document AI'
  | 'Gemini'
  | 'Document AI + Gemini'
  | 'Manual'
  | 'Final'
  | 'Reconciled'
  | 'document_ai'
  | 'gemini'
  | 'merged'
  | 'manual'
  | string;

export type CourseMatchType =
  | 'matched'
  | 'document_ai_only'
  | 'gemini_only'
  | 'gemini_only_new_transcript'
  | 'document_ai_only_duplicate_suppressed'
  | 'gemini_only_duplicate_suppressed'
  | 'field_mismatch'
  | 'manual'
  | 'unknown'
  | string;

export type CourseDecision =
  | 'use_document_ai'
  | 'use_gemini'
  | 'use_both'
  | 'manual_review'
  | 'manual_review_update'
  | 'user_resolved'
  | 'accept_final'
  | 'keep'
  | 'remove'
  | 'review'
  | string;

export type CourseFieldDecisions = Record<string, string | null | undefined>;

export type CourseFieldDifferences = Record<
  string,
  {
    document_ai?: unknown;
    gemini?: unknown;
    final?: unknown;
    selected?: unknown;
    [key: string]: unknown;
  }
>;

export type CourseReconciliationSummary = {
  status?: string | null;
  process_status?: string | null;
  file_status?: string | null;
  validation_type?: string | null;

  is_new_transcript_type?: boolean | null;
  storage_source?: 'new_transcript_tables' | string | null;
  review_bucket?: ExtractorReviewBucket | null;
  student_needs_review?: boolean | null;
  student_audit_required?: boolean | null;
  student_review_reasons?: string[];
  structure_was_normalised?: boolean | null;
  unresolved_courses?: number | null;
  clean_count?: number | null;

  extraction_file_id?: number | null;
  student_db_id?: number | null;

  document_ai_course_count?: number | null;
  raw_document_ai_course_count?: number | null;
  document_ai_raw_course_count?: number | null;
  course_details_count?: number | null;

  gemini_course_count?: number | null;
  raw_gemini_course_count?: number | null;
  gemini_raw_course_count?: number | null;
  gemini_course_details_count?: number | null;

  final_course_count?: number | null;
  actual_final_course_count?: number | null;
  final_course_details_count?: number | null;

  raw_max_source_course_count?: number | null;
  raw_expected_final_course_count?: number | null;
  expected_final_course_count?: number | null;
  removed_course_count?: number | null;
  potential_missing_course_count?: number | null;
  course_count_difference?: number | null;
  raw_count_difference_from_max?: number | null;
  final_count_shortfall?: boolean | null;
  counts_match?: boolean | null;

  needs_review_count?: number | null;
  final_needs_review_count?: number | null;
  reviewed_course_count?: number | null;
  unreviewed_course_count?: number | null;
  unresolved_match_count?: number | null;
  course_id_mismatch_count?: number | null;
  field_difference_count?: number | null;
  open_review_count?: number | null;
  unresolved_count?: number | null;
  unresolved_review_count?: number | null;

  matched_count?: number | null;
  matched_course_count?: number | null;
  document_ai_only_count?: number | null;
  gemini_only_count?: number | null;

  suppressed_document_ai_duplicate_count?: number | null;
  suppressed_gemini_duplicate_count?: number | null;

  auto_fixed_count?: number | null;
  auto_applied_count?: number | null;

  match_counts?: Record<string, number>;

  review_reason?: string | null;
  review_reason_text?: string | null;
  review_reasons?: string[];
  warnings?: string[];

  course_math_explanation?: string | null;
  model?: string | null;

  [key: string]: unknown;
};

export type GeminiCourseDetail = {
  id?: number;
  s_id?: number | null;
  source_file?: number | null;

  crs_id?: string | number | null;
  crs_letter_grade?: string | null;
  crs_description?: string | null;
  crs_hs?: string | null;
  crs_grade?: number | string | null;
  crs_month?: number | string | null;
  crs_year?: number | string | null;
  crs_credit_attempted?: number | string | null;
  crs_credit_completed?: number | string | null;
  crs_term_gpa?: number | string | null;

  row_index?: number | null;
  course_index?: number | null;
  extraction_confidence?: number | string | null;
  model?: string | null;
  raw_payload?: JsonObject | null;

  created_at?: string | null;
  updated_at?: string | null;
};

export type CourseExtractionMatch = {
  id?: number;

  extraction_file_id?: number | null;
  source_file?: number | null;

  s_id?: number | null;
  student_id?: number | null;

  document_ai_course_detail_id?: number | null;
  gemini_course_detail_id?: number | null;
  final_course_detail_id?: number | null;

  match_type?: CourseMatchType | null;
  match_confidence?: number | string | null;

  course_id_match?: boolean | null;
  course_name_match?: boolean | null;
  letter_grade_match?: boolean | null;
  grade_level_match?: boolean | null;
  month_match?: boolean | null;
  year_match?: boolean | null;
  credit_attempted_match?: boolean | null;
  credit_completed_match?: boolean | null;

  course_name_score?: number | string | null;
  course_id_score?: number | string | null;
  overall_match_score?: number | string | null;
  match_score?: number | string | null;

  selected_course_id_source?: CourseSource | null;
  selected_course_name_source?: CourseSource | null;
  selected_letter_grade_source?: CourseSource | null;
  selected_grade_level_source?: CourseSource | null;
  selected_month_source?: CourseSource | null;
  selected_year_source?: CourseSource | null;
  selected_credit_attempted_source?: CourseSource | null;
  selected_credit_completed_source?: CourseSource | null;

  needs_review?: boolean | null;
  review_reason?: string | null;
  resolution_reason?: string | null;
  reviewed_by_user?: boolean | null;
  reviewed_at?: string | null;
  review_status?: string | null;

  document_ai_snapshot?: JsonObject | null;
  gemini_snapshot?: JsonObject | null;
  field_differences?: CourseFieldDifferences | JsonObject | null;
  field_decisions?: CourseFieldDecisions | null;
  field_sources?: CourseFieldDecisions | null;

  /** Compatibility-only. Current DB may not have this column. */
  decision?: CourseDecision | null;

  created_at?: string | null;
  updated_at?: string | null;

  [key: string]: unknown;
};

export type FinalCourseDetail = {
  id?: number | string;

  /**
   * Present only for Gemini-only new transcript rows.
   * The public API id/final_course_id may be negative; do not normalize it.
   */
  new_transcript_course_id?: number | null;
  is_new_transcript_type?: boolean | null;
  storage_source?: 'new_transcript_course_details' | string | null;

  s_id?: number | string | null;
  student_id?: number | string | null;

  source_file?: number | null;
  extraction_file_id?: number | null;

  document_ai_course_detail_id?: number | null;
  gemini_course_detail_id?: number | null;

  crs_id?: number | string | null;
  course_id?: number | string | null;
  course_id_raw?: string | null;
  final_course_id?: number | string | null;
  final_crs_id?: number | string | null;

  crs_letter_grade?: string | null;
  letter_grade?: string | null;
  grade?: string | null;
  final_grade?: string | null;

  crs_description?: string | null;
  course_name?: string | null;
  name?: string | null;
  final_course_name?: string | null;

  crs_hs?: string | null;
  school?: string | null;
  school_name?: string | null;
  final_school?: string | null;

  crs_grade?: number | string | null;
  grade_level?: number | string | null;
  final_grade_level?: number | string | null;

  crs_month?: number | string | null;
  month?: number | string | null;
  final_month?: number | string | null;

  crs_year?: number | string | null;
  year?: number | string | null;
  academic_year?: string | number | null;
  final_year?: number | string | null;

  crs_credit_attempted?: number | string | null;
  credit_attempted?: number | string | null;
  credits_attempted?: number | string | null;
  final_credit_attempted?: number | string | null;

  crs_credit_completed?: number | string | null;
  credit_completed?: number | string | null;
  credits_completed?: number | string | null;
  credits?: number | string | null;
  final_credit_completed?: number | string | null;

  crs_term_gpa?: number | string | null;
  term_gpa?: number | string | null;

  final_source?: CourseSource | null;
  source?: CourseSource | null;
  extraction_source?: CourseSource | null;
  selected_source?: CourseSource | null;
  trusted_source?: CourseSource | null;

  crs_id_source?: CourseSource | null;
  course_id_source?: CourseSource | null;
  selected_course_id_source?: CourseSource | null;

  crs_description_source?: CourseSource | null;
  crs_letter_grade_source?: CourseSource | null;
  crs_hs_source?: CourseSource | null;
  crs_grade_source?: CourseSource | null;
  crs_month_source?: CourseSource | null;
  crs_year_source?: CourseSource | null;
  crs_credit_attempted_source?: CourseSource | null;
  crs_credit_completed_source?: CourseSource | null;
  crs_term_gpa_source?: CourseSource | null;

  review_status?: string | null;
  needs_review?: boolean | null;
  review_required?: boolean | null;
  reviewed?: boolean | null;
  reviewed_by_user?: boolean | null;
  status?: string | null;
  final_status?: string | null;
  review_reason?: string | null;
  needs_review_reason?: string | null;
  reason?: string | null;
  resolution_reason?: string | null;

  document_ai_snapshot?: JsonObject | null;
  gemini_snapshot?: JsonObject | null;
  field_decisions?: CourseFieldDecisions | null;
  field_sources?: CourseFieldDecisions | null;
  source_summary?: CourseFieldDecisions | null;
  field_source?: string | null;
  source_notes?: string | null;
  field_differences?: CourseFieldDifferences | JsonObject | null;

  changed_by_gemini?: boolean | null;
  gemini_corrected_fields?: string[];
  gemini_fields_used?: string[];
  gemini_confidence?: number | string | null;

  course_id_match?: boolean | null;
  course_id_score?: number | string | null;

  decision?: CourseDecision | null;
  match_decision?: CourseDecision | null;
  final_decision?: CourseDecision | null;
  resolution?: string | null;
  match_type?: CourseMatchType | null;
  match_status?: CourseMatchType | null;
  match_score?: number | string | null;
  match_confidence?: number | string | null;
  confidence?: number | string | null;

  section_name?: string | null;
  term_name?: string | null;
  course_type?: string | null;
  course_category?: string | null;

  mapping_status?: string | null;
  mapped_uc_course?: {
    id: number;
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

  document_ai_course_id?: number | string | null;
  document_ai_course_name?: string | null;
  document_ai_grade?: string | null;
  document_ai_credit_attempted?: number | string | null;
  document_ai_credit_completed?: number | string | null;
  document_ai_grade_level?: number | string | null;
  document_ai_month?: number | string | null;
  document_ai_year?: number | string | null;
  document_ai_school?: string | null;

  gemini_course_id?: number | string | null;
  gemini_course_name?: string | null;
  gemini_grade?: string | null;
  gemini_credit_attempted?: number | string | null;
  gemini_credit_completed?: number | string | null;
  gemini_grade_level?: number | string | null;
  gemini_month?: number | string | null;
  gemini_year?: number | string | null;
  gemini_school?: string | null;

  course_extraction_match_id?: number | null;
  match_id?: number | null;
  reconciliation_match_id?: number | null;
  validation_match_id?: number | null;

  is_manual?: boolean | null;
  manual_entry?: boolean | null;
  added_by_gemini?: boolean | null;
  is_gemini_added?: boolean | null;
  suggested_by_gemini?: string | null;
  auto_applied?: boolean | null;
  auto_fixed?: boolean | null;
  auto_action?: string | null;

  created_at?: string | null;
  updated_at?: string | null;

  [key: string]: unknown;
};

export type StudentCourse = FinalCourseDetail;

/**
 * Old validation aliases kept only for compatibility with screens/components
 * that still import these names. They map to the clean reconciliation types.
 */
export type ValidationMatchType = CourseMatchType;

export type ValidationAutoAction =
  | 'manual_review'
  | 'auto_add_candidate'
  | 'auto_added'
  | 'already_exists'
  | 'user_added'
  | 'user_confirmed_added'
  | 'user_confirmed_removed'
  | 'user_confirmed_keep'
  | string;

export type ValidationCourseMatch = CourseExtractionMatch & {
  validation_match_id?: number;
  validation_result_id?: number;
  gemini_course_name?: string | null;
  document_ai_course_name?: string | null;
  course_name?: string | null;
  suggestion?: string | null;
  row_index?: number | null;
  grade_level?: number | string | null;
  term_name?: string | null;
  academic_year?: string | number | null;
  course_id_raw?: string | null;
  course_prefix?: string | null;
  course_number?: string | number | null;
  has_plus_marker?: boolean | null;
  has_star_marker?: boolean | null;
  gemini_grade?: string | null;
  grade?: string | null;
  credits?: number | string | null;
  credit_attempted?: number | string | null;
  credit_completed?: number | string | null;
  year?: number | string | null;
  month?: number | string | null;
  school?: string | null;
  auto_action?: ValidationAutoAction | null;
  auto_applied?: boolean;
  reviewed_at?: string | null;
  applied_course_detail_id?: number | null;
  needs_confirmation?: boolean;
  suggested_by?: string | null;
};

export type SuggestedCourseToAdd = ValidationCourseMatch & {
  course_name?: string | null;
  name?: string | null;
  course?: string | null;
  suggested_subject?: string | null;
  subject?: string | null;
  course_category?: string | null;
};

export type SuggestedCourseToRemove = ValidationCourseMatch & {
  course_name?: string | null;
};

export type MatchedCourse = ValidationCourseMatch;

export type GeminiCourseItem = {
  section_name?: string | null;
  course_name?: string | null;
  course_id_raw?: string | null;
  grade?: string | null;
  credit_attempted?: number | string | null;
  credit_completed?: number | string | null;
  gemini_confidence?: number | null;
};

export type CourseValidationResult = CourseReconciliationSummary & {
  validation_result_id?: number | null;
  validation_status?: string | null;

  gemini_reported_total_course_count?: number | null;
  gemini_course_names?: string[];
  gemini_course_items?: GeminiCourseItem[];
  sections?: unknown[];

  missing_from_extraction?: string[];
  extra_in_extraction?: string[];

  suggested_courses_to_add?: SuggestedCourseToAdd[];
  suggested_courses_to_remove?: SuggestedCourseToRemove[];

  missing_course_details?: ValidationCourseMatch[];
  extra_course_details?: ValidationCourseMatch[];

  auto_add_candidates?: SuggestedCourseToAdd[];
  auto_applied_courses?: ValidationCourseMatch[];

  matched_courses?: MatchedCourse[];
  validation_matches?: ValidationCourseMatch[];

  parser_warnings?: string[];
  raw_gemini_response?: string | null;
};

export type ExtractionFile = {
  id: number;
  student_id?: string | number | null;
  file_name: string;

  process_status: string | null;
  file_status?: string | null;

  upload_date?: string | null;
  processed_date?: string | null;
  processed_at?: string | null;

  institution_id: number;
  year_intake?: string | null;
  program_id?: number | null;
  classifier_type?: string | number | null;

  is_new_transcript_type?: boolean | null;
  storage_source?: 'new_transcript_tables' | string | null;
  mode?: string | null;
  review_bucket?: ExtractorReviewBucket | null;
  unresolved_courses?: number | null;
  student_needs_review?: boolean | null;
  student_audit_required?: boolean | null;
  student_review_reasons?: string[];
  structure_was_normalised?: boolean | null;

  course_reconciliation?: CourseReconciliationSummary | null;
  reconciliation_summary?: CourseReconciliationSummary | null;

  validation_result?: CourseValidationResult | CourseReconciliationSummary | null;
  course_validation?: CourseValidationResult | CourseReconciliationSummary | null;
  course_validation_result?: CourseValidationResult | null;
  gemini_validation_result?: CourseValidationResult | null;

  validation_result_id?: number | null;
  validation_type?: string | null;
  validation_status?: string | null;

  document_ai_course_count?: number | null;
  raw_document_ai_course_count?: number | null;
  document_ai_raw_course_count?: number | null;
  course_details_count?: number | null;

  gemini_course_count?: number | null;
  raw_gemini_course_count?: number | null;
  gemini_raw_course_count?: number | null;
  gemini_course_details_count?: number | null;

  final_course_count?: number | null;
  actual_final_course_count?: number | null;
  final_course_details_count?: number | null;

  expected_final_course_count?: number | null;
  course_count_difference?: number | null;
  final_count_shortfall?: boolean | null;
  counts_match?: boolean | null;

  matched_course_count?: number | null;
  matched_count?: number | null;

  needs_review_count?: number | null;
  open_review_count?: number | null;
  unresolved_count?: number | null;
  unresolved_review_count?: number | null;

  document_ai_only_count?: number | null;
  gemini_only_count?: number | null;
  suppressed_document_ai_duplicate_count?: number | null;
  suppressed_gemini_duplicate_count?: number | null;
  auto_fixed_count?: number | null;
  auto_applied_count?: number | null;

  review_reason?: string | null;
  review_reason_text?: string | null;
  review_reasons?: string[];
  warnings?: string[];

  course_math_explanation?: string | null;
};

export type StudentWithCoursesBase = {
  /**
   * Audit responses may contain a file-only row with no student record yet.
   */
  id: NullableApiId;
  student_id?: NullableApiId;
  db_id?: NullableApiId;

  /**
   * Present only for rows stored in new_transcript_student_details.
   * db_id/id may be negative in API responses; preserve that value in requests.
   */
  new_transcript_student_id?: number | null;
  is_new_transcript_type?: boolean | null;
  storage_source?: 'new_transcript_tables' | string | null;
  review_bucket?: ExtractorReviewBucket | null;
  student_needs_review?: boolean | null;
  student_audit_required?: boolean | null;
  student_review_reasons?: string[];
  structure_was_normalised?: boolean | null;

  student_name: string;
  file_name?: string | null;
  is_file_only?: boolean;

  email?: string | null;
  format?: string | null;
  school_name?: string | null;

  birth_date?: string | null;
  graduation_date?: string | null;
  address?: string | null;

  gpa?: number | string | null;
  recalculated_gpa?: number | null;
  marks?: string | null;

  processed_at?: string | null;
  source_file?: number | null;
  course_count?: number | null;

  file_status?: string | null;
  process_status?: string | null;
  effective_status?: string | null;
  review_reason?: string | null;

  student_data_complete?: boolean | null;

  course_reconciliation?: CourseReconciliationSummary | null;
  reconciliation_summary?: CourseReconciliationSummary | null;

  validation_result?: CourseValidationResult | CourseReconciliationSummary | null;
  course_validation?: CourseValidationResult | CourseReconciliationSummary | null;
  course_validation_result?: CourseValidationResult | null;
  gemini_validation_result?: CourseValidationResult | null;

  validation_result_id?: number | null;
  validation_type?: string | null;
  validation_status?: string | null;

  document_ai_course_count?: number | null;
  raw_document_ai_course_count?: number | null;
  document_ai_raw_course_count?: number | null;
  course_details_count?: number | null;

  gemini_course_count?: number | null;
  raw_gemini_course_count?: number | null;
  gemini_raw_course_count?: number | null;
  gemini_course_details_count?: number | null;

  final_course_count?: number | null;
  actual_final_course_count?: number | null;
  final_course_details_count?: number | null;

  expected_final_course_count?: number | null;
  course_count_difference?: number | null;
  final_count_shortfall?: boolean | null;
  counts_match?: boolean | null;

  matched_course_count?: number | null;
  matched_count?: number | null;

  missing_from_document_ai_count?: number | null;
  extra_in_document_ai_count?: number | null;

  document_ai_only_count?: number | null;
  gemini_only_count?: number | null;
  suppressed_document_ai_duplicate_count?: number | null;
  suppressed_gemini_duplicate_count?: number | null;

  needs_review_count?: number | null;
  open_review_count?: number | null;
  unresolved_count?: number | null;
  unresolved_review_count?: number | null;

  auto_fixed_count?: number | null;
  auto_applied_count?: number | null;

  model?: string | null;
  review_reason_text?: string | null;
  review_reasons?: string[];
  warnings?: string[];

  course_math_explanation?: string | null;

  final_courses?: FinalCourseDetail[];
  final_course_details?: FinalCourseDetail[];
  trusted_courses?: FinalCourseDetail[];
  courses?: FinalCourseDetail[];

  course_extraction_matches?: CourseExtractionMatch[];
  matches?: CourseExtractionMatch[];

  /** Empty old-validator arrays may still be returned for compatibility only. */
  missing_from_extraction?: string[];
  extra_in_extraction?: string[];
  suggested_courses_to_add?: SuggestedCourseToAdd[];
  suggested_courses_to_remove?: SuggestedCourseToRemove[];
  missing_course_details?: ValidationCourseMatch[];
  extra_course_details?: ValidationCourseMatch[];
  auto_add_candidates?: SuggestedCourseToAdd[];
  auto_applied_courses?: ValidationCourseMatch[];
  matched_courses?: MatchedCourse[];
  gemini_course_items?: GeminiCourseItem[];
  validation_matches?: ValidationCourseMatch[];

  ok?: boolean;
  [key: string]: unknown;
};

export type StudentWithCoursesCompleted = StudentWithCoursesBase & {
  admission_decision?: string | null;
  /** Whether a counselor has confirmed this student off the Pending Review list. */
  reviewed?: boolean | null;
};

export type StudentWithCourses = StudentWithCoursesBase;

export type ReviewStudentCoursePayload = {
  id?: ApiId;
  final_course_id?: ApiId;
  final_course_detail_id?: ApiId;
  new_transcript_course_id?: number;

  is_new_transcript_type?: boolean;
  storage_source?: 'new_transcript_course_details' | string;

  match_id?: number;
  course_extraction_match_id?: number;
  reconciliation_match_id?: number;

  name?: string;
  course_name?: string;
  crs_description?: string;

  grade?: string;
  letter_grade?: string;
  crs_letter_grade?: string;

  credits?: string | number;
  credit_completed?: string | number;
  credits_completed?: string | number;
  credit_attempted?: string | number;
  credits_attempted?: string | number;

  crs_id?: string | number;
  course_id?: string | number;
  course_id_raw?: string;

  grade_level?: string | number;
  month?: string | number;
  year?: string | number;

  school?: string;
  school_name?: string;
  crs_hs?: string;

  crs_grade?: string | number;
  crs_month?: string | number;
  crs_year?: string | number;
  term_gpa?: string | number;
  crs_term_gpa?: string | number;

  section_name?: string;
  term_name?: string;
  academic_year?: string | number;

  source?: CourseSource;
  extraction_source?: CourseSource;

  needs_review?: boolean;
  reviewed_by_user?: boolean;
  mark_reviewed?: boolean;
  review_status?: string;
  review_reason?: string | null;

  action?: 'review' | 'remove' | 'keep' | 'accept_final' | string;
  resolution?: string;
  decision?: CourseDecision;

  field_sources?: CourseFieldDecisions;
  field_decisions?: CourseFieldDecisions;

  subject?: string;
  course_category?: string;
  is_gemini_suggested?: boolean;
  subject_confirmed?: boolean;
};

export type ReviewStudentPayload = {
  student_id?: number | string;
  student_name?: string;
  name?: string;

  is_new_transcript_type?: boolean;
  storage_source?: 'new_transcript_tables' | string;

  format?: string;
  school?: string;
  school_name?: string;

  address?: string;
  phone_number?: string;
  gender?: string;
  birth_date?: string;
  state_id?: number | string;
  counselor_name?: string;
  grade_level?: number | string;
  total_units_earned?: number | string;

  graduation_date?: string;
  enter_date?: string;

  gpa?: string | number | null;
  academic_gpa?: string | number | null;
  university_gpa?: string | number | null;

  courses?: ReviewStudentCoursePayload[];
};

export type ReviewFinalCoursePayload = ReviewStudentCoursePayload & {
  final_course?: ReviewStudentCoursePayload;
};

export type ResolveCourseExtractionMatchPayload = {
  action?: 'accept_final' | 'remove' | 'keep' | 'review' | string;
  resolution?: string;
  decision?: CourseDecision;
  final_course_id?: ApiId;
  final_course_detail_id?: ApiId;
  final_course?: ReviewStudentCoursePayload;
  /** Which extractor the accepted row came from (document_ai/gemini/merged);
   * normalized server-side to satisfy the final_source check constraint. */
  final_source?: string;
  needs_review?: boolean;
  review_reason?: string | null;
  reviewed_by_user?: boolean;
  mark_reviewed?: boolean;
  review_status?: string;
};

export type ResolveCourseExtractionMatchResponse = {
  ok: boolean;
  match_id?: number;
  file_id?: number;
  process_status?: string | null;
  [key: string]: unknown;
};

export type ReviewFinalCourseResponse =
  | StudentWithCourses
  | {
      ok?: boolean;
      course_id?: ApiId;
      file_id?: number;
      process_status?: string | null;
      reviewed_by_user?: boolean;
      [key: string]: unknown;
    };

export type UpdateStudentReviewLightResponse = {
  ok: boolean;
  student_id?: ApiId;
  source_file?: number;
  is_new_transcript_type?: boolean;
  process_status?: string | null;
  file_status?: string | null;
  effective_status?: string | null;
  [key: string]: unknown;
};

export type ConfirmAddMissingCoursePayload = ReviewStudentCoursePayload;

export type ConfirmRemoveExtraCoursePayload = {
  course_detail_id?: ApiId;
  final_course_id?: ApiId;
  final_course_detail_id?: ApiId;
  id?: ApiId;
};

export type RerunFileResponse = {
  ok: boolean;
  file_id?: number;

  is_new_transcript_type?: boolean;
  mode?: string | null;
  review_bucket?: ExtractorReviewBucket | null;
  unresolved_courses?: number | null;
  student_needs_review?: boolean | null;
  student_audit_required?: boolean | null;
  student_review_reasons?: string[];
  structure_was_normalised?: boolean | null;
  reason?: string | null;
  message?: string | null;

  students: number;
  courses: number;
  final_courses?: number;

  process_status?: string | null;

  document_ai_courses_inserted?: number | null;
  gemini_courses_inserted?: number | null;

  raw_document_ai_course_count?: number | null;
  raw_gemini_course_count?: number | null;

  document_ai_course_count?: number | null;
  gemini_course_count?: number | null;
  final_course_count?: number | null;

  course_reconciliation?: CourseReconciliationSummary | null;
  reconciliation_summary?: CourseReconciliationSummary | null;

  /** Compatibility aliases. */
  course_validation?: CourseReconciliationSummary | CourseValidationResult | null;
  validation_save_result?: CourseReconciliationSummary | CourseValidationResult | null;
};

export type CompleteExtractionFileResponse = {
  ok: boolean;
  file_id?: number;
  process_status?: string | null;
  is_new_transcript_type?: boolean;
  summary?: CourseReconciliationSummary | null;
  [key: string]: unknown;
};

export type ExtractorSectionCounts = {
  completed: number;
  needs_review: number;
  needs_review_audit: number;
  audit_review: number;
  human_review_with_audit: number;
  not_processed: number;
  new_type: number;
  admitted: number;
  denied: number;
  waitlisted: number;
  pending: number;
  [key: string]: number;
};

export type FileCourseMatchesResponse = {
  file_id: number;
  summary: CourseReconciliationSummary;
  matches: CourseExtractionMatch[];
  is_new_transcript_type?: boolean;
};

function buildQuery(params: Record<string, string | string[] | undefined>): string {
  const searchParams = new URLSearchParams();

  for (const [key, value] of Object.entries(params)) {
    if (value === undefined) continue;

    if (Array.isArray(value)) {
      if (value.length) {
        searchParams.set(key, value.join(','));
      }
      continue;
    }

    if (value !== '') {
      searchParams.set(key, value);
    }
  }

  const query = searchParams.toString();

  return query ? `?${query}` : '';
}

export function getTranscriptPdfUrl(fileId: ApiId): string {
  return `/api/extractor/files/${fileId}/pdf`;
}

export async function fetchExtractionFiles(
  statuses?: string[],
  term?: string,
): Promise<ExtractionFile[]> {
  const qs = buildQuery({
    status: statuses,
    term,
  });

  return apiFetch<ExtractionFile[]>(`/api/extractor/files${qs}`);
}

export async function fetchExtractorSectionCounts(
  term?: string,
): Promise<ExtractorSectionCounts> {
  const qs = buildQuery({ term });

  return apiFetch<ExtractorSectionCounts>(
    `/api/extractor/section-counts${qs}`,
  );
}

/** Compatibility alias for components that import the shorter name. */
export const fetchSectionCounts = fetchExtractorSectionCounts;

export async function fetchCompletedStudents(
  term?: string,
  slim = false,
): Promise<StudentWithCoursesCompleted[]> {
  const qs = buildQuery({ term, slim: slim ? '1' : undefined });

  return apiFetch<StudentWithCoursesCompleted[]>(`/api/extractor/completed${qs}`);
}

/** Full student (with courses + reconciliation) fetched on demand when needed.
 *
 * Completed / Human Review lists may stay slim. Human Review with Audit now
 * receives its Gemini-only course rows from /audit-review so the modal can open
 * immediately; this detail endpoint remains the fallback.
 */
export async function fetchStudentDetail(
  studentDbId: ApiId,
): Promise<StudentWithCourses> {
  return apiFetch<StudentWithCourses>(
    `/api/extractor/students/${studentDbId}/detail`,
  );
}

export async function fetchNeedsReviewStudents(
  term?: string,
): Promise<StudentWithCourses[]> {
  const qs = buildQuery({ term });

  return apiFetch<StudentWithCourses[]>(
    `/api/extractor/needs-review${qs}`,
  );
}

export async function fetchAuditReviewStudents(
  term?: string,
): Promise<StudentWithCourses[]> {
  const qs = buildQuery({ term });

  return apiFetch<StudentWithCourses[]>(
    `/api/extractor/audit-review${qs}`,
  );
}

export async function fetchNotProcessedFiles(
  term?: string,
): Promise<ExtractionFile[]> {
  const qs = buildQuery({ term });

  return apiFetch<ExtractionFile[]>(`/api/extractor/not-processed${qs}`);
}

/**
 * Compatibility helper.
 *
 * The backend does not expose /files/{fileId}/students. Build the same result
 * from supported list endpoints instead of calling a route that returns 404.
 */
export async function fetchStudentsForFile(
  fileId: number,
  term?: string,
): Promise<{
  file: ExtractionFile;
  students: StudentWithCourses[];
}> {
  const [files, completed, humanReview, auditReview] = await Promise.all([
    fetchExtractionFiles(undefined, term),
    fetchCompletedStudents(term, true),
    fetchNeedsReviewStudents(term),
    fetchAuditReviewStudents(term),
  ]);

  const file = files.find((item) => Number(item.id) === Number(fileId));
  if (!file) {
    throw new Error(`Extraction file ${fileId} was not found.`);
  }

  const deduplicated = new Map<string, StudentWithCourses>();

  for (const student of [
    ...completed,
    ...humanReview,
    ...auditReview,
  ]) {
    if (Number(student.source_file) !== Number(fileId)) continue;

    const key = [
      String(student.db_id ?? ''),
      String(student.id ?? ''),
      String(student.source_file ?? ''),
    ].join(':');

    deduplicated.set(key, student);
  }

  return {
    file,
    students: [...deduplicated.values()],
  };
}

export async function rerunFile(fileId: number): Promise<RerunFileResponse> {
  const response = await apiFetch<Partial<RerunFileResponse>>(
    `/api/extractor/files/${fileId}/rerun`,
    {
      method: 'POST',
    },
  );

  return {
    ...response,
    ok: response.ok ?? true,
    students: Number(response.students ?? 0),
    courses: Number(response.courses ?? 0),
  };
}

export async function fetchCourseExtractionMatchesForFile(
  fileId: number,
): Promise<FileCourseMatchesResponse> {
  return apiFetch<FileCourseMatchesResponse>(
    `/api/extractor/files/${fileId}/matches`,
  );
}

export async function completeExtractionFile(
  fileId: number,
): Promise<CompleteExtractionFileResponse> {
  return apiFetch<CompleteExtractionFileResponse>(
    `/api/extractor/files/${fileId}/complete`,
    {
      method: 'POST',
    },
  );
}

export async function createStudentForFile(
  fileId: number,
  payload: ReviewStudentPayload,
): Promise<StudentWithCourses> {
  return apiFetch<StudentWithCourses>(`/api/extractor/files/${fileId}/create-student`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

export async function updateStudentAndCourses(
  studentId: ApiId,
  payload: ReviewStudentPayload,
): Promise<StudentWithCourses>;

export async function updateStudentAndCourses(
  studentId: ApiId,
  payload: ReviewStudentPayload,
  light: false,
): Promise<StudentWithCourses>;

export async function updateStudentAndCourses(
  studentId: ApiId,
  payload: ReviewStudentPayload,
  light: true,
): Promise<UpdateStudentReviewLightResponse>;

export async function updateStudentAndCourses(
  studentId: ApiId,
  payload: ReviewStudentPayload,
  light = false,
): Promise<StudentWithCourses | UpdateStudentReviewLightResponse> {
  return apiFetch<StudentWithCourses | UpdateStudentReviewLightResponse>(
    `/api/extractor/students/${studentId}/review${light ? '?light=true' : ''}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export async function reviewFinalCourse(
  courseId: ApiId,
  payload: ReviewFinalCoursePayload,
  light = false,
): Promise<ReviewFinalCourseResponse> {
  // light=true still commits the course update, but skips rebuilding and
  // serializing the whole student/file response. Audit Mark as reviewed uses
  // this path so each click stays fast even on 50-90 course transcripts.
  return apiFetch<ReviewFinalCourseResponse>(
    `/api/extractor/final-courses/${courseId}/review${light ? '?light=true' : ''}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

export async function resolveCourseExtractionMatch(
  matchId: number,
  payload: ResolveCourseExtractionMatchPayload = {},
  light = false,
): Promise<ResolveCourseExtractionMatchResponse> {
  // light=true keeps the response small. The backend still refreshes the
  // file status before committing, so light requests cannot leave stale status.
  return apiFetch<ResolveCourseExtractionMatchResponse>(
    `/api/extractor/course-extraction-matches/${matchId}/resolve${light ? '?light=true' : ''}`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    },
  );
}

/**
 * Compatibility wrappers.
 *
 * These no longer call old /validation-matches endpoints.
 * They map old frontend actions to the new course-extraction-matches resolver.
 */

export async function confirmAddMissingCourse(
  matchId: number,
  payload: ConfirmAddMissingCoursePayload = {},
): Promise<ResolveCourseExtractionMatchResponse> {
  return resolveCourseExtractionMatch(matchId, {
    action: 'accept_final',
    resolution: 'accept_final',
    decision: 'user_resolved',
    mark_reviewed: true,
    reviewed_by_user: true,
    needs_review: false,
    review_status: 'reviewed',
    final_course: {
      ...payload,
      needs_review: false,
      reviewed_by_user: true,
      mark_reviewed: true,
      review_status: 'reviewed',
    },
  });
}

export async function confirmRemoveExtraCourse(
  matchId: number,
  payload: ConfirmRemoveExtraCoursePayload = {},
): Promise<ResolveCourseExtractionMatchResponse> {
  return resolveCourseExtractionMatch(matchId, {
    action: 'remove',
    resolution: 'remove',
    decision: 'remove',
    reviewed_by_user: true,
    needs_review: false,
    review_status: 'removed',
    final_course_id:
      payload.final_course_id ??
      payload.final_course_detail_id ??
      payload.course_detail_id ??
      payload.id,
  });
}

export async function confirmKeepExtraCourse(
  matchId: number,
): Promise<ResolveCourseExtractionMatchResponse> {
  return resolveCourseExtractionMatch(matchId, {
    action: 'keep',
    resolution: 'keep',
    decision: 'user_resolved',
    mark_reviewed: true,
    needs_review: false,
    reviewed_by_user: true,
    review_status: 'reviewed',
  });
}