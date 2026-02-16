import { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Eye, Download, Edit2, Trash2, Search, Plus } from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { Input } from '@/components/ui/input';
import { Button } from '@/components/ui/button';
import { StatusBadge } from '@/components/shared/StatusBadge';
import { Card, CardContent } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
// no shared Select import — pages don't use a common status filter
import { toast } from 'sonner';
import { ManualEntryDialog } from '@/components/dialogs/ManualEntryDialog';

interface Transcript {
  id: string;
  studentName: string;
  uploadDate: string;
  status: 'processed' | 'failed' | 'queue';
  gpa?: number;
  ucMatch?: boolean;
  reviewReason?: string;
  position?: number;
  school?: string;
  email?: string;
  fileUrl?: string;
}

const mockProcessedTranscripts: Transcript[] = [
  { id: '1', studentName: 'John Smith', uploadDate: '2025-01-08', status: 'processed', gpa: 3.85, ucMatch: true, school: 'Lincoln High School', email: 'jsmith@email.com', fileUrl: '/assets/transcripts/john-smith.pdf' },
  { id: '2', studentName: 'Sarah Johnson', uploadDate: '2025-01-07', status: 'processed', gpa: 3.92, ucMatch: true, school: 'Lincoln High School', email: 'sjohnson@email.com', fileUrl: '/assets/transcripts/sarah-johnson.pdf' },
  { id: '3', studentName: 'James Wilson', uploadDate: '2025-01-06', status: 'processed', gpa: 3.45, ucMatch: false, school: 'Lincoln High School', email: 'jwilson@email.com', fileUrl: '/assets/transcripts/james-wilson.pdf' },
];

const mockManualReviewTranscripts: Transcript[] = [
  { id: '4', studentName: 'Michael Brown', uploadDate: '2025-01-07', status: 'failed', reviewReason: 'Invalid file format', school: 'Central High', email: 'mbrown@email.com', fileUrl: '/assets/transcripts/michael-brown.pdf' },
  { id: '5', studentName: 'David Chen', uploadDate: '2025-01-05', status: 'failed', reviewReason: 'OCR extraction failed', school: 'Central High', email: 'dchen@email.com', fileUrl: '/assets/transcripts/david-chen.pdf' },
];

const mockQueueTranscripts: Transcript[] = [
  { id: '6', studentName: 'Emily Davis', uploadDate: '2025-01-06', status: 'queue', position: 1, school: 'Washington High', email: 'edavis@email.com', fileUrl: '/assets/transcripts/emily-davis.pdf' },
  { id: '7', studentName: 'Amanda Lee', uploadDate: '2025-01-05', status: 'queue', position: 2, school: 'Roosevelt High', email: 'alee@email.com', fileUrl: '/assets/transcripts/amanda-lee.pdf' },
];

const mockAllTranscripts: Transcript[] = [
  ...mockProcessedTranscripts,
  ...mockManualReviewTranscripts,
  ...mockQueueTranscripts,
];

export default function TranscriptsList() {
  const location = useLocation();
  const navigate = useNavigate();
  const pathname = location.pathname || '';
  const type: 'all' | 'processed' | 'manual-review' | 'queue' =
    pathname.includes('/transcripts/processed')
      ? 'processed'
      : pathname.includes('/transcripts/manual-review')
      ? 'manual-review'
      : pathname.includes('/transcripts/queue')
      ? 'queue'
      : 'all';
  const [searchTerm, setSearchTerm] = useState('');
  const [manualEntryOpen, setManualEntryOpen] = useState(false);
  const [selectedTranscript, setSelectedTranscript] = useState<Transcript | null>(null);

  // Filter transcripts based on page type and search
  const getFilteredTranscripts = () => {
    let data: Transcript[] = [];

    // Select data based on page type
    if (type === 'processed') {
      data = mockProcessedTranscripts;
    } else if (type === 'manual-review') {
      data = mockManualReviewTranscripts;
    } else if (type === 'queue') {
      data = mockQueueTranscripts;
    } else {
      data = mockAllTranscripts;
    }

    // Filter by search term
    if (searchTerm) {
      data = data.filter(t =>
        t.studentName.toLowerCase().includes(searchTerm.toLowerCase()) ||
        t.email?.toLowerCase().includes(searchTerm.toLowerCase())
      );
    }

    return data;
  };

  const handleOpenManualEntry = (transcript?: Transcript) => {
    setSelectedTranscript(transcript || null);
    setManualEntryOpen(true);
  };

  const handleViewStudent = (transcript: Transcript) => {
    // For processed transcripts, navigate to detail page
    if (type === 'processed') {
      navigate(`/transcripts/${transcript.id}`);
    }
  };

  const handleDelete = () => {
    if (window.confirm('Are you sure you want to delete this transcript?')) {
      toast.success('Transcript deleted');
    }
  };

  const filteredTranscripts = getFilteredTranscripts();
  
  const getPageConfig = () => {
    switch (type) {
      case 'processed':
        return { title: 'Processed Transcripts', subtitle: 'View and manage processed transcripts' };
      case 'manual-review':
        return { title: 'Manual Review', subtitle: 'Transcripts requiring manual review' };
      case 'queue':
        return { title: 'In Queue', subtitle: 'Transcripts waiting to be processed' };
      default:
        return { title: 'All Transcripts', subtitle: 'View and manage all transcripts' };
    }
  };

  const config = getPageConfig();

  return (
    <div className="space-y-6">
      <PageHeader title={config.title} subtitle={config.subtitle} />

      {/* Filter Bar */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search by name or email..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="pl-9"
          />
        </div>

        <div className="flex gap-2">
          {/* no common status filter - pages are separate */}

          {type === 'manual-review' && (
            <Button onClick={() => handleOpenManualEntry()}>
              <Plus className="h-4 w-4 mr-2" />
              Enter New Student
            </Button>
          )}
        </div>
      </div>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Student Name</TableHead>
                  <TableHead>Email</TableHead>
                  <TableHead>Upload Date</TableHead>
                  <TableHead>Status</TableHead>
                  {type !== 'queue' && <TableHead>GPA</TableHead>}
                  {type !== 'queue' && <TableHead>UC Match</TableHead>}
                  {type === 'manual-review' && <TableHead className="text-amber-600">Review Reason</TableHead>}
                  {type === 'queue' && <TableHead>Position</TableHead>}
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredTranscripts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                      No transcripts found
                    </TableCell>
                  </TableRow>
                ) : (
                  filteredTranscripts.map((transcript) => (
                    <TableRow key={transcript.id} className="hover:bg-muted/50">
                      <TableCell className="font-medium">{transcript.studentName}</TableCell>
                      <TableCell className="text-sm text-muted-foreground">{transcript.email}</TableCell>
                      <TableCell>{transcript.uploadDate}</TableCell>
                      <TableCell>
                        <StatusBadge status={transcript.status === 'failed' ? 'failed' : transcript.status} />
                      </TableCell>
                      {type !== 'queue' && <TableCell>{transcript.gpa ? transcript.gpa.toFixed(2) : '—'}</TableCell>}
                      {type !== 'queue' && (
                        <TableCell>
                          <div className="flex items-center gap-1">
                            {transcript.ucMatch ? (
                              <span className="text-green-600">✓ Yes</span>
                            ) : (
                              <span className="text-red-600">✗ No</span>
                            )}
                          </div>
                        </TableCell>
                      )}
                      {type === 'manual-review' && (
                        <TableCell className="text-amber-600 text-sm">{transcript.reviewReason}</TableCell>
                      )}
                      {type === 'queue' && <TableCell>#{transcript.position}</TableCell>}
                      <TableCell>
                        <div className="flex gap-2 items-center">
                          {type === 'processed' && (
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleViewStudent(transcript)}
                              title="View Student Information"
                            >
                              <Eye className="h-4 w-4" />
                            </Button>
                          )}
                          <Button variant="ghost" size="icon" title="Download">
                            <Download className="h-4 w-4" />
                          </Button>
                          {type === 'manual-review' && (
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleOpenManualEntry(transcript)}
                              className="text-xs"
                            >
                              <Edit2 className="h-3 w-3 mr-1" />
                              Enter Manually
                            </Button>
                          )}
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={handleDelete}
                            title="Delete"
                          >
                            <Trash2 className="h-4 w-4 text-red-600" />
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

      {/* Manual Entry Dialog */}
      {(
        <ManualEntryDialog
          open={manualEntryOpen}
          onOpenChange={setManualEntryOpen}
          transcript={selectedTranscript || undefined}
        />
      )}
    </div>
  );
}
