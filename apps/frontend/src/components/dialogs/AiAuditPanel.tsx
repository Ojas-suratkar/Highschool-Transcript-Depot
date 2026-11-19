import { useEffect, useRef, useState } from 'react';
import { Sparkles, Check, X, ChevronDown, ChevronUp, History } from 'lucide-react';
import { Verdict, getVerdict, getVerdictHistory } from '@/lib/api/termRules';

function decColor(d: string | null | undefined) {
  if (d === 'admitted') return 'bg-emerald-100 text-emerald-700';
  if (d === 'denied') return 'bg-red-100 text-red-700';
  if (d === 'waitlisted') return 'bg-amber-100 text-amber-700';
  return 'bg-slate-100 text-slate-600';
}

/**
 * Handbook-rule audit for one student.
 *
 * Two render modes:
 *  - embedded (used by the Admission Decision card): body only — reasoning,
 *    per-area citations, learned rules and history. No card chrome and no
 *    decision badge of its own, because the parent card owns the single
 *    decision headline. This is what keeps the tab from showing three
 *    competing verdicts.
 *  - standalone (default): the original self-contained collapsible card.
 *
 * `onVerdictChange` lets the parent read the handbook recommendation so it can
 * show one "checks agree / disagree" line instead of a second verdict badge.
 */
export default function AiAuditPanel({
  studentId,
  embedded = false,
  onVerdictChange,
}: {
  studentId?: number | null;
  embedded?: boolean;
  onVerdictChange?: (v: Verdict | null) => void;
}) {
  const [verdict, setVerdict] = useState<Verdict | null>(null);
  const [history, setHistory] = useState<Verdict[]>([]);
  const [open, setOpen] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  // Kept in a ref so a new inline callback from the parent never re-triggers
  // the fetch effect.
  const onVerdictChangeRef = useRef(onVerdictChange);
  onVerdictChangeRef.current = onVerdictChange;

  useEffect(() => {
    setVerdict(null); setHistory([]); setOpen(false); setShowHistory(false);
    onVerdictChangeRef.current?.(null);
    if (!studentId) return;
    let cancelled = false;
    getVerdict(studentId)
      .then((v) => {
        if (cancelled) return;
        setVerdict(v);
        onVerdictChangeRef.current?.(v);
      })
      .catch(() => {});
    getVerdictHistory(studentId)
      .then((h) => { if (!cancelled) setHistory(h); })
      .catch(() => {});
    return () => { cancelled = true; };
  }, [studentId]);

  if (!studentId || !verdict) return null;

  const effective = verdict.overridden ? verdict.override_decision : verdict.decision;
  const previous = history.filter((h) => h.id !== verdict.id);

  const body = (
    <>
      {verdict.reason && (
        <p className="text-xs leading-5 text-slate-700">{verdict.reason}</p>
      )}

      {verdict.per_area && verdict.per_area.length > 0 && (
        <div className="mt-2 grid gap-1 sm:grid-cols-2">
          {verdict.per_area.map((a, i) => (
            <div key={i} className="flex items-start gap-1.5 rounded bg-white/70 px-2 py-1 text-[11px]">
              {a.satisfied ? <Check className="mt-0.5 h-3 w-3 shrink-0 text-emerald-600" /> : <X className="mt-0.5 h-3 w-3 shrink-0 text-red-500" />}
              <span className="min-w-0">
                <span className="font-semibold uppercase">{a.area}</span>: {a.reason}
                {a.cited_courses && a.cited_courses.length > 0 && (
                  <span className="text-slate-500"> — {a.cited_courses.join(', ')}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {verdict.learned_rules && verdict.learned_rules.length > 0 && (
        <div className="mt-2 rounded border border-amber-200 bg-amber-50 p-2 text-[11px] text-amber-800">
          <span className="font-semibold">New rules applied (review on Term Rules):</span>
          <ul className="ml-3 list-disc">
            {verdict.learned_rules.map((r, i) => (
              <li key={i}>{r.title}{r.why_applied ? ` — ${r.why_applied}` : ''}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Previous audits — timeline across handbook versions */}
      {previous.length > 0 && (
        <div className="mt-3">
          <button className="flex items-center gap-1.5 text-[11px] font-medium text-slate-500 hover:text-slate-700" onClick={() => setShowHistory((v) => !v)}>
            <History className="h-3 w-3" /> Previous audits ({previous.length}) {showHistory ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
          </button>
          {showHistory && (
            <div className="mt-1.5 space-y-1.5 border-l-2 border-violet-200 pl-3">
              {previous.map((h) => (
                <div key={h.id} className="text-[11px]">
                  <div className="flex items-center gap-2">
                    <span className={`rounded px-1.5 py-0.5 font-semibold ${decColor(h.overridden ? h.override_decision : h.decision)}`}>
                      {((h.overridden ? h.override_decision : h.decision) || '—').toUpperCase()}
                    </span>
                    <span className="text-slate-400">
                      ruleset v{h.ruleset_version} · {new Date(h.updated_at).toLocaleDateString()}
                      {h.overridden ? ' · overridden' : ''}
                    </span>
                  </div>
                  {h.reason && <p className="mt-0.5 text-slate-500">{h.reason}</p>}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </>
  );

  // Embedded: the parent card supplies the heading, the recommendation chip and
  // the disclosure, so render the reasoning only.
  if (embedded) return <div>{body}</div>;

  return (
    <div className="mb-2 rounded-lg border border-violet-200 bg-violet-50/50">
      {/* Collapsed summary row — always one line */}
      <button
        className="flex w-full items-center justify-between gap-2 px-3 py-2 text-left"
        onClick={() => setOpen((v) => !v)}
      >
        <div className="flex min-w-0 items-center gap-2">
          <Sparkles className="h-4 w-4 shrink-0 text-violet-600" />
          <span className="text-xs font-semibold text-violet-800">Handbook rules</span>
          <span className="text-[10px] text-violet-500">recommends</span>
          <span className={`shrink-0 rounded px-1.5 py-0.5 text-xs font-semibold ${decColor(effective)}`}>
            {(effective || '—').toUpperCase()}
          </span>
          {verdict.overridden && <span className="shrink-0 text-[10px] text-violet-600">(overridden)</span>}
          {!open && verdict.reason && (
            <span className="truncate text-xs text-slate-500">{verdict.reason}</span>
          )}
        </div>
        <span className="flex shrink-0 items-center gap-1 text-[11px] text-violet-600">
          {open ? 'Hide' : 'Details'} {open ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </span>
      </button>

      {open && (
        <div className="border-t border-violet-100 px-3 pb-3 pt-2">
          {body}
          <p className="mt-2 text-[10px] text-slate-400">
            Advisory only — the decision buttons set the final decision.
          </p>
        </div>
      )}
    </div>
  );
}
