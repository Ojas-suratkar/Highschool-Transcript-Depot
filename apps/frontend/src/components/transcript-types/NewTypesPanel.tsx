import { useCallback, useEffect, useState } from 'react';
import { CheckCircle2, Clock, FolderPlus, Loader2, RefreshCw, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Progress } from '@/components/ui/progress';
import { apiFetch } from '@/lib/utils';

type Group = {
  key: string;
  label: string;
  semester: string;
  doc_count: number;
  threshold: number;
  status: string;
  message?: string | null;
};

function prettyLabel(label: string): string {
  return label.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Needs Setup = new transcript layouts the classifier doesn't recognize yet.
 * Each is auto-grouped and collecting transcripts; once a group reaches the
 * threshold it's ready to teach the classifier. This board shows that progress
 * and where each one is in its lifecycle.
 */
export function NewTypesPanel() {
  const [groups, setGroups] = useState<Group[]>([]);
  const [threshold, setThreshold] = useState(15);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await apiFetch<{ groups: Group[]; threshold: number }>(
        '/api/transcript-types/classifier/groups',
      );
      setGroups(res.groups || []);
      setThreshold(res.threshold || 15);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load new types');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  function statusFor(g: Group): {
    text: string;
    badge: 'default' | 'secondary' | 'destructive' | 'outline';
    icon: React.ReactNode;
    ready: boolean;
  } {
    const ready = g.doc_count >= g.threshold;
    if (g.status === 'promoted')
      return { text: 'Trained — configure extractor', badge: 'default', icon: <CheckCircle2 className="h-3 w-3" />, ready: true };
    if (g.status === 'training' || g.status === 'checking')
      return { text: 'Training in progress', badge: 'outline', icon: <Loader2 className="h-3 w-3 animate-spin" />, ready: true };
    if (g.status === 'held')
      return { text: 'Held — review required', badge: 'destructive', icon: <Clock className="h-3 w-3" />, ready: true };
    if (ready || g.status === 'ready')
      return { text: 'Ready for training', badge: 'default', icon: <Sparkles className="h-3 w-3" />, ready: true };
    return {
      text: `Collecting — ${g.threshold - g.doc_count} remaining`,
      badge: 'secondary',
      icon: <FolderPlus className="h-3 w-3" />,
      ready: false,
    };
  }

  if (loading && groups.length === 0) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Scanning for new transcript types…
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
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Transcript types not yet recognized by the classifier. A type becomes eligible for
          classifier training at <span className="font-medium">{threshold}</span> transcripts.
        </p>
        <Button variant="ghost" size="sm" onClick={load} disabled={loading}>
          <RefreshCw className={`mr-1 h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} /> Refresh
        </Button>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No unrecognized transcript types. New types appear here automatically, grouped by layout.
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2">
          {groups.map((g) => {
            const s = statusFor(g);
            const pct = Math.min(100, Math.round((g.doc_count / Math.max(1, g.threshold)) * 100));
            return (
              <div key={`${g.semester}-${g.key}`} className="flex flex-col gap-3 rounded-lg border bg-card p-4 shadow-sm">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <div className="truncate text-sm font-medium">{prettyLabel(g.label)}</div>
                    <div className="truncate text-xs text-muted-foreground">{g.semester}</div>
                  </div>
                  <Badge variant={s.badge} className="shrink-0 gap-1">
                    {s.icon}
                    {s.text}
                  </Badge>
                </div>

                <div>
                  <div className="mb-1 flex items-center justify-between text-xs text-muted-foreground">
                    <span>Collected</span>
                    <span className="font-medium">
                      {g.doc_count} / {g.threshold}
                    </span>
                  </div>
                  <Progress value={pct} className={`h-2 ${s.ready ? '' : ''}`} />
                </div>

                <div className="text-xs text-muted-foreground">
                  {s.ready
                    ? 'Sufficient transcripts collected. Train the classifier to enable routing.'
                    : 'Collecting transcripts of this type.'}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
