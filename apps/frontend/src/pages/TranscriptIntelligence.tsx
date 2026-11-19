import { useNavigate } from 'react-router-dom';
import {
  UploadCloud,
  FolderOpen,
  FileSpreadsheet,
  CheckCircle2,
  UserRound,
  ShieldAlert,
  ArrowRight,
  Sparkles,
} from 'lucide-react';

type Step = { n: number; title: string; desc: string; icon: any; color: string; to: string };

// Same task logos + colors used across the app.
const STEPS: Step[] = [
  {
    n: 1,
    title: 'Upload',
    desc: 'Add transcript PDFs, or upload an entire folder. Classification starts automatically.',
    icon: UploadCloud,
    color: '#2563eb',
    to: '/app/cloud-folders',
  },
  {
    n: 2,
    title: 'Classify',
    desc: 'Each document is identified — ready to process, needs a new extractor, or not a transcript.',
    icon: FolderOpen,
    color: '#16a34a',
    to: '/app/classify',
  },
  {
    n: 3,
    title: 'Extract',
    desc: 'AI pulls out courses, grades, GPA, credits, graduation date, school, and student info.',
    icon: FileSpreadsheet,
    color: '#7c3aed',
    to: '/app/extract',
  },
];

const OUTCOMES = [
  {
    title: 'Auto-Complete',
    tag: 'High confidence',
    desc: 'Everything looks complete and accurate. No review needed.',
    icon: CheckCircle2,
    color: '#16a34a',
    tint: 'var(--green-t)',
    to: '/app/extract',
  },
  {
    title: 'Needs Review',
    tag: 'Some items need checking',
    desc: 'Please review the highlighted fields before completing the transcript.',
    icon: UserRound,
    color: '#ea580c',
    tint: 'var(--amber-t)',
    to: '/app/extract?tab=review',
  },
  {
    title: 'Full Review',
    tag: 'Needs careful review',
    desc: 'The transcript could not be reliably read. Please review the full transcript and confirm the data.',
    icon: ShieldAlert,
    color: '#dc2626',
    tint: 'var(--danger-t)',
    to: '/app/extract?tab=audit',
  },
];

export default function TranscriptIntelligence() {
  const navigate = useNavigate();
  const go = (to: string) => navigate(to);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-start gap-3">
        <span
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl"
          style={{ background: 'var(--violet-t)', color: '#7c3aed' }}
        >
          <Sparkles className="h-6 w-6" />
        </span>
        <div>
          <h1 className="text-[22px] font-bold tracking-tight text-[var(--ink)]">Transcript Intelligence Center</h1>
          <p className="mt-1 text-[13.5px] text-[var(--ink-2)]">
            From upload to outcome — process every transcript through three steps, ending in an automatic or
            human-reviewed result.
          </p>
        </div>
      </div>

      {/* Flow */}
      <div className="rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-6 shadow-[var(--sh-sm)]">
        <div className="flex flex-nowrap items-stretch justify-center gap-3 overflow-x-auto">
          {STEPS.map((step, i) => {
            const Icon = step.icon;
            return (
              <div key={step.n} className="flex items-center gap-4">
                <button
                  type="button"
                  onClick={() => go(step.to)}
                  className="group relative flex w-[210px] flex-col gap-3 rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-5 text-left shadow-[var(--sh-sm)] transition hover:-translate-y-0.5 hover:shadow-[var(--sh)]"
                >
                  <div className="flex items-center justify-between">
                    <span
                      className="grid h-20 w-20 place-items-center rounded-2xl"
                      style={{ background: `${step.color}14`, color: step.color }}
                    >
                      <Icon className="h-12 w-12" strokeWidth={1.8} />
                    </span>
                    <span
                      className="grid h-7 w-7 place-items-center rounded-full text-[13px] font-bold text-white"
                      style={{ background: step.color }}
                    >
                      {step.n}
                    </span>
                  </div>
                  <div className="text-[16px] font-bold" style={{ color: step.color }}>
                    {step.title}
                  </div>
                  <p className="text-[12.5px] leading-snug text-[var(--ink-2)]">{step.desc}</p>
                  <span className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--ink-3)] transition group-hover:text-[var(--ink)]">
                    Open <ArrowRight className="h-3.5 w-3.5" />
                  </span>
                </button>
                {i < STEPS.length - 1 && (
                  <ArrowRight className="hidden h-6 w-6 shrink-0 text-[var(--ink-4)] lg:block" />
                )}
              </div>
            );
          })}

          {/* Branch to outcomes */}
          <div className="hidden flex-col items-center justify-center px-2 xl:flex">
            <div className="h-8 w-px bg-[var(--dline)]" />
            <ArrowRight className="h-6 w-6 text-[var(--ink-4)]" />
          </div>
          <div className="flex flex-col justify-center gap-3">
            {OUTCOMES.map((o) => {
              const Icon = o.icon;
              return (
                <button
                  key={o.title}
                  type="button"
                  onClick={() => go(o.to)}
                  className="flex w-[300px] items-start gap-3 rounded-2xl border p-4 text-left transition hover:-translate-y-0.5 hover:shadow-[var(--sh)]"
                  style={{ background: o.tint, borderColor: `${o.color}40` }}
                >
                  <span
                    className="grid h-10 w-10 shrink-0 place-items-center rounded-xl"
                    style={{ background: `${o.color}1f`, color: o.color }}
                  >
                    <Icon className="h-5 w-5" strokeWidth={2} />
                  </span>
                  <div>
                    <div className="text-[15px] font-bold leading-tight" style={{ color: o.color }}>
                      {o.title}
                    </div>
                    <div className="text-[12px] font-semibold" style={{ color: o.color }}>
                      {o.tag}
                    </div>
                    <p className="mt-1.5 text-[12.5px] leading-snug text-[var(--ink-2)]">{o.desc}</p>
                  </div>
                </button>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
