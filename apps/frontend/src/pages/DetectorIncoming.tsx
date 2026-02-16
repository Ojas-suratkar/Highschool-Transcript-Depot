import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useState } from 'react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';

type Row = { id: string; format: string; count: number };

const data: Row[] = [
  { id: 'f1', format: 'Lincoln High School', count: 320 },
  { id: 'f2', format: 'Roosevelt District', count: 240 },
  { id: 'f3', format: 'Jefferson Academy', count: 180 },
  { id: 'f4', format: 'West County HS', count: 120 },
  { id: 'f5', format: 'Other Formats', count: 140 },
];

export default function DetectorIncoming() {
  const [preview, setPreview] = useState<{ open: boolean; label?: string }>({ open: false });

  const columns: ColumnDef<Row>[] = [
    { header: 'Transcript Format', accessor: 'format' },
    { header: 'Quantity', accessor: 'count' },
    {
      header: 'View',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: Row) => (
        <Button variant="ghost" onClick={() => setPreview({ open: true, label: `Format: ${row.format} (id: ${row.id})` })}>
          <Eye className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Incoming Transcripts" subtitle="Summary of all transcript formats currently arriving (count: 1000)" />
  <DataTable columns={columns} data={data} keyExtractor={(r) => r.id} />
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
