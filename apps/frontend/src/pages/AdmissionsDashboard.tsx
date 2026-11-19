import { useState, useEffect, useMemo } from 'react';
import { Users, CheckCircle2, XCircle, AlertCircle, BarChart3, TrendingUp } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useTerm } from '@/contexts/TermContext';

const PERIODS = [
  { months: 1, label: 'This month' },
  { months: 2, label: 'Last 2 months' },
  { months: 3, label: 'Last 3 months' },
  { months: 6, label: 'Last 6 months' },
  { months: 12, label: 'Last 12 months' },
];

export default function AdmissionsDashboard() {
  // Scope the whole dashboard to the currently selected term.
  const { terms, currentTerm } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [counts, setCounts] = useState({ admitted: 0, denied: 0, waitlisted: 0 });
  useEffect(() => {
    if (!termName) {
      setCounts({ admitted: 0, denied: 0, waitlisted: 0 });
      return;
    }
    let on = true;
    fetch(`/api/extractor/section-counts?term=${encodeURIComponent(termName)}`, { cache: 'no-store' })
      .then((r) => r.json())
      .then((d) => {
        if (on) {
          setCounts({
            admitted: Number(d.admitted) || 0,
            denied: Number(d.denied) || 0,
            waitlisted: Number(d.waitlisted) || 0,
          });
        }
      })
      .catch(() => {});
    return () => { on = false; };
  }, [termName]);

  // Real month-wise decision data (grouped by the month each transcript was
  // processed), keyed "YYYY-MM".
  const [trendsByMonth, setTrendsByMonth] = useState<
    Record<string, { admitted: number; denied: number; waitlisted: number }>
  >({});
  useEffect(() => {
    if (!termName) { setTrendsByMonth({}); return; }
    let on = true;
    fetch(`/api/extractor/decision-trends?term=${encodeURIComponent(termName)}`, { cache: 'no-store' })
      .then((r) => r.json())
      .then((d) => {
        if (!on) return;
        const map: Record<string, { admitted: number; denied: number; waitlisted: number }> = {};
        for (const m of (d.months || [])) {
          map[m.ym] = {
            admitted: Number(m.admitted) || 0,
            denied: Number(m.denied) || 0,
            waitlisted: Number(m.waitlisted) || 0,
          };
        }
        setTrendsByMonth(map);
      })
      .catch(() => {});
    return () => { on = false; };
  }, [termName]);

  const canBeAdmitted = counts.admitted;
  const cannotBeAdmitted = counts.denied;
  const needsVerification = counts.waitlisted;
  const totalEvaluated = canBeAdmitted + cannotBeAdmitted + needsVerification;

  const pct = (n: number) => (totalEvaluated ? Math.round((n / totalEvaluated) * 1000) / 10 : 0);
  const eligiblePercentage = pct(canBeAdmitted);
  const ineligiblePercentage = pct(cannotBeAdmitted);
  const verificationPercentage = pct(needsVerification);

  // Animated pie chart state
  const [animatedAngles, setAnimatedAngles] = useState({ eligible: 0, ineligible: 0, verification: 0 });
  const [hoveredSegment, setHoveredSegment] = useState<string | null>(null);

  // Calculate pie chart segments
  const total = totalEvaluated || 1;
  const eligibleAngle = (canBeAdmitted / total) * 360;
  const ineligibleAngle = (cannotBeAdmitted / total) * 360;
  const verificationAngle = (needsVerification / total) * 360;

  // Animate pie chart on mount / when the term data changes
  useEffect(() => {
    const duration = 1000;
    const steps = 60;
    const stepDuration = duration / steps;
    let currentStep = 0;

    const interval = setInterval(() => {
      currentStep++;
      const progress = currentStep / steps;
      const easeOutCubic = 1 - Math.pow(1 - progress, 3);

      setAnimatedAngles({
        eligible: eligibleAngle * easeOutCubic,
        ineligible: ineligibleAngle * easeOutCubic,
        verification: verificationAngle * easeOutCubic
      });

      if (currentStep >= steps) {
        clearInterval(interval);
      }
    }, stepDuration);

    return () => clearInterval(interval);
  }, [eligibleAngle, ineligibleAngle, verificationAngle]);

  // Trend chart — a selectable window of the last N calendar months ending in the
  // current month, filled from REAL per-month decision data (0 for months with no
  // decisions).
  const [periodMonths, setPeriodMonths] = useState(3);
  const monthlyTrends = useMemo(() => {
    const now = new Date();
    const out: { month: string; eligible: number; ineligible: number; verification: number }[] = [];
    for (let i = periodMonths - 1; i >= 0; i--) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const ym = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
      const label = d.toLocaleString('en-US', { month: 'short' });
      const v = trendsByMonth[ym] || { admitted: 0, denied: 0, waitlisted: 0 };
      out.push({ month: label, eligible: v.admitted, ineligible: v.denied, verification: v.waitlisted });
    }
    return out;
  }, [periodMonths, trendsByMonth]);

  const maxTrendValue = Math.max(1, ...monthlyTrends.map(m => m.eligible + m.ineligible + m.verification));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Admission Dashboard</h1>
        <p className="text-muted-foreground">
          Overview of admission decisions{termName ? ` — ${termName}` : ''}
        </p>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="shadow-card bg-blue-600 text-white">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-blue-100">Total Evaluated</p>
                <p className="text-3xl font-bold">{totalEvaluated}</p>
              </div>
              <Users className="h-12 w-12 text-blue-200" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-green-500 text-white">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-green-100">Admitted</p>
                <p className="text-3xl font-bold">{canBeAdmitted}</p>
                <p className="text-xs text-green-100 mt-1">↑ 8% from last month</p>
              </div>
              <CheckCircle2 className="h-12 w-12 text-green-200" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-red-500 text-white">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-red-100">Denied</p>
                <p className="text-3xl font-bold">{cannotBeAdmitted}</p>
              </div>
              <XCircle className="h-12 w-12 text-red-200" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-orange-500 text-white">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-orange-100">Waitlisted</p>
                <p className="text-3xl font-bold">{needsVerification}</p>
              </div>
              <AlertCircle className="h-12 w-12 text-orange-200" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-6 md:grid-cols-2">
        {/* Admission Distribution Pie Chart */}
        <Card className="shadow-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <TrendingUp className="h-5 w-5" />
              Admission Distribution
            </CardTitle>
            <CardDescription>Breakdown of admission decisions</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-center py-8">
              <div className="relative w-64 h-64">
                <svg viewBox="0 0 200 200" className="w-full h-full transform transition-transform duration-300">
                  {/* Eligible segment (green) */}
                  <circle
                    cx="100"
                    cy="100"
                    r="80"
                    fill="none"
                    stroke="#22c55e"
                    strokeWidth={hoveredSegment === 'eligible' ? '65' : '60'}
                    strokeDasharray={`${(animatedAngles.eligible / 360) * 502.65} 502.65`}
                    transform="rotate(-90 100 100)"
                    className="transition-all duration-300 cursor-pointer"
                    onMouseEnter={() => setHoveredSegment('eligible')}
                    onMouseLeave={() => setHoveredSegment(null)}
                    style={{ filter: hoveredSegment === 'eligible' ? 'brightness(1.1)' : 'none' }}
                  />
                  {/* Ineligible segment (red) */}
                  <circle
                    cx="100"
                    cy="100"
                    r="80"
                    fill="none"
                    stroke="#ef4444"
                    strokeWidth={hoveredSegment === 'ineligible' ? '65' : '60'}
                    strokeDasharray={`${(animatedAngles.ineligible / 360) * 502.65} 502.65`}
                    strokeDashoffset={`-${(animatedAngles.eligible / 360) * 502.65}`}
                    transform="rotate(-90 100 100)"
                    className="transition-all duration-300 cursor-pointer"
                    onMouseEnter={() => setHoveredSegment('ineligible')}
                    onMouseLeave={() => setHoveredSegment(null)}
                    style={{ filter: hoveredSegment === 'ineligible' ? 'brightness(1.1)' : 'none' }}
                  />
                  {/* Verification segment (orange) */}
                  <circle
                    cx="100"
                    cy="100"
                    r="80"
                    fill="none"
                    stroke="#f97316"
                    strokeWidth={hoveredSegment === 'verification' ? '65' : '60'}
                    strokeDasharray={`${(animatedAngles.verification / 360) * 502.65} 502.65`}
                    strokeDashoffset={`-${((animatedAngles.eligible + animatedAngles.ineligible) / 360) * 502.65}`}
                    transform="rotate(-90 100 100)"
                    className="transition-all duration-300 cursor-pointer"
                    onMouseEnter={() => setHoveredSegment('verification')}
                    onMouseLeave={() => setHoveredSegment(null)}
                    style={{ filter: hoveredSegment === 'verification' ? 'brightness(1.1)' : 'none' }}
                  />
                  {/* Center text */}
                  <text
                    x="100"
                    y="95"
                    textAnchor="middle"
                    className="text-2xl font-bold fill-foreground"
                  >
                    {totalEvaluated}
                  </text>
                  <text
                    x="100"
                    y="110"
                    textAnchor="middle"
                    className="text-xs fill-muted-foreground"
                  >
                    Total
                  </text>
                </svg>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4 mt-4">
              <div
                className={`flex flex-col items-center p-3 rounded-lg transition-all cursor-pointer ${
                  hoveredSegment === 'eligible' ? 'bg-green-50' : 'hover:bg-slate-50'
                }`}
                onMouseEnter={() => setHoveredSegment('eligible')}
                onMouseLeave={() => setHoveredSegment(null)}
              >
                <div className="h-3 w-3 rounded-full bg-green-500 mb-2" />
                <span className="text-xs text-muted-foreground">Admitted</span>
                <span className="text-lg font-bold text-green-600">{canBeAdmitted}</span>
                <span className="text-xs text-muted-foreground">{eligiblePercentage}%</span>
              </div>
              <div
                className={`flex flex-col items-center p-3 rounded-lg transition-all cursor-pointer ${
                  hoveredSegment === 'ineligible' ? 'bg-red-50' : 'hover:bg-slate-50'
                }`}
                onMouseEnter={() => setHoveredSegment('ineligible')}
                onMouseLeave={() => setHoveredSegment(null)}
              >
                <div className="h-3 w-3 rounded-full bg-red-500 mb-2" />
                <span className="text-xs text-muted-foreground">Denied</span>
                <span className="text-lg font-bold text-red-600">{cannotBeAdmitted}</span>
                <span className="text-xs text-muted-foreground">{ineligiblePercentage}%</span>
              </div>
              <div
                className={`flex flex-col items-center p-3 rounded-lg transition-all cursor-pointer ${
                  hoveredSegment === 'verification' ? 'bg-orange-50' : 'hover:bg-slate-50'
                }`}
                onMouseEnter={() => setHoveredSegment('verification')}
                onMouseLeave={() => setHoveredSegment(null)}
              >
                <div className="h-3 w-3 rounded-full bg-orange-500 mb-2" />
                <span className="text-xs text-muted-foreground">Waitlisted</span>
                <span className="text-lg font-bold text-orange-600">{needsVerification}</span>
                <span className="text-xs text-muted-foreground">{verificationPercentage}%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Decision Breakdown */}
        <Card className="shadow-card">
          <CardHeader>
            <CardTitle>Decision Breakdown</CardTitle>
            <CardDescription>Detailed status of evaluated students</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg bg-green-50 border border-green-200 p-4 transition-all hover:shadow-md">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-5 w-5 text-green-600" />
                  <span className="text-sm font-medium text-green-900">Admitted</span>
                </div>
                <span className="text-2xl font-bold text-green-600">{eligiblePercentage}%</span>
              </div>
              <p className="text-xs text-green-700 ml-7">{canBeAdmitted} students met the admission requirements</p>
              <div className="mt-3 ml-7">
                <div className="h-2 bg-green-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-green-600 rounded-full transition-all duration-1000"
                    style={{ width: `${eligiblePercentage}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-red-50 border border-red-200 p-4 transition-all hover:shadow-md">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <XCircle className="h-5 w-5 text-red-600" />
                  <span className="text-sm font-medium text-red-900">Denied</span>
                </div>
                <span className="text-2xl font-bold text-red-600">{ineligiblePercentage}%</span>
              </div>
              <p className="text-xs text-red-700 ml-7">{cannotBeAdmitted} students did not meet the admission requirements</p>
              <div className="mt-3 ml-7">
                <div className="h-2 bg-red-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-red-600 rounded-full transition-all duration-1000"
                    style={{ width: `${ineligiblePercentage}%` }}
                  />
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-orange-50 border border-orange-200 p-4 transition-all hover:shadow-md">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <AlertCircle className="h-5 w-5 text-orange-600" />
                  <span className="text-sm font-medium text-orange-900">Waitlisted</span>
                </div>
                <span className="text-2xl font-bold text-orange-600">{verificationPercentage}%</span>
              </div>
              <p className="text-xs text-orange-700 ml-7">{needsVerification} students are waitlisted for further review</p>
              <div className="mt-3 ml-7">
                <div className="h-2 bg-orange-200 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-orange-600 rounded-full transition-all duration-1000"
                    style={{ width: `${verificationPercentage}%` }}
                  />
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Monthly Trends */}
      <Card className="shadow-card">
        <CardHeader>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2">
                <BarChart3 className="h-5 w-5" />
                Admission Trends
              </CardTitle>
              <CardDescription>
                Admission decisions over {PERIODS.find((p) => p.months === periodMonths)?.label.toLowerCase()}
              </CardDescription>
            </div>
            <Select value={String(periodMonths)} onValueChange={(v) => setPeriodMonths(Number(v))}>
              <SelectTrigger className="w-[168px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PERIODS.map((p) => (
                  <SelectItem key={p.months} value={String(p.months)}>
                    {p.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-end justify-around gap-4">
              {monthlyTrends.map((data, index) => {
                const eligibleHeight = (data.eligible / maxTrendValue) * 100;
                const ineligibleHeight = (data.ineligible / maxTrendValue) * 100;
                const verificationHeight = (data.verification / maxTrendValue) * 100;
                const total = data.eligible + data.ineligible + data.verification;

                return (
                  <div key={index} className="flex-1 flex flex-col items-center gap-2 group">
                    <div className="w-full max-w-[110px] h-64 flex flex-col items-center justify-end gap-0.5 relative">
                      {/* Tooltip on hover */}
                      <div className="absolute -top-20 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-xs rounded-lg p-2 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                        <div className="font-medium mb-1">{data.month}</div>
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-500" />
                            <span>Admitted: {data.eligible}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-red-500" />
                            <span>Denied: {data.ineligible}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-orange-500" />
                            <span>Waitlisted: {data.verification}</span>
                          </div>
                          <div className="border-t border-slate-700 mt-1 pt-1">
                            <span>Total: {total}</span>
                          </div>
                        </div>
                      </div>

                      <div
                        className="w-full bg-green-500 rounded-t transition-all hover:bg-green-600 cursor-pointer"
                        style={{ height: `${eligibleHeight}%` }}
                        title={`Admitted: ${data.eligible}`}
                      />
                      <div
                        className="w-full bg-red-500 transition-all hover:bg-red-600 cursor-pointer"
                        style={{ height: `${ineligibleHeight}%` }}
                        title={`Denied: ${data.ineligible}`}
                      />
                      <div
                        className="w-full bg-orange-500 rounded-b transition-all hover:bg-orange-600 cursor-pointer"
                        style={{ height: `${verificationHeight}%` }}
                        title={`Waitlisted: ${data.verification}`}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground font-medium">{data.month}</span>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center justify-center gap-6 pt-4 border-t">
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-green-500" />
                <span className="text-sm text-muted-foreground">Admitted</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-red-500" />
                <span className="text-sm text-muted-foreground">Denied</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-orange-500" />
                <span className="text-sm text-muted-foreground">Waitlisted</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

