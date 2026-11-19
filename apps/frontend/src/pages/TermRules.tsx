import { useEffect, useRef, useState } from 'react';
import { Upload, Loader2, CheckCircle2, AlertTriangle, Quote } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Switch } from '@/components/ui/switch';
import { toast } from 'sonner';
import { useTerm } from '@/contexts/TermContext';
import { batchCalculateAdmission } from '@/lib/api/studentAgSummary';
import { invalidateCache } from '@/lib/useStaleData';
import {
  RuleSet, TermRule, LearnedRule, RULE_TYPE_LABELS,
  getTermRules, uploadTermRules, saveTermRules, approveTermRules, getLearnedRules,
  reprocessTermRules,
} from '@/lib/api/termRules';
import { Lightbulb, RotateCcw } from 'lucide-react';

export default function TermRules() {
  const { terms, currentTerm } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [ruleset, setRuleset] = useState<RuleSet | null>(null);
  const [rules, setRules] = useState<TermRule[]>([]);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [learned, setLearned] = useState<(LearnedRule & { count?: number })[]>([]);
  const [elapsed, setElapsed] = useState(0);
  const [showExcluded, setShowExcluded] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  // Split by A-G relevance, keeping original indices so edits target the right rule.
  const indexed = rules.map((r, i) => ({ r, i }));
  const relevantRules = indexed.filter(({ r }) => r.relevant !== false);
  const excludedRules = indexed.filter(({ r }) => r.relevant === false);

  const load = () => {
    if (!termName) return;
    getTermRules(termName).then((rs) => {
      setRuleset(rs);
      setRules(rs?.rules ?? []);
    }).catch(() => {});
    getLearnedRules(termName).then(setLearned).catch(() => setLearned([]));
  };
  useEffect(load, [termName]);

  const processing = ruleset?.status === 'processing';

  // Poll while Gemini is extracting in the background; tick an elapsed counter.
  useEffect(() => {
    if (!processing || !termName) return;
    setElapsed(0);
    const tick = setInterval(() => setElapsed((e) => e + 1), 1000);
    const poll = setInterval(() => {
      getTermRules(termName).then((rs) => {
        if (rs && rs.status !== 'processing') {
          setRuleset(rs);
          setRules(rs.rules ?? []);
          if (rs.status === 'error') toast.error('Extraction failed — see details below');
          else toast.success(`Compiled ${rs.rules?.length ?? 0} rules`);
        } else if (rs) {
          setRuleset(rs);
          setRules(rs.rules ?? []); // partial rules grow live while processing
        }
      }).catch(() => {});
    }, 3000);
    return () => { clearInterval(poll); clearInterval(tick); };
  }, [processing, termName]);

  const onUpload = async (file: File) => {
    if (!termName) { toast.error('Select a term first'); return; }
    setUploading(true);
    try {
      const rs = await uploadTermRules(termName, file);
      setRuleset(rs);
      setRules(rs.rules ?? []);
      if (rs.status === 'processing') {
        toast.success('Uploaded — Gemini is reading the handbook…');
      } else {
        toast.success(`Compiled ${rs.rules?.length ?? 0} rules from ${file.name}`);
      }
    } catch (e: any) {
      toast.error(e?.message || 'Upload failed');
    } finally {
      setUploading(false);
    }
  };

  const retryExtraction = async () => {
    if (!ruleset) return;
    try {
      const rs = await reprocessTermRules(ruleset.id);
      setRuleset(rs);
      toast.success('Reprocessing the stored handbook…');
    } catch (e: any) {
      toast.error(e?.message || 'Reprocess failed');
    }
  };

  const setRule = (i: number, patch: Partial<TermRule>) => {
    setRules((prev) => prev.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  };

  const saveEdits = async () => {
    if (!ruleset) return;
    setSaving(true);
    try {
      const rs = await saveTermRules(ruleset.id, rules);
      setRuleset(rs);
      toast.success('Saved');
    } catch (e: any) {
      toast.error(e?.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  const approve = async () => {
    if (!ruleset) return;
    const approvedCount = rules.filter((r) => r.approved).length;
    if (approvedCount === 0) { toast.error('Approve at least one rule first'); return; }
    setSaving(true);
    try {
      await saveTermRules(ruleset.id, rules);
      const rs = await approveTermRules(ruleset.id);
      setRuleset(rs);
      setRules(rs.rules ?? []);
      const boundCount = (rs.rules ?? []).filter((r) => r.engine_binding).length;
      toast.success(
        `Activated ${rs.rules?.length ?? 0} rules for ${termName}` +
        (boundCount ? ` — ${boundCount} configured into the engine` : ''),
      );
      // Apply immediately: force-recalculate every student's decision under the
      // new rules (fire-and-forget; engine is instant, AI audits fill in and
      // cache as they complete).
      if (termName) {
        toast.success('Recalculating all student decisions with the new rules…');
        void batchCalculateAdmission(termName, true)
          .then(({ processed }) => {
            invalidateCache('completed:');
            if (processed > 0) toast.success(`${processed} students re-decided under the new rules`);
          })
          .catch(() => {});
      }
    } catch (e: any) {
      toast.error(e?.message || 'Approve failed');
    } finally {
      setSaving(false);
    }
  };

  const isApproved = ruleset?.status === 'approved';

  return (
    <div className="space-y-4">
      <PageHeader title="Advanced Admission Rules" subtitle="Upload a term's admissions handbook. Gemini compiles it into structured, cited rules for you to review and approve. The document is not stored — only the extracted rules." />

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 py-4">
          <div className="text-xs text-muted-foreground">
            {ruleset ? (
              <>
                <span className="font-medium text-foreground">{ruleset.document_name || 'Uploaded document'}</span>
                {' · '}v{ruleset.version} · {' '}
                <span className={isApproved ? 'text-emerald-600' : ruleset.status === 'error' ? 'text-red-600' : 'text-amber-600'}>
                  {isApproved
                    ? `approved${ruleset.approved_by ? ` by ${ruleset.approved_by}` : ''}`
                    : ruleset.status === 'processing' ? 'processing…'
                    : ruleset.status === 'error' ? 'extraction failed'
                    : 'draft — needs review'}
                </span>
                {termName ? ` · ${termName}` : ''}
                {ruleset.document_gcs_path && (
                  <div className="mt-0.5 text-[10px] text-muted-foreground">
                    Stored: {ruleset.document_gcs_path} (replaced on new upload; removed with the term)
                  </div>
                )}
              </>
            ) : (
              termName ? `No rules compiled yet for ${termName}.` : 'Select a term.'
            )}
          </div>
          <div className="flex gap-2">
            <input
              ref={fileRef}
              type="file"
              accept="application/pdf"
              className="hidden"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ''; }}
            />
            <Button size="sm" onClick={() => fileRef.current?.click()} disabled={uploading || processing || !termName}>
              {uploading || processing ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <Upload className="mr-1 h-4 w-4" />}
              {uploading ? 'Uploading…' : processing ? 'Processing…' : 'Upload handbook PDF'}
            </Button>
          </div>
        </CardContent>
      </Card>

      {processing && (
        <Card>
          <CardContent className="py-6">
            <div className="flex flex-col items-center gap-3 text-center">
              <Loader2 className="h-7 w-7 animate-spin text-violet-500" />
              <div className="text-sm font-medium">Gemini is reading and structuring the handbook…</div>
              <div className="text-xs text-muted-foreground">
                {ruleset?.pages_total
                  ? <>Reading pages {ruleset.pages_done ?? 0} / {ruleset.pages_total} · {rules.length} rule{rules.length === 1 ? '' : 's'} found so far · {elapsed}s</>
                  : <>Preparing the document… {elapsed}s</>}
              </div>
              <div className="h-1.5 w-full max-w-sm overflow-hidden rounded-full bg-slate-100">
                <div
                  className="h-full rounded-full bg-violet-500 transition-all duration-500"
                  style={{
                    width: ruleset?.pages_total
                      ? `${Math.round(((ruleset.pages_done ?? 0) / ruleset.pages_total) * 100)}%`
                      : `${Math.min(20, elapsed)}%`,
                  }}
                />
              </div>
              {elapsed > 300 && (
                <div className="flex items-center gap-2 text-xs text-amber-600">
                  This is taking longer than usual.
                  <Button size="sm" variant="outline" className="h-7 px-2 text-xs" onClick={retryExtraction}>
                    <RotateCcw className="mr-1 h-3 w-3" /> Retry from stored handbook
                  </Button>
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {ruleset?.status === 'error' && (
        <Card>
          <CardContent className="py-4">
            <div className="flex items-start justify-between gap-2 text-sm text-red-700">
              <div className="flex items-start gap-2">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <div>
                  <div className="font-medium">Extraction failed</div>
                  <div className="text-xs text-red-600">{ruleset.error || 'Gemini could not process this document. Retry, or use a text-based (non-scanned) PDF.'}</div>
                </div>
              </div>
              <Button size="sm" variant="outline" className="h-7 shrink-0 px-2 text-xs" onClick={retryExtraction}>
                <RotateCcw className="mr-1 h-3 w-3" /> Retry
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {rules.length > 0 && !processing && (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between pb-3">
            <CardTitle className="text-sm">
              A-G rules ({relevantRules.filter(({ r }) => r.approved).length}/{relevantRules.length} approved)
            </CardTitle>
            <div className="flex gap-2">
              <Button size="sm" variant="outline" onClick={() => setRules((p) => p.map((r) => (r.relevant === false ? r : { ...r, approved: true })))}>Approve all</Button>
              <Button size="sm" variant="outline" onClick={saveEdits} disabled={saving}>Save draft</Button>
              <Button size="sm" onClick={approve} disabled={saving}>
                {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <CheckCircle2 className="mr-1 h-4 w-4" />}
                Approve &amp; activate
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">
              Only rules that affect A-G unit counting are listed here. Everything else the document contained is preserved under "Excluded" below — nothing was discarded.
            </p>
            {relevantRules.map(({ r, i }) => (
              <div key={r.id + i} className={`rounded-md border p-3 ${r.approved ? 'border-emerald-200 bg-emerald-50/40' : 'border-slate-200'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-600">{RULE_TYPE_LABELS[r.type] || r.type}</span>
                      {r.area && <span className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-600">Area {r.area.toUpperCase()}</span>}
                      <span className={`rounded px-1.5 py-0.5 ${r.confidence >= 0.7 ? 'bg-emerald-100 text-emerald-700' : 'bg-amber-100 text-amber-700'}`}>
                        {Math.round(r.confidence * 100)}% conf
                      </span>
                      {r.engine_binding ? (
                        <span className="rounded bg-emerald-600 px-1.5 py-0.5 font-semibold text-white" title={r.engine_binding.label}>
                          ⚙ {r.engine_binding.label.replace(/^Engine: /, '')}
                        </span>
                      ) : (
                        <span className="rounded bg-violet-100 px-1.5 py-0.5 font-semibold text-violet-700" title="No deterministic-engine equivalent — applied by the AI audit layer with citations.">
                          AI audit layer
                        </span>
                      )}
                    </div>
                    <div className="mt-1 text-sm font-medium">{r.title}</div>
                    {Object.keys(r.params || {}).length > 0 && (
                      <div className="mt-0.5 font-mono text-[11px] text-slate-500">{JSON.stringify(r.params)}</div>
                    )}
                    {r.source_quote && (
                      <div className="mt-1.5 flex items-start gap-1.5 text-xs text-muted-foreground">
                        <Quote className="mt-0.5 h-3 w-3 shrink-0" />
                        <span className="italic">"{r.source_quote}"{r.source_page ? ` (p.${r.source_page})` : ''}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex shrink-0 flex-col items-end gap-1">
                    <Switch checked={r.approved} onCheckedChange={(v) => setRule(i, { approved: v })} />
                    <span className="text-[10px] text-muted-foreground">{r.approved ? 'approved' : 'excluded'}</span>
                  </div>
                </div>
              </div>
            ))}
            {relevantRules.length === 0 && (
              <p className="text-xs text-muted-foreground">No A-G-relevant rules found in this document.</p>
            )}
          </CardContent>
        </Card>
      )}

      {excludedRules.length > 0 && !processing && (
        <Card>
          <CardHeader className="pb-3">
            <button className="flex w-full items-center justify-between text-left" onClick={() => setShowExcluded((v) => !v)}>
              <CardTitle className="text-sm text-slate-500">
                Excluded — not A-G unit counting ({excludedRules.length})
              </CardTitle>
              <span className="text-xs text-muted-foreground">{showExcluded ? 'Hide' : 'Show'}</span>
            </button>
          </CardHeader>
          {showExcluded && (
            <CardContent className="space-y-2">
              <p className="text-xs text-muted-foreground">
                Rules the document contained that don't change A-G course counting (GPA math, index thresholds, policies). If anything here actually belongs in the A-G list, click "Move to A-G rules" — nothing has been deleted.
              </p>
              {excludedRules.map(({ r, i }) => (
                <div key={r.id + i} className="rounded-md border border-slate-200 bg-slate-50/50 p-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 text-xs">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-500">{RULE_TYPE_LABELS[r.type] || r.type}</span>
                        <span className="font-medium text-slate-700">{r.title}</span>
                      </div>
                      {r.relevance_reason && <div className="mt-0.5 text-muted-foreground">{r.relevance_reason}</div>}
                      {r.source_quote && <div className="mt-0.5 italic text-muted-foreground">"{r.source_quote.slice(0, 140)}"{r.source_page ? ` (p.${r.source_page})` : ''}</div>}
                    </div>
                    <Button size="sm" variant="outline" className="h-7 shrink-0 px-2 text-[11px]" onClick={() => setRule(i, { relevant: true, relevance_reason: 'Moved to A-G rules by reviewer' })}>
                      Move to A-G rules
                    </Button>
                  </div>
                </div>
              ))}
            </CardContent>
          )}
        </Card>
      )}

      {learned.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm text-violet-700">
              <Lightbulb className="h-4 w-4" /> Rules Gemini learned while evaluating ({learned.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">While auditing students, Gemini applied these rules that weren't in your approved set. Review them and add them to your handbook or a future upload so they become explicit.</p>
            {learned.map((l, i) => (
              <div key={i} className="rounded-md border border-violet-200 bg-violet-50/40 p-2.5 text-xs">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{l.title}</span>
                  {l.count ? <span className="rounded bg-violet-100 px-1.5 py-0.5 text-[10px] text-violet-700">{l.count} student{l.count === 1 ? '' : 's'}</span> : null}
                </div>
                {l.why_applied && <div className="text-muted-foreground">{l.why_applied}</div>}
                {l.source && <div className="mt-0.5 italic text-muted-foreground">source: {l.source}</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}

      {ruleset?.unsupported && ruleset.unsupported.length > 0 && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="flex items-center gap-2 text-sm text-amber-700">
              <AlertTriangle className="h-4 w-4" /> Flagged — not yet supported ({ruleset.unsupported.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">These rules were found in the document but don't map to a supported rule type yet. They are not applied — they're surfaced so nothing is silently ignored.</p>
            {ruleset.unsupported.map((u, i) => (
              <div key={i} className="rounded-md border border-amber-200 bg-amber-50/40 p-2.5 text-xs">
                <div className="font-medium">{u.title || 'Unmapped rule'}</div>
                {u.reason && <div className="text-muted-foreground">{u.reason}</div>}
                {u.source_quote && <div className="mt-1 italic text-muted-foreground">"{u.source_quote}"</div>}
              </div>
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
