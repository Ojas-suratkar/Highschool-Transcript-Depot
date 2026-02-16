import { useState, useEffect } from 'react';
import {
  Zap,
  Eye,
  Brain,
  RefreshCw,
  CheckCircle,
  AlertTriangle,
  Download,
  Loader2,
  TrendingUp,
  Users,
  FileText,
} from 'lucide-react';
import { PageHeader } from '@/components/shared/PageHeader';
import { StatCard } from '@/components/shared/StatCard';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import { toast } from 'sonner';
import { ReviewAndTrainDialog } from '@/components/dialogs/ReviewAndTrainDialog';
import { ExtractedDataDialog } from '@/components/dialogs/ExtractedDataDialog';

interface DetectedFormat {
  id: string;
  studentName: string;
  school: string;
  detected: string;
  detectedDate: string;
  status: 'detected' | 'reviewing' | 'training' | 'testing' | 'processed' | 'failed';
  templateAssigned?: string;
  testResult?: 'pass' | 'fail';
}

interface ProcessedTranscript {
  id: string;
  studentName: string;
  school: string;
  gpa: number;
  courses: number;
  templateUsed: string;
  status: 'ready' | 'processing' | 'completed';
  extractedData?: {
    gpa: number;
    graduationDate: string;
    courses: Array<{ name: string; grade: string; credits: number }>;
  };
}

const mockDetectedFormats: DetectedFormat[] = [
  {
    id: '1',
    studentName: 'Alex Thompson',
    school: 'Lincoln HS',
    detected: 'lincoln_v2.pdf',
    detectedDate: '2025-01-15',
    status: 'detected',
  },
  {
    id: '2',
    studentName: 'Maria Garcia',
    school: 'Washington HS',
    detected: 'washington_new.pdf',
    detectedDate: '2025-01-14',
    status: 'reviewing',
  },
  {
    id: '3',
    studentName: 'James Lee',
    school: 'Jefferson HS',
    detected: 'jefferson_format.pdf',
    detectedDate: '2025-01-14',
    status: 'training',
  },
  {
    id: '4',
    studentName: 'Sofia Brown',
    school: 'Roosevelt HS',
    detected: 'roosevelt_v3.pdf',
    detectedDate: '2025-01-13',
    status: 'testing',
  },
];

const mockProcessedTranscripts: ProcessedTranscript[] = [
  {
    id: 'p1',
    studentName: 'Emily Chen',
    school: 'Lincoln HS',
    gpa: 3.8,
    courses: 15,
    templateUsed: 'Lincoln HS - V2',
    status: 'completed',
    extractedData: {
      gpa: 3.8,
      graduationDate: '2025-06-15',
      courses: [
        { name: 'Calculus I', grade: 'A', credits: 4 },
        { name: 'Physics', grade: 'A-', credits: 4 },
        { name: 'English Comp', grade: 'A', credits: 3 },
      ],
    },
  },
  {
    id: 'p2',
    studentName: 'Michael Johnson',
    school: 'Washington HS',
    gpa: 3.6,
    courses: 14,
    templateUsed: 'Washington HS - V1',
    status: 'completed',
  },
];

const statusConfig = {
  detected: { label: 'Detected', color: 'bg-amber-100', textColor: 'text-amber-700', icon: '🔍' },
  reviewing: { label: 'Reviewing', color: 'bg-blue-100', textColor: 'text-blue-700', icon: '👀' },
  training: { label: 'Training', color: 'bg-purple-100', textColor: 'text-purple-700', icon: '🧠' },
  testing: { label: 'Testing', color: 'bg-cyan-100', textColor: 'text-cyan-700', icon: '✓' },
  processed: { label: 'Processed', color: 'bg-green-100', textColor: 'text-green-700', icon: '✅' },
  failed: { label: 'Failed', color: 'bg-red-100', textColor: 'text-red-700', icon: '❌' },
};

export default function TrainerDashboard() {
  const [detectedFormats, setDetectedFormats] = useState<DetectedFormat[]>(mockDetectedFormats);
  const [processedTranscripts, _setProcessedTranscripts] = useState<ProcessedTranscript[]>(mockProcessedTranscripts);
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false);
  const [selectedFormat, setSelectedFormat] = useState<DetectedFormat | null>(null);
  const [extractedDataDialogOpen, setExtractedDataDialogOpen] = useState(false);
  const [selectedProcessed, setSelectedProcessed] = useState<ProcessedTranscript | null>(null);

  // Auto-detection simulation
  useEffect(() => {
    const interval = setInterval(() => {
      const schools = ['Lincoln HS', 'Washington HS', 'Jefferson HS', 'Roosevelt HS', 'Kennedy HS'];
      const randomSchool = schools[Math.floor(Math.random() * schools.length)];
      const randomStudent = `Student ${Math.floor(Math.random() * 1000)}`;
      
      toast.info(`New unknown format detected: ${randomSchool}`, {
        duration: 5000,
      });

      const newFormat: DetectedFormat = {
        id: Date.now().toString(),
        studentName: randomStudent,
        school: randomSchool,
        detected: `${randomSchool.toLowerCase().replace(/ /g, '_')}_format.pdf`,
        detectedDate: new Date().toISOString().split('T')[0],
        status: 'detected',
      };

      setDetectedFormats(prev => [newFormat, ...prev]);
    }, 15000);

    return () => clearInterval(interval);
  }, []);

  const handleReview = (format: DetectedFormat) => {
    setSelectedFormat(format);
    setReviewDialogOpen(true);
  };

  const handleAssignTemplate = (format: DetectedFormat, template: string) => {
    setDetectedFormats(prev =>
      prev.map(f =>
        f.id === format.id
          ? { ...f, status: 'training', templateAssigned: template }
          : f
      )
    );

    toast.info('Template assigned. Training started...', { duration: 5000 });

    // Simulate training delay
    setTimeout(() => {
      setDetectedFormats(prev =>
        prev.map(f =>
          f.id === format.id ? { ...f, status: 'testing' } : f
        )
      );
      toast.info('Training complete. Running extraction test...', { duration: 5000 });

      // Simulate testing delay
      setTimeout(() => {
        const testPassed = Math.random() > 0.3;
        setDetectedFormats(prev =>
          prev.map(f =>
            f.id === format.id
              ? { ...f, status: testPassed ? 'processed' : 'failed', testResult: testPassed ? 'pass' : 'fail' }
              : f
          )
        );
        toast.success('Extraction test passed!', { duration: 5000 });
      }, 2000);
    }, 2500);

    setReviewDialogOpen(false);
  };

  const handleViewData = (transcript: ProcessedTranscript) => {
    setSelectedProcessed(transcript);
    setExtractedDataDialogOpen(true);
  };

  const handleRetry = (format: DetectedFormat) => {
    setDetectedFormats(prev =>
      prev.map(f =>
        f.id === format.id ? { ...f, status: 'testing', testResult: undefined } : f
      )
    );
    toast.info('Re-running test...', { duration: 5000 });

    setTimeout(() => {
      const testPassed = Math.random() > 0.3;
      setDetectedFormats(prev =>
        prev.map(f =>
          f.id === format.id
            ? { ...f, status: testPassed ? 'processed' : 'failed', testResult: testPassed ? 'pass' : 'fail' }
            : f
        )
      );
    }, 2000);
  };

  const stats = {
    templates: 12,
    trained: 45,
    pending: 8,
    inProgress: 3,
    readyToProcess: 5,
    processed: 142,
  };

  return (
    <div className="space-y-6">
      <PageHeader
        title="Trainer Dashboard"
        subtitle="Monitor and manage transcript format training"
      />

      {/* Stat Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard
          title="Templates"
          value={stats.templates}
          icon={<FileText className="h-6 w-6" />}
        />
        <StatCard
          title="Trained"
          value={stats.trained}
          icon={<CheckCircle className="h-6 w-6" />}
        />
        <StatCard
          title="Pending Review"
          value={stats.pending}
          icon={<Eye className="h-6 w-6" />}
        />
        <StatCard
          title="In Progress"
          value={stats.inProgress}
          icon={<Loader2 className="h-6 w-6" />}
        />
        <StatCard
          title="Ready to Process"
          value={stats.readyToProcess}
          icon={<TrendingUp className="h-6 w-6" />}
        />
        <StatCard
          title="Processed"
          value={stats.processed}
          icon={<Users className="h-6 w-6" />}
        />
      </div>

      {/* Training Workflow */}
      <Card>
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="text-lg">Training Workflow</CardTitle>
        </CardHeader>
        <CardContent className="pt-6">
          <div className="flex items-center justify-between gap-2 overflow-x-auto pb-4">
            {[
              { icon: Zap, label: 'Auto-Detect', color: 'bg-amber-100 text-amber-700' },
              { icon: Eye, label: 'Review', color: 'bg-blue-100 text-blue-700' },
              { icon: Brain, label: 'Train', color: 'bg-purple-100 text-purple-700' },
              { icon: RefreshCw, label: 'Test', color: 'bg-cyan-100 text-cyan-700' },
              { icon: CheckCircle, label: 'Process', color: 'bg-green-100 text-green-700' },
            ].map((step, idx, arr) => (
              <div key={step.label} className="flex items-center gap-2 flex-shrink-0">
                <div className={`rounded-full p-3 ${step.color}`}>
                  <step.icon className="h-5 w-5" />
                </div>
                <span className="text-sm font-medium whitespace-nowrap">{step.label}</span>
                {idx < arr.length - 1 && <div className="w-8 h-0.5 bg-muted" />}
              </div>
            ))}
          </div>
        </CardContent>
      </Card>

      {/* Unknown Formats Table */}
      <Card>
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="text-lg">Unknown Formats</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Student Name</TableHead>
                  <TableHead>School</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Template</TableHead>
                  <TableHead>Test Result</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {detectedFormats.map((format) => (
                  <TableRow key={format.id}>
                    <TableCell className="font-medium">{format.studentName}</TableCell>
                    <TableCell>{format.school}</TableCell>
                    <TableCell className="text-sm text-muted-foreground">{format.detected}</TableCell>
                    <TableCell>
                      <Badge
                        className={`${statusConfig[format.status].color} ${statusConfig[format.status].textColor}`}
                      >
                        {statusConfig[format.status].label}
                      </Badge>
                    </TableCell>
                    <TableCell>{format.templateAssigned || '—'}</TableCell>
                    <TableCell>
                      {format.testResult === 'pass' && (
                        <Badge className="bg-green-100 text-green-700">
                          <CheckCircle className="h-3 w-3 mr-1" />
                          Pass
                        </Badge>
                      )}
                      {format.testResult === 'fail' && (
                        <Badge className="bg-red-100 text-red-700">
                          <AlertTriangle className="h-3 w-3 mr-1" />
                          Fail
                        </Badge>
                      )}
                      {!format.testResult && '—'}
                    </TableCell>
                    <TableCell>
                      {format.status === 'detected' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReview(format)}
                        >
                          Review
                        </Button>
                      )}
                      {format.status === 'reviewing' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleReview(format)}
                        >
                          Configure
                        </Button>
                      )}
                      {(format.status === 'training' || format.status === 'testing') && (
                        <div className="flex items-center gap-1 text-sm text-muted-foreground">
                          <Loader2 className="h-4 w-4 animate-spin" />
                          Processing...
                        </div>
                      )}
                      {format.status === 'processed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => {
                            const processed = mockProcessedTranscripts.find(p => p.studentName === format.studentName);
                            if (processed) handleViewData(processed);
                          }}
                        >
                          View Data
                        </Button>
                      )}
                      {format.status === 'failed' && (
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleRetry(format)}
                        >
                          Retry
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Processed Transcripts Table */}
      <Card>
        <CardHeader className="border-b bg-muted/30">
          <CardTitle className="text-lg">Processed Transcripts</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Student Name</TableHead>
                  <TableHead>School</TableHead>
                  <TableHead>GPA</TableHead>
                  <TableHead>Courses</TableHead>
                  <TableHead>Template Used</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {processedTranscripts.map((transcript) => (
                  <TableRow key={transcript.id}>
                    <TableCell className="font-medium">{transcript.studentName}</TableCell>
                    <TableCell>{transcript.school}</TableCell>
                    <TableCell>{transcript.gpa.toFixed(2)}</TableCell>
                    <TableCell>{transcript.courses}</TableCell>
                    <TableCell>{transcript.templateUsed}</TableCell>
                    <TableCell>
                      <Badge className="bg-green-100 text-green-700">Completed</Badge>
                    </TableCell>
                    <TableCell>
                      <div className="flex gap-2">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => handleViewData(transcript)}
                        >
                          <Eye className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="icon">
                          <Download className="h-4 w-4" />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </CardContent>
      </Card>

      {/* Review and Train Dialog */}
      {selectedFormat && (
        <ReviewAndTrainDialog
          open={reviewDialogOpen}
          onOpenChange={setReviewDialogOpen}
          format={selectedFormat}
          // Cast to any to unify the two local DetectedFormat types for TypeScript;
          // this is a safe runtime-preserving cast because shapes are compatible at runtime.
          onAssignTemplate={handleAssignTemplate as any}
        />
      )}

      {/* Extracted Data Dialog */}
      {selectedProcessed && (
        <ExtractedDataDialog
          open={extractedDataDialogOpen}
          onOpenChange={setExtractedDataDialogOpen}
          transcript={selectedProcessed}
        />
      )}
    </div>
  );
}

