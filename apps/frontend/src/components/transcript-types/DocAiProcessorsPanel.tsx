import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Clock, Cpu, Loader2, RefreshCw, Zap } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';

type ClassifierLabel = { label: string; key: string; integrated: boolean };

/** Pick the classifier label that best matches an extractor's name. */
function bestLabelMatch(labels: ClassifierLabel[], displayName: string): ClassifierLabel | null {
  const avail = labels.filter((l) => !l.integrated);
  if (!avail.length) return null;
  const target = sanitizeKey(displayName);
  const exact = avail.find((l) => l.key === target);
  if (exact) return exact;
  const contains = avail.find((l) => target.includes(l.key) || l.key.includes(target));
  if (contains) return contains;
  const tokens = new Set(target.split('_').filter(Boolean));
  let best: ClassifierLabel | null = null;
  let bestScore = 0;
  for (const l of avail) {
    const overlap = l.key.split('_').filter((t) => tokens.has(t)).length;
    if (overlap > bestScore) {
      bestScore = overlap;
      best = l;
    }
  }
  return bestScore > 0 ? best : null;
}

/** Normalize a label/name into the type key (lowercase, underscores) — must match
 *  the backend's sanitize_classifier_key so the key lines up with routing. */
function sanitizeKey(value: string): string {
  return String(value || '')
    .trim()
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .replace(/[\s-]+/g, '_')
    .replace(/^_+|_+$/g, '');
}

type Processor = {
  id: string;
  display_name: string;
  state: string;
  lifecycle: 'ready' | 'in_setup';
  trained: boolean;          // has a deployed custom-trained version
  training: boolean;         // a custom version is being built right now
  has_custom_version: boolean;
  default_version: string | null;
  integrated: boolean;
  classifier_name: string;
  label: string;
};

type ProcessorsResponse = {
  ready: Processor[];
  in_setup: Processor[];
  project: string;
  location: string;
};

/**
 * Mirrors the Google Document AI console: lists custom-extraction processors by
 * lifecycle. In "ready" mode each trained processor can be integrated into the
 * app (provisions the classifier_type row, GCS folder, and existing-types entry
 * in one click); "in_setup" mode shows processors still being trained.
 */
export function DocAiProcessorsPanel({ mode }: { mode: 'ready' | 'in_setup' }) {
  const [data, setData] = useState<ProcessorsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [integratingId, setIntegratingId] = useState<string | null>(null);
  const [integrateTarget, setIntegrateTarget] = useState<Processor | null>(null);
  const [typeKey, setTypeKey] = useState('');
  const [classifierLabels, setClassifierLabels] = useState<ClassifierLabel[]>([]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch('/api/transcript-types/processors');
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || `Failed to load processors (${res.status})`);
      }
      setData(await res.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load processors');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const openIntegrate = async (proc: Processor) => {
    setIntegrateTarget(proc);
    setTypeKey(sanitizeKey(proc.display_name));
    setClassifierLabels([]);
    try {
      const res = await fetch('/api/transcript-types/classifier-labels');
      if (res.ok) {
        const body = await res.json();
        const labels: ClassifierLabel[] = body.labels ?? [];
        setClassifierLabels(labels);
        const match = bestLabelMatch(labels, proc.display_name);
        if (match) setTypeKey(match.key); // auto-pick the classifier's real label
      }
    } catch {
      /* labels are optional — fall back to the editable key */
    }
  };

  const confirmIntegrate = async () => {
    const proc = integrateTarget;
    const key = sanitizeKey(typeKey);
    if (!proc || !key) return;
    setIntegratingId(proc.id);
    try {
      const res = await fetch('/api/transcript-types/integrate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ processor_id: proc.id, classifier_name: key, display_name: proc.display_name }),
      });
      const body = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(body.detail || 'Integration failed');
      toast.success(
        `Integrated as "${body.classifier_name}" — wired the extractor and created ${
          body.created_folders?.length ?? 0
        } folder(s).`,
      );
      setIntegrateTarget(null);
      await load();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Integration failed');
    } finally {
      setIntegratingId(null);
    }
  };

  const processors = (data?.[mode] ?? []) as Processor[];

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Loading Document AI processors…
      </div>
    );
  }

  if (error) {
    return (
      <div className="rounded-md border border-destructive/30 bg-destructive/10 p-4 text-sm text-destructive">
        {error}
        <Button variant="ghost" size="sm" className="ml-3" onClick={load}>
          <RefreshCw className="mr-1 h-3.5 w-3.5" /> Retry
        </Button>
      </div>
    );
  }

  return (
    <>
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {data ? (
            <>
              {data.project} · {data.location} ·{' '}
              {mode === 'ready'
                ? 'Trained extractors available for integration.'
                : 'Extractors currently in training.'}
            </>
          ) : null}
        </p>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {processors.length === 0 ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          {mode === 'ready'
            ? 'No trained extractors available.'
            : 'No extractors are currently in training.'}
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {processors.map((proc) => (
            <div key={proc.id} className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-start gap-2.5 min-w-0">
                  <Cpu className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{proc.label || proc.display_name}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {proc.display_name} · {proc.id}
                    </div>
                  </div>
                </div>
                {mode === 'ready' ? (
                  proc.integrated ? (
                    <Badge variant="default" className="shrink-0 gap-1">
                      <CheckCircle2 className="h-3 w-3" /> Integrated
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="shrink-0">
                      {proc.state}
                    </Badge>
                  )
                ) : proc.training ? (
                  <Badge variant="outline" className="shrink-0 gap-1">
                    <Loader2 className="h-3 w-3 animate-spin" /> Training
                  </Badge>
                ) : (
                  <Badge variant="outline" className="shrink-0 gap-1 text-muted-foreground">
                    <Clock className="h-3 w-3" />
                    {proc.has_custom_version ? 'Trained · not deployed' : 'Awaiting training'}
                  </Badge>
                )}
              </div>

              <div className="flex items-center justify-between gap-2">
                <span className="text-xs text-muted-foreground">
                  {proc.default_version ? `version ${proc.default_version}` : 'no default version'}
                </span>
                {mode === 'ready' && !proc.integrated && (
                  <Button
                    size="sm"
                    className="h-8 gap-1.5"
                    disabled={integratingId === proc.id || !proc.trained}
                    onClick={() => openIntegrate(proc)}
                  >
                    {integratingId === proc.id ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Zap className="h-3.5 w-3.5" />
                    )}
                    Integrate
                  </Button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>

      <Dialog open={!!integrateTarget} onOpenChange={(o) => !o && setIntegrateTarget(null)}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Integrate “{integrateTarget?.display_name}”</DialogTitle>
            <DialogDescription>
              Integrate this extractor into the application. The transcript type key must
              match the corresponding classifier label; transcripts classified under that
              label are routed to this extractor.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            {classifierLabels.filter((l) => !l.integrated).length > 0 && (
              <div className="space-y-1.5">
                <Label>Classifier label for this type</Label>
                <Select
                  value={classifierLabels.find((l) => l.key === sanitizeKey(typeKey))?.label ?? ''}
                  onValueChange={(value) => {
                    const match = classifierLabels.find((l) => l.label === value);
                    if (match) setTypeKey(match.key);
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Pick the classifier's label…" />
                  </SelectTrigger>
                  <SelectContent>
                    {classifierLabels
                      .filter((l) => !l.integrated)
                      .map((l) => (
                        <SelectItem key={l.key} value={l.label}>
                          {l.label}
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Classifier labels for this processor. The closest match is preselected;
                  select the label this extractor handles.
                </p>
              </div>
            )}
            <div className="space-y-1.5">
              <Label htmlFor="type-key">Transcript type key</Label>
              <Input
                id="type-key"
                value={typeKey}
                onChange={(e) => setTypeKey(e.target.value)}
                placeholder="e.g. saint_pius"
              />
              <p className="text-xs text-muted-foreground">
                Must match the classifier label. Folder{' '}
                <span className="font-mono">transcript/{sanitizeKey(typeKey) || '…'}/</span>
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setIntegrateTarget(null)}>
              Cancel
            </Button>
            <Button
              disabled={!sanitizeKey(typeKey) || integratingId === integrateTarget?.id}
              onClick={confirmIntegrate}
            >
              {integratingId === integrateTarget?.id ? (
                <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
              ) : (
                <Zap className="mr-1.5 h-3.5 w-3.5" />
              )}
              Integrate
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
