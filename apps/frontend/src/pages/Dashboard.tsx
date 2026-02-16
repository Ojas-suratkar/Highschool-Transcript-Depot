import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText,
  Users,
  CheckCircle2,
  XCircle,
  Clock,
  TrendingUp,
  FileCheck,
  AlertCircle,
  ArrowRight,
} from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Progress } from '@/components/ui/progress';
import { Skeleton } from '@/components/ui/skeleton';
import { getDashboardStats } from '@/lib/admissionsApi';
import type { DashboardStats } from '@/types/admissions';

export default function Dashboard() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getDashboardStats().then((data) => {
      setStats(data);
      setLoading(false);
    });
  }, []);

  const transcriptSuccessRate = stats
    ? Math.round((stats.transcriptsProcessed / stats.transcriptsTotal) * 100)
    : 0;

  const admissionEligibilityRate = stats && stats.applicationsReceived > 0
    ? Math.round((stats.eligible / stats.applicationsReceived) * 100)
    : 0;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Dashboard</h1>
        <p className="text-muted-foreground">Overview of transcript processing and admissions</p>
      </div>

      {/* Key Metrics */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="shadow-card">
          <CardContent className="pt-6">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-16" />
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Total Transcripts</p>
                  <p className="text-2xl font-bold">{stats?.transcriptsTotal}</p>
                </div>
                <FileText className="h-8 w-8 text-muted-foreground" />
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-card border-success/20 bg-success/5">
          <CardContent className="pt-6">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-16" />
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Processed</p>
                  <p className="text-2xl font-bold text-success">{stats?.transcriptsProcessed}</p>
                </div>
                <CheckCircle2 className="h-8 w-8 text-success" />
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-card border-destructive/20 bg-destructive/5">
          <CardContent className="pt-6">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-16" />
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">Failed</p>
                  <p className="text-2xl font-bold text-destructive">{stats?.transcriptsFailed}</p>
                </div>
                <XCircle className="h-8 w-8 text-destructive" />
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-card border-info/20 bg-info/5">
          <CardContent className="pt-6">
            {loading ? (
              <div className="space-y-2">
                <Skeleton className="h-4 w-24" />
                <Skeleton className="h-8 w-16" />
              </div>
            ) : (
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-muted-foreground">In Queue</p>
                  <p className="text-2xl font-bold text-info">{stats?.transcriptsInQueue}</p>
                </div>
                <Clock className="h-8 w-8 text-info" />
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Processing & Admissions Overview */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="shadow-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <FileCheck className="h-5 w-5" />
              Transcript Processing
            </CardTitle>
            <CardDescription>Current processing status and success rate</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Success Rate</span>
                    <span className="font-medium">{transcriptSuccessRate}%</span>
                  </div>
                  <Progress value={transcriptSuccessRate} className="h-2" />
                </div>
                <div className="grid grid-cols-3 gap-4 pt-2">
                  <div>
                    <p className="text-xs text-muted-foreground">Processed</p>
                    <p className="text-lg font-semibold text-success">{stats?.transcriptsProcessed}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Failed</p>
                    <p className="text-lg font-semibold text-destructive">{stats?.transcriptsFailed}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">In Queue</p>
                    <p className="text-lg font-semibold text-info">{stats?.transcriptsInQueue}</p>
                  </div>
                </div>
                <Button variant="outline" className="w-full" asChild>
                  <Link to="/transcripts">
                    View All Transcripts
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>

        <Card className="shadow-card">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Users className="h-5 w-5" />
              Admissions Overview
            </CardTitle>
            <CardDescription>Application status and eligibility</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {loading ? (
              <>
                <Skeleton className="h-4 w-full" />
                <Skeleton className="h-4 w-3/4" />
              </>
            ) : (
              <>
                <div className="space-y-2">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-muted-foreground">Eligibility Rate</span>
                    <span className="font-medium">{admissionEligibilityRate}%</span>
                  </div>
                  <Progress value={admissionEligibilityRate} className="h-2" />
                </div>
                <div className="grid grid-cols-3 gap-4 pt-2">
                  <div>
                    <p className="text-xs text-muted-foreground">Eligible</p>
                    <p className="text-lg font-semibold text-success">{stats?.eligible}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Ineligible</p>
                    <p className="text-lg font-semibold text-destructive">{stats?.ineligible}</p>
                  </div>
                  <div>
                    <p className="text-xs text-muted-foreground">Needs Review</p>
                    <p className="text-lg font-semibold text-warning">{stats?.needsVerification}</p>
                  </div>
                </div>
                <Button variant="outline" className="w-full" asChild>
                  <Link to="/admissions">
                    View All Applications
                    <ArrowRight className="ml-2 h-4 w-4" />
                  </Link>
                </Button>
              </>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Quick Actions & Alerts */}
      <div className="grid gap-4 md:grid-cols-2">
        <Card className="shadow-card">
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
            <CardDescription>Common tasks and workflows</CardDescription>
          </CardHeader>
          <CardContent className="space-y-2">
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link to="/ingestion">
                <FileText className="mr-2 h-4 w-4" />
                Upload New Transcripts
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link to="/admissions">
                <Users className="mr-2 h-4 w-4" />
                Review Applications
              </Link>
            </Button>
            <Button variant="outline" className="w-full justify-start" asChild>
              <Link to="/programs">
                <TrendingUp className="mr-2 h-4 w-4" />
                Manage Programs
              </Link>
            </Button>
          </CardContent>
        </Card>

        <Card className="shadow-card border-warning/20">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="h-5 w-5 text-warning" />
              Alerts & Notifications
            </CardTitle>
            <CardDescription>Items requiring attention</CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {loading ? (
              <>
                <Skeleton className="h-12 w-full" />
                <Skeleton className="h-12 w-full" />
              </>
            ) : (
              <>
                {stats && stats.transcriptsFailed > 0 && (
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-destructive/10">
                    <XCircle className="h-5 w-5 text-destructive mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium">{stats.transcriptsFailed} Failed Transcripts</p>
                      <p className="text-xs text-muted-foreground">Review and retry processing</p>
                    </div>
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/transcripts?tab=failed">View</Link>
                    </Button>
                  </div>
                )}
                {stats && stats.needsVerification > 0 && (
                  <div className="flex items-start gap-3 p-3 rounded-lg bg-warning/10">
                    <AlertCircle className="h-5 w-5 text-warning mt-0.5" />
                    <div className="flex-1">
                      <p className="text-sm font-medium">{stats.needsVerification} Applications Need Review</p>
                      <p className="text-xs text-muted-foreground">Manual verification required</p>
                    </div>
                    <Button variant="ghost" size="sm" asChild>
                      <Link to="/admissions?tab=needs_verification">Review</Link>
                    </Button>
                  </div>
                )}
                {stats && stats.transcriptsFailed === 0 && stats.needsVerification === 0 && (
                  <div className="text-center py-6 text-muted-foreground">
                    <CheckCircle2 className="h-8 w-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">No alerts at this time</p>
                  </div>
                )}
              </>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

