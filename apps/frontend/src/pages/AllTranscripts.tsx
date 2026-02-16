import { useState, useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import { FileText, Search, Trash2, Filter, Download, Eye, RefreshCw, Calendar } from 'lucide-react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue
} from '@/components/ui/select';
import { Checkbox } from '@/components/ui/checkbox';

interface TranscriptRecord {
  id: string;
  studentName: string;
  studentId: string;
  fileName: string;
  uploadDate: string;
  processedDate?: string;
  status: 'Processed' | 'Failed' | 'In Queue';
  gpa?: number;
  source: 'Manual Upload' | 'Google Drive' | 'Dropbox';
  ucDoorwayValidated: boolean;
}

const mockTranscripts: TranscriptRecord[] = [
  { id: '1', studentName: 'Alice Johnson', studentId: 'STU001', fileName: 'transcript_alice.pdf', uploadDate: '2024-01-15', processedDate: '2024-01-15', status: 'Processed', gpa: 3.8, source: 'Manual Upload', ucDoorwayValidated: true },
  { id: '2', studentName: 'Bob Smith', studentId: 'STU002', fileName: 'transcript_bob.pdf', uploadDate: '2024-01-14', processedDate: '2024-01-14', status: 'Processed', gpa: 3.5, source: 'Google Drive', ucDoorwayValidated: true },
  { id: '3', studentName: 'Carol Davis', studentId: 'STU003', fileName: 'transcript_carol.pdf', uploadDate: '2024-01-14', status: 'Failed', source: 'Manual Upload', ucDoorwayValidated: false },
  { id: '4', studentName: 'David Wilson', studentId: 'STU004', fileName: 'transcript_david.pdf', uploadDate: '2024-01-13', status: 'In Queue', source: 'Dropbox', ucDoorwayValidated: false },
  { id: '5', studentName: 'Emma Brown', studentId: 'STU005', fileName: 'transcript_emma.pdf', uploadDate: '2024-01-13', processedDate: '2024-01-13', status: 'Processed', gpa: 3.9, source: 'Manual Upload', ucDoorwayValidated: true },
  { id: '6', studentName: 'Frank Miller', studentId: 'STU006', fileName: 'transcript_frank.pdf', uploadDate: '2024-01-12', status: 'In Queue', source: 'Google Drive', ucDoorwayValidated: false },
  { id: '7', studentName: 'Grace Lee', studentId: 'STU007', fileName: 'transcript_grace.pdf', uploadDate: '2024-01-12', processedDate: '2024-01-12', status: 'Processed', gpa: 3.7, source: 'Manual Upload', ucDoorwayValidated: true },
  { id: '8', studentName: 'Henry Martinez', studentId: 'STU008', fileName: 'transcript_henry.pdf', uploadDate: '2024-01-11', processedDate: '2024-01-11', status: 'Processed', gpa: 3.6, source: 'Dropbox', ucDoorwayValidated: true },
  { id: '9', studentName: 'Ivy Chen', studentId: 'STU009', fileName: 'transcript_ivy.pdf', uploadDate: '2024-01-11', status: 'Failed', source: 'Manual Upload', ucDoorwayValidated: false },
  { id: '10', studentName: 'Jack Robinson', studentId: 'STU010', fileName: 'transcript_jack.pdf', uploadDate: '2024-01-10', processedDate: '2024-01-10', status: 'Processed', gpa: 3.4, source: 'Google Drive', ucDoorwayValidated: true },
];

export default function AllTranscripts() {
  const location = useLocation();
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<string>('all');
  const [sourceFilter, setSourceFilter] = useState<string>('all');
  const [selectedTranscripts, setSelectedTranscripts] = useState<Set<string>>(new Set());
  const [showFilters, setShowFilters] = useState(false);

  // Determine the page type from the route
  const getPageType = () => {
    if (location.pathname === '/transcripts/processed') return 'Processed';
    if (location.pathname === '/transcripts/failed') return 'Failed';
    if (location.pathname === '/transcripts/queue') return 'In Queue';
    return 'all';
  };

  const pageType = getPageType();

  // Set initial status filter based on route
  useEffect(() => {
    setStatusFilter(pageType);
  }, [pageType]);

  const filteredTranscripts = mockTranscripts.filter((t) => {
    const matchesSearch =
      t.studentName.toLowerCase().includes(search.toLowerCase()) ||
      t.studentId.toLowerCase().includes(search.toLowerCase()) ||
      t.fileName.toLowerCase().includes(search.toLowerCase());

    const matchesStatus = statusFilter === 'all' || t.status === statusFilter;
    const matchesSource = sourceFilter === 'all' || t.source === sourceFilter;

    return matchesSearch && matchesStatus && matchesSource;
  });

  const handleSelectAll = (checked: boolean) => {
    if (checked) {
      setSelectedTranscripts(new Set(filteredTranscripts.map(t => t.id)));
    } else {
      setSelectedTranscripts(new Set());
    }
  };

  const handleSelectOne = (id: string, checked: boolean) => {
    const newSelected = new Set(selectedTranscripts);
    if (checked) {
      newSelected.add(id);
    } else {
      newSelected.delete(id);
    }
    setSelectedTranscripts(newSelected);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case 'Processed':
        return <Badge className="bg-green-500 hover:bg-green-600">Processed</Badge>;
      case 'Failed':
        return <Badge className="bg-red-500 hover:bg-red-600">Failed</Badge>;
      case 'In Queue':
        return <Badge className="bg-orange-500 hover:bg-orange-600">In Queue</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  const getSourceBadge = (source: string) => {
    const colors: Record<string, string> = {
      'Manual Upload': 'bg-blue-100 text-blue-700 border-blue-200',
      'Google Drive': 'bg-purple-100 text-purple-700 border-purple-200',
      'Dropbox': 'bg-cyan-100 text-cyan-700 border-cyan-200'
    };
    return <Badge variant="outline" className={colors[source] || ''}>{source}</Badge>;
  };

  const stats = {
    total: mockTranscripts.length,
    processed: mockTranscripts.filter(t => t.status === 'Processed').length,
    failed: mockTranscripts.filter(t => t.status === 'Failed').length,
    inQueue: mockTranscripts.filter(t => t.status === 'In Queue').length,
    validated: mockTranscripts.filter(t => t.ucDoorwayValidated).length
  };

  // Get page title and description based on route
  const getPageInfo = () => {
    switch (pageType) {
      case 'Processed':
        return {
          title: 'Processed Transcripts',
          description: 'Successfully processed and validated transcripts'
        };
      case 'Failed':
        return {
          title: 'Failed Transcripts',
          description: 'Transcripts that failed processing or validation'
        };
      case 'In Queue':
        return {
          title: 'Transcripts In Queue',
          description: 'Transcripts waiting to be processed'
        };
      default:
        return {
          title: 'All Transcripts',
          description: 'View and manage all uploaded student transcripts'
        };
    }
  };

  const pageInfo = getPageInfo();

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
            Export All
          </Button>
          <Button variant="outline" size="sm">
            <RefreshCw className="h-4 w-4 mr-2" />
            Refresh
          </Button>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid gap-4 md:grid-cols-5">
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Total Transcripts</CardDescription>
            <CardTitle className="text-3xl">{stats.total}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Processed</CardDescription>
            <CardTitle className="text-3xl text-green-600">{stats.processed}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>Failed</CardDescription>
            <CardTitle className="text-3xl text-red-600">{stats.failed}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>In Queue</CardDescription>
            <CardTitle className="text-3xl text-orange-600">{stats.inQueue}</CardTitle>
          </CardHeader>
        </Card>
        <Card className="shadow-card">
          <CardHeader className="pb-2">
            <CardDescription>UC Validated</CardDescription>
            <CardTitle className="text-3xl text-blue-600">{stats.validated}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="shadow-card">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="h-5 w-5" />
            Transcript Records
          </CardTitle>
          <CardDescription>
            {filteredTranscripts.length} transcript{filteredTranscripts.length !== 1 ? 's' : ''} found
            {selectedTranscripts.size > 0 && ` • ${selectedTranscripts.size} selected`}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="space-y-4 mb-4">
            <div className="flex gap-2">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search by student name, ID, or filename..."
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
                      <SelectItem value="Processed">Processed</SelectItem>
                      <SelectItem value="Failed">Failed</SelectItem>
                      <SelectItem value="In Queue">In Queue</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex-1">
                  <label className="text-sm font-medium mb-2 block">Source</label>
                  <Select value={sourceFilter} onValueChange={setSourceFilter}>
                    <SelectTrigger>
                      <SelectValue placeholder="All sources" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">All Sources</SelectItem>
                      <SelectItem value="Manual Upload">Manual Upload</SelectItem>
                      <SelectItem value="Google Drive">Google Drive</SelectItem>
                      <SelectItem value="Dropbox">Dropbox</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="flex items-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => {
                      setStatusFilter('all');
                      setSourceFilter('all');
                    }}
                  >
                    Clear Filters
                  </Button>
                </div>
              </div>
            )}

            {selectedTranscripts.size > 0 && (
              <div className="flex items-center gap-2 p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <span className="text-sm font-medium text-blue-900">
                  {selectedTranscripts.size} item{selectedTranscripts.size !== 1 ? 's' : ''} selected
                </span>
                <div className="flex gap-2 ml-auto">
                  <Button variant="outline" size="sm">
                    <Download className="h-4 w-4 mr-2" />
                    Download Selected
                  </Button>
                  <Button variant="outline" size="sm" className="text-red-600 hover:text-red-700">
                    <Trash2 className="h-4 w-4 mr-2" />
                    Delete Selected
                  </Button>
                </div>
              </div>
            )}
          </div>

          <div className="rounded-md border">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <Checkbox
                      checked={selectedTranscripts.size === filteredTranscripts.length && filteredTranscripts.length > 0}
                      onCheckedChange={handleSelectAll}
                    />
                  </TableHead>
                  <TableHead>Student Name</TableHead>
                  <TableHead>Student ID</TableHead>
                  <TableHead>File Name</TableHead>
                  <TableHead>Source</TableHead>
                  <TableHead>Upload Date</TableHead>
                  <TableHead>GPA</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>UC Validated</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredTranscripts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center py-8 text-muted-foreground">
                      No transcripts found matching your criteria
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredTranscripts.map((transcript) => (
                    <TableRow key={transcript.id} className="hover:bg-slate-50">
                      <TableCell>
                        <Checkbox
                          checked={selectedTranscripts.has(transcript.id)}
                          onCheckedChange={(checked) => handleSelectOne(transcript.id, checked as boolean)}
                        />
                      </TableCell>
                      <TableCell className="font-medium">{transcript.studentName}</TableCell>
                      <TableCell className="text-muted-foreground">{transcript.studentId}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{transcript.fileName}</TableCell>
                      <TableCell>{getSourceBadge(transcript.source)}</TableCell>
                      <TableCell className="text-sm">
                        <div className="flex items-center gap-1">
                          <Calendar className="h-3 w-3 text-muted-foreground" />
                          {transcript.uploadDate}
                        </div>
                      </TableCell>
                      <TableCell>
                        {transcript.gpa ? (
                          <span className="font-medium">{transcript.gpa.toFixed(2)}</span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                      <TableCell>{getStatusBadge(transcript.status)}</TableCell>
                      <TableCell>
                        {transcript.ucDoorwayValidated ? (
                          <Badge className="bg-green-100 text-green-700 border-green-200" variant="outline">
                            Validated
                          </Badge>
                        ) : (
                          <Badge className="bg-gray-100 text-gray-700 border-gray-200" variant="outline">
                            Pending
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button variant="ghost" size="sm" title="View transcript">
                            <Eye className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" title="Download transcript">
                            <Download className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" className="text-red-600 hover:text-red-700" title="Delete transcript">
                            <Trash2 className="h-4 w-4" />
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

