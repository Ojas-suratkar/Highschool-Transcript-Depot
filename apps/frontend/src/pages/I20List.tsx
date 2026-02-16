import { useState } from 'react';
import { Eye, Download, XCircle } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { StatusBadge } from '@/components/shared/StatusBadge';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';

interface I20Document {
  id: string;
  studentName: string;
  program: string;
  generatedDate: string;
  status: 'active' | 'revoked';
}

export default function I20List() {
  const [documents] = useState<I20Document[]>([
    {
      id: '1',
      studentName: 'Emily Chen',
      program: 'Computer Science (MS)',
      generatedDate: '2025-01-06',
      status: 'active',
    },
  ]);
  const [showRevokeDialog, setShowRevokeDialog] = useState(false);

  const columns: ColumnDef<I20Document>[] = [
    { header: 'Student', accessor: 'studentName' },
    { header: 'Program', accessor: 'program' },
    {
      header: 'Generated Date',
      accessor: (row) => new Date(row.generatedDate).toLocaleDateString(),
    },
    {
      header: 'Status',
      accessor: (row) => <StatusBadge status={row.status} />,
    },
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex gap-1">
          <Button size="sm" variant="outline">
            <Eye className="h-4 w-4 mr-1" />
            View
          </Button>
          <Button size="sm" variant="outline">
            <Download className="h-4 w-4 mr-1" />
            Download
          </Button>
          {row.status === 'active' && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setShowRevokeDialog(true)}
            >
              <XCircle className="h-4 w-4 mr-1 text-destructive" />
              Revoke
            </Button>
          )}
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Generated I-20s"
        subtitle="Manage issued I-20 documents"
      />

      <DataTable
        columns={columns}
        data={documents}
        keyExtractor={(row) => row.id}
        emptyMessage="No I-20 documents generated"
      />

      <Dialog open={showRevokeDialog} onOpenChange={setShowRevokeDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Revoke I-20</DialogTitle>
            <DialogDescription>
              Are you sure you want to revoke this I-20 document? This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowRevokeDialog(false)}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={() => setShowRevokeDialog(false)}>
              Revoke I-20
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

