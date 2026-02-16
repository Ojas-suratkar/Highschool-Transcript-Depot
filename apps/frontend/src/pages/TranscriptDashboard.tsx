import { FileText, CheckCircle, XCircle, Clock, TrendingUp, Users } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { ResponsiveContainer, PieChart, Pie, Cell, Legend, Tooltip, AreaChart, Area, XAxis, YAxis, CartesianGrid, BarChart, Bar, LineChart, Line } from 'recharts';

export default function TranscriptDashboard() {
  // Processing Status Data
  const processingStatusData = [
    { name: 'Processed', value: 1245, color: '#22c55e' },
    { name: 'Failed', value: 23, color: '#ef4444' },
    { name: 'In Queue', value: 87, color: '#f59e0b' },
  ];

  // UC Match Results Data
  const ucMatchData = [
    { name: 'Pass', value: 892, color: '#22c55e' },
    { name: 'Fail', value: 156, color: '#ef4444' },
    { name: 'Pending', value: 197, color: '#6b7280' },
  ];

  // Daily Processing Volume Data
  const dailyVolumeData = [
    { date: 'Mon', processed: 180, failed: 5, queue: 15 },
    { date: 'Tue', processed: 220, failed: 3, queue: 12 },
    { date: 'Wed', processed: 195, failed: 8, queue: 18 },
    { date: 'Thu', processed: 240, failed: 2, queue: 10 },
    { date: 'Fri', processed: 210, failed: 5, queue: 14 },
    { date: 'Sat', processed: 120, failed: 0, queue: 8 },
    { date: 'Sun', processed: 80, failed: 0, queue: 10 },
  ];

  // Transcripts by School Data
  const schoolData = [
    { school: 'Lincoln HS', count: 245 },
    { school: 'Washington HS', count: 198 },
    { school: 'Jefferson HS', count: 176 },
    { school: 'Roosevelt HS', count: 154 },
    { school: 'Kennedy HS', count: 132 },
  ];

  // Average Processing Time Data
  const processingTimeData = [
    { date: 'Week 1', time: 3.2 },
    { date: 'Week 2', time: 3.0 },
    { date: 'Week 3', time: 2.9 },
    { date: 'Week 4', time: 2.8 },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Transcript Dashboard"
        subtitle="Monitor transcript processing and UC match results"
      />

      {/* Stat Cards Row */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard
          title="Total Transcripts"
          value="1,355"
          icon={<FileText className="h-6 w-6" />}
        />
        <StatCard
          title="Processed"
          value="1,245"
          icon={<CheckCircle className="h-6 w-6" />}
          trend={{ value: 12, isPositive: true }}
        />
        <StatCard
          title="Failed"
          value="23"
          icon={<XCircle className="h-6 w-6" />}
        />
        <StatCard
          title="In Queue"
          value="87"
          icon={<Clock className="h-6 w-6" />}
        />
        <StatCard
          title="UC Match Pass"
          value="892"
          icon={<TrendingUp className="h-6 w-6" />}
          trend={{ value: 8, isPositive: true }}
        />
        <StatCard
          title="Applications"
          value="1,048"
          icon={<Users className="h-6 w-6" />}
        />
      </div>

      {/* Charts Row 1 */}
      <div className="grid gap-6 lg:grid-cols-3">
        {/* Processing Status Donut */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">Processing Status</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={processingStatusData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {processingStatusData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* UC Match Results Donut */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">UC Match Results</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={250}>
              <PieChart>
                <Pie
                  data={ucMatchData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={80}
                  paddingAngle={2}
                  dataKey="value"
                >
                  {ucMatchData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Daily Processing Volume - Full Width Stacked Area Chart */}
        <Card className="shadow-sm lg:col-span-3">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">Daily Processing Volume</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={dailyVolumeData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Area type="monotone" dataKey="processed" stackId="1" stroke="#22c55e" fill="#22c55e" name="Processed" />
                <Area type="monotone" dataKey="failed" stackId="1" stroke="#ef4444" fill="#ef4444" name="Failed" />
                <Area type="monotone" dataKey="queue" stackId="1" stroke="#f59e0b" fill="#f59e0b" name="In Queue" />
              </AreaChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Charts Row 2 */}
      <div className="grid gap-6 lg:grid-cols-2">
        {/* Transcripts by School - Horizontal Bar */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">Transcripts by School</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={300}>
              <BarChart data={schoolData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis type="number" />
                <YAxis dataKey="school" type="category" width={120} />
                <Tooltip />
                <Bar dataKey="count" fill="#3b82f6" />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Average Processing Time - Line Chart */}
        <Card className="shadow-sm">
          <CardHeader className="border-b bg-muted/30">
            <CardTitle className="text-lg font-semibold">Average Processing Time</CardTitle>
          </CardHeader>
          <CardContent className="pt-6">
            <ResponsiveContainer width="100%" height={300}>
              <LineChart data={processingTimeData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="time" stroke="#a855f7" strokeWidth={2} name="Avg Time (s)" />
              </LineChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      {/* Processing Summary Card */}
      <Card className="shadow-sm">
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="text-lg font-semibold">Processing Summary</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {/* Success Rate */}
            <div className="p-6 rounded-lg border-2 border-green-200 bg-green-50 dark:bg-green-950 dark:border-green-800 text-center">
              <CheckCircle className="h-8 w-8 mx-auto mb-3 text-green-600" />
              <div className="text-3xl font-bold text-green-900 dark:text-green-100">98.5%</div>
              <div className="text-sm text-green-700 dark:text-green-300 mt-1">Success Rate</div>
            </div>

            {/* Avg Processing Time */}
            <div className="p-6 rounded-lg border-2 border-blue-200 bg-blue-50 dark:bg-blue-950 dark:border-blue-800 text-center">
              <Clock className="h-8 w-8 mx-auto mb-3 text-blue-600" />
              <div className="text-3xl font-bold text-blue-900 dark:text-blue-100">2.8s</div>
              <div className="text-sm text-blue-700 dark:text-blue-300 mt-1">Avg Processing Time</div>
            </div>

            {/* This Week */}
            <div className="p-6 rounded-lg border-2 border-purple-200 bg-purple-50 dark:bg-purple-950 dark:border-purple-800 text-center">
              <TrendingUp className="h-8 w-8 mx-auto mb-3 text-purple-600" />
              <div className="text-3xl font-bold text-purple-900 dark:text-purple-100">+23%</div>
              <div className="text-sm text-purple-700 dark:text-purple-300 mt-1">This Week</div>
            </div>

            {/* Need Attention */}
            <div className="p-6 rounded-lg border-2 border-amber-200 bg-amber-50 dark:bg-amber-950 dark:border-amber-800 text-center">
              <XCircle className="h-8 w-8 mx-auto mb-3 text-amber-600" />
              <div className="text-3xl font-bold text-amber-900 dark:text-amber-100">3</div>
              <div className="text-sm text-amber-700 dark:text-amber-300 mt-1">Need Attention</div>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
