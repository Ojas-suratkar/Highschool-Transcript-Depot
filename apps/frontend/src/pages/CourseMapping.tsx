import { useEffect, useMemo, useState } from 'react';
import { Search, Plus, Trash2, Loader2, ArrowRight, RefreshCw } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from '@/components/ui/select';
import { toast } from 'sonner';
import { useTerm } from '@/contexts/TermContext';
import { batchCalculateAdmission } from '@/lib/api/studentAgSummary';
import { invalidateCache } from '@/lib/useStaleData';
import {
  AG_TARGETS, agLabel,
  CourseHit, CourseOverride,
  searchUcCourses, listCourseOverrides, upsertCourseOverride, deleteCourseOverride,
} from '@/lib/api/courseMapping';

export default function CourseMapping() {
  const { terms, currentTerm } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [query, setQuery] = useState('');
  const [hits, setHits] = useState<CourseHit[]>([]);
  const [searching, setSearching] = useState(false);
  const [selected, setSelected] = useState<CourseHit | null>(null);
  const [target, setTarget] = useState<string>('');
  const [saving, setSaving] = useState(false);

  const [overrides, setOverrides] = useState<CourseOverride[]>([]);
  const [recalculating, setRecalculating] = useState(false);

  // New-course form
  const [newName, setNewName] = useState('');
  const [newTarget, setNewTarget] = useState('');

  const refreshOverrides = () => { listCourseOverrides().then(setOverrides).catch(() => {}); };
  useEffect(() => { refreshOverrides(); }, []);

  // Debounced search
  useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setHits([]); return; }
    setSearching(true);
    const t = setTimeout(() => {
      searchUcCourses(q, 30)
        .then((r) => setHits(r))
        .catch(() => setHits([]))
        .finally(() => setSearching(false));
    }, 300);
    return () => clearTimeout(t);
  }, [query]);

  const overrideForSelected = useMemo(() => {
    if (!selected) return undefined;
    const name = selected.course_name.toLowerCase();
    const disc = (selected.discipline ?? '').toLowerCase() || null;
    return overrides.find(
      (o) => o.course_name === name && (o.discipline ?? null) === disc,
    );
  }, [selected, overrides]);

  const openCard = (hit: CourseHit) => {
    setSelected(hit);
    const name = hit.course_name.toLowerCase();
    const disc = (hit.discipline ?? '').toLowerCase() || null;
    const existing = overrides.find((o) => o.course_name === name && (o.discipline ?? null) === disc);
    setTarget(existing?.target_ag ?? (hit.ag_letter?.toLowerCase() || ''));
  };

  const saveReassign = async () => {
    if (!selected || !target) return;
    setSaving(true);
    try {
      await upsertCourseOverride({
        course_name: selected.course_name,
        discipline: selected.discipline ?? null,
        original_ag: selected.ag_letter ?? null,
        target_ag: target,
      });
      toast.success(`"${selected.course_name}" → ${agLabel(target)}`);
      refreshOverrides();
      setSelected(null);
    } catch (e: any) {
      toast.error(e?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const addNew = async () => {
    if (!newName.trim() || !newTarget) return;
    setSaving(true);
    try {
      await upsertCourseOverride({ course_name: newName.trim(), target_ag: newTarget, is_new: true });
      toast.success(`Added "${newName.trim()}" → ${agLabel(newTarget)}`);
      setNewName(''); setNewTarget('');
      refreshOverrides();
    } catch (e: any) {
      toast.error(e?.message || 'Failed to add');
    } finally {
      setSaving(false);
    }
  };

  const remove = async (o: CourseOverride) => {
    try {
      await deleteCourseOverride(o.id);
      setOverrides((prev) => prev.filter((x) => x.id !== o.id));
      toast.success('Override removed');
    } catch (e: any) {
      toast.error(e?.message || 'Failed to remove');
    }
  };

  const recalc = async () => {
    if (!termName) { toast.error('Select a term first'); return; }
    setRecalculating(true);
    try {
      await batchCalculateAdmission(termName, true);
      invalidateCache('completed:');
      toast.success(`Recalculated decisions for ${termName}`);
    } catch (e: any) {
      toast.error(e?.message || 'Recalculation failed');
    } finally {
      setRecalculating(false);
    }
  };

  return (
    <div className="space-y-4">
      <PageHeader title="Course Mapping" subtitle="Reassign a course's A-G category (overrides UC Doorways) or add a new course. Applies to every student on the next recalculation." />

      <div className="flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          {overrides.length} override{overrides.length === 1 ? '' : 's'} active
          {termName ? ` · term: ${termName}` : ''}
        </p>
        <Button size="sm" variant="outline" onClick={recalc} disabled={recalculating}>
          {recalculating ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : <RefreshCw className="mr-1 h-4 w-4" />}
          Recalculate decisions
        </Button>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {/* Search + results */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">Find a course</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Search UC Doorways courses (e.g. AP Calculus, Choir)…"
                className="h-9 pl-8 text-sm"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
              />
            </div>
            <div className="max-h-80 space-y-1 overflow-y-auto">
              {searching && <p className="px-1 py-2 text-xs text-muted-foreground">Searching…</p>}
              {!searching && query.trim().length >= 2 && hits.length === 0 && (
                <p className="px-1 py-2 text-xs text-muted-foreground">No matches.</p>
              )}
              {hits.map((h, i) => (
                <button
                  key={`${h.course_name}-${h.discipline}-${i}`}
                  onClick={() => openCard(h)}
                  className={`flex w-full items-center justify-between gap-2 rounded-md border px-3 py-2 text-left text-xs hover:bg-slate-50 ${
                    selected?.course_name === h.course_name && selected?.discipline === h.discipline ? 'border-slate-400 bg-slate-50' : 'border-slate-200'
                  }`}
                >
                  <div className="min-w-0">
                    <div className="truncate font-medium">{h.course_name}</div>
                    <div className="truncate text-muted-foreground">{h.discipline || '—'} · {h.occurrences.toLocaleString()} schools</div>
                  </div>
                  <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-semibold text-slate-600">
                    {(h.ag_letter || '—').toUpperCase()}
                  </span>
                </button>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Selected course card + reassign */}
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm">{selected ? 'Reassign course' : 'Course details'}</CardTitle>
          </CardHeader>
          <CardContent>
            {!selected ? (
              <p className="text-xs text-muted-foreground">Pick a course on the left to view and reassign it.</p>
            ) : (
              <div className="space-y-3">
                <div>
                  <div className="text-sm font-semibold">{selected.course_name}</div>
                  <div className="text-xs text-muted-foreground">Discipline: {selected.discipline || '—'}</div>
                  <div className="text-xs text-muted-foreground">Appears in {selected.occurrences.toLocaleString()} UC Doorways school lists</div>
                </div>
                <div className="flex items-center gap-2 text-xs">
                  <span className="text-muted-foreground">UC Doorways A-G:</span>
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 font-semibold">{agLabel(selected.ag_letter)}</span>
                  {overrideForSelected && (
                    <>
                      <ArrowRight className="h-3 w-3 text-muted-foreground" />
                      <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-semibold text-emerald-700">{agLabel(overrideForSelected.target_ag)} (current override)</span>
                    </>
                  )}
                </div>
                <div className="space-y-1.5">
                  <Label className="text-xs">Reassign to</Label>
                  <Select value={target} onValueChange={setTarget}>
                    <SelectTrigger className="h-9 text-xs"><SelectValue placeholder="Choose A-G category" /></SelectTrigger>
                    <SelectContent>
                      {AG_TARGETS.map((t) => (
                        <SelectItem key={t.value} value={t.value} className="text-xs">{t.label}</SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" onClick={saveReassign} disabled={saving || !target}>
                    {saving ? <Loader2 className="mr-1 h-4 w-4 animate-spin" /> : null}
                    Save override
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setSelected(null)}>Cancel</Button>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Add a new course (not in UC Doorways) */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Add a new course</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[220px] flex-1 space-y-1.5">
              <Label className="text-xs">Course name (as it appears on transcripts)</Label>
              <Input className="h-9 text-xs" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="e.g. Ethnic Studies Seminar" />
            </div>
            <div className="w-64 space-y-1.5">
              <Label className="text-xs">A-G category</Label>
              <Select value={newTarget} onValueChange={setNewTarget}>
                <SelectTrigger className="h-9 text-xs"><SelectValue placeholder="Choose" /></SelectTrigger>
                <SelectContent>
                  {AG_TARGETS.map((t) => (
                    <SelectItem key={t.value} value={t.value} className="text-xs">{t.label}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <Button size="sm" onClick={addNew} disabled={saving || !newName.trim() || !newTarget}>
              <Plus className="mr-1 h-4 w-4" /> Add
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Existing overrides */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Active overrides</CardTitle>
        </CardHeader>
        <CardContent>
          {overrides.length === 0 ? (
            <p className="text-xs text-muted-foreground">No overrides yet. UC Doorways classifications are used as-is.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="border-b text-left text-muted-foreground">
                    <th className="py-1.5 pr-3 font-medium">Course</th>
                    <th className="py-1.5 pr-3 font-medium">Discipline</th>
                    <th className="py-1.5 pr-3 font-medium">UC A-G</th>
                    <th className="py-1.5 pr-3 font-medium">Reassigned to</th>
                    <th className="py-1.5 pr-3 font-medium"></th>
                  </tr>
                </thead>
                <tbody>
                  {overrides.map((o) => (
                    <tr key={o.id} className="border-b last:border-0">
                      <td className="py-1.5 pr-3 font-medium capitalize">
                        {o.course_name}
                        {o.is_new ? <span className="ml-1 rounded bg-blue-100 px-1 text-[10px] text-blue-700">new</span> : null}
                      </td>
                      <td className="py-1.5 pr-3 capitalize text-muted-foreground">{o.discipline || '—'}</td>
                      <td className="py-1.5 pr-3">{(o.original_ag || '—').toUpperCase()}</td>
                      <td className="py-1.5 pr-3">
                        <span className="rounded bg-emerald-100 px-1.5 py-0.5 font-semibold text-emerald-700">{agLabel(o.target_ag)}</span>
                      </td>
                      <td className="py-1.5 pr-3 text-right">
                        <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => remove(o)} title="Remove override">
                          <Trash2 className="h-3.5 w-3.5" />
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
