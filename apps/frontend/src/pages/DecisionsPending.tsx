import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { useEffect, useMemo, useState } from 'react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';

type Decision = { id: string; studentName: string; program: string; status: 'pending' | 'admitted' | 'denied' | 'waitlisted' };

const STORAGE_KEY = 'admission_decisions_v1';

export default function DecisionsPending() {
  const [items, setItems] = useState<Decision[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);

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

    // seed demo decisions if empty
    if (!all || all.length === 0) {
      all = [
        { id: 'stu-2001', studentName: 'John Smith', program: 'Computer Science', status: 'pending' },
        { id: 'stu-2002', studentName: 'Maria Gomez', program: 'Biology', status: 'admitted' },
        { id: 'stu-2003', studentName: 'Alex Johnson', program: 'Chemistry', status: 'waitlisted' },
        { id: 'stu-2004', studentName: 'Sana Patel', program: 'Economics', status: 'admitted' },
        { id: 'stu-2005', studentName: 'Liam Chen', program: 'Mathematics', status: 'denied' },
      ];
      localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
    }

    setItems(all);
  }, []);

  const pending = useMemo(() => items.filter((i) => i.status === 'pending'), [items]);

  const columns: ColumnDef<Decision>[] = [
    { header: 'Student Name', accessor: 'studentName' },
    { header: 'Program', accessor: 'program' },
  // Status column removed per request
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Pending Review" subtitle="Students awaiting final admission decision" />
      <DataTable columns={columns} data={pending} keyExtractor={(r) => r.id} />
      <Dialog open={!!openId} onOpenChange={() => setOpenId(null)}>
        <DialogContent className="!w-[700px] !max-w-[95%]">
          <DialogHeader>
            <DialogTitle>{items.find((i) => i.id === openId)?.studentName}</DialogTitle>
          </DialogHeader>
          <div className="p-4">
            <div className="text-sm text-muted-foreground">Student ID</div>
            <div className="font-medium mb-3">{items.find((i) => i.id === openId)?.id}</div>
            <div className="text-sm text-muted-foreground">Program</div>
            <div className="font-medium mb-3">{items.find((i) => i.id === openId)?.program}</div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpenId(null)}>Close</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
