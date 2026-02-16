import { PageHeader } from '@/components/shared/PageHeader';
import { useState, useEffect } from 'react';
import { Button } from '@/components/ui/button';
import { toast } from 'sonner';
import { Eye } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
// PdfPreviewDialog removed — Eye now opens the details dialog
import seedTranscriptTypesIfMissing from '@/lib/transcriptTypesSeeder';

type TT = {
  id: string;
  name: string;
  processed: number;
  readySince: string;
  status: 'Needs Setup' | 'In Setup' | 'Ready';
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


export default function TranscriptTypesReady() {
  const [rows, setRows] = useState<TT[]>([]);
  const [openRow, setOpenRow] = useState<TT | null>(null);

  useEffect(() => {
  seedTranscriptTypesIfMissing();
  const all = readAll();
  setRows(all.filter((r) => r.status === 'Ready'));
  }, []);

  function readExisting(): any[] {
    try {
      const raw = localStorage.getItem('detector_existing_v1');
      if (!raw) return [];
      return JSON.parse(raw);
    } catch {
      return [];
    }
  }

  function writeExisting(list: { id: string; format: string; count?: number }[]) {
    localStorage.setItem('detector_existing_v1', JSON.stringify(list));
  }

  const handleMoveToExisting = (id: string) => {
    const all = readAll();
    const item = all.find((r) => r.id === id);
    if (!item) {
      toast('Item not found');
      return;
    }
    // remove from transcript types
    const remaining = all.filter((r) => r.id !== id);
    // persist remaining transcript types
    function writeAll(list: TT[]) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(list));
    }
    writeAll(remaining as TT[]);
    setRows(remaining.filter((r) => r.status === 'Ready'));

    // add a full transcript-like record to detector existing storage so the Existing page can show details
    const existing = readExisting();
    const sample = {
      id: `existing-${item.id}`,
      studentName: `${item.name} (Example)` ,
      format: item.name,
      status: 'existing',
      courses: [
        { name: 'Algebra II', grade: 'A', credits: '4' },
        { name: 'English Literature', grade: 'B+', credits: '3' },
      ],
      gpa: '3.5',
      marks: undefined,
      processed: item.processed ?? 0,
      readySince: item.readySince ?? new Date().toISOString(),
    };
    existing.unshift(sample);
    writeExisting(existing);

    toast('Moved to Existing Transcript Types');
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Ready"
        subtitle="Transcript types the system understands — read-only"
      />

      <div className="rounded-md border bg-card p-4">
        <table className="w-full text-left">
          <colgroup>
            <col />
            <col style={{ width: 140 }} />
            <col style={{ width: 220 }} />
          </colgroup>
          <thead>
            <tr className="text-sm text-muted-foreground">
              <th className="pb-2 align-middle">Transcript Type</th>
              <th className="pb-2 text-center align-middle">Processed</th>
              <th className="pb-2 text-right align-middle">Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.id} className="border-t">
                <td className="py-3 align-middle">{row.name}</td>
                <td className="py-3 text-center align-middle">{row.processed ?? 0}</td>
                {/* status column removed for demo */}
                <td className="py-3 text-right align-middle">
                  <div className="inline-flex items-center gap-2 justify-end">
                    <Button size="icon" variant="ghost" onClick={() => setOpenRow(row)}>
                      <Eye className="h-4 w-4" />
                    </Button>
                    <Button size="sm" variant="secondary" onClick={() => handleMoveToExisting(row.id)}>Move to Existing</Button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      
      <Dialog open={!!openRow} onOpenChange={() => setOpenRow(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Transcript Type Details</DialogTitle>
            <DialogDescription>
              {openRow ? (
                <div className="space-y-2">
                  <p className="font-medium">{openRow.name}</p>
                  <p className="text-sm text-muted-foreground">
                    Processed: {openRow.processed ?? 0}
                  </p>
                  <p className="text-sm text-muted-foreground">Ready since: {openRow.readySince ?? '—'}</p>
                  <p className="text-sm">This is a non-technical summary: the system has observed consistent structure and will route new transcripts of this type directly to extraction.</p>
                </div>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button onClick={() => setOpenRow(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
