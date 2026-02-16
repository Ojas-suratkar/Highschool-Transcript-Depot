import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useMemo, useState, useEffect } from 'react';
import seedAllDemoDataIfMissing from '@/lib/demoSeeder';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { toast } from 'sonner';

type Transcript = {
  id: string;
  format?: string | null;
  status: 'needs_manual_review' | string;
  reason?: string | null;
};

// seed individual transcripts (status=needs_manual_review); grouping will aggregate by format
const seedTranscripts: Transcript[] = [
  { id: 'a1', format: 'Northside Preparatory', status: 'needs_manual_review', reason: 'Unreadable format' },
  { id: 'a2', format: 'Northside Preparatory', status: 'needs_manual_review', reason: 'Unreadable format' },
  { id: 'a3', format: 'Northside Preparatory', status: 'needs_manual_review', reason: 'Missing required information' },
  { id: 'b1', format: 'Green Valley Charter', status: 'needs_manual_review', reason: 'Missing required information' },
  { id: 'b2', format: 'Green Valley Charter', status: 'needs_manual_review', reason: 'Missing required information' },
  { id: 'c1', format: null, status: 'needs_manual_review', reason: 'Poor scan quality' },
  { id: 'c2', format: null, status: 'needs_manual_review', reason: 'Poor scan quality' },
  { id: 'c3', format: null, status: 'needs_manual_review', reason: 'Unsupported layout' },
];

export default function ExtractorNeedsReview() {
  const STORAGE_KEY = 'detector_needs_review_v1';
  const [transcripts, setTranscripts] = useState<Transcript[]>([]);

  useEffect(() => {
    // Ensure global demo data exists (safe, only writes missing keys)
    try {
      seedAllDemoDataIfMissing();
    } catch (e) {
      // ignore in non-browser or restricted environments
    }

    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        const parsed = JSON.parse(raw) as Transcript[];
        if (Array.isArray(parsed) && parsed.length > 0) {
          setTranscripts(parsed);
          return;
        }
      } catch (e) {
        // fall through to seed fallback
      }
    }

    // As a deterministic fallback for local testing, force seed the needs-review list
    // so the page shows demo rows immediately. This is reversible and only affects demo data.
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(seedTranscripts));
      setTranscripts(seedTranscripts);
    } catch (e) {
      // ignore possible storage exceptions
    }
  }, []);

  // Individual list: show each transcript that needs manual review
  const needsReview = useMemo(() => transcripts.filter((t) => t.status === 'needs_manual_review'), [transcripts]);

  const [openTranscriptId, setOpenTranscriptId] = useState<string | null>(null);
  const [formState, setFormState] = useState({
    studentName: '',
    email: '',
    schoolName: '',
    birthDate: '',
    graduationDate: '',
    gpa: '',
    marks: '',
    notes: '',
  });
  const [courses, setCourses] = useState<Array<{ id: string; name: string; grade: string; credits: string }>>([
    { id: Date.now().toString(), name: '', grade: '', credits: '' },
  ]);

  const handleOpenForm = (id: string) => {
    const t = transcripts.find((x) => x.id === id)!;
    setFormState({
      studentName: (t as any).studentName || '',
      email: (t as any).email || '',
      schoolName: t.format || '',
      birthDate: (t as any).birthDate || '',
      graduationDate: (t as any).graduationDate || '',
      gpa: (t as any).gpa || '',
      marks: (t as any).marks || '',
      notes: (t as any).notes || '',
    });
    setCourses(
      (t as any).courses
        ? (t as any).courses.map((c: any, i: number) => ({ id: String(i), name: c.name || '', grade: c.grade || '', credits: c.credits || '' }))
        : [{ id: Date.now().toString(), name: '', grade: '', credits: '' }]
    );
    setOpenTranscriptId(id);
  };

  const handleSave = () => {
    if (!openTranscriptId) return;
    const all = transcripts.map((t) => {
      if (t.id !== openTranscriptId) return t;
      return {
        ...t,
        studentName: formState.studentName || null,
        email: formState.email || null,
        format: formState.schoolName || t.format,
        birthDate: formState.birthDate || null,
        graduationDate: formState.graduationDate || null,
        courses: courses.map((c) => ({ name: c.name, grade: c.grade, credits: c.credits })),
        gpa: formState.gpa || null,
        marks: formState.marks || null,
        notes: formState.notes || null,
        status: 'completed',
        processedAt: new Date().toISOString(),
      } as Transcript & Record<string, any>;
    });
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    setTranscripts(all);
    toast.success('Manual entry saved — transcript marked Completed');
    setOpenTranscriptId(null);
  };

  type Row = { id: string; serial: string; format: string | null; reason?: string | null };
  const columns: ColumnDef<Row>[] = [
    { header: 'S/N', accessor: 'serial' },
    { header: 'Transcript ID', accessor: 'id' },
    { header: 'Transcript Format', accessor: 'format' },
    { header: 'Reason', accessor: 'reason' },
    {
      header: 'Actions',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: Row) => (
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => setPreview({ open: true, label: `Transcript ${row.id} (format: ${row.format ?? 'Unknown'})` })}>
            <Eye className="h-4 w-4" />
          </Button>
          <Button variant="secondary" onClick={() => handleOpenForm(row.id)}>
            Enter Manually
          </Button>
        </div>
      ),
    },
  ];

  const [preview, setPreview] = useState<{ open: boolean; label?: string }>({ open: false });

  return (
    <div className="space-y-6">
      <PageHeader title="Needs Review" subtitle="Individual transcripts requiring manual entry" />
      {needsReview.length === 0 ? (
        <div className="rounded-md border p-6 text-center">
          <p className="mb-4 text-muted-foreground">No transcripts require manual review right now.</p>
          <div className="flex items-center justify-center gap-3">
            <Button onClick={() => {
              try {
                localStorage.setItem(STORAGE_KEY, JSON.stringify(seedTranscripts));
                setTranscripts(seedTranscripts);
              } catch (e) {
                // ignore storage errors
              }
            }}>Populate demo rows</Button>
            <Button variant="outline" onClick={() => setTranscripts([])}>Clear</Button>
          </div>
          <p className="text-xs text-muted-foreground mt-3">After populating, use the eye icon to preview or "Enter Manually" to open the manual entry form.</p>
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={needsReview.map((t, i) => ({ id: t.id, serial: `NR-${String(i + 1).padStart(3, '0')}`, format: t.format ?? null, reason: t.reason ?? null }))}
          keyExtractor={(r) => r.id}
        />
      )}

      <Dialog open={!!openTranscriptId} onOpenChange={() => setOpenTranscriptId(null)}>
        <DialogContent className="!w-[850px] !max-w-[85%]">
          <DialogHeader>
            <DialogTitle>Manual Student Entry</DialogTitle>
            <div className="mt-2">
              <p className="text-sm text-muted-foreground">Transcript: {openTranscriptId}</p>
            </div>
          </DialogHeader>
          <div className="space-y-6 py-4">
            <div className="grid grid-cols-2 gap-6">
              <div>
                <Label htmlFor="studentName">Student Name</Label>
                <Input id="studentName" className="mt-1" value={formState.studentName} onChange={(e) => setFormState({ ...formState, studentName: e.target.value })} placeholder="Full name" />
              </div>
              <div>
                <Label htmlFor="email">Email</Label>
                <Input id="email" className="mt-1" value={formState.email} onChange={(e) => setFormState({ ...formState, email: e.target.value })} placeholder="student@example.com" />
              </div>
              <div>
                <Label htmlFor="schoolName">School</Label>
                <Input id="schoolName" className="mt-1" value={formState.schoolName} onChange={(e) => setFormState({ ...formState, schoolName: e.target.value })} placeholder="School name" />
              </div>
              <div>
                <Label htmlFor="gpa">GPA</Label>
                <Input id="gpa" className="mt-1" value={formState.gpa} onChange={(e) => setFormState({ ...formState, gpa: e.target.value })} placeholder="GPA" />
              </div>
              <div>
                <Label htmlFor="birthDate">Date of Birth</Label>
                <Input id="birthDate" className="mt-1" type="date" value={formState.birthDate} onChange={(e) => setFormState({ ...formState, birthDate: e.target.value })} />
              </div>
              <div>
                <Label htmlFor="graduationDate">Graduation Date</Label>
                <Input id="graduationDate" className="mt-1" type="date" value={formState.graduationDate} onChange={(e) => setFormState({ ...formState, graduationDate: e.target.value })} />
              </div>
            </div>

            <div>
              <div className="flex items-center justify-between">
                <h4 className="text-sm font-medium">Courses</h4>
                <Button variant="ghost" onClick={() => setCourses([...courses, { id: Date.now().toString(), name: '', grade: '', credits: '' }])}>+ Add Course</Button>
              </div>

              <div className="space-y-3 mt-4">
                {courses.map((c) => (
                  <div key={c.id} className="grid grid-cols-12 gap-3 items-center">
                    <div className="col-span-5">
                      <Input className="mt-1" placeholder="Course Name" value={c.name} onChange={(e) => setCourses(courses.map((r) => (r.id === c.id ? { ...r, name: e.target.value } : r)))} />
                    </div>
                    <div className="col-span-3">
                      <select className="mt-1 h-10 w-full rounded-md border bg-background px-3" value={c.grade} onChange={(e) => setCourses(courses.map((r) => (r.id === c.id ? { ...r, grade: e.target.value } : r)))}>
                        <option value="">Grade</option>
                        <option>A</option>
                        <option>B</option>
                        <option>C</option>
                        <option>D</option>
                        <option>F</option>
                      </select>
                    </div>
                    <div className="col-span-3">
                      <Input className="mt-1" placeholder="Credits" value={c.credits} onChange={(e) => setCourses(courses.map((r) => (r.id === c.id ? { ...r, credits: e.target.value } : r)))} />
                    </div>
                    <div className="col-span-1">
                      <Button variant="ghost" onClick={() => setCourses(courses.filter((r) => r.id !== c.id))}>🗑️</Button>
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <Label htmlFor="marks">Marks / Total</Label>
              <Input id="marks" className="mt-1" value={formState.marks} onChange={(e) => setFormState({ ...formState, marks: e.target.value })} placeholder="e.g. 450/500" />
            </div>

            <div>
              <Label htmlFor="notes">Notes</Label>
              <textarea id="notes" className="mt-1 block w-full rounded-md border px-3 py-2" value={formState.notes} onChange={(e) => setFormState({ ...formState, notes: e.target.value })} />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenTranscriptId(null)}>Cancel</Button>
            <Button onClick={handleSave}>Save Student Information</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
