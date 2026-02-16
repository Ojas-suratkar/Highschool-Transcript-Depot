// Mock API layer for Highschool Transcript Depot Admissions System
import type {
  DashboardStats,
  CloudFolderSource,
  TranscriptUpload,
  Transcript,
  TranscriptDetail,
  Application,
  Program,
  
  InstitutionCriteria,
  ProcessingStats,
  AcademicTerm,
  User,
  Institution,
  AdmissionRule,
  Course,
} from '@/types/admissions';

const delay = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

// Current user context
const currentInstitution: Institution = {
  id: 'inst-1',
  name: 'University of California, Berkeley',
  code: 'UCB',
  logoUrl: '/placeholder.svg',
};

const currentUser: User = {
  id: 'user-1',
  name: 'Dr. Sarah Martinez',
  email: 'smartinez@berkeley.edu',
  role: 'admissions_officer',
  institution: currentInstitution,
};

const academicTerms: AcademicTerm[] = [
  { id: 'term-1', name: 'Fall 2025', semester: 'fall', year: 2025, isCurrent: true },
  { id: 'term-2', name: 'Spring 2026', semester: 'spring', year: 2026, isCurrent: false },
  { id: 'term-3', name: 'Fall 2024', semester: 'fall', year: 2024, isCurrent: false },
];

// Mock data
const mockTranscripts: Transcript[] = [
  {
    id: 't-1',
    student: { id: 's-1', name: 'Emily Chen', studentId: 'STU-2024-001', program: 'Computer Science', enrollmentYear: 2024 },
    institution: { id: 'mit', name: 'MIT', code: 'MIT' },
    term: academicTerms[0],
    gpa: 3.89,
    totalCredits: 128,
    status: 'processed',
    uploadedAt: '2025-01-05T14:30:00Z',
    processedAt: '2025-01-05T14:32:00Z',
    source: 'manual',
    ucDoorwayValidated: true,
  },
  {
    id: 't-2',
    student: { id: 's-2', name: 'Marcus Johnson', studentId: 'STU-2024-002', program: 'Electrical Engineering' },
    institution: { id: 'stanford', name: 'Stanford University', code: 'SU' },
    term: academicTerms[0],
    gpa: 3.54,
    totalCredits: 96,
    status: 'processed',
    uploadedAt: '2025-01-04T09:15:00Z',
    processedAt: '2025-01-04T09:18:00Z',
    source: 'cloud',
    ucDoorwayValidated: true,
  },
  {
    id: 't-3',
    student: { id: 's-3', name: 'Aisha Patel', studentId: 'STU-2024-003', program: 'Data Science' },
    institution: { id: 'ucsd', name: 'UC San Diego', code: 'UCSD' },
    term: academicTerms[0],
    gpa: 3.72,
    totalCredits: 112,
    status: 'processing',
    uploadedAt: '2025-01-06T08:00:00Z',
    source: 'manual',
    ucDoorwayValidated: false,
  },
  {
    id: 't-4',
    student: { id: 's-4', name: 'James Wilson', studentId: 'STU-2024-004', program: 'Physics' },
    institution: { id: 'caltech', name: 'Caltech', code: 'CT' },
    term: academicTerms[0],
    gpa: 2.89,
    totalCredits: 84,
    status: 'failed',
    uploadedAt: '2025-01-03T16:45:00Z',
    source: 'cloud',
    ucDoorwayValidated: false,
    error: 'OCR failed: Document quality too low',
  },
  {
    id: 't-5',
    student: { id: 's-5', name: 'Sofia Rodriguez', studentId: 'STU-2024-005', program: 'Biology' },
    institution: { id: 'ucla', name: 'UCLA', code: 'UCLA' },
    term: academicTerms[0],
    gpa: 3.95,
    totalCredits: 132,
    status: 'in_queue',
    uploadedAt: '2025-01-06T10:30:00Z',
    source: 'manual',
    ucDoorwayValidated: false,
  },
];

const mockCourses: Course[] = [
  { id: 'c-1', code: 'CS101', name: 'Introduction to Programming', credits: 4, grade: 'A', points: 4.0, term: 'Fall 2023', agGroup: 'g', ucDoorwayMatch: { matched: true, standardizedCode: 'CS-INTRO-101', standardizedName: 'Intro to Computer Science', confidence: 98 } },
  { id: 'c-2', code: 'CS201', name: 'Data Structures', credits: 4, grade: 'A-', points: 3.7, term: 'Spring 2024', agGroup: 'g', ucDoorwayMatch: { matched: true, standardizedCode: 'CS-DS-201', standardizedName: 'Data Structures & Algorithms', confidence: 95 } },
  { id: 'c-3', code: 'MATH201', name: 'Linear Algebra', credits: 3, grade: 'B+', points: 3.3, term: 'Fall 2023', agGroup: 'c', ucDoorwayMatch: { matched: true, standardizedCode: 'MATH-LA-201', standardizedName: 'Linear Algebra', confidence: 99 } },
  { id: 'c-4', code: 'PHYS101', name: 'Physics I', credits: 4, grade: 'A', points: 4.0, term: 'Fall 2023', agGroup: 'd', ucDoorwayMatch: { matched: true, standardizedCode: 'PHYS-101', standardizedName: 'Introductory Physics I', confidence: 97 } },
  { id: 'c-5', code: 'ENG101', name: 'Academic Writing', credits: 3, grade: 'A-', points: 3.7, term: 'Fall 2023', agGroup: 'a', ucDoorwayMatch: { matched: true, standardizedCode: 'ENG-AW-101', standardizedName: 'College Writing', confidence: 92 } },
  { id: 'c-6', code: 'HIST150', name: 'World History', credits: 3, grade: 'B', points: 3.0, term: 'Spring 2024', agGroup: 'a', ucDoorwayMatch: { matched: false, confidence: 45 } },
];

const mockPrograms: Program[] = [
  {
    id: 'prog-1',
    name: 'Computer Science (MS)',
    code: 'CS-MS',
    degreeLevel: 'graduate',
    intakeTerms: ['Fall 2025', 'Spring 2026'],
    status: 'active',
    applicantCount: 245,
    requirements: {
      id: 'req-1',
      programId: 'prog-1',
      rules: [],
    },
  },
  {
    id: 'prog-2',
    name: 'Data Science (MS)',
    code: 'DS-MS',
    degreeLevel: 'graduate',
    intakeTerms: ['Fall 2025'],
    status: 'active',
    applicantCount: 189,
    requirements: {
      id: 'req-2',
      programId: 'prog-2',
      rules: [],
    },
  },
];

const mockApplications: Application[] = [
  {
    id: 'app-1',
    student: mockTranscripts[0].student,
    transcript: mockTranscripts[0],
    program: mockPrograms[0],
    status: 'eligible',
    i20Status: 'generated',
    i20GeneratedAt: '2025-01-06T10:00:00Z',
    evaluationSummary: 'All requirements met',
    evaluationDetails: [],
    appliedAt: '2025-01-05T15:00:00Z',
    decidedAt: '2025-01-06T09:00:00Z',
  },
  {
    id: 'app-2',
    student: mockTranscripts[1].student,
    transcript: mockTranscripts[1],
    program: mockPrograms[0],
    status: 'needs_verification',
    i20Status: 'not_generated',
    evaluationSummary: 'Manual review required for portfolio',
    evaluationDetails: [],
    appliedAt: '2025-01-04T10:00:00Z',
  },
];

const mockCloudFolders: CloudFolderSource[] = [
  {
    id: 'cf-1',
    name: 'Admissions Dropbox',
    url: 'https://dropbox.com/admissions',
    provider: 'dropbox',
    lastPolled: '2025-01-06T08:00:00Z',
    status: 'active',
    fileCount: 42,
  },
  {
    id: 'cf-2',
    name: 'Transfer Documents',
    url: 'https://drive.google.com/transfer',
    provider: 'google_drive',
    lastPolled: '2025-01-05T22:00:00Z',
    status: 'active',
    fileCount: 18,
  },
];

const mockUploads: TranscriptUpload[] = [
  {
    id: 'up-1',
    fileName: 'chen_emily_transcript.pdf',
    source: 'manual',
    status: 'processed',
    uploadedAt: '2025-01-05T14:30:00Z',
    processedAt: '2025-01-05T14:32:00Z',
  },
  {
    id: 'up-2',
    fileName: 'johnson_marcus_transcript.pdf',
    source: 'cloud',
    sourceName: 'Admissions Dropbox',
    status: 'processed',
    uploadedAt: '2025-01-04T09:15:00Z',
    processedAt: '2025-01-04T09:18:00Z',
  },
  {
    id: 'up-3',
    fileName: 'patel_aisha_transcript.pdf',
    source: 'manual',
    status: 'processing',
    uploadedAt: '2025-01-06T08:00:00Z',
  },
];

// API Functions
export async function getCurrentUser(): Promise<User> {
  await delay(100);
  return currentUser;
}

export async function getAcademicTerms(): Promise<AcademicTerm[]> {
  await delay(100);
  return academicTerms;
}

export async function getDashboardStats(): Promise<DashboardStats> {
  await delay(300);
  return {
    transcriptsTotal: mockTranscripts.length,
    transcriptsProcessed: mockTranscripts.filter(t => t.status === 'processed').length,
    transcriptsFailed: mockTranscripts.filter(t => t.status === 'failed').length,
    transcriptsInQueue: mockTranscripts.filter(t => t.status === 'in_queue' || t.status === 'processing').length,
    applicationsReceived: mockApplications.length,
    eligible: mockApplications.filter(a => a.status === 'eligible').length,
    ineligible: mockApplications.filter(a => a.status === 'ineligible').length,
    needsVerification: mockApplications.filter(a => a.status === 'needs_verification').length,
    i20sGenerated: mockApplications.filter(a => a.i20Status === 'generated').length,
  };
}

export async function getCloudFolders(): Promise<CloudFolderSource[]> {
  await delay(200);
  return mockCloudFolders;
}

export async function addCloudFolder(folder: Omit<CloudFolderSource, 'id' | 'status' | 'fileCount'>): Promise<CloudFolderSource> {
  await delay(500);
  const newFolder: CloudFolderSource = {
    ...folder,
    id: `cf-${Date.now()}`,
    status: 'active',
    fileCount: 0,
  };
  mockCloudFolders.push(newFolder);
  return newFolder;
}

export async function pollCloudFolder(id: string): Promise<{ success: boolean; filesFound: number }> {
  await delay(1000);
  const folder = mockCloudFolders.find(f => f.id === id);
  if (folder) {
    folder.lastPolled = new Date().toISOString();
    folder.fileCount = (folder.fileCount || 0) + Math.floor(Math.random() * 5);
  }
  return { success: true, filesFound: Math.floor(Math.random() * 5) };
}

export async function getRecentUploads(): Promise<TranscriptUpload[]> {
  await delay(200);
  return mockUploads;
}

export async function uploadTranscript(file: File): Promise<{ success: boolean; uploadId: string }> {
  await delay(1500);
  const newUpload: TranscriptUpload = {
    id: `up-${Date.now()}`,
    fileName: file.name,
    source: 'manual',
    status: 'in_queue',
    uploadedAt: new Date().toISOString(),
  };
  mockUploads.unshift(newUpload);
  return { success: true, uploadId: newUpload.id };
}

export async function listTranscripts(): Promise<Transcript[]> {
  await delay(300);
  return mockTranscripts;
}

export async function getTranscript(id: string): Promise<TranscriptDetail | null> {
  await delay(200);
  const transcript = mockTranscripts.find(t => t.id === id);
  if (!transcript) return null;

  return {
    ...transcript,
    courses: mockCourses,
    personalData: {
      'Full Name': transcript.student.name,
      'Student ID': transcript.student.studentId || '',
      'Date of Birth': '1998-05-15',
      'Email': transcript.student.email || 'student@example.com',
    },
    standardizationSummary: {
      totalCourses: mockCourses.length,
      matched: mockCourses.filter(c => c.ucDoorwayMatch?.matched).length,
      unmatched: mockCourses.filter(c => !c.ucDoorwayMatch?.matched).length,
      agGroupCounts: {
        a: mockCourses.filter(c => c.agGroup === 'a').length,
        c: mockCourses.filter(c => c.agGroup === 'c').length,
        d: mockCourses.filter(c => c.agGroup === 'd').length,
        g: mockCourses.filter(c => c.agGroup === 'g').length,
      },
    },
  };
}

export async function retryTranscript(id: string): Promise<{ success: boolean }> {
  await delay(500);
  const transcript = mockTranscripts.find(t => t.id === id);
  if (transcript) {
    transcript.status = 'in_queue';
    transcript.error = undefined;
  }
  return { success: true };
}

export async function getProcessingStats(): Promise<ProcessingStats> {
  await delay(100);
  return {
    inQueue: mockTranscripts.filter(t => t.status === 'in_queue').length,
    processing: mockTranscripts.filter(t => t.status === 'processing').length,
    processed: mockTranscripts.filter(t => t.status === 'processed').length,
    failed: mockTranscripts.filter(t => t.status === 'failed').length,
  };
}

export async function listApplications(): Promise<Application[]> {
  await delay(300);
  return mockApplications;
}

export async function getApplication(id: string): Promise<Application | null> {
  await delay(200);
  return mockApplications.find(a => a.id === id) || null;
}

export async function updateApplicationStatus(
  id: string,
  status: Application['status'],
  reason?: string
): Promise<{ success: boolean }> {
  await delay(500);
  const app = mockApplications.find(a => a.id === id);
  if (app) {
    app.status = status;
    app.decidedAt = new Date().toISOString();
    if (reason) app.overrideReason = reason;
  }
  return { success: true };
}

export async function generateI20(applicationId: string): Promise<{ success: boolean; i20Id: string }> {
  await delay(1000);
  const app = mockApplications.find(a => a.id === applicationId);
  if (app) {
    app.i20Status = 'generated';
    app.i20GeneratedAt = new Date().toISOString();
  }
  return { success: true, i20Id: `i20-${Date.now()}` };
}

export async function listPrograms(): Promise<Program[]> {
  await delay(200);
  return mockPrograms;
}

export async function getProgram(id: string): Promise<Program | null> {
  await delay(200);
  return mockPrograms.find(p => p.id === id) || null;
}

export async function updateProgramRequirements(
  programId: string,
  rules: AdmissionRule[]
): Promise<{ success: boolean }> {
  await delay(500);
  const program = mockPrograms.find(p => p.id === programId);
  if (program) {
    program.requirements.rules = rules;
  }
  return { success: true };
}

export async function getInstitutionCriteria(institutionId: string, termId: string): Promise<InstitutionCriteria | null> {
  await delay(200);
  return {
    id: 'crit-1',
    institutionId,
    termId,
    rules: [],
    updatedAt: new Date().toISOString(),
    updatedBy: currentUser.id,
  };
}

export async function updateInstitutionCriteria(
  _institutionId: string,
  _termId: string,
  _rules: AdmissionRule[]
): Promise<{ success: boolean }> {
  await delay(500);
  return { success: true };
}

