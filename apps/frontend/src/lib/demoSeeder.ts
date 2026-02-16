// Lightweight demo data seeder used at app startup to ensure pages show sample cases
const safeSet = (key: string, value: any, force = false) => {
  try {
    const raw = localStorage.getItem(key);
    // Special-case: if stored value is an empty array, treat as missing for demo keys
    const treatEmptyAsMissing = (k: string) => k === 'detector_needs_review_v1';
    if (!raw || force) {
      localStorage.setItem(key, JSON.stringify(value));
      return;
    }

    if (treatEmptyAsMissing(key)) {
      try {
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed) && parsed.length === 0) {
          localStorage.setItem(key, JSON.stringify(value));
          return;
        }
      } catch (e) {
        // fall through to overwrite
        localStorage.setItem(key, JSON.stringify(value));
        return;
      }
    }
  } catch (e) {
    // ignore in non-browser environments
  }
};

export function seedAllDemoDataIfMissing() {
  try {
    // Extractor: needs review
    const needs = [
      { id: 'nr-1', format: 'Northside Prep', status: 'needs_manual_review', reason: 'Unreadable format' },
      { id: 'nr-2', format: null, status: 'needs_manual_review', reason: 'Poor scan' },
      { id: 'nr-3', format: 'Green Valley', status: 'needs_manual_review', reason: 'Missing grades' },
    ];
    safeSet('detector_needs_review_v1', needs);

    // Detector existing / known formats
    const existing = [
      { id: 'e1', name: 'Lincoln HS - Common', lastSeen: new Date().toISOString(), processed: 42 },
      { id: 'e2', name: 'Washington HS - Standard', lastSeen: new Date().toISOString(), processed: 19 },
    ];
    safeSet('detector_existing_v1', existing);

    // Processed transcripts (lightweight preview)
    const processed = [
      { id: 'p1', studentName: 'Emily Chen', school: 'Lincoln HS', gpa: 3.8, courses: 12, templateUsed: 'Lincoln V2', status: 'completed' },
      { id: 'p2', studentName: 'Michael Johnson', school: 'Washington HS', gpa: 3.6, courses: 14, templateUsed: 'Washington V1', status: 'completed' },
    ];
    safeSet('processedTranscripts_v1', processed);

    // Programs (for Programs / ProgramCriteria pages)
    const programs = [
      { id: 'prog-1', name: 'Computer Science (MS)', code: 'CS-MS', degreeLevel: 'graduate', status: 'active' },
      { id: 'prog-2', name: 'Business Administration (BS)', code: 'BA-BS', degreeLevel: 'undergraduate', status: 'active' },
    ];
    safeSet('programs_v1', programs);

    // Admission criteria stub
    const admissionCriteria = {
      id: 'criteria-1',
      name: 'Undergraduate Default',
      rules: [{ id: 'r1', description: 'Minimum GPA 2.5' }],
    };
    safeSet('admissionCriteria', admissionCriteria);

    // App theme preference
    safeSet('app_theme_v1', { theme: 'light' });
  } catch (e) {
    // ignore
  }
}

export default seedAllDemoDataIfMissing;
