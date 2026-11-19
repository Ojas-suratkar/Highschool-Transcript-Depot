import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import TranscriptDetailDialog, { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';
import { fetchCompletedStudents } from '@/lib/api/extractor';
import { batchCalculateAdmission } from '@/lib/api/studentAgSummary';
import { mapStudentToTranscriptRecord } from '@/lib/studentUtils';
import { useTerm } from '@/contexts/TermContext';
import { useStaleData } from '@/lib/useStaleData';

export default function DecisionsPending() {
  const navigate = useNavigate();
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  // Increment to force useStaleData to re-fetch after batch-calculate saves decisions
  const [refreshKey, setRefreshKey] = useState(0);

  const { data: rawStudents, refreshing } = useStaleData(
    `completed:${termName ?? ''}:${refreshKey}`,
    () => fetchCompletedStudents(termName, true),
    [termName, refreshKey],
    { refreshIntervalMs: 8000 },
  );

  // Auto-calculate on mount / term change so freshly extracted students get
  // recommendations saved without anyone needing to open a dialog.
  useEffect(() => {
    if (!termName) return;
    batchCalculateAdmission(termName).then(({ processed }) => {
      if (processed > 0) setRefreshKey((k) => k + 1);
    });
  }, [termName]);

  const [openId, setOpenId]       = useState<string | null>(null);
  const [active, setActive]       = useState<TranscriptRecord | null>(null);
  const [initialTab, setInitialTab] = useState<'personal' | 'courses' | 'standardization' | 'agRequirement' | 'gpaCalculation' | 'transcript'>('personal');

  // Pending = the unopened (not-yet-reviewed) admitted/denied results.
  const pending = useMemo(() => {
    if (!rawStudents) return [];
    return rawStudents
      .filter((s) => {
        const reviewed = (s as { reviewed?: boolean }).reviewed;
        const decision = (s as { admission_decision?: string }).admission_decision;
        return !reviewed && (decision === 'admitted' || decision === 'denied');
      })
      .map((s) => mapStudentToTranscriptRecord(s, 'completed'))
      .filter((t) => t.studentName || (t.courses && t.courses.length))
      .map((t, idx) => ({ ...t, serial: idx + 1 }));
  }, [rawStudents]);

  // Viewing a student does NOT confirm them. A counselor confirms a student by
  // clicking "Review" on the Admitted/Denied page, which sets reviewed=true and
  // removes them from this Pending list.
  const openDetail = (row: TranscriptRecord, tab: typeof initialTab = 'personal') => {
    setActive(row);
    setOpenId(row.id);
    setInitialTab(tab);
  };

  const columns: ColumnDef<TranscriptRecord>[] = [
    { header: 'S.No', accessor: 'serial', cell: (v) => v ?? '—' },
    { header: 'Student ID', accessor: (r) => r.studentId ?? r.id ?? '—' },
    { header: 'Student Name', accessor: (r) => r as unknown as React.ReactNode, cell: (_, r: TranscriptRecord) => r.studentName || `Unknown Student ${r.id}` },
    { header: 'School', accessor: 'format', cell: (v) => v ?? '—' },
    {
      header: 'Actions',
      accessor: (r) => r as unknown as React.ReactNode,
      cell: (_, row: TranscriptRecord) => (
        <div className="flex items-center gap-2">
          <Button variant="ghost" size="sm" title="View transcript" onClick={() => openDetail(row, 'personal')}>
            <Eye className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader title="Pending Review" subtitle="Students awaiting counselor confirmation" />
      {refreshing && pending.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">Loading…</div>
      ) : (
        <DataTable columns={columns} data={pending} keyExtractor={(r) => r.id} />
      )}

      <TranscriptDetailDialog
        open={!!openId}
        onOpenChange={(open) => { if (!open) setOpenId(null); }}
        transcript={active}
        initialTab={initialTab}
        onDecisionSaved={(decision) => {
          setOpenId(null);
          navigate(`/app/decisions/${decision}`);
        }}
      />
    </div>
  );
}
