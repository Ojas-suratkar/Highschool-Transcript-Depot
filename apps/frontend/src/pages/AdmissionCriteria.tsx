import { useEffect, useState } from 'react';
import { Save, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Switch } from '@/components/ui/switch';
import { PageHeader } from '@/components/shared/PageHeader';
import { useTerm } from '@/contexts/TermContext';
import {
  AgCriteriaInput,
  AgRuleConfig,
  DEFAULT_AG_CRITERIA,
  getAgCriteriaForTerm,
  upsertAgCriteria,
} from '@/lib/api/institutionAgCriteria';
import { batchCalculateAdmission } from '@/lib/api/studentAgSummary';
import { invalidateCache } from '@/lib/useStaleData';
import { toast } from 'sonner';

const AG_ROWS: Array<{ key: keyof AgCriteriaInput; label: string }> = [
  { key: 'a_required', label: 'A — History / Social Science' },
  { key: 'b_required', label: 'B — English' },
  { key: 'c_required', label: 'C — Mathematics' },
  { key: 'd1_required', label: 'D1 — Biological Science' },
  { key: 'd2_required', label: 'D2 — Physical Science' },
  { key: 'd_required', label: 'D — Laboratory Science (total)' },
  { key: 'e_required', label: 'E — Language Other Than English' },
  { key: 'f_required', label: 'F — Visual & Performing Arts' },
  { key: 'g_required', label: 'G — College-Preparatory Elective' },
];

const GPA_ROWS: Array<{ key: keyof AgCriteriaInput; label: string }> = [
  { key: 'min_gpa_cumulative', label: 'Min Cumulative GPA' },
  { key: 'min_gpa_english', label: 'Min English GPA' },
  { key: 'min_gpa_math', label: 'Min Math GPA' },
  { key: 'min_gpa_science', label: 'Min Science GPA' },
  { key: 'min_csulb_score', label: 'Min CSULB Index — CA resident' },
  { key: 'min_stem_score', label: 'Min STEM Index' },
  { key: 'california_resident_min_gpa', label: 'CA Resident Min GPA' },
  { key: 'non_resident_min_gpa', label: 'Non-resident Min GPA' },
  { key: 'non_resident_csulb_score', label: 'Min CSULB Index — non-resident' },
];

// Strict handbook A-G rules. Each defaults OFF; turning one on re-decides
// students on the next recalc. Discipline classification uses UC Doorways.
const STRICT_RULES: Array<{ key: keyof AgRuleConfig; label: string; hint: string }> = [
  {
    key: 'strict_c_math_slots',
    label: 'C — Math: enforce distinct slots',
    hint: 'Requires Algebra I, Geometry, and Algebra II/Statistics slots. Pre-Calc/Calculus fills any ONE empty slot (not all three).',
  },
  {
    key: 'strict_a_history_anchor',
    label: 'A — History: require U.S. History',
    hint: 'The 2 years must include a U.S. History year: 2 sems U.S. History, or 1 sem U.S. History + 1 sem American Government.',
  },
  {
    key: 'strict_f_same_discipline',
    label: 'F — Arts: one discipline for the year',
    hint: 'The 1 year of VPA must be 2 semesters of the SAME discipline (not 1 sem music + 1 sem art).',
  },
];

const ALL_HS_GRADES = [8, 9, 10, 11, 12];

function HsGradeSelector({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: number[] | null;
  onChange: (grades: number[] | null) => void;
}) {
  const selected = value ?? ALL_HS_GRADES;

  const toggle = (grade: number) => {
    const next = selected.includes(grade)
      ? selected.filter((g) => g !== grade)
      : [...selected, grade].sort((a, b) => a - b);
    onChange(next.length === 0 ? [grade] : next);
  };

  return (
    <div className="rounded-md border bg-slate-50 p-4">
      <p className="mb-1 text-sm font-medium">{label}</p>
      <p className="mb-3 text-xs text-muted-foreground">{hint}</p>
      <div className="flex flex-wrap gap-2">
        {ALL_HS_GRADES.map((grade) => {
          const checked = selected.includes(grade);
          return (
            <button
              key={grade}
              type="button"
              onClick={() => toggle(grade)}
              className={`rounded-md border px-3 py-1 text-xs font-semibold transition-colors ${
                checked
                  ? 'border-blue-500 bg-blue-500 text-white'
                  : 'border-slate-300 bg-white text-slate-500 hover:border-blue-400'
              }`}
            >
              {grade}
            </button>
          );
        })}
      </div>
      <p className="mt-2 text-xs text-muted-foreground">
        Selected: grades {selected.join(', ')}
      </p>
    </div>
  );
}

function AgCriteriaPanel({ yearIntake }: { yearIntake: string }) {
  const [criteria, setCriteria] = useState<AgCriteriaInput>({
    year_intake: yearIntake,
    ...DEFAULT_AG_CRITERIA,
  });
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!yearIntake) return;
    setLoading(true);
    getAgCriteriaForTerm(yearIntake)
      .then((data) => {
        if (data) {
          setCriteria({
            year_intake: data.year_intake,
            a_required: data.a_required,
            b_required: data.b_required,
            c_required: data.c_required,
            d1_required: data.d1_required,
            d2_required: data.d2_required,
            d_required: data.d_required,
            e_required: data.e_required,
            f_required: data.f_required,
            g_required: data.g_required,
            min_gpa_cumulative: data.min_gpa_cumulative,
            min_gpa_english: data.min_gpa_english,
            min_gpa_math: data.min_gpa_math,
            min_gpa_science: data.min_gpa_science,
            min_csulb_score: data.min_csulb_score,
            min_stem_score: data.min_stem_score,
            california_resident_min_gpa: data.california_resident_min_gpa,
            non_resident_min_gpa: data.non_resident_min_gpa,
            non_resident_csulb_score: data.non_resident_csulb_score,
            ag_hs_grades: data.ag_hs_grades,
            gpa_hs_grades: data.gpa_hs_grades,
            gpa_cumulative_hs_grades: data.gpa_cumulative_hs_grades,
            rule_config: data.rule_config ?? { ...DEFAULT_AG_CRITERIA.rule_config },
          });
        } else {
          setCriteria({ year_intake: yearIntake, ...DEFAULT_AG_CRITERIA });
        }
      })
      .catch(() => {
        setCriteria({ year_intake: yearIntake, ...DEFAULT_AG_CRITERIA });
      })
      .finally(() => setLoading(false));
  }, [yearIntake]);

  const setInt = (key: keyof AgCriteriaInput, val: string) => {
    const n = parseInt(val, 10);
    setCriteria((c) => ({ ...c, [key]: Number.isNaN(n) ? 0 : n }));
  };

  const setFloat = (key: keyof AgCriteriaInput, val: string) => {
    setCriteria((c) => ({ ...c, [key]: val === '' ? null : parseFloat(val) }));
  };

  const setRule = (key: keyof AgRuleConfig, val: boolean) => {
    setCriteria((c) => ({ ...c, rule_config: { ...(c.rule_config ?? {}), [key]: val } }));
  };

  const save = async () => {
    setSaving(true);
    try {
      await upsertAgCriteria({ ...criteria, year_intake: yearIntake });
      invalidateCache('completed:');
      toast.success('Criteria saved — admission decisions are recalculating…');
      // Fire-and-forget the recalc: don't block the Save button on the slow
      // per-student recompute (force=true overrides reviewed flags). It runs as a
      // normal foreground request (so Cloud Run keeps CPU allocated until it
      // finishes); decisions refresh as it completes.
      void batchCalculateAdmission(yearIntake, true)
        .then(({ processed }) => {
          invalidateCache('completed:');
          if (processed > 0) {
            toast.success(`${processed} student${processed === 1 ? '' : 's'} recalculated`);
          }
        })
        .catch(() => {});
    } catch (err: any) {
      toast.error(err?.message || 'Failed to save criteria');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center gap-2 py-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading criteria...
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-white p-4">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-base font-semibold">A-G and GPA Criteria for {yearIntake}</h3>
        <Button size="sm" onClick={save} disabled={saving}>
          {saving ? (
            <Loader2 className="mr-1 h-4 w-4 animate-spin" />
          ) : (
            <Save className="mr-1 h-4 w-4" />
          )}
          {saving ? 'Saving...' : 'Save Criteria'}
        </Button>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        <div>
          <p className="mb-3 text-sm font-medium text-muted-foreground">Required Semesters</p>
          <div className="space-y-2">
            {AG_ROWS.map(({ key, label }) => (
              <div key={key} className="flex items-center gap-3">
                <Label className="w-56 text-xs">{label}</Label>
                <Input
                  type="number"
                  min={0}
                  className="h-8 w-20 text-xs"
                  value={criteria[key] as number}
                  onChange={(e) => setInt(key, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="mb-3 text-sm font-medium text-muted-foreground">GPA / Score Thresholds</p>
          <div className="space-y-2">
            {GPA_ROWS.map(({ key, label }) => (
              <div key={key} className="flex items-center gap-3">
                <Label className="w-56 text-xs">{label}</Label>
                <Input
                  type="number"
                  step="0.01"
                  min={0}
                  placeholder="—"
                  className="h-8 w-20 text-xs"
                  value={(criteria[key] as number | null) ?? ''}
                  onChange={(e) => setFloat(key, e.target.value)}
                />
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="mt-6 grid gap-6 md:grid-cols-2">
        <HsGradeSelector
          label="HS Grades for A-G Calculation"
          hint="Only courses from selected grade levels count toward A-G semesters."
          value={criteria.ag_hs_grades}
          onChange={(grades) => setCriteria((c) => ({ ...c, ag_hs_grades: grades }))}
        />
        <HsGradeSelector
          label="HS Grades for Cumulative GPA (CSULB Index)"
          hint="Grade levels used for the cumulative GPA that drives the CSULB Index. CSU standard: 10–12 (9th grade excluded)."
          value={criteria.gpa_cumulative_hs_grades}
          onChange={(grades) => setCriteria((c) => ({ ...c, gpa_cumulative_hs_grades: grades }))}
        />
        <HsGradeSelector
          label="HS Grades for Subject GPAs (English / Math / Science)"
          hint="Grade levels used for the English, Math and Science GPAs. CSU standard: 9–12 (9th grade included)."
          value={criteria.gpa_hs_grades}
          onChange={(grades) => setCriteria((c) => ({ ...c, gpa_hs_grades: grades }))}
        />
      </div>

      <div className="mt-6 border-t pt-4">
        <p className="mb-1 text-sm font-medium text-muted-foreground">Strict Handbook A-G Rules</p>
        <p className="mb-3 text-xs text-muted-foreground">
          Off by default. Turning a rule on applies stricter CSU-handbook logic and re-decides students on the next recalc.
        </p>
        <div className="space-y-3">
          {STRICT_RULES.map(({ key, label, hint }) => (
            <div key={key} className="flex items-start gap-3">
              <Switch
                checked={!!criteria.rule_config?.[key]}
                onCheckedChange={(val) => setRule(key, val)}
                className="mt-0.5"
              />
              <div className="min-w-0">
                <Label className="text-xs font-medium">{label}</Label>
                <p className="text-xs leading-5 text-muted-foreground">{hint}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

export default function AdmissionCriteria() {
  const { terms, currentTerm } = useTerm();
  const currentTermName = terms.find((t) => t.id === currentTerm)?.term_name ?? '';

  return (
    <div className="space-y-6">
      <PageHeader
        title="University Admission Rules"
        subtitle="Configure institution-level A-G and GPA admission thresholds per term"
      />

      {currentTermName ? (
        <AgCriteriaPanel yearIntake={currentTermName} />
      ) : (
        <p className="text-sm text-muted-foreground">
          No term selected. Use the term selector in the top bar to choose a term.
        </p>
      )}
    </div>
  );
}
