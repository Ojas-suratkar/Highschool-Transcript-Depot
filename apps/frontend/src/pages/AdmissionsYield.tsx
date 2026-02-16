import { useState } from 'react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { cn } from '@/lib/utils';

interface YieldData {
  id: string;
  college: string;
  department: string;
  major: string;
  semester: string;
  goal: number;
  admitted: number;
  deposited: number;
  yield: number;
  delta: number;
}

export default function AdmissionsYield() {
  const [data] = useState<YieldData[]>([
    {
      id: '1',
      college: 'Engineering',
      department: 'Computer Science',
      major: 'Computer Science (MS)',
      semester: 'Fall 2025',
      goal: 50,
      admitted: 120,
      deposited: 48,
      yield: 40,
      delta: -2,
    },
    {
      id: '2',
      college: 'Engineering',
      department: 'Electrical Engineering',
      major: 'Electrical Engineering (MS)',
      semester: 'Fall 2025',
      goal: 40,
      admitted: 95,
      deposited: 42,
      yield: 44.2,
      delta: 2,
    },
  ]);

  const totalGoal = data.reduce((sum, d) => sum + d.goal, 0);
  const totalAdmitted = data.reduce((sum, d) => sum + d.admitted, 0);
  const totalDeposited = data.reduce((sum, d) => sum + d.deposited, 0);
  const overallYield = Math.round((totalDeposited / totalAdmitted) * 100);
  const goalAttainment = Math.round((totalDeposited / totalGoal) * 100);

  const columns: ColumnDef<YieldData>[] = [
    { header: 'College', accessor: 'college' },
    { header: 'Department', accessor: 'department' },
    { header: 'Major', accessor: 'major' },
    { header: 'Semester', accessor: 'semester' },
    { header: 'Goal', accessor: 'goal' },
    { header: 'Admitted', accessor: 'admitted' },
    { header: 'Deposited', accessor: 'deposited' },
    {
      header: 'Yield %',
      accessor: (row) => `${row.yield.toFixed(1)}%`,
    },
    {
      header: 'Delta',
      accessor: (row) => (
        <span className={cn(row.delta < 0 ? 'text-destructive' : 'text-success')}>
          {row.delta > 0 ? '+' : ''}
          {row.delta}
        </span>
      ),
  },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Yield"
        subtitle="Track admissions funnel metrics"
      />

      <div className="grid gap-4 md:grid-cols-5">
        <StatCard title="Total Goal" value={totalGoal} icon={<div />} />
        <StatCard title="Admitted" value={totalAdmitted} icon={<div />} />
        <StatCard title="Deposited" value={totalDeposited} icon={<div />} />
        <StatCard
          title="Overall Yield %"
          value={`${overallYield}%`}
          icon={<div />}
          className="border-info/20 bg-info/5"
        />
        <StatCard
          title="Goal Attainment %"
          value={`${goalAttainment}%`}
          icon={<div />}
          className={cn(
            goalAttainment >= 100
              ? 'border-success/20 bg-success/5'
              : 'border-warning/20 bg-warning/5'
          )}
        />
      </div>

      <DataTable
        columns={columns}
        data={data}
        keyExtractor={(row) => row.id}
        emptyMessage="No yield data available"
      />
    </div>
  );
}

