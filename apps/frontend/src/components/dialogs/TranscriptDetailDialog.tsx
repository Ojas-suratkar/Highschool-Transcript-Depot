import { useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

export type TranscriptRecord = {
  id: string;
  status?: string;
  studentName?: string | null;
  email?: string | null;
  format?: string | null;
  birthDate?: string | null;
  graduationDate?: string | null;
  address?: string | null;
  courses?: Array<{ name?: string; grade?: string; credits?: string }>;
  gpa?: string | null;
  marks?: string | null;
  notes?: string | null;
  processed?: number;
  [k: string]: any;
};

function gradeToPoints(grade?: string) {
  if (!grade) return null;
  const g = grade.trim().toUpperCase();
  if (g === 'A+' || g === 'A') return 4.0;
  if (g === 'A-') return 3.7;
  if (g === 'B+') return 3.3;
  if (g === 'B') return 3.0;
  if (g === 'B-') return 2.7;
  if (g === 'C+') return 2.3;
  if (g === 'C') return 2.0;
  if (g === 'C-') return 1.7;
  if (g === 'D') return 1.0;
  if (g === 'F') return 0.0;
  const num = parseFloat(g);
  if (!Number.isNaN(num)) {
    if (num >= 90) return 4.0;
    if (num >= 80) return 3.0;
    if (num >= 70) return 2.0;
    if (num >= 60) return 1.0;
    return 0.0;
  }
  return null;
}

function computeRecalculatedGPA(courses?: TranscriptRecord['courses']) {
  if (!courses || courses.length === 0) return null;
  let totalPoints = 0;
  let totalCredits = 0;
  for (const c of courses) {
    const credits = c?.credits ? parseFloat(String(c.credits)) || 0 : 0;
    const pts = gradeToPoints(c?.grade) ?? 0;
    totalPoints += pts * credits;
    totalCredits += credits;
  }
  if (totalCredits === 0) return null;
  return +(totalPoints / totalCredits).toFixed(2);
}

function parseMarksPercent(marks?: string | null) {
  if (!marks) return null;
  const m = marks.trim();
  const parts = m.split('/');
  if (parts.length === 2) {
    const n = parseFloat(parts[0]);
    const d = parseFloat(parts[1]);
    if (!Number.isNaN(n) && !Number.isNaN(d) && d > 0) return Math.round((n / d) * 100);
  }
  const n = parseFloat(m);
  if (!Number.isNaN(n)) {
    if (n <= 100) return Math.round(n);
    return Math.round((n / 1000) * 100);
  }
  return null;
}

export function TranscriptDetailBody({ transcript }: { transcript?: TranscriptRecord | null }) {
  const [activeTab, setActiveTab] = useState<'personal' | 'courses' | 'standardization'>('personal');

  return (
    <div>
      <div className="mt-4">
        <div className="inline-flex rounded-md bg-muted p-1">
          <button
            onClick={() => setActiveTab('personal')}
            className={
              activeTab === 'personal'
                ? 'px-3 py-1 text-sm font-medium rounded-md bg-background border border-border'
                : 'px-3 py-1 text-sm text-muted-foreground rounded-md'
            }
          >
            Personal Data
          </button>
          <button
            onClick={() => setActiveTab('courses')}
            className={
              activeTab === 'courses'
                ? 'px-3 py-1 text-sm font-medium rounded-md bg-background border border-border'
                : 'px-3 py-1 text-sm text-muted-foreground rounded-md'
            }
          >
            Courses
          </button>
          <button
            onClick={() => setActiveTab('standardization')}
            className={
              activeTab === 'standardization'
                ? 'px-3 py-1 text-sm font-medium rounded-md bg-background border border-border'
                : 'px-3 py-1 text-sm text-muted-foreground rounded-md'
            }
          >
            Standardization
          </button>
        </div>
      </div>

      <div className="mt-4">
        {activeTab === 'personal' && (
          <div className="rounded-md border bg-white shadow-sm">
            <div className="p-4">
              <h4 className="text-lg font-medium">Personal Information</h4>
            </div>
            <div className="divide-y border-t">
              <div className="px-4 py-4 grid grid-cols-4 items-center text-sm">
                <div className="text-muted-foreground">Name</div>
                <div className="font-medium text-foreground">{transcript?.studentName || '—'}</div>
                <div className="text-muted-foreground">Dob</div>
                <div className="font-medium text-foreground">{transcript?.birthDate || '—'}</div>
              </div>
              <div className="px-4 py-4 grid grid-cols-4 items-center text-sm">
                <div className="text-muted-foreground">Student Id</div>
                <div className="font-medium text-foreground">{transcript?.id || '—'}</div>
                <div className="text-muted-foreground">School</div>
                <div className="font-medium text-foreground">{transcript?.format || '—'}</div>
              </div>
              <div className="px-4 py-4 grid grid-cols-4 items-center text-sm">
                <div className="text-muted-foreground">Graduation Date</div>
                <div className="font-medium text-foreground">{transcript?.graduationDate || '—'}</div>
                <div className="text-muted-foreground">Address</div>
                <div className="font-medium text-foreground">{transcript?.address || '—'}</div>
              </div>
            </div>
          </div>
        )}

        {activeTab === 'courses' && transcript?.courses && transcript.courses.length > 0 && (
          <div className="mt-4 rounded-md border p-4 bg-white">
            <h4 className="text-md font-medium">Courses</h4>
            <div className="mt-2 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-muted-foreground">
                    <th className="pb-2">Course</th>
                    <th className="pb-2">Grade</th>
                    <th className="pb-2">Credits</th>
                  </tr>
                </thead>
                <tbody>
                  {transcript.courses.map((c, i) => (
                    <tr key={i} className="border-t">
                      <td className="py-2">{c.name || '—'}</td>
                      <td className="py-2">{c.grade || '—'}</td>
                      <td className="py-2">{c.credits || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {activeTab === 'standardization' && (
          <div className="mt-4">
            <div className="rounded-md border p-4 bg-white">
              <h4 className="text-lg font-medium">Standardization Summary</h4>
              <div className="mt-4 grid grid-cols-3 gap-4">
                <div>
                  <p className="text-sm text-muted-foreground">Extracted GPA</p>
                  <p className="text-2xl font-bold">{transcript?.gpa ?? '—'}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Recalculated GPA</p>
                  <p className="text-2xl font-bold text-green-600">{computeRecalculatedGPA(transcript?.courses) ?? '—'}</p>
                </div>
                <div>
                  <p className="text-sm text-muted-foreground">Marks</p>
                  <p className="text-2xl font-bold">{transcript?.marks ?? '—'}{parseMarksPercent(transcript?.marks) ? ` (${parseMarksPercent(transcript?.marks)}%)` : ''}</p>
                </div>
              </div>

              <div className="mt-6">
                <h5 className="text-sm text-muted-foreground mb-2">Courses (recalculated points)</h5>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-muted-foreground">
                        <th className="pb-2">Course</th>
                        <th className="pb-2">Grade</th>
                        <th className="pb-2">Credits</th>
                        <th className="pb-2">Grade Points</th>
                        <th className="pb-2">Weighted</th>
                        <th className="pb-2">Standardized</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(transcript?.courses || []).map((c, i) => {
                        const credits = c?.credits ? parseFloat(String(c.credits)) || 0 : 0;
                        const pts = gradeToPoints(c?.grade) ?? 0;
                        return (
                          <tr key={i} className="border-t">
                            <td className="py-2">{c?.name || '—'}</td>
                            <td className="py-2">{c?.grade || '—'}</td>
                            <td className="py-2">{credits}</td>
                            <td className="py-2">{pts}</td>
                            <td className="py-2">{(pts * credits).toFixed(2)}</td>
                            <td className="py-2 text-muted-foreground">{(c as any)?.standardizedCode ? (c as any).standardizedCode : 'Not available'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function TranscriptDetailDialog({
  open,
  onOpenChange,
  transcript,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript?: TranscriptRecord | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!w-[900px] !max-w-[95%]">
        <DialogHeader>
          <DialogTitle>Transcript: {transcript?.studentName || transcript?.id || 'Unknown'}</DialogTitle>
          <div className="mt-2">
            <p className="text-sm text-muted-foreground">Student ID: {transcript?.id}</p>
          </div>
        </DialogHeader>

        <TranscriptDetailBody transcript={transcript} />

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Close
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
