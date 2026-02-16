import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useState } from 'react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';

type Row = { id: string; format: string; count: number };

const data: Row[] = [
  { id: 'np1', format: 'Lakeside Institute', count: 80 },
  { id: 'np2', format: 'Community College - Strange Layout', count: 60 },
  { id: 'np3', format: 'Unknown Format #3', count: 30 },
];

export default function ExtractorNotProcessed() {
  // no navigation needed; Eye opens preview dialog

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

  const [preview, setPreview] = useState<{ open: boolean; label?: string }>({ open: false });

  return (
    <div className="space-y-6">
      <PageHeader title="Not Processed" subtitle="Formats waiting in backlog (grouped)" />
      <DataTable columns={columns} data={data} keyExtractor={(r) => r.id} />
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
