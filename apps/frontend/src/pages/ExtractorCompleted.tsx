import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye, Download } from 'lucide-react';
// removed unused useNavigate
import { toast } from 'sonner';
import { useEffect, useMemo, useState } from 'react';
import TranscriptDetailDialog from '@/components/dialogs/TranscriptDetailDialog';

type TranscriptRecord = {
  id: string;
  status?: string;
  studentName?: string | null;
  email?: string | null;
  format?: string | null;
  birthDate?: string | null;
  graduationDate?: string | null;
  courses?: Array<{ name?: string; grade?: string; credits?: string }>;
  gpa?: string | null;
  marks?: string | null;
  notes?: string | null;
  [k: string]: any;
};

export default function ExtractorCompleted() {
  // navigate removed (not used in this component)
  const STORAGE_KEY = 'detector_needs_review_v1';
  const [transcripts, setTranscripts] = useState<TranscriptRecord[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    let all: TranscriptRecord[] = [];
    if (raw) {
      try {
        all = JSON.parse(raw) as TranscriptRecord[];
      } catch (e) {
        all = [];
      }
    }

    // If there are no completed transcripts, seed demo completed students
    const demoCompleted: TranscriptRecord[] = [
      {
        id: 'stu-2001',
        status: 'completed',
        studentName: 'John Smith',
        email: 'john.smith@example.edu',
        format: 'Lincoln High School',
        birthDate: '2006-05-15',
        graduationDate: '2025-06-15',
        address: '123 Main St, Los Angeles, CA 90001',
        courses: [
          { name: 'Algebra II', grade: 'A', credits: '4' },
          { name: 'English Literature', grade: 'A-', credits: '4' },
        ],
        gpa: '3.9',
        marks: '880/1000',
        notes: 'Verified by manual entry',
      },
      {
        id: 'stu-2002',
        status: 'completed',
        studentName: 'Maria Gomez',
        email: 'm.gomez@example.edu',
        format: 'Roosevelt District',
        birthDate: '2005-11-02',
        graduationDate: '2024-06-10',
        address: '45 Oak Ave, San Francisco, CA 94102',
        courses: [
          { name: 'Biology', grade: 'B+', credits: '4' },
          { name: 'World History', grade: 'A', credits: '3' },
        ],
        gpa: '3.6',
        marks: '820/1000',
      },
      {
        id: 'stu-2003',
        status: 'completed',
        studentName: 'Alex Johnson',
        email: 'alex.j@example.edu',
        format: 'Jefferson Academy',
        birthDate: '2006-02-20',
        graduationDate: '2025-05-30',
        address: '200 Pine St, Sacramento, CA 95814',
        courses: [
          { name: 'Chemistry', grade: 'B', credits: '4' },
          { name: 'Calculus', grade: 'B+', credits: '4' },
        ],
        gpa: '3.4',
        marks: '780/1000',
      },
      {
        id: 'stu-2004',
        status: 'completed',
        studentName: 'Sana Patel',
        email: 'sana.patel@example.edu',
        format: 'Green Valley Charter',
        birthDate: '2005-07-08',
        graduationDate: '2024-06-12',
        address: '88 Market St, San Jose, CA 95113',
        courses: [
          { name: 'Physics', grade: 'A', credits: '4' },
          { name: 'Economics', grade: 'A', credits: '3' },
        ],
        gpa: '3.95',
        marks: '900/1000',
      },
    ];

    // Ensure demo completed records exist (merge/overwrite by id)
    for (const demo of demoCompleted) {
      const idx = all.findIndex((t) => t.id === demo.id);
      if (idx === -1) {
        all.push(demo);
      } else {
        // replace existing record to guarantee demo data is present
        all[idx] = demo;
      }
    }

    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    setTranscripts(all);
  }, []);

  const completed = useMemo(() => transcripts.filter((t) => t.status === 'completed'), [transcripts]);

  const [active, setActive] = useState<TranscriptRecord | null>(null);
  const [_activeTab, _setActiveTab] = useState<'personal' | 'courses' | 'standardization'>('personal');

  const openDetail = (id: string) => {
    const t = transcripts.find((x) => x.id === id) || null;
    setActive(t);
    setOpenId(id);
  };

  // gradeToPoints helper removed from this file (duplicate elsewhere)

  // helper functions removed from this file; duplicate implementations exist where needed

  const columns: ColumnDef<TranscriptRecord>[] = [
    {
      header: 'Student Name',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: TranscriptRecord) => row.studentName || `Unknown Student ${row.id}`,
    },
    { header: 'Transcript Format', accessor: 'format' },
    {
      header: 'Status',
      accessor: () => 'Completed',
      cell: () => <span className="inline-flex items-center rounded-full bg-green-100 px-2 py-0.5 text-xs font-medium text-green-800">Completed</span>,
    },
    {
      header: 'Actions',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: TranscriptRecord) => (
        <div className="flex gap-2">
          <Button variant="ghost" onClick={() => openDetail(row.id)}>
            <Eye className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            onClick={() => {
              toast('Starting download...');
            }}
          >
            <Download className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Completed" subtitle="Successfully extracted transcripts (student view)" />
      <DataTable columns={columns} data={completed} keyExtractor={(r) => r.id} />

  <TranscriptDetailDialog open={!!openId} onOpenChange={(open) => { if (!open) setOpenId(null); }} transcript={active} />
    </div>
  );
}
