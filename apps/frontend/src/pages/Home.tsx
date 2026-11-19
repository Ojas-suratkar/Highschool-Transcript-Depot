import { useNavigate } from 'react-router-dom';
import {
  Building2,
  FileText,
  Target,
  SlidersHorizontal,
  Tag,
  BookOpen,
  UploadCloud,
  Layers,
  CheckCircle2,
  ScanLine,
  LineChart,
  Clock,
  ArrowRight,
} from 'lucide-react';
import { useTerm } from '@/contexts/TermContext';
import { useAuth } from '@/contexts/AuthContext';
import { useStaleData } from '@/lib/useStaleData';

type Feature = { icon: any; title: string; desc: string };
type BucketCard = {
  key: string;
  step: number;
  title: string;
  short: string;
  sub: string;
  icon: any;
  color: string;
  tint: string;
  to: string;
  features: Feature[];
  status: (c: Record<string, number>, n: Record<string, number>) => { tone: string; text: string };
};

const CARDS: BucketCard[] = [
  {
    key: 'setup',
    step: 1,
    title: 'Institution Setup',
    short: 'Institution',
    sub: 'Configure your rules and preferences',
    icon: Building2,
    color: '#2563eb',
    tint: 'var(--blue-t)',
    to: '/app/admission-criteria',
    features: [
      { icon: SlidersHorizontal, title: 'University Admission Rules', desc: 'Requirements, GPA & index thresholds' },
      { icon: BookOpen, title: 'Program Admission Rules', desc: 'Per-program major requirements' },
      { icon: BookOpen, title: 'Advanced Admission Rules', desc: 'Handbook compiled into cited rules' },
      { icon: Tag, title: 'Transcript Settings', desc: 'Grade and course-code rules' },
      { icon: Tag, title: 'Course Matching', desc: 'Map courses to A-G / UC Doorways' },
    ],
    status: () => ({ tone: '#059669', text: 'All rules configured' }),
  },
  {
    key: 'process',
    step: 2,
    title: 'Transcript Intelligence Center',
    short: 'Transcript',
    sub: 'Upload, classify, and extract transcripts',
    icon: FileText,
    color: '#059669',
    tint: 'var(--green-t)',
    to: '/app/cloud-folders',
    features: [
      { icon: UploadCloud, title: 'Upload', desc: 'Add files or connect a folder' },
      { icon: Layers, title: 'Classify', desc: 'How each document was identified' },
      { icon: CheckCircle2, title: 'Extract', desc: 'Audit and approve extracted data' },
    ],
    status: (c) => ({
      tone: '#d97706',
      text: `${c.not_processed ?? 0} processing · ${c.needs_review ?? 0} need review`,
    }),
  },
  {
    key: 'admissions',
    step: 3,
    title: 'Admission Center',
    short: 'Admissions',
    sub: 'Review students and record decisions',
    icon: Target,
    color: '#7c3aed',
    tint: 'var(--violet-t)',
    to: '/app/decisions/admitted',
    features: [
      { icon: ScanLine, title: 'Evaluate Students', desc: 'Apply your rules to each student' },
      { icon: Target, title: 'Decisions', desc: 'Admit, deny, or waitlist' },
      { icon: LineChart, title: 'Reports & Insights', desc: 'Outcomes and trends' },
    ],
    status: (c) => ({
      tone: '#7c3aed',
      text: `${(c.admitted ?? 0) + (c.denied ?? 0) + (c.waitlisted ?? 0)} decisions recorded`,
    }),
  },
  {
    key: 'extractor',
    step: 4,
    title: 'Extractor Setup Studio',
    short: 'Extractor',
    sub: 'Configure processing for new transcript formats',
    icon: SlidersHorizontal,
    color: '#d97706',
    tint: 'var(--amber-t)',
    to: '/app/transcripts/new-types/needs-setup',
    features: [
      { icon: ScanLine, title: 'New Transcript Formats', desc: 'Formats not yet recognized' },
      { icon: SlidersHorizontal, title: 'Configure New Format', desc: 'Provide samples and set up' },
      { icon: Clock, title: 'Activate & Monitor', desc: 'Activate and track accuracy' },
    ],
    status: (_c, n) => ({ tone: '#d97706', text: `${n.needs_setup ?? 0} formats ready to set up` }),
  },
];

function Card({
  card,
  counts,
  newTypeCounts,
  onOpen,
}: {
  card: BucketCard;
  counts: Record<string, number>;
  newTypeCounts: Record<string, number>;
  onOpen: (to: string) => void;
}) {
  const Icon = card.icon;
  const status = card.status(counts, newTypeCounts);
  return (
    <div className="flex flex-col overflow-hidden rounded-2xl border border-[var(--dline)] bg-[var(--panel)] shadow-[var(--sh-sm)]">
      <div className="h-[3px]" style={{ background: card.color }} />
      <div className="flex flex-1 flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <span
            className="grid h-9 w-9 place-items-center rounded-[9px]"
            style={{ background: card.tint, color: card.color }}
          >
            <Icon className="h-[18px] w-[18px]" />
          </span>
          <div>
            <div className="text-[10.5px] font-bold uppercase tracking-wider" style={{ color: card.color }}>
              Step {card.step}
            </div>
            <h3 className="text-[14.5px] font-bold leading-tight text-[var(--ink)]">{card.title}</h3>
          </div>
        </div>

        <p className="text-[12px] text-[var(--ink-3)]">{card.sub}</p>

        <div className="flex flex-col">
          {card.features.map((f) => {
            const FIcon = f.icon;
            return (
              <div key={f.title} className="flex items-center gap-2.5 border-t border-[var(--line-2)] py-2">
                <FIcon className="h-[15px] w-[15px] shrink-0 text-[var(--ink-3)]" />
                <div>
                  <b className="text-[12.5px] font-semibold text-[var(--ink)]">{f.title}</b>
                  <span className="block text-[11px] leading-tight text-[var(--ink-3)]">{f.desc}</span>
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-auto flex items-center gap-2 rounded-lg border border-[var(--line-2)] bg-[var(--panel-2)] px-3 py-2.5 text-[12px] font-semibold">
          <span className="h-1.5 w-1.5 rounded-full" style={{ background: status.tone }} />
          <span className="text-[var(--ink-2)]">{status.text}</span>
        </div>
      </div>

      <div className="border-t border-[var(--line-2)] p-3">
        <button
          type="button"
          onClick={() => onOpen(card.to)}
          className="flex w-full items-center justify-center gap-2 rounded-lg border px-3 py-2 text-[12.5px] font-semibold transition hover:brightness-105"
          style={{ color: card.color, borderColor: `${card.color}33` }}
        >
          Open {card.short}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

export default function Home() {
  const navigate = useNavigate();
  const { terms, currentTerm } = useTerm();
  useAuth();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const { data: counts } = useStaleData<Record<string, number>>(
    `home-section-counts:${termName ?? ''}`,
    async () => {
      const res = await fetch(`/api/extractor/section-counts?term=${encodeURIComponent(termName ?? '')}`);
      if (!res.ok) throw new Error('counts failed');
      return res.json();
    },
    [termName],
    { refreshIntervalMs: 30000 },
  );
  const { data: newTypeCounts } = useStaleData<Record<string, number>>(
    'home-new-types',
    async () => {
      const res = await fetch('/api/classifier-training/school-types/counts');
      if (!res.ok) throw new Error('counts failed');
      return res.json();
    },
    [],
    { refreshIntervalMs: 60000 },
  );

  const c = counts ?? {};
  const n = newTypeCounts ?? {};

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-[19px] font-bold tracking-tight text-[var(--ink)]">
            Your end-to-end admissions workspace
          </h1>
          <p className="mt-0.5 text-[13px] text-[var(--ink-3)]">Follow the four steps in order, left to right.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 items-stretch gap-3 md:grid-cols-2 xl:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
        {CARDS.map((card, i) => (
          <div key={card.key} className="contents">
            <Card card={card} counts={c} newTypeCounts={n} onOpen={navigate} />
            {i < CARDS.length - 1 && (
              <div className="hidden items-center justify-center text-[var(--ink-4)] xl:flex">
                <ArrowRight className="h-5 w-5" />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
