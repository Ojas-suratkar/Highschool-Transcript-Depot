import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useState } from 'react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';

type Row = { id: string; format: string; count: number };

const data: Row[] = [
  { id: 'u1', format: 'Unknown Format #1', count: 60 },
  { id: 'u2', format: 'Unknown Format #2', count: 40 },
];

export default function DetectorUnknown() {
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
      <PageHeader title="Unknown Transcript Type" subtitle="Formats the system cannot classify yet (count: 100)" />
  <DataTable columns={columns} data={data} keyExtractor={(r) => r.id} />
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
