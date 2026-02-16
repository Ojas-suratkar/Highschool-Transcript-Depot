import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Eye } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { listApplications } from '@/lib/admissionsApi';
import type { Application } from '@/types/admissions';

export default function ApplicationList() {
  const location = useLocation();
  const navigate = useNavigate();
  const [applications, setApplications] = useState<Application[]>([]);
  const [search, setSearch] = useState('');

  const getPageTitle = () => {
    if (location.pathname.includes('received')) return 'Applications Received';
    if (location.pathname.includes('eligible')) return 'Can Be Admitted';
    if (location.pathname.includes('ineligible')) return 'Cannot Be Admitted';
    if (location.pathname.includes('verification')) return 'Need Verification';
    return 'Applications';
  };

  const getStatusFilter = () => {
    if (location.pathname.includes('eligible')) return 'eligible';
    if (location.pathname.includes('ineligible')) return 'ineligible';
    if (location.pathname.includes('verification')) return 'needs_verification';
    return null;
  };

  useEffect(() => {
    listApplications().then((data) => {
      const statusFilter = getStatusFilter();
      const filtered = statusFilter
        ? data.filter((app) => app.status === statusFilter)
        : data;
      setApplications(filtered);
    });
  }, [location.pathname]);

  const filteredApplications = applications.filter((app) =>
    app.student.name.toLowerCase().includes(search.toLowerCase())
  );

  const columns: ColumnDef<Application>[] = [
    {
      header: 'Student',
      accessor: (row) => (
        <div>
          <div className="font-medium">{row.student.name}</div>
          <div className="text-sm text-muted-foreground">{row.student.email}</div>
        </div>
      ),
    },
    { header: 'Program', accessor: (row) => row.program.name },
    { header: 'GPA', accessor: (row) => row.transcript.gpa },
    {
      header: 'Status',
      accessor: (row) => <StatusBadge status={row.status} />,
    },
    { header: 'Applied Date', accessor: (row) => new Date(row.appliedAt).toLocaleDateString() },
    ...(location.pathname.includes('eligible')
      ? [
          {
            header: 'I-20 Status',
            accessor: (row: Application) => <StatusBadge status={row.i20Status} />,
          },
        ]
      : []),
    ...(location.pathname.includes('ineligible')
      ? [
          {
            header: 'Reason',
            accessor: (row: Application) => row.evaluationSummary,
          },
        ]
      : []),
    {
      header: 'Actions',
      accessor: (row) => (
        <div className="flex gap-1">
          {location.pathname.includes('eligible') && (
            <>
              <Button size="sm" variant="outline">
                Generate I-20
              </Button>
              <Button size="sm" variant="outline">
                Reject
              </Button>
            </>
          )}
          {location.pathname.includes('received') && (
            <>
              <Button size="sm">Approve</Button>
              <Button size="sm" variant="outline">
                Reject
              </Button>
            </>
          )}
          {location.pathname.includes('ineligible') && (
            <Button size="sm" variant="outline">
              Override
            </Button>
          )}
          {location.pathname.includes('verification') && (
            <Button size="sm">Verify</Button>
          )}
          <Button
            size="sm"
            variant="ghost"
            onClick={() => navigate(`/admissions/applications/${row.id}`)}
          >
            <Eye className="h-4 w-4" />
          </Button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title={getPageTitle()}
        subtitle={`Manage ${getPageTitle().toLowerCase()}`}
      />

      <div className="flex gap-4">
        <Input
          placeholder="Search students..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="max-w-sm"
        />
      </div>

      <DataTable
        columns={columns}
        data={filteredApplications}
        keyExtractor={(row) => row.id}
        emptyMessage="No applications found"
      />
    </div>
  );
}

