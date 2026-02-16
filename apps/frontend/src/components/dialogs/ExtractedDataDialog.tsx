import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';

interface Course {
  name: string;
  grade: string;
  credits: number;
}

interface ProcessedTranscript {
  id: string;
  studentName: string;
  school: string;
  gpa: number;
  courses: number;
  templateUsed: string;
  extractedData?: {
    gpa: number;
    graduationDate: string;
    courses: Course[];
  };
}

interface ExtractedDataDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript: ProcessedTranscript;
}

export function ExtractedDataDialog({
  open,
  onOpenChange,
  transcript,
}: ExtractedDataDialogProps) {
  const data = transcript.extractedData;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Extracted Data</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Student Information */}
          <div className="flex gap-3">
            <Badge>{transcript.studentName}</Badge>
            <Badge variant="outline">{transcript.school}</Badge>
          </div>

          {/* Key Information */}
          {data && (
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-1">
                <div className="text-sm text-muted-foreground">GPA</div>
                <div className="text-2xl font-bold">{data.gpa.toFixed(2)}</div>
              </div>
              <div className="space-y-1">
                <div className="text-sm text-muted-foreground">Graduation Date</div>
                <div className="text-2xl font-bold">{data.graduationDate}</div>
              </div>
            </div>
          )}

          {/* Courses Table */}
          {data?.courses && (
            <div className="space-y-3">
              <div className="text-sm font-semibold">Courses</div>
              <div className="border rounded-lg overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50">
                      <TableHead>Course Name</TableHead>
                      <TableHead>Grade</TableHead>
                      <TableHead>Credits</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.courses.map((course, idx) => (
                      <TableRow key={idx}>
                        <TableCell className="font-medium">{course.name}</TableCell>
                        <TableCell>{course.grade}</TableCell>
                        <TableCell>{course.credits}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
