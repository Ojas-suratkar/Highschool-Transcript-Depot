import { PageHeader } from '@/components/shared/PageHeader';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { useEffect, useState } from 'react';
import seedTranscriptTypesIfMissing from '@/lib/transcriptTypesSeeder';

type TT = {
  id: string;
  name: string;
  count: number;
  status: 'Needs Setup' | 'In Setup' | 'Ready';
};

const seed: TT[] = [
  { id: 't1', name: 'Example High School - Unknown Format', count: 5, status: 'Needs Setup' },
  { id: 't4', name: 'Community College - Strange Layout', count: 2, status: 'Needs Setup' },
  { id: 't5', name: 'Roosevelt Academy - Handwritten Grades', count: 3, status: 'Needs Setup' },
  { id: 't6', name: 'Valley Technical - Multi-column', count: 7, status: 'Needs Setup' },
  { id: 't7', name: 'International - Foreign language headers', count: 4, status: 'Needs Setup' },
];

// seeding is handled by shared seeder

const STORAGE_KEY = 'transcriptTypes_v1';

function readAll(): TT[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return seed;
    return JSON.parse(raw) as TT[];
  } catch {
    return seed;
  }
}

function writeAll(list: TT[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
}

export default function TranscriptTypesNeedsSetup() {
  const navigate = useNavigate();
  const [rows, setRows] = useState<TT[]>([]);
  const [preview, setPreview] = useState<{ open: boolean; label?: string }>({ open: false });

  useEffect(() => {
    seedTranscriptTypesIfMissing();
    setRows(readAll().filter((r) => r.status === 'Needs Setup'));
  }, []);

  const handleObserve = (id: string) => {
  const all = readAll().map((r) =>
    r.id === id
      ? {
          ...r,
          status: 'In Setup',
          analyzing: 1 + Math.floor(Math.random() * 8), // initial analyzing progress (1-8)
          lastUpdated: new Date().toISOString(),
        }
      : r,
  );
  writeAll(all as TT[]);
  setRows(all.filter((r) => r.status === 'Needs Setup') as TT[]);
    toast('Moved to Setup — system will begin analyzing this type');
    navigate('/transcripts/new-types/in-setup');
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Needs Setup"
        subtitle="Auto-detected transcript types awaiting setup"
      />

      <div className="rounded-md border bg-card p-4">
        <table className="w-full text-left">
          <colgroup>
            <col />
            <col style={{ width: 120 }} />
            <col style={{ width: 220 }} />
          </colgroup>
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="pb-2 align-middle">Transcript Type</th>
              <th className="pb-2 text-center align-middle">Count</th>
              <th className="pb-2 text-right align-middle">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="py-3 align-middle">{row.name}</td>
                <td className="py-3 text-center align-middle">{row.count}</td>
                {/* status column removed for demo */}
                <td className="py-3 text-right align-middle">
                  <div className="inline-flex items-center gap-2 justify-end">
                    <Button size="icon" variant="ghost" onClick={() => setPreview({ open: true, label: `Transcript Type: ${row.name}` })}>
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => handleObserve(row.id)}>Move to Setup</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
