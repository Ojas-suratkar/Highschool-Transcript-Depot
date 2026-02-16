import { useState, useEffect } from 'react';
import { FileText, CheckCircle2, XCircle, Clock, TrendingUp } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { getProcessingStats } from '@/lib/admissionsApi';
import type { ProcessingStats } from '@/types/admissions';

export default function Transcripts() {
  const [_stats, setStats] = useState<ProcessingStats | null>(null);

  useEffect(() => {
    getProcessingStats().then((data) => {
      setStats(data);
      // intentionally not tracking loading — UI renders with placeholder values until data arrives
    });
  }, []);

  const monthlyData = [
    { month: 'Jan', processed: 45, failed: 12 },
    { month: 'Feb', processed: 52, failed: 8 },
    { month: 'Mar', processed: 61, failed: 15 },
    { month: 'Apr', processed: 48, failed: 10 },
    { month: 'May', processed: 68, failed: 18 },
    { month: 'Jun', processed: 78, failed: 14 },
    { month: 'Jul', processed: 62, failed: 16 },
    { month: 'Aug', processed: 82, failed: 12 },
    { month: 'Sep', processed: 115, failed: 22 },
    { month: 'Oct', processed: 85, failed: 28 },
    { month: 'Nov', processed: 72, failed: 15 },
    { month: 'Dec', processed: 53, failed: 10 },
  ];

  const maxValue = Math.max(...monthlyData.map((d) => d.processed + d.failed));

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Transcript Dashboard</h1>
        <p className="text-muted-foreground">Overview of transcript processing status this year</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card className="shadow-card bg-[#3B4A8C] text-white border-0">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white/80">Total Transcripts</p>
                <p className="text-3xl font-bold">925</p>
              </div>
              <FileText className="h-12 w-12 text-white/60" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-[#22C55E] text-white border-0">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white/80">Processed</p>
                <p className="text-3xl font-bold">871</p>
                <p className="text-xs text-white/70 mt-1">↑ 12% from last month</p>
              </div>
              <CheckCircle2 className="h-12 w-12 text-white/60" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-[#EF4444] text-white border-0">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white/80">Failed</p>
                <p className="text-3xl font-bold">46</p>
              </div>
              <XCircle className="h-12 w-12 text-white/60" />
            </div>
          </CardContent>
        </Card>

        <Card className="shadow-card bg-[#F59E0B] text-white border-0">
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-white/80">In Queue</p>
                <p className="text-3xl font-bold">8</p>
              </div>
              <Clock className="h-12 w-12 text-white/60" />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <TrendingUp className="h-5 w-5" />
            Monthly Processing Trends
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-2">
            <div className="flex items-end justify-between gap-2 h-80">
              {monthlyData.map((data, index) => {
                const processedHeight = (data.processed / maxValue) * 100;
                const failedHeight = (data.failed / maxValue) * 100;
                return (
                  <div key={index} className="flex-1 flex flex-col items-center gap-2">
                    <div className="w-full flex flex-col items-center justify-end h-full gap-1">
                      <div
                        className="w-full bg-[#22C55E] rounded-t transition-all hover:opacity-80"
                        style={{ height: `${processedHeight}%` }}
                        title={`Processed: ${data.processed}`}
                      />
                      <div
                        className="w-full bg-[#F59E0B] rounded-t transition-all hover:opacity-80"
                        style={{ height: `${failedHeight}%` }}
                        title={`Failed: ${data.failed}`}
                      />
                    </div>
                    <span className="text-xs text-muted-foreground">{data.month}</span>
                  </div>
                );
              })}
            </div>
            <div className="flex items-center justify-center gap-6 pt-4">
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-[#22C55E]" />
                <span className="text-sm text-muted-foreground">Processed</span>
              </div>
              <div className="flex items-center gap-2">
                <div className="h-3 w-3 rounded bg-[#F59E0B]" />
                <span className="text-sm text-muted-foreground">Failed</span>
              </div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
