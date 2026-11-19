import { useEffect, useState } from 'react';
import { Plus, Pencil, Trash2, Loader2, Save, X, FileText, Globe } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { PageHeader } from '@/components/shared/PageHeader';
import { toast } from 'sonner';
import {
  type TranscriptCode,
  type TranscriptCodeInput,
  type CodePosition,
  type CodeMeaning,
  MEANING_LABELS,
  POSITION_LABELS,
  listTranscriptTypes,
  listTranscriptCodes,
  createTranscriptCode,
  updateTranscriptCode,
  deleteTranscriptCode,
} from '@/lib/api/transcriptCodes';

const MEANINGS = Object.entries(MEANING_LABELS) as [CodeMeaning, string][];
const POSITIONS = Object.entries(POSITION_LABELS) as [CodePosition, string][];

const MEANING_BADGE: Record<CodeMeaning, string> = {
  honors: 'bg-purple-100 text-purple-700',
  non_academic: 'bg-slate-100 text-slate-600',
  repeated: 'bg-orange-100 text-orange-700',
  college_prep: 'bg-blue-100 text-blue-700',
  ap: 'bg-indigo-100 text-indigo-700',
  dual_enrollment: 'bg-teal-100 text-teal-700',
  other: 'bg-gray-100 text-gray-600',
};

function emptyInput(schoolName: string | null): TranscriptCodeInput {
  return {
    code: '',
    position: 'prefix',
    meaning: 'other',
    label: '',
    school_name: schoolName,
    affects_ag: true,
    strip_for_matching: true,
  };
}

// ---------------------------------------------------------------------------
// Inline add/edit form — shown inside a school card
// ---------------------------------------------------------------------------
function CodeForm({
  initial,
  onSave,
  onCancel,
  saving,
}: {
  initial: TranscriptCodeInput;
  onSave: (v: TranscriptCodeInput) => void;
  onCancel: () => void;
  saving: boolean;
}) {
  const [form, setForm] = useState<TranscriptCodeInput>(initial);
  const set = <K extends keyof TranscriptCodeInput>(k: K, v: TranscriptCodeInput[K]) =>
    setForm((f) => ({ ...f, [k]: v }));

  return (
    <tr className="bg-slate-50">
      <td colSpan={6} className="px-4 py-3">
        <div className="flex flex-wrap items-end gap-3">
          {/* Code */}
          <div className="w-28">
            <Label className="mb-1 block text-xs font-medium">
              Code <span className="text-red-500">*</span>
            </Label>
            <Input
              value={form.code}
              onChange={(e) => set('code', e.target.value)}
              placeholder="+ or * or HP"
              className="h-8 font-mono text-sm"
              maxLength={20}
              autoFocus
            />
          </div>

          {/* Position */}
          <div className="w-32">
            <Label className="mb-1 block text-xs font-medium">Position</Label>
            <select
              value={form.position}
              onChange={(e) => set('position', e.target.value as CodePosition)}
              className="h-8 w-full rounded-md border border-input bg-white px-2 text-sm"
            >
              {POSITIONS.map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>

          {/* Meaning */}
          <div className="w-48">
            <Label className="mb-1 block text-xs font-medium">Meaning</Label>
            <select
              value={form.meaning}
              onChange={(e) => set('meaning', e.target.value as CodeMeaning)}
              className="h-8 w-full rounded-md border border-input bg-white px-2 text-sm"
            >
              {MEANINGS.map(([val, label]) => (
                <option key={val} value={val}>{label}</option>
              ))}
            </select>
          </div>

          {/* Flags */}
          <div className="flex gap-4">
            <label className="flex cursor-pointer items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={form.strip_for_matching}
                onChange={(e) => set('strip_for_matching', e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Strip for UC Doorways
            </label>
            <label className="flex cursor-pointer items-center gap-1.5 text-xs">
              <input
                type="checkbox"
                checked={form.affects_ag}
                onChange={(e) => set('affects_ag', e.target.checked)}
                className="h-3.5 w-3.5"
              />
              Affects A-G
            </label>
          </div>

          {/* Actions */}
          <div className="flex gap-2">
            <Button size="sm" onClick={() => onSave(form)} disabled={saving || !form.code.trim()}>
              {saving
                ? <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />
                : <Save className="mr-1 h-3.5 w-3.5" />}
              {saving ? 'Saving…' : 'Save'}
            </Button>
            <Button size="sm" variant="outline" onClick={onCancel} disabled={saving}>
              <X className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Single code row
// ---------------------------------------------------------------------------
function CodeRow({
  c, editing, saving, onEdit, onSave, onCancel, onDelete,
}: {
  c: TranscriptCode;
  editing: boolean;
  saving: boolean;
  onEdit: () => void;
  onSave: (v: TranscriptCodeInput) => void;
  onCancel: () => void;
  onDelete: () => void;
}) {
  return (
    <>
      <tr className="border-t hover:bg-slate-50/60">
        <td className="px-4 py-2.5">
          <code className="rounded bg-slate-100 px-2 py-0.5 text-sm font-bold">{c.code}</code>
        </td>
        <td className="px-4 py-2.5 text-xs text-slate-500">{POSITION_LABELS[c.position]}</td>
        <td className="px-4 py-2.5">
          <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${MEANING_BADGE[c.meaning] ?? 'bg-gray-100 text-gray-600'}`}>
            {MEANING_LABELS[c.meaning] ?? c.meaning}
          </span>
        </td>
        <td className="px-4 py-2.5">
          <div className="flex gap-2">
            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${c.strip_for_matching ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-400'}`}>
              {c.strip_for_matching ? 'Strip' : 'No strip'}
            </span>
            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${c.affects_ag ? 'bg-orange-100 text-orange-700' : 'bg-slate-100 text-slate-400'}`}>
              {c.affects_ag ? 'Affects A-G' : 'No A-G effect'}
            </span>
          </div>
        </td>
        <td className="px-4 py-2.5 text-sm text-slate-500">
          {c.label || '—'}
        </td>
        <td className="px-4 py-2.5">
          <div className="flex gap-1.5">
            <Button size="sm" variant="ghost" className="h-7 w-7 p-0" onClick={onEdit}>
              <Pencil className="h-3.5 w-3.5" />
            </Button>
            <Button
              size="sm"
              variant="ghost"
              className="h-7 w-7 p-0 text-red-500 hover:bg-red-50 hover:text-red-600"
              onClick={onDelete}
            >
              <Trash2 className="h-3.5 w-3.5" />
            </Button>
          </div>
        </td>
      </tr>
      {editing && (
        <CodeForm
          initial={{
            code: c.code,
            position: c.position,
            meaning: c.meaning,
            label: c.label,
            school_name: c.school_name,
            affects_ag: c.affects_ag,
            strip_for_matching: c.strip_for_matching,
          }}
          onSave={onSave}
          onCancel={onCancel}
          saving={saving}
        />
      )}
    </>
  );
}

// ---------------------------------------------------------------------------
// Transcript type card — one per type (+ one for institution-wide)
// ---------------------------------------------------------------------------
function TranscriptTypeCard({
  typeName,
  codes,
  editingId,
  addingFor,
  saving,
  onEdit,
  onSave,
  onCancelEdit,
  onDelete,
  onStartAdd,
  onCancelAdd,
}: {
  typeName: string | null;
  codes: TranscriptCode[];
  editingId: number | null;
  addingFor: string | null;
  saving: boolean;
  onEdit: (id: number) => void;
  onSave: (input: TranscriptCodeInput, existingId?: number) => void;
  onCancelEdit: () => void;
  onDelete: (id: number, code: string) => void;
  onStartAdd: (typeName: string | null) => void;
  onCancelAdd: () => void;
}) {
  const cardKey = typeName ?? '__institution__';
  const isAdding = addingFor === cardKey;
  const isInstitutionWide = typeName === null;

  return (
    <div className="overflow-hidden rounded-lg border bg-white">
      {/* Card header */}
      <div className={`flex items-center justify-between gap-3 px-4 py-2.5 ${isInstitutionWide ? 'bg-slate-50 border-b' : 'bg-amber-50 border-b border-amber-100'}`}>
        <div className="flex items-center gap-2">
          {isInstitutionWide
            ? <Globe className="h-4 w-4 text-slate-400" />
            : <FileText className="h-4 w-4 text-amber-600" />
          }
          <span className={`text-sm font-semibold ${isInstitutionWide ? 'text-slate-600' : 'text-amber-900'}`}>
            {isInstitutionWide ? 'Institution-wide Fallback' : typeName}
          </span>
          {isInstitutionWide && (
            <span className="text-xs text-slate-400">— applies to all transcript types unless overridden</span>
          )}
          {codes.length > 0 && (
            <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${isInstitutionWide ? 'bg-slate-200 text-slate-600' : 'bg-amber-200 text-amber-800'}`}>
              {codes.length}
            </span>
          )}
        </div>
        <Button
          size="sm"
          variant="outline"
          className="h-7 text-xs"
          onClick={() => onStartAdd(typeName)}
          disabled={isAdding}
        >
          <Plus className="mr-1 h-3.5 w-3.5" />
          Add Code
        </Button>
      </div>

      {/* Table */}
      {(codes.length > 0 || isAdding) && (
        <table className="w-full text-sm">
          {codes.length > 0 && (
            <thead className="text-left text-xs font-medium text-slate-400">
              <tr>
                <th className="px-4 py-1.5">Code</th>
                <th className="px-4 py-1.5">Position</th>
                <th className="px-4 py-1.5">Meaning</th>
                <th className="px-4 py-1.5">Flags</th>
                <th className="px-4 py-1.5">Label</th>
                <th className="px-4 py-1.5"></th>
              </tr>
            </thead>
          )}
          <tbody>
            {codes.map((c) => (
              <CodeRow
                key={c.id}
                c={c}
                editing={editingId === c.id}
                saving={saving}
                onEdit={() => onEdit(c.id)}
                onSave={(input) => onSave(input, c.id)}
                onCancel={onCancelEdit}
                onDelete={() => onDelete(c.id, c.code)}
              />
            ))}
            {isAdding && (
              <CodeForm
                initial={emptyInput(typeName)}
                onSave={(input) => onSave(input)}
                onCancel={onCancelAdd}
                saving={saving}
              />
            )}
          </tbody>
        </table>
      )}

      {/* Empty state */}
      {codes.length === 0 && !isAdding && (
        <p className="px-4 py-3 text-xs text-muted-foreground">
          No codes configured. Click <strong>Add Code</strong> to add one.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------
export default function TranscriptCodes() {
  const [transcriptTypes, setTranscriptTypes] = useState<string[]>([]);
  const [codes, setCodes] = useState<TranscriptCode[]>([]);
  const [loading, setLoading] = useState(true);

  const [saving, setSaving] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [addingFor, setAddingFor] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listTranscriptTypes(), listTranscriptCodes()])
      .then(([t, c]) => { setTranscriptTypes(t); setCodes(c); })
      .finally(() => setLoading(false));
  }, []);

  const handleSave = async (input: TranscriptCodeInput, existingId?: number) => {
    if (!input.code.trim()) { toast.error('Code cannot be empty'); return; }
    setSaving(true);
    try {
      if (existingId != null) {
        const updated = await updateTranscriptCode(existingId, input);
        setCodes((prev) => prev.map((c) => (c.id === existingId ? updated : c)));
        toast.success('Code updated');
        setEditingId(null);
      } else {
        const created = await createTranscriptCode(input);
        setCodes((prev) => [...prev, created]);
        toast.success(`Code "${created.code}" added`);
        setAddingFor(null);
      }
    } catch (err: any) {
      toast.error(err?.message || 'Failed to save');
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: number, code: string) => {
    if (!confirm(`Delete code "${code}"?`)) return;
    try {
      await deleteTranscriptCode(id);
      setCodes((prev) => prev.filter((c) => c.id !== id));
      toast.success(`Code "${code}" deleted`);
    } catch (err: any) {
      toast.error(err?.message || 'Failed to delete');
    }
  };

  const handleStartAdd = (schoolName: string | null) => {
    setEditingId(null);
    setAddingFor(schoolName ?? '__institution__');
  };

  const handleCancelAdd = () => setAddingFor(null);
  const handleEdit = (id: number) => { setAddingFor(null); setEditingId(id); };
  const handleCancelEdit = () => setEditingId(null);

  // Group codes by transcript type (school_name stores the classifier_name)
  const codesByType = new Map<string, TranscriptCode[]>();
  codesByType.set('__institution__', []);
  for (const t of transcriptTypes) codesByType.set(t, []);
  for (const c of codes) {
    const key = c.school_name ?? '__institution__';
    if (!codesByType.has(key)) codesByType.set(key, []);
    codesByType.get(key)!.push(c);
  }

  // Institution-wide first, then transcript types alphabetically
  const typeKeys = ['__institution__', ...transcriptTypes];
  // Also include any type that has codes but wasn't in the fetched list
  for (const key of codesByType.keys()) {
    if (key !== '__institution__' && !transcriptTypes.includes(key)) typeKeys.push(key);
  }

  if (loading) {
    return (
      <div className="space-y-6">
        <PageHeader title="Transcript Settings" subtitle="Configure course ID codes per transcript type" />
        <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Loading…
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <PageHeader
        title="Transcript Settings"
        subtitle="Transcript types are auto-populated from your uploaded transcripts. Add codes per type to control how course IDs are interpreted — e.g. '+' for Mayfair means Honors, '*' for another type means Non-Academic."
      />

      {typeKeys.length === 1 && (codesByType.get('__institution__') ?? []).length === 0 ? (
        <div className="rounded-lg border border-dashed bg-white py-16 text-center text-sm text-muted-foreground">
          <FileText className="mx-auto mb-3 h-8 w-8 text-slate-300" />
          <p className="font-medium">No transcript data uploaded yet</p>
          <p className="mt-1 text-xs">
            Upload transcripts first — transcript types will appear here automatically so you can configure their codes.
          </p>
        </div>
      ) : (
        <div className="space-y-3">
          {typeKeys.map((key) => {
            const typeName = key === '__institution__' ? null : key;
            const typeCodes = codesByType.get(key) ?? [];
            return (
              <TranscriptTypeCard
                key={key}
                typeName={typeName}
                codes={typeCodes}
                editingId={editingId}
                addingFor={addingFor}
                saving={saving}
                onEdit={handleEdit}
                onSave={handleSave}
                onCancelEdit={handleCancelEdit}
                onDelete={handleDelete}
                onStartAdd={handleStartAdd}
                onCancelAdd={handleCancelAdd}
              />
            );
          })}
        </div>
      )}
    </div>
  );
}
