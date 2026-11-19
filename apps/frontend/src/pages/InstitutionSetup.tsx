import { useNavigate } from 'react-router-dom';
import {
  Building2,
  Landmark,
  BookOpen,
  Sparkles,
  Settings2,
  Link2,
  ArrowRight,
} from 'lucide-react';

type Option = { title: string; desc: string; icon: any; color: string; to: string };

const OPTIONS: Option[] = [
  {
    title: 'University Admission Rules',
    desc: 'Set the institution-wide A-G and GPA thresholds a student must meet for admission.',
    icon: Landmark,
    color: '#2563eb',
    to: '/app/admission-criteria',
  },
  {
    title: 'Program Admission Rules',
    desc: 'Define per-program requirements — majors, minimum GPA, and program-specific criteria.',
    icon: BookOpen,
    color: '#7c3aed',
    to: '/app/program-criteria',
  },
  {
    title: 'Advanced Admission Rules',
    desc: "Upload a term's admissions handbook and compile it into structured, cited rules.",
    icon: Sparkles,
    color: '#d97706',
    to: '/app/term-rules',
  },
  {
    title: 'Transcript Settings',
    desc: 'Configure grade scales and course-ID codes used when reading each transcript type.',
    icon: Settings2,
    color: '#0891b2',
    to: '/app/transcript-codes',
  },
  {
    title: 'Course Matching',
    desc: 'Map courses to the UC Doorways catalog and add or override A-G assignments.',
    icon: Link2,
    color: '#059669',
    to: '/app/course-mapping',
  },
];

export default function InstitutionSetup() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start gap-3">
        <span
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl"
          style={{ background: 'var(--blue-t)', color: '#2563eb' }}
        >
          <Building2 className="h-6 w-6" />
        </span>
        <div>
          <h1 className="text-[22px] font-bold tracking-tight text-[var(--ink)]">Institution Setup</h1>
          <p className="mt-1 text-[13.5px] text-[var(--ink-2)]">
            Configure how this institution admits students — the rules, settings, and course mappings the rest of
            the workspace relies on.
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {OPTIONS.map((o) => {
          const Icon = o.icon;
          return (
            <button
              key={o.title}
              type="button"
              onClick={() => navigate(o.to)}
              className="group flex flex-col gap-3 rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-5 text-left shadow-[var(--sh-sm)] transition hover:-translate-y-0.5 hover:shadow-[var(--sh)]"
            >
              <span
                className="grid h-14 w-14 place-items-center rounded-2xl"
                style={{ background: `${o.color}14`, color: o.color }}
              >
                <Icon className="h-7 w-7" strokeWidth={1.8} />
              </span>
              <div className="text-[16px] font-bold" style={{ color: o.color }}>
                {o.title}
              </div>
              <p className="text-[12.5px] leading-snug text-[var(--ink-2)]">{o.desc}</p>
              <span className="mt-1 inline-flex items-center gap-1 text-[12px] font-semibold text-[var(--ink-3)] transition group-hover:text-[var(--ink)]">
                Open <ArrowRight className="h-3.5 w-3.5" />
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
