import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useEffect, useState } from 'react';
import { useTerm } from '@/contexts/TermContext';
import { useStaleData } from '@/lib/useStaleData';
import { useAuth } from '@/contexts/AuthContext';
import {
  Home,
  Building2,
  FileText,
  Target,
  SlidersHorizontal,
  ChevronRight,
  GraduationCap,
  LifeBuoy,
  UploadCloud,
  FolderOpen,
  FileSpreadsheet,
  CheckCircle2,
  XCircle,
  Clock,
  Landmark,
  BookOpen,
  Sparkles,
  Settings2,
  Link2,
  LayoutTemplate,
  BarChart3,
  Wrench,
  Cog,
  Goal,
  TrendingUp,
} from 'lucide-react';
import { Sidebar } from '@/components/ui/sidebar';

type Leaf = { label: string; path: string; countKey?: string; icon?: any; iconColor?: string; step?: number };
type Bucket = { key: string; label: string; icon: any; warnKey?: string; to?: string; children: Leaf[] };

// Four-bucket workflow (matches the artifact), mapped onto the app's real routes.
const BUCKETS: Bucket[] = [
  {
    key: 'setup',
    label: 'Institution Setup',
    icon: Building2,
    to: '/institution-setup',
    children: [
      { label: 'University Admission Rules', path: '/admission-criteria', icon: Landmark, iconColor: '#2563eb' },
      { label: 'Program Admission Rules', path: '/program-criteria', icon: BookOpen, iconColor: '#7c3aed' },
      { label: 'Advanced Admission Rules', path: '/term-rules', icon: Sparkles, iconColor: '#d97706' },
      { label: 'Transcript Settings', path: '/transcript-codes', icon: Settings2, iconColor: '#0891b2' },
      { label: 'Course Matching', path: '/course-mapping', icon: Link2, iconColor: '#059669' },
    ],
  },
  {
    key: 'process',
    label: 'Transcript Intelligence Center',
    icon: FileText,
    warnKey: 'extract_total',
    to: '/transcript-intelligence',
    children: [
      { label: 'Upload', path: '/cloud-folders', countKey: 'upload_total', icon: UploadCloud, iconColor: '#2563eb', step: 1 },
      { label: 'Classify', path: '/classify', countKey: 'classify_total', icon: FolderOpen, iconColor: '#059669', step: 2 },
      { label: 'Extract', path: '/extract', countKey: 'extract_total', icon: FileSpreadsheet, iconColor: '#7c3aed', step: 3 },
    ],
  },
  {
    key: 'admissions',
    label: 'Admission Center',
    icon: Target,
    warnKey: 'decisions_total',
    to: '/admission-center',
    children: [
      { label: 'Admitted', path: '/decisions/admitted', countKey: 'admitted', icon: CheckCircle2, iconColor: '#059669' },
      { label: 'Denied', path: '/decisions/denied', countKey: 'denied', icon: XCircle, iconColor: '#dc2626' },
      { label: 'Waitlisted', path: '/decisions/waitlisted', countKey: 'waitlisted', icon: Clock, iconColor: '#d97706' },
      { label: 'Decision Templates', path: '/admissions/templates', icon: LayoutTemplate, iconColor: '#2563eb' },
      { label: 'Enrollment Targets', path: '/admissions/enrollment-goals', icon: Goal, iconColor: '#7c3aed' },
      { label: 'Admission Yield', path: '/admissions/yield', icon: TrendingUp, iconColor: '#0891b2' },
      { label: 'Reports & Insights', path: '/admissions/reports', icon: BarChart3, iconColor: '#db2777' },
    ],
  },
  {
    key: 'extractor',
    label: 'Extractor Setup Studio',
    icon: SlidersHorizontal,
    children: [
      { label: 'Needs Setup', path: '/transcripts/new-types/needs-setup', countKey: 'needs_setup', icon: Wrench, iconColor: '#d97706' },
      { label: 'In Setup', path: '/transcripts/new-types/in-setup', countKey: 'in_setup', icon: Cog, iconColor: '#2563eb' },
      { label: 'Ready', path: '/transcripts/new-types/ready', countKey: 'ready', icon: CheckCircle2, iconColor: '#059669' },
    ],
  },
];

const resolvePath = (p: string) => `/app${p}`.replace(/\/\//g, '/');

const bucketForPath = (pathname: string): string | null => {
  for (const b of BUCKETS) {
    if (b.children.some((c) => resolvePath(c.path) === pathname)) return b.key;
  }
  return null;
};

export function AppSidebar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { terms, currentTerm } = useTerm();
  const { user } = useAuth();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [openBuckets, setOpenBuckets] = useState<string[]>(['process']);

  // Refetch the badge counts immediately after any action (every action fires an
  // app-notify event) and on navigation, so the sidebar numbers update instantly
  // instead of waiting for the polling interval / a hard refresh.
  const [refreshTick, setRefreshTick] = useState(0);
  useEffect(() => {
    const bump = () => setRefreshTick((t) => t + 1);
    window.addEventListener('app-notify', bump);
    window.addEventListener('focus', bump);
    document.addEventListener('visibilitychange', bump);
    return () => {
      window.removeEventListener('app-notify', bump);
      window.removeEventListener('focus', bump);
      document.removeEventListener('visibilitychange', bump);
    };
  }, []);
  useEffect(() => {
    setRefreshTick((t) => t + 1);
  }, [location.pathname]);

  const { data: counts } = useStaleData<Record<string, number>>(
    `section-counts:${termName ?? ''}`,
    async () => {
      // no-store: without it the browser can serve a cached count response on a
      // re-fetch, so the badges only changed on a hard refresh (which bypasses
      // the cache). Force a fresh read every poll / action.
      const res = await fetch(`/api/extractor/section-counts?term=${encodeURIComponent(termName ?? '')}`, {
        cache: 'no-store',
      });
      if (!res.ok) throw new Error('counts failed');
      return res.json();
    },
    [termName, refreshTick],
    { refreshIntervalMs: 10000 },
  );

  const { data: newTypeCounts } = useStaleData<Record<string, number>>(
    'section-counts:new-types',
    async () => {
      const res = await fetch('/api/classifier-training/school-types/counts', { cache: 'no-store' });
      if (!res.ok) throw new Error('counts failed');
      return res.json();
    },
    [refreshTick],
    { refreshIntervalMs: 10000 },
  );

  const countOf = (key?: string): number | undefined => {
    if (!key) return undefined;
    // Extract = the whole extraction stage: Completed (auto) + Human Review +
    // Human Review with Audit, so the badge reflects every extracted student, not
    // just the review queue.
    if (key === 'extract_total') {
      const c = counts ?? {};
      return (c.completed ?? 0) + (c.needs_review ?? 0) + (c.not_processed ?? 0);
    }
    if (key in (newTypeCounts ?? {})) return newTypeCounts?.[key];
    return counts?.[key];
  };

  // Auto-open the bucket that contains the active route.
  useEffect(() => {
    const bk = bucketForPath(location.pathname);
    if (bk && !openBuckets.includes(bk)) setOpenBuckets((prev) => [...prev, bk]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.pathname]);

  const toggleBucket = (key: string) =>
    setOpenBuckets((prev) => (prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key]));

  const homeActive = location.pathname === '/app/home';

  const userName = (user as any)?.name || (user as any)?.full_name || (user as any)?.email || 'Signed in';
  const userInitials =
    String(userName)
      .split(/[\s@.]+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((s: string) => s[0]?.toUpperCase())
      .join('') || 'U';

  return (
    <Sidebar className="border-r border-[var(--dline)] bg-[var(--dsidebar)] p-0">
      <div className="dpt-side">
        {/* Brand */}
        <Link to="/app/home" className="dpt-brand">
          <span className="dpt-mk">
            <GraduationCap className="h-5 w-5" />
          </span>
          <div>
            <b>Highschool Transcript Depot</b>
            <small>Admissions Intelligence</small>
          </div>
        </Link>

        {/* Nav */}
        <nav className="dpt-nav">
          <Link to="/app/home" className={`dpt-navitem ${homeActive ? 'active' : ''}`}>
            <Home className="dpt-ic h-4 w-4" />
            Home
          </Link>

          <div className="dpt-sec">Workflow</div>
          {BUCKETS.map((b) => {
            const Icon = b.icon;
            const open = openBuckets.includes(b.key);
            const warn = countOf(b.warnKey);
            const headerActive = b.to ? location.pathname === resolvePath(b.to) : false;
            const onHeaderClick = () => {
              if (b.to) {
                navigate(resolvePath(b.to));
                setOpenBuckets((prev) => (prev.includes(b.key) ? prev : [...prev, b.key]));
              } else {
                toggleBucket(b.key);
              }
            };
            return (
              <div key={b.key} className={`dpt-navgroup ${open ? 'open' : ''}`}>
                <button
                  type="button"
                  className={`dpt-navitem ${warn ? 'warn' : ''} ${headerActive ? 'active' : ''}`}
                  onClick={onHeaderClick}
                >
                  <Icon className="dpt-ic h-4 w-4" />
                  {b.label}
                  {warn ? <span className="dpt-cnt">{warn}</span> : null}
                  <ChevronRight
                    className="dpt-chev h-4 w-4"
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleBucket(b.key);
                    }}
                  />
                </button>
                <div className="dpt-subnav">
                  {b.children.map((c) => {
                    const to = resolvePath(c.path);
                    const active = to === location.pathname;
                    const cnt = countOf(c.countKey);
                    const LeafIcon = c.icon;
                    return (
                      <Link
                        key={c.path}
                        to={to}
                        className={`dpt-navitem ${c.icon ? 'has-ic' : ''} ${c.step ? 'has-step' : ''} ${active ? 'active' : ''}`}
                      >
                        {c.step ? (
                          <span className="dpt-step" style={{ background: c.iconColor }}>
                            {c.step}
                          </span>
                        ) : null}
                        {LeafIcon ? (
                          <LeafIcon className="dpt-ic h-4 w-4" style={{ color: c.iconColor }} />
                        ) : null}
                        {c.label}
                        {cnt != null ? <span className="dpt-cnt">{cnt}</span> : null}
                      </Link>
                    );
                  })}
                </div>
              </div>
            );
          })}

          <div className="dpt-sec">Help</div>
          <a href="mailto:support@csulb.edu" className="dpt-navitem">
            <LifeBuoy className="dpt-ic h-4 w-4" />
            Contact Support
          </a>
        </nav>

        {/* User footer */}
        <div className="dpt-foot">
          <div className="u">
            <span
              className="dpt-avatar"
              style={{ width: 30, height: 30, fontSize: 11, background: 'linear-gradient(135deg,#db2777,#7c3aed)' }}
            >
              {userInitials}
            </span>
            <div style={{ flex: 1, minWidth: 0 }}>
              <b className="truncate">{userName}</b>
              <span className="block truncate">{(user as any)?.institution?.name || 'Admissions'}</span>
            </div>
          </div>
        </div>
      </div>
    </Sidebar>
  );
}
