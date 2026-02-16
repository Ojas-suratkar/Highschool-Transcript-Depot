import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';

type Decision = { id: string; studentName: string; program: string; status: 'pending' | 'admitted' | 'denied' | 'waitlisted' };

const STORAGE_KEY = 'admission_decisions_v1';

export default function DecisionsAdmitted() {
  const [items, setItems] = useState<Decision[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [active, setActive] = useState<Decision | null>(null);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    let all: Decision[] = [];
    if (raw) {
      try {
        all = JSON.parse(raw) as Decision[];
      } catch (e) {
        all = [];
      }
    }
    setItems(all);
  }, []);

  const admitted = useMemo(() => items.filter((i) => i.status === 'admitted'), [items]);

  const columns: ColumnDef<Decision>[] = [
    { header: 'Student Name', accessor: 'studentName' },
    { header: 'Program', accessor: 'program' },
  // Status column removed per request
    {
      header: 'Actions',
      accessor: (r) => r.id,
      cell: (_, row: Decision) => (
        <div className="flex items-center gap-2">
          <Button variant="ghost" onClick={() => { setActive(row); setOpenId(row.id); }}>
            <Eye className="h-4 w-4" />
          </Button>
          <Button variant="ghost">Generate I-20</Button>
          <Button variant="ghost">Download</Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Admitted" subtitle="Students who have been accepted" />
      <DataTable columns={columns} data={admitted} keyExtractor={(r) => r.id} />

      <Dialog open={!!openId} onOpenChange={() => setOpenId(null)}>
        <DialogContent className="!w-[700px] !max-w-[95%]">
          <DialogHeader>
            <DialogTitle>{active?.studentName}</DialogTitle>
          </DialogHeader>
          <div className="p-4">
            <div className="text-sm text-muted-foreground">Student ID</div>
            <div className="font-medium mb-3">{active?.id}</div>
            <div className="text-sm text-muted-foreground">Program</div>
            <div className="font-medium mb-3">{active?.program}</div>
            <div className="text-sm text-muted-foreground">Status</div>
            <div className="font-medium text-green-700">Admitted</div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenId(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
