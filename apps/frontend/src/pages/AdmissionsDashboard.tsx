import { useState, useEffect } from 'react';
import { Users, CheckCircle2, XCircle, AlertCircle, TrendingUp, BarChart3 } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export default function AdmissionsDashboard() {
  const totalEvaluated = 226;
  const canBeAdmitted = 156;
  const cannotBeAdmitted = 42;
  const needsVerification = 28;

  const eligiblePercentage = 69.0;
  const ineligiblePercentage = 18.6;
  const verificationPercentage = 12.4;

  // Animated pie chart state
  const [animatedAngles, setAnimatedAngles] = useState({ eligible: 0, ineligible: 0, verification: 0 });
  const [hoveredSegment, setHoveredSegment] = useState<string | null>(null);

  // Calculate pie chart segments
  const total = canBeAdmitted + cannotBeAdmitted + needsVerification;
  const eligibleAngle = (canBeAdmitted / total) * 360;
  const ineligibleAngle = (cannotBeAdmitted / total) * 360;
  const verificationAngle = (needsVerification / total) * 360;

  // Animate pie chart on mount
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

  // Monthly trend data
  const monthlyTrends = [
    { month: 'Jan', eligible: 45, ineligible: 12, verification: 8 },
    { month: 'Feb', eligible: 52, ineligible: 10, verification: 6 },
    { month: 'Mar', eligible: 61, ineligible: 15, verification: 9 },
    { month: 'Apr', eligible: 48, ineligible: 11, verification: 7 },
    { month: 'May', eligible: 68, ineligible: 18, verification: 12 },
    { month: 'Jun', eligible: 78, ineligible: 14, verification: 10 },
  ];

  const maxTrendValue = Math.max(...monthlyTrends.map(m => m.eligible + m.ineligible + m.verification));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Admission Dashboard</h1>
        <p className="text-muted-foreground">Overview of student admission eligibility status</p>
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
                <p className="text-sm text-green-100">Can be Admitted</p>
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
                <p className="text-sm text-red-100">Cannot be Admitted</p>
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
                <p className="text-sm text-orange-100">Needs Verification</p>
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
            <CardDescription>Breakdown of applicant eligibility status</CardDescription>
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
                <span className="text-xs text-muted-foreground">Eligible</span>
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
                <span className="text-xs text-muted-foreground">Ineligible</span>
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
                <span className="text-xs text-muted-foreground">Verification</span>
                <span className="text-lg font-bold text-orange-600">{needsVerification}</span>
                <span className="text-xs text-muted-foreground">{verificationPercentage}%</span>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Eligibility Breakdown */}
        <Card className="shadow-card">
          <CardHeader>
            <CardTitle>Eligibility Breakdown</CardTitle>
            <CardDescription>Detailed status of evaluated applications</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="rounded-lg bg-green-50 border border-green-200 p-4 transition-all hover:shadow-md">
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  <CheckCircle2 className="h-5 w-5 text-green-600" />
                  <span className="text-sm font-medium text-green-900">Eligible for Admission</span>
                </div>
                <span className="text-2xl font-bold text-green-600">{eligiblePercentage}%</span>
              </div>
              <p className="text-xs text-green-700 ml-7">{canBeAdmitted} students meet all GPA and A-G course requirements</p>
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
                  <span className="text-sm font-medium text-red-900">Not Eligible</span>
                </div>
                <span className="text-2xl font-bold text-red-600">{ineligiblePercentage}%</span>
              </div>
              <p className="text-xs text-red-700 ml-7">{cannotBeAdmitted} students do not meet minimum requirements</p>
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
                  <span className="text-sm font-medium text-orange-900">Verification Required</span>
                </div>
                <span className="text-2xl font-bold text-orange-600">{verificationPercentage}%</span>
              </div>
              <p className="text-xs text-orange-700 ml-7">{needsVerification} students need manual course verification</p>
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
          <CardTitle className="flex items-center gap-2">
            <BarChart3 className="h-5 w-5" />
            Monthly Admission Trends
          </CardTitle>
          <CardDescription>Eligibility status trends over the past 6 months</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            <div className="flex items-end justify-between gap-2 h-64">
              {monthlyTrends.map((data, index) => {
                const eligibleHeight = (data.eligible / maxTrendValue) * 100;
                const ineligibleHeight = (data.ineligible / maxTrendValue) * 100;
                const verificationHeight = (data.verification / maxTrendValue) * 100;
                const total = data.eligible + data.ineligible + data.verification;

                return (
                  <div key={index} className="flex-1 flex flex-col items-center gap-2 group">
                    <div className="w-full flex flex-col items-center justify-end h-full gap-0.5 relative">
                      {/* Tooltip on hover */}
                      <div className="absolute -top-20 left-1/2 -translate-x-1/2 bg-slate-900 text-white text-xs rounded-lg p-2 opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
                        <div className="font-medium mb-1">{data.month}</div>
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-green-500" />
                            <span>Eligible: {data.eligible}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-red-500" />
                            <span>Ineligible: {data.ineligible}</span>
                          </div>
                          <div className="flex items-center gap-2">
                            <div className="w-2 h-2 rounded-full bg-orange-500" />
                            <span>Verification: {data.verification}</span>
                          </div>
                          <div className="border-t border-slate-700 mt-1 pt-1">
                            <span>Total: {total}</span>
                          </div>
                        </div>
                      </div>

                      <div
                        className="w-full bg-green-500 rounded-t transition-all hover:bg-green-600 cursor-pointer"
                        style={{ height: `${eligibleHeight}%` }}
                        title={`Eligible: ${data.eligible}`}
                      />
                      <div
                        className="w-full bg-red-500 transition-all hover:bg-red-600 cursor-pointer"
                        style={{ height: `${ineligibleHeight}%` }}
                        title={`Ineligible: ${data.ineligible}`}
                      />
                      <div
                        className="w-full bg-orange-500 rounded-b transition-all hover:bg-orange-600 cursor-pointer"
                        style={{ height: `${verificationHeight}%` }}
                        title={`Verification: ${data.verification}`}
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
                <span className="text-sm text-muted-foreground">Eligible</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-red-500" />
                <span className="text-sm text-muted-foreground">Ineligible</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-orange-500" />
                <span className="text-sm text-muted-foreground">Verification Needed</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

