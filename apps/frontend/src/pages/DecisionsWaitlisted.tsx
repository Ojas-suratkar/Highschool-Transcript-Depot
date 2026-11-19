import { PageHeader } from '@/components/shared/PageHeader';
import { StandardTable } from '@/components/shared/StandardTable';
import { decisionColumns, schoolOf, DecisionRow } from './decisions/decisionColumns';
import { Clock } from 'lucide-react';
import { useMemo, useState } from 'react';
import TranscriptDetailDialog, { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';
import { fetchCompletedStudents } from '@/lib/api/extractor';
import { mapStudentToTranscriptRecord } from '@/lib/studentUtils';
import { useTerm } from '@/contexts/TermContext';
import { useStaleData } from '@/lib/useStaleData';

export default function DecisionsWaitlisted() {
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const { data: rawStudents, refreshing } = useStaleData(
    `completed:${termName ?? ''}`,
    () => fetchCompletedStudents(termName, true),
    [termName],
  );

  const [openId, setOpenId] = useState<string | null>(null);
  const [active, setActive] = useState<TranscriptRecord | null>(null);

  const waitlisted = useMemo<DecisionRow[]>(() => {
    if (!rawStudents) return [];
    return rawStudents
      .filter((s) => s.admission_decision === 'waitlisted')
      .map((s, idx) => ({ ...mapStudentToTranscriptRecord(s, 'completed'), school: schoolOf(s), serial: idx + 1 }));
  }, [rawStudents]);

  const columns = useMemo(
    () =>
      decisionColumns((r) => {
        setActive(r);
        setOpenId(r.id);
      }),
    [],
  );

  return (
    <div className="space-y-6">
      <PageHeader title="Waitlisted" icon={Clock} iconColor="text-amber-600" subtitle="Students deferred for later consideration" />
      {refreshing && waitlisted.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">Loading…</div>
      ) : (
        <StandardTable
          columns={columns}
          data={waitlisted}
          rowKey={(r) => r.id}
          flagId={(r) => r.id}
          search
          searchPlaceholder="Search students, schools…"
          storageKey="decisions:waitlisted"
          emptyMessage="No waitlisted students yet."
        />
      )}

      <TranscriptDetailDialog
        open={!!openId}
        onOpenChange={(open) => {
          if (!open) setOpenId(null);
        }}
        transcript={active}
      />
    </div>
  );
}
