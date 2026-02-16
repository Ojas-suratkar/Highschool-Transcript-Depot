// Highschool Transcript Depot - Admissions System Types

export type UserRole = 'admissions_officer' | 'administrator';

export type TranscriptStatus = 
  | 'in_queue' 
  | 'processing' 
  | 'processed' 
  | 'failed';

export type AdmissionStatus = 
  | 'eligible' 
  | 'ineligible' 
  | 'needs_verification';

export type I20Status = 
  | 'not_generated' 
  | 'generated' 
  | 'revoked';

export type RuleOperator = 'and' | 'or';

export type RuleType = 
  | 'gpa_minimum' 
  | 'course_required' 
  | 'course_group' 
  | 'ag_years' 
  | 'test_score' 
  | 'portfolio' 
  | 'experience';

// Institution
export interface Institution {
  id: string;
  name: string;
  code: string;
  logoUrl?: string;
}

// Academic Terms
export interface AcademicTerm {
  id: string;
  name: string; // e.g., "Fall 2025"
  semester: 'fall' | 'spring' | 'summer' | 'winter';
  year: number;
  isCurrent: boolean;
}

// User
export interface User {
  id: string;
  name: string;
  email: string;
  role: UserRole;
  institution: Institution;
  avatarUrl?: string;
}

// Dashboard Stats
export interface DashboardStats {
  transcriptsTotal: number;
  transcriptsProcessed: number;
  transcriptsFailed: number;
  transcriptsInQueue: number;
  applicationsReceived: number;
  eligible: number;
  ineligible: number;
  needsVerification: number;
  i20sGenerated: number;
}

// Cloud Folder Source
export interface CloudFolderSource {
  id: string;
  name: string;
  url: string;
  provider: 'google_drive' | 'dropbox' | 'onedrive' | 's3';
  lastPolled?: string;
  status: 'active' | 'error' | 'paused';
  fileCount?: number;
}

// Transcript Upload
export interface TranscriptUpload {
  id: string;
  fileName: string;
  source: 'manual' | 'cloud';
  sourceName?: string;
  status: TranscriptStatus;
  uploadedAt: string;
  processedAt?: string;
  error?: string;
}

// Student (from transcript)
export interface Student {
  id: string;
  name: string;
  email?: string;
  studentId?: string;
  program?: string;
  major?: string;
  enrollmentYear?: number;
}

// Course (standardized via UC Doorway)
export interface Course {
  id: string;
  code: string;
  name: string;
  credits: number;
  grade: string;
  points: number;
  term: string;
  agGroup?: 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'g';
  ucDoorwayMatch?: {
    matched: boolean;
    standardizedCode?: string;
    standardizedName?: string;
    confidence: number;
  };
}

// Transcript
export interface Transcript {
  id: string;
  student: Student;
  institution: Institution;
  term: AcademicTerm;
  gpa: number;
  totalCredits: number;
  status: TranscriptStatus;
  uploadedAt: string;
  processedAt?: string;
  source: 'manual' | 'cloud';
  ucDoorwayValidated: boolean;
  error?: string;
}

// Transcript Detail
export interface TranscriptDetail extends Transcript {
  courses: Course[];
  personalData: Record<string, string>;
  rawJson?: object;
  standardizationSummary?: {
    totalCourses: number;
    matched: number;
    unmatched: number;
    agGroupCounts: Record<string, number>;
  };
}

// Application
export interface Application {
  id: string;
  student: Student;
  transcript: Transcript;
  program: Program;
  status: AdmissionStatus;
  i20Status: I20Status;
  i20GeneratedAt?: string;
  evaluationSummary: string;
  evaluationDetails: RuleEvaluationResult[];
  appliedAt: string;
  decidedAt?: string;
  overrideReason?: string;
}

// Rule Evaluation Result
export interface RuleEvaluationResult {
  ruleId: string;
  ruleName: string;
  passed: boolean;
  isRequired: boolean;
  isManual: boolean;
  message: string;
  details?: string;
}

// I-20 Document
export interface I20Document {
  id: string;
  applicationId: string;
  studentName: string;
  program: string;
  generatedAt: string;
  status: 'active' | 'revoked';
  revokedAt?: string;
  revokeReason?: string;
}

// Program
export interface Program {
  id: string;
  name: string;
  code: string;
  degreeLevel: 'undergraduate' | 'graduate' | 'doctoral' | 'certificate';
  intakeTerms: string[];
  status: 'active' | 'inactive';
  applicantCount: number;
  requirements: ProgramRequirements;
}

// Program Requirements
export interface ProgramRequirements {
  id: string;
  programId: string;
  rules: AdmissionRule[];
}

// Admission Rule (for rule builder)
export interface AdmissionRule {
  id: string;
  type: RuleType;
  operator?: RuleOperator;
  isRequired: boolean;
  isManual: boolean;
  label: string;
  config: RuleConfig;
  children?: AdmissionRule[]; // For nested AND/OR groups
}

// Rule Configuration
export type RuleConfig =
  | GPAConfig
  | CourseRequiredConfig
  | CourseGroupConfig
  | AGYearsConfig
  | TestScoreConfig
  | GenericConfig;

export interface GPAConfig {
  type: 'gpa_minimum';
  minimumGPA: number;
  scale: number;
}

export interface CourseRequiredConfig {
  type: 'course_required';
  courseCode: string;
  courseName: string;
  minimumGrade: string;
}

export interface CourseGroupConfig {
  type: 'course_group';
  groupName: string;
  courses: string[];
  requiredCount: number;
  minimumGrade: string;
}

export interface AGYearsConfig {
  type: 'ag_years';
  group: 'a' | 'b' | 'c' | 'd' | 'e' | 'f' | 'g';
  minimumYears: number;
}

export interface TestScoreConfig {
  type: 'test_score';
  testName: string;
  minimumScore: number;
}

export interface GenericConfig {
  type: 'portfolio' | 'experience';
  description: string;
}

// Institution Admission Criteria
export interface InstitutionCriteria {
  id: string;
  institutionId: string;
  termId: string;
  rules: AdmissionRule[];
  updatedAt: string;
  updatedBy: string;
}

// Processing Stats
export interface ProcessingStats {
  inQueue: number;
  processing: number;
  processed: number;
  failed: number;
}

// Filter Options
export interface TranscriptFilters {
  status?: TranscriptStatus[];
  gpaMin?: number;
  gpaMax?: number;
  search?: string;
  ucDoorwayValidated?: boolean;
}

export interface ApplicationFilters {
  status?: AdmissionStatus[];
  i20Status?: I20Status[];
  programId?: string;
  search?: string;
}

