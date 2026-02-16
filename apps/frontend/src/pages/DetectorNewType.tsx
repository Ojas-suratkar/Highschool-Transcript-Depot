import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useState } from 'react';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';

type Row = { id: string; format: string; count: number };

const data: Row[] = [
  { id: 'n1', format: 'Northside Preparatory (new)', count: 200 },
  { id: 'n2', format: 'Green Valley Charter (new)', count: 180 },
  { id: 'n3', format: 'Lakeside Institute (new)', count: 120 },
];

export default function DetectorNewType() {
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
      <PageHeader title="New Transcript Type" subtitle="Formats the system is still learning (count: 500)" />
  <DataTable columns={columns} data={data} keyExtractor={(r) => r.id} />
  <PdfPreviewDialog open={preview.open} onOpenChange={(o) => setPreview({ open: o })} idLabel={preview.label} />
    </div>
  );
}
