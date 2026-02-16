import { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Users, Search, Filter, Download, Eye, CheckCircle2, AlertCircle, FileText } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

interface Application {
  id: string;
  studentName: string;
  studentId: string;
  email: string;
  program: string;
  appliedDate: string;
  status: 'Received' | 'Eligible' | 'Ineligible' | 'Verification' | 'I-20 Generated';
  gpa: number;
  ucValidated: boolean;
  missingDocs?: string[];
}

const mockApplications: Application[] = [
  { id: '1', studentName: 'Alice Johnson', studentId: 'STU001', email: 'alice@example.com', program: 'Computer Science', appliedDate: '2024-01-15', status: 'Eligible', gpa: 3.8, ucValidated: true },
  { id: '2', studentName: 'Bob Smith', studentId: 'STU002', email: 'bob@example.com', program: 'Engineering', appliedDate: '2024-01-14', status: 'I-20 Generated', gpa: 3.5, ucValidated: true },
  { id: '3', studentName: 'Carol Davis', studentId: 'STU003', email: 'carol@example.com', program: 'Business', appliedDate: '2024-01-14', status: 'Ineligible', gpa: 2.8, ucValidated: true, missingDocs: ['GPA below minimum'] },
  { id: '4', studentName: 'David Wilson', studentId: 'STU004', email: 'david@example.com', program: 'Computer Science', appliedDate: '2024-01-13', status: 'Verification', gpa: 3.6, ucValidated: false, missingDocs: ['Transcript verification pending'] },
  { id: '5', studentName: 'Emma Brown', studentId: 'STU005', email: 'emma@example.com', program: 'Mathematics', appliedDate: '2024-01-13', status: 'Eligible', gpa: 3.9, ucValidated: true },
  { id: '6', studentName: 'Frank Miller', studentId: 'STU006', email: 'frank@example.com', program: 'Physics', appliedDate: '2024-01-12', status: 'Received', gpa: 3.4, ucValidated: true },
  { id: '7', studentName: 'Grace Lee', studentId: 'STU007', email: 'grace@example.com', program: 'Chemistry', appliedDate: '2024-01-12', status: 'Eligible', gpa: 3.7, ucValidated: true },
  { id: '8', studentName: 'Henry Martinez', studentId: 'STU008', email: 'henry@example.com', program: 'Biology', appliedDate: '2024-01-11', status: 'I-20 Generated', gpa: 3.6, ucValidated: true },
  { id: '9', studentName: 'Ivy Chen', studentId: 'STU009', email: 'ivy@example.com', program: 'Computer Science', appliedDate: '2024-01-11', status: 'Ineligible', gpa: 2.5, ucValidated: true, missingDocs: ['Missing required courses'] },
  { id: '10', studentName: 'Jack Robinson', studentId: 'STU010', email: 'jack@example.com', program: 'Engineering', appliedDate: '2024-01-10', status: 'Verification', gpa: 3.4, ucValidated: false, missingDocs: ['English proficiency pending'] },
];

export default function Admissions() {
  const location = useLocation();
  const [search, setSearch] = useState('');
  const [programFilter, setProgramFilter] = useState<string>('all');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [showFilters, setShowFilters] = useState(false);

  // Determine the page type from the route
  const getPageType = () => {
    if (location.pathname === '/admissions/applications') return 'Received';
    if (location.pathname === '/admissions/eligible') return 'Eligible';
    if (location.pathname === '/admissions/ineligible') return 'Ineligible';
    if (location.pathname === '/admissions/verification') return 'Verification';
    if (location.pathname === '/admissions/i20s') return 'I-20 Generated';
    return 'all';
  };

  const pageType = getPageType();

  // Set initial status filter based on route
  useEffect(() => {
    setStatusFilter(pageType);
  }, [pageType]);

  const filteredApplications = mockApplications.filter((app) => {
    const matchesSearch =
      app.studentName.toLowerCase().includes(search.toLowerCase()) ||
      app.studentId.toLowerCase().includes(search.toLowerCase()) ||
      app.email.toLowerCase().includes(search.toLowerCase()) ||
      app.program.toLowerCase().includes(search.toLowerCase());

    const matchesStatus = statusFilter === 'all' || app.status === statusFilter;
    const matchesProgram = programFilter === 'all' || app.program === programFilter;

    return matchesSearch && matchesStatus && matchesProgram;
  });

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Eligible':
        return <Badge className="bg-green-500 hover:bg-green-600">Can be Admitted</Badge>;
      case 'Ineligible':
        return <Badge className="bg-red-500 hover:bg-red-600">Cannot be Admitted</Badge>;
      case 'Verification':
        return <Badge className="bg-orange-500 hover:bg-orange-600">Needs Verification</Badge>;
      case 'I-20 Generated':
        return <Badge className="bg-blue-500 hover:bg-blue-600">I-20 Generated</Badge>;
      case 'Received':
        return <Badge className="bg-gray-500 hover:bg-gray-600">Received</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  const getPageInfo = () => {
    switch (pageType) {
      case 'Received':
        return {
          title: 'Applications Received',
          description: 'All applications that have been submitted and are awaiting review'
        };
      case 'Eligible':
        return {
          title: 'Can be Admitted',
          description: 'Students who meet all admission requirements'
        };
      case 'Ineligible':
        return {
          title: 'Cannot be Admitted',
          description: 'Students who do not meet admission requirements'
        };
      case 'Verification':
        return {
          title: 'Needs Verification',
          description: 'Applications requiring manual review or additional documentation'
        };
      case 'I-20 Generated':
        return {
          title: 'Generated I-20s',
          description: 'Students with generated I-20 immigration documents'
        };
      default:
        return {
          title: 'Admissions Overview',
          description: 'Review and manage all student applications'
        };
    }
  };

  const pageInfo = getPageInfo();

  const stats = {
    total: mockApplications.length,
    received: mockApplications.filter(a => a.status === 'Received').length,
    eligible: mockApplications.filter(a => a.status === 'Eligible').length,
    ineligible: mockApplications.filter(a => a.status === 'Ineligible').length,
    verification: mockApplications.filter(a => a.status === 'Verification').length,
    i20s: mockApplications.filter(a => a.status === 'I-20 Generated').length,
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{pageInfo.title}</h1>
          <p className="text-muted-foreground">{pageInfo.description}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm">
            <Download className="h-4 w-4 mr-2" />
            Export
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Total Applications</CardDescription>
            <CardTitle className="text-3xl">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Can be Admitted</CardDescription>
            <CardTitle className="text-3xl text-green-600">{stats.eligible}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Cannot be Admitted</CardDescription>
            <CardTitle className="text-3xl text-red-600">{stats.ineligible}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Needs Verification</CardDescription>
            <CardTitle className="text-3xl text-orange-600">{stats.verification}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>I-20s Generated</CardDescription>
            <CardTitle className="text-3xl text-blue-600">{stats.i20s}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      {/* Applications Table */}
      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Users className="h-5 w-5" />
            Applications
          </CardTitle>
          <CardDescription>
            {filteredApplications.length} application{filteredApplications.length !== 1 ? 's' : ''} found
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 mb-4">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search by name, ID, email, or program..."
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-10"
                />
              </div>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setShowFilters(!showFilters)}
                className={showFilters ? 'bg-slate-100' : ''}
              >
                <Filter className="h-4 w-4" />
              </Button>
            </div>

            {showFilters && (
              <div className="flex gap-4 p-4 bg-slate-50 rounded-lg border">
                <div className="flex-1">
                  <label className="text-sm font-medium mb-2 block">Status</label>
                  <Select value={statusFilter} onValueChange={setStatusFilter}>
                    <SelectTrigger>
                      <SelectValue placeholder="All statuses" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Statuses</SelectItem>
                      <SelectItem value="Received">Received</SelectItem>
                      <SelectItem value="Eligible">Can be Admitted</SelectItem>
                      <SelectItem value="Ineligible">Cannot be Admitted</SelectItem>
                      <SelectItem value="Verification">Needs Verification</SelectItem>
                      <SelectItem value="I-20 Generated">I-20 Generated</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <label className="text-sm font-medium mb-2 block">Program</label>
                  <Select value={programFilter} onValueChange={setProgramFilter}>
                    <SelectTrigger>
                      <SelectValue placeholder="All programs" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Programs</SelectItem>
                      <SelectItem value="Computer Science">Computer Science</SelectItem>
                      <SelectItem value="Engineering">Engineering</SelectItem>
                      <SelectItem value="Business">Business</SelectItem>
                      <SelectItem value="Mathematics">Mathematics</SelectItem>
                      <SelectItem value="Physics">Physics</SelectItem>
                      <SelectItem value="Chemistry">Chemistry</SelectItem>
                      <SelectItem value="Biology">Biology</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setStatusFilter('all');
                      setProgramFilter('all');
                    }}
                  >
                    Clear Filters
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Student Name</TableHead>
                  <TableHead>Student ID</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Program</TableHead>
                  <TableHead>Applied Date</TableHead>
                  <TableHead>GPA</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>UC Validated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredApplications.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={9} className="text-center py-8 text-muted-foreground">
                      No applications found matching your criteria
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredApplications.map((app) => (
                    <TableRow key={app.id} className="hover:bg-slate-50">
                      <TableCell className="font-medium">{app.studentName}</TableCell>
                      <TableCell className="text-muted-foreground">{app.studentId}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{app.email}</TableCell>
                      <TableCell>
                        <Badge variant="outline">{app.program}</Badge>
                      </TableCell>
                      <TableCell className="text-sm">{app.appliedDate}</TableCell>
                      <TableCell>
                        <span className="font-medium">{app.gpa.toFixed(2)}</span>
                      </TableCell>
                      <TableCell>{getStatusBadge(app.status)}</TableCell>
                      <TableCell>
                        {app.ucValidated ? (
                          <div className="flex items-center gap-1 text-green-600">
                            <CheckCircle2 className="h-4 w-4" />
                            <span className="text-xs">Validated</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-orange-600">
                            <AlertCircle className="h-4 w-4" />
                            <span className="text-xs">Pending</span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" title="View application">
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" title="View transcript">
                            <FileText className="h-4 w-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

