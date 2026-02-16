import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useState, useEffect } from 'react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import type { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';

function readExisting(): TranscriptRecord[] {
  try {
    const raw = localStorage.getItem('detector_existing_v1');
    if (!raw) return [];
    return JSON.parse(raw) as TranscriptRecord[];
  } catch {
    return [];
  }
}

export default function DetectorExisting() {
  const [preview, setPreview] = useState<{ open: boolean; label?: string }>({ open: false });
  const [rows, setRows] = useState<TranscriptRecord[]>([]);

  useEffect(() => {
    setRows(readExisting());
  }, []);

  const columns: ColumnDef<TranscriptRecord>[] = [
    { header: 'Transcript Format', accessor: (r) => r.format ?? r.studentName ?? 'Unknown' },
    { header: 'Quantity', accessor: (r) => (r.processed ?? r.count ?? '-') as unknown as React.ReactNode },
    {
      header: 'View',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: TranscriptRecord) => (
        <Button
          variant="ghost"
          onClick={() => setPreview({ open: true, label: `${row.studentName ?? row.format ?? 'Format'} — id: ${row.id}` })}
        >
          <Eye className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Existing Transcript Type" subtitle="Formats the system already recognizes" />
  <DataTable columns={columns} data={rows} keyExtractor={(r) => r.id} />

  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o, label: preview.label })} idLabel={preview.label} />
    </div>
  );
}
