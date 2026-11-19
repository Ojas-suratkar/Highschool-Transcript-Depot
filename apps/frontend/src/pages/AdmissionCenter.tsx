import { useNavigate } from 'react-router-dom';
import {
  Target,
  CheckCircle2,
  XCircle,
  Clock,
  LayoutTemplate,
  Goal,
  TrendingUp,
  BarChart3,
  ArrowRight,
} from 'lucide-react';

type Option = { title: string; desc: string; icon: any; color: string; to: string };

const OPTIONS: Option[] = [
  {
    title: 'Admitted',
    desc: 'Students who met the admission requirements for their program and term.',
    icon: CheckCircle2,
    color: '#059669',
    to: '/app/decisions/admitted',
  },
  {
    title: 'Denied',
    desc: 'Students who did not meet the admission requirements.',
    icon: XCircle,
    color: '#dc2626',
    to: '/app/decisions/denied',
  },
  {
    title: 'Waitlisted',
    desc: 'Students held for a final decision pending capacity or further review.',
    icon: Clock,
    color: '#d97706',
    to: '/app/decisions/waitlisted',
  },
  {
    title: 'Decision Templates',
    desc: 'Reusable decision letters and communication templates.',
    icon: LayoutTemplate,
    color: '#2563eb',
    to: '/app/admissions/templates',
  },
  {
    title: 'Enrollment Targets',
    desc: 'Set and track enrollment targets per college, department, and program.',
    icon: Goal,
    color: '#7c3aed',
    to: '/app/admissions/enrollment-goals',
  },
  {
    title: 'Admission Yield',
    desc: 'Track the admissions funnel — admitted, deposited, and yield against targets.',
    icon: TrendingUp,
    color: '#0891b2',
    to: '/app/admissions/yield',
  },
  {
    title: 'Reports & Insights',
    desc: 'Dashboards summarizing admission decisions across programs and terms.',
    icon: BarChart3,
    color: '#db2777',
    to: '/app/admissions/reports',
  },
];

export default function AdmissionCenter() {
  const navigate = useNavigate();

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start gap-3">
        <span
          className="grid h-11 w-11 shrink-0 place-items-center rounded-xl"
          style={{ background: 'var(--violet-t)', color: '#7c3aed' }}
        >
          <Target className="h-6 w-6" />
        </span>
        <div>
          <h1 className="text-[22px] font-bold tracking-tight text-[var(--ink)]">Admission Center</h1>
          <p className="mt-1 text-[13.5px] text-[var(--ink-2)]">
            Review admission decisions, manage templates, and track enrollment targets and yield.
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
