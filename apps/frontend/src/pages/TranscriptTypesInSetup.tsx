import { PageHeader } from '@/components/shared/PageHeader';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useEffect, useState } from 'react';
import TranscriptDetailDialog, { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';
import seedTranscriptTypesIfMissing from '@/lib/transcriptTypesSeeder';
import { Progress } from '@/components/ui/progress';

type TT = {
  id: string;
  name: string;
  analyzing: number;
  lastUpdated?: string;
  status: 'Needs Setup' | 'In Setup' | 'Ready';
  processed?: number;
  readySince?: string;
};

const STORAGE_KEY = 'transcriptTypes_v1';

function readAll(): TT[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    return JSON.parse(raw) as TT[];
  } catch {
    return [];
  }
}

function writeAll(list: TT[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}


export default function TranscriptTypesInSetup() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<TT[]>([]);
  const [detail, setDetail] = useState<TranscriptRecord | null>(null);

  function createSampleTranscript(r: TT): TranscriptRecord {
    return {
      id: `insetup-${r.id}`,
      studentName: `${r.name} Student`,
      email: `${r.name.replace(/\s+/g, '').toLowerCase()}@example.edu`,
      format: r.name,
      birthDate: '2004-05-12',
      graduationDate: '2022-06-01',
      courses: [
        { name: 'Algebra II', grade: 'A', credits: '4' },
        { name: 'English Literature', grade: 'B+', credits: '3' },
        { name: 'Biology', grade: 'A-', credits: '4' },
      ],
      gpa: '3.67',
      marks: '330/400',
      notes: 'Demo transcript generated for preview',
    };
  }

  useEffect(() => {
  seedTranscriptTypesIfMissing();
  const all = readAll();
  setRows(all.filter((r) => r.status === 'In Setup') as TT[]);
  }, []);

  // Simulate background progress for demo purposes and optionally auto-advance to Ready
  useEffect(() => {
  const interval = setInterval(() => {
      // Read latest from storage so other tabs/changes are respected
      const all = readAll();
      let updated = false;

      const next = all.map((r) => {
        if (r.status !== 'In Setup') return r;
        // already finished
        if (r.analyzing >= 10) return r;
        // random small increment to make progress look organic
        const inc = +(Math.random() * 0.9 + 0.4).toFixed(2); // 0.4 - 1.3
        const newAnalyzing = Math.min(10, +(r.analyzing + inc).toFixed(2));
        if (newAnalyzing !== r.analyzing) updated = true;
        return { ...r, analyzing: newAnalyzing };
      });

      if (updated) {
        // Persist progress but don't auto-promote; user must click Move to Ready
        writeAll(next as TT[]);
        const inSetup = next.filter((r) => r.status === 'In Setup') as TT[];
        setRows(inSetup);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [navigate]);

  const handlePromote = (id: string) => {
    const all = readAll().map((r) =>
      r.id === id
        ? { ...r, status: 'Ready', processed: r.analyzing * 10, readySince: new Date().toISOString() }
        : r,
    );
  writeAll(all as TT[]);
    setRows(all.filter((r) => r.status === 'In Setup') as TT[]);
    toast('Moved to Ready — transcript type is now available');
    navigate('/transcripts/new-types/ready');
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="In Setup"
        subtitle="System is learning these transcript types (Training)"
      />

      <div className="rounded-md border bg-card p-4">
        <table className="w-full text-left">
          <colgroup>
            <col />
            <col style={{ width: 160 }} />
            <col style={{ width: 220 }} />
          </colgroup>
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="pb-2 align-middle">Transcript Type</th>
              <th className="pb-2 text-center align-middle">Progress</th>
              <th className="pb-2 text-right align-middle">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="py-3 align-middle">{row.name}</td>
                <td className="py-3 w-48 align-middle">
                  <div className="flex items-center gap-2 justify-center">
                    <div className="w-full max-w-md">
                      <Progress value={Math.min(100, Math.round((row.analyzing / 10) * 100))} className="h-2" />
                    </div>
                    <div className="w-12 text-sm text-muted-foreground text-center align-middle">{Math.min(100, Math.round((row.analyzing / 10) * 100))}%</div>
                  </div>
                </td>
                {/* status column removed for demo */}
                <td className="py-3 text-right align-middle">
                  <div className="inline-flex items-center gap-2 justify-end">
                    <Button size="icon" variant="ghost" onClick={() => setDetail(createSampleTranscript(row))}>
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => handlePromote(row.id)}>Move to Ready</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  <TranscriptDetailDialog open={!!detail} onOpenChange={(open) => { if (!open) setDetail(null); }} transcript={detail} />
    </div>
  );
}
