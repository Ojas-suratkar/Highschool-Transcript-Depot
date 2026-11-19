import { PageHeader } from '@/components/shared/PageHeader';
import { StandardTable } from '@/components/shared/StandardTable';
import { decisionColumns, schoolOf, DecisionRow } from './decisions/decisionColumns';
import { CheckCircle2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import TranscriptDetailDialog, { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';
import { fetchCompletedStudents } from '@/lib/api/extractor';
import { batchCalculateAdmission } from '@/lib/api/studentAgSummary';
import { mapStudentToTranscriptRecord } from '@/lib/studentUtils';
import { useTerm } from '@/contexts/TermContext';
import { useStaleData } from '@/lib/useStaleData';

export default function DecisionsAdmitted() {
  const navigate = useNavigate();
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [refreshKey, setRefreshKey] = useState(0);

  const { data: rawStudents, refreshing } = useStaleData(
    `completed:${termName ?? ''}:${refreshKey}`,
    () => fetchCompletedStudents(termName, true),
    [termName, refreshKey],
    { refreshIntervalMs: 8000 },
  );

  // Auto-route: compute decisions so admitted students appear right after extraction.
  useEffect(() => {
    if (!termName) return;
    batchCalculateAdmission(termName)
      .then(({ processed }) => {
        if (processed > 0) setRefreshKey((k) => k + 1);
      })
      .catch(() => {});
  }, [termName]);

  const [openId, setOpenId] = useState<string | null>(null);
  const [active, setActive] = useState<TranscriptRecord | null>(null);

  const admitted = useMemo<DecisionRow[]>(() => {
    if (!rawStudents) return [];
    return rawStudents
      .filter((s) => s.admission_decision === 'admitted')
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
      <PageHeader
        title="Admitted"
        icon={CheckCircle2}
        iconColor="text-emerald-600"
        subtitle="Students who meet the admission criteria"
        tone="success"
      />
      {refreshing && admitted.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">Loading…</div>
      ) : (
        <StandardTable
          columns={columns}
          data={admitted}
          rowKey={(r) => r.id}
          flagId={(r) => r.id}
          search
          searchPlaceholder="Search students, schools…"
          storageKey="decisions:admitted"
          emptyMessage="No admitted students yet."
        />
      )}

      <TranscriptDetailDialog
        open={!!openId}
        onOpenChange={(open) => {
          if (!open) setOpenId(null);
        }}
        transcript={active}
        onDecisionSaved={(decision) => {
          setOpenId(null);
          setRefreshKey((k) => k + 1);
          if (decision !== 'admitted') navigate(`/app/decisions/${decision}`);
        }}
      />
    </div>
  );
}
