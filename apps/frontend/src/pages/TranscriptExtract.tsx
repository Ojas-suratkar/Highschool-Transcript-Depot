import { useCallback, useEffect, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import {
  CheckCircle2,
  FileSpreadsheet,
  ShieldAlert,
  UserRound,
  RotateCcw,
  Loader2,
} from 'lucide-react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { PageHeader } from '@/components/shared/PageHeader';
import { useTerm } from '@/contexts/TermContext';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';
import { listCloudFolders } from '@/lib/api/cloudFolders';
import { emitNotification } from '@/lib/notify';

import ExtractorCompleted from './ExtractorCompleted';
import ExtractorNeedsReview from './ExtractorNeedsReview';
import ExtractorNotProcessed from './ExtractorNotProcessed';

type TabKey = 'completed' | 'review' | 'audit';
type Tone = 'green' | 'amber' | 'red';

type CanonicalCounts = {
  completed: number;
  needs_review: number;
  needs_review_audit: number;
};

type CountUpdateDetail = {
  termName?: string | null;
  count?: number;
  counts?: Partial<CanonicalCounts>;
};

const EMPTY_COUNTS: CanonicalCounts = {
  completed: 0,
  needs_review: 0,
  needs_review_audit: 0,
};

const TABS: {
  key: TabKey;
  label: string;
  confidence: string;
  countKey: keyof CanonicalCounts;
  tone: Tone;
  icon: typeof CheckCircle2;
}[] = [
  {
    key: 'completed',
    label: 'Auto Complete',
    confidence: 'High confidence',
    countKey: 'completed',
    tone: 'green',
    icon: CheckCircle2,
  },
  {
    key: 'review',
    label: 'Human Review',
    confidence: 'Low confidence',
    countKey: 'needs_review',
    tone: 'amber',
    icon: UserRound,
  },
  {
    key: 'audit',
    label: 'Human Review with Audit',
    confidence: 'Very low confidence',
    countKey: 'needs_review_audit',
    tone: 'red',
    icon: ShieldAlert,
  },
];

const TONE: Record<
  Tone,
  {
    border: string;
    text: string;
    icon: string;
    badge: string;
  }
> = {
  green: {
    border: 'border-emerald-500',
    text: 'text-emerald-700',
    icon: 'text-emerald-600',
    badge: 'bg-emerald-100 text-emerald-700',
  },
  amber: {
    border: 'border-amber-500',
    text: 'text-amber-700',
    icon: 'text-amber-600',
    badge: 'bg-amber-100 text-amber-700',
  },
  red: {
    border: 'border-red-500',
    text: 'text-red-700',
    icon: 'text-red-600',
    badge: 'bg-red-100 text-red-700',
  },
};

function readCount(
  payload: Record<string, unknown>,
  keys: string[],
): number {
  for (const key of keys) {
    const value = Number(payload[key]);
    if (Number.isFinite(value) && value >= 0) {
      return value;
    }
  }

  return 0;
}

function normalizeCounts(
  payload: Record<string, unknown>,
): CanonicalCounts {
  return {
    completed: readCount(payload, [
      'completed',
      'auto_complete',
      'auto_completed',
    ]),
    needs_review: readCount(payload, [
      'needs_review',
      'human_review',
      'review',
    ]),
    needs_review_audit: readCount(payload, [
      'needs_review_audit',
      'audit_review',
      'human_review_with_audit',
      'not_processed',
    ]),
  };
}

export default function TranscriptExtract() {
  // Keep teammate/main behavior: the selected tab is reflected in the URL.
  const [searchParams, setSearchParams] = useSearchParams();
  const paramTab = searchParams.get('tab');
  const tab: TabKey =
    paramTab === 'review' || paramTab === 'audit'
      ? paramTab
      : 'completed';

  const { terms, currentTerm } = useTerm();
  const termName = terms.find(
    (term) => term.id === currentTerm,
  )?.term_name;

  // Re-extract every transcript in the term: fan the extraction job across all of
  // the term's upload folders.
  const { startJob } = useExtractionJobs();
  const [reExtracting, setReExtracting] = useState(false);
  const reExtractAll = async () => {
    if (!termName) return;
    setReExtracting(true);
    try {
      const folders = await listCloudFolders(termName);
      if (!folders.length) {
        toast.info('No upload folders found for this term.');
        return;
      }
      await Promise.all(folders.map((f) => startJob({ id: f.id, label: f.label }).catch(() => null)));
      emitNotification({
        kind: 'info',
        title: 'Re-extraction started',
        message: `Re-running extraction for every transcript in ${termName}…`,
        term: termName,
      });
    } catch (e: any) {
      toast.error(e?.message || 'Failed to start re-extraction');
    } finally {
      setReExtracting(false);
    }
  };

  // Keep our canonical/event-driven count logic so all three badges track the
  // selected term correctly, including needs_review_audit.
  const [counts, setCounts] = useState<CanonicalCounts | null>(null);
  const [countLoading, setCountLoading] = useState(false);
  const requestSequenceRef = useRef(0);
  const refreshTimeoutRef = useRef<number | null>(null);

  const loadCounts = useCallback(async () => {
    if (!termName) {
      setCounts(EMPTY_COUNTS);
      return;
    }

    const requestSequence = requestSequenceRef.current + 1;
    requestSequenceRef.current = requestSequence;
    setCountLoading(true);

    try {
      const response = await fetch(
        `/api/extractor/section-counts?term=${encodeURIComponent(termName)}`,
        {
          cache: 'no-store',
          headers: {
            Accept: 'application/json',
          },
        },
      );

      if (!response.ok) {
        throw new Error('Unable to load extraction counts');
      }

      const payload = (await response.json()) as Record<string, unknown>;

      if (requestSequenceRef.current !== requestSequence) {
        return;
      }

      setCounts(normalizeCounts(payload));
    } catch {
      // Preserve the most recent valid counts instead of flashing incorrect zeros.
      setCounts((current) => current ?? EMPTY_COUNTS);
    } finally {
      if (requestSequenceRef.current === requestSequence) {
        setCountLoading(false);
      }
    }
  }, [termName]);

  const scheduleCountRefresh = useCallback(() => {
    if (refreshTimeoutRef.current !== null) {
      window.clearTimeout(refreshTimeoutRef.current);
    }

    refreshTimeoutRef.current = window.setTimeout(() => {
      refreshTimeoutRef.current = null;
      void loadCounts();
    }, 250);
  }, [loadCounts]);

  useEffect(() => {
    setCounts(null);
    void loadCounts();

    // Event-driven updates handle normal changes. This is only a low-frequency
    // safety refresh in case an event is missed.
    const intervalId = window.setInterval(() => {
      void loadCounts();
    }, 60_000);

    return () => {
      window.clearInterval(intervalId);
    };
  }, [loadCounts]);

  useEffect(() => {
    const matchesCurrentTerm = (
      detail: CountUpdateDetail | undefined,
    ): boolean => {
      if (!detail?.termName || !termName) {
        return true;
      }

      return detail.termName === termName;
    };

    const handleAuditCountUpdate = (event: Event) => {
      const detail = (
        event as CustomEvent<CountUpdateDetail>
      ).detail;

      if (!matchesCurrentTerm(detail)) {
        return;
      }

      const value = Number(detail?.count);
      if (!Number.isFinite(value) || value < 0) {
        scheduleCountRefresh();
        return;
      }

      setCounts((current) => ({
        ...(current ?? EMPTY_COUNTS),
        needs_review_audit: value,
      }));
    };

    const handleReviewCountUpdate = (event: Event) => {
      const detail = (
        event as CustomEvent<CountUpdateDetail>
      ).detail;

      if (!matchesCurrentTerm(detail)) {
        return;
      }

      const value = Number(detail?.count);
      if (!Number.isFinite(value) || value < 0) {
        scheduleCountRefresh();
        return;
      }

      setCounts((current) => ({
        ...(current ?? EMPTY_COUNTS),
        needs_review: value,
      }));
    };

    const handleCompletedCountUpdate = (event: Event) => {
      const detail = (
        event as CustomEvent<CountUpdateDetail>
      ).detail;

      if (!matchesCurrentTerm(detail)) {
        return;
      }

      const value = Number(detail?.count);
      if (!Number.isFinite(value) || value < 0) {
        scheduleCountRefresh();
        return;
      }

      setCounts((current) => ({
        ...(current ?? EMPTY_COUNTS),
        completed: value,
      }));
    };

    const handleAllCountsUpdate = (event: Event) => {
      const detail = (
        event as CustomEvent<CountUpdateDetail>
      ).detail;

      if (!matchesCurrentTerm(detail)) {
        return;
      }

      if (!detail?.counts) {
        scheduleCountRefresh();
        return;
      }

      setCounts((current) => ({
        ...(current ?? EMPTY_COUNTS),
        ...detail.counts,
      }));
    };

    const refreshWhenVisible = () => {
      if (document.visibilityState === 'visible') {
        scheduleCountRefresh();
      }
    };

    window.addEventListener(
      'extract-audit-count-updated',
      handleAuditCountUpdate,
    );
    window.addEventListener(
      'extract-review-count-updated',
      handleReviewCountUpdate,
    );
    window.addEventListener(
      'extract-completed-count-updated',
      handleCompletedCountUpdate,
    );
    window.addEventListener(
      'extract-section-counts-updated',
      handleAllCountsUpdate,
    );
    window.addEventListener(
      'transcript-extraction-complete',
      scheduleCountRefresh,
    );
    window.addEventListener('focus', scheduleCountRefresh);
    document.addEventListener(
      'visibilitychange',
      refreshWhenVisible,
    );

    return () => {
      window.removeEventListener(
        'extract-audit-count-updated',
        handleAuditCountUpdate,
      );
      window.removeEventListener(
        'extract-review-count-updated',
        handleReviewCountUpdate,
      );
      window.removeEventListener(
        'extract-completed-count-updated',
        handleCompletedCountUpdate,
      );
      window.removeEventListener(
        'extract-section-counts-updated',
        handleAllCountsUpdate,
      );
      window.removeEventListener(
        'transcript-extraction-complete',
        scheduleCountRefresh,
      );
      window.removeEventListener('focus', scheduleCountRefresh);
      document.removeEventListener(
        'visibilitychange',
        refreshWhenVisible,
      );

      if (refreshTimeoutRef.current !== null) {
        window.clearTimeout(refreshTimeoutRef.current);
        refreshTimeoutRef.current = null;
      }
    };
  }, [scheduleCountRefresh, termName]);

  const handleTabChange = (nextTab: TabKey) => {
    // Keep teammate/main URL-tab behavior and our immediate count refresh.
    setSearchParams(
      nextTab === 'completed' ? {} : { tab: nextTab },
      { replace: true },
    );
    scheduleCountRefresh();
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Extract"
        icon={FileSpreadsheet}
        iconColor="text-violet-600"
        subtitle="Extraction results are grouped by how confident the AI was — the lower the confidence, the more human attention each transcript needs"
        right={
          <Button
            onClick={reExtractAll}
            disabled={reExtracting || !termName}
            className="gap-1.5 bg-emerald-600 text-white hover:bg-emerald-700"
          >
            {reExtracting ? <Loader2 className="h-4 w-4 animate-spin" /> : <RotateCcw className="h-4 w-4" />}
            Re-extract All
          </Button>
        }
      />

      <div className="flex flex-wrap items-stretch gap-1 border-b border-slate-200">
        {TABS.map((tabItem) => {
          const active = tabItem.key === tab;
          const tone = TONE[tabItem.tone];
          const Icon = tabItem.icon;
          const count = counts?.[tabItem.countKey];

          return (
            <button
              key={tabItem.key}
              type="button"
              onClick={() => handleTabChange(tabItem.key)}
              className={`-mb-px flex items-center gap-2.5 border-b-2 px-4 py-2.5 transition-colors ${
                active
                  ? `${tone.border} ${tone.text}`
                  : 'border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              <Icon
                className={`h-4 w-4 shrink-0 ${
                  active ? tone.icon : 'text-slate-400'
                }`}
              />

              <span className="flex flex-col items-start text-left leading-tight">
                <span className="text-sm font-medium">
                  {tabItem.label}
                </span>
                <span className="text-[11px] text-slate-400">
                  {tabItem.confidence}
                </span>
              </span>

              <Badge
                variant="secondary"
                className={`ml-1 min-w-7 justify-center tabular-nums ${
                  active
                    ? tone.badge
                    : 'bg-slate-100 text-slate-500'
                }`}
              >
                {counts === null && countLoading
                  ? '…'
                  : count ?? 0}
              </Badge>
            </button>
          );
        })}
      </div>

      {tab === 'completed' && <ExtractorCompleted embedded />}
      {tab === 'review' && <ExtractorNeedsReview embedded />}
      {tab === 'audit' && <ExtractorNotProcessed embedded />}
    </div>
  );
}
