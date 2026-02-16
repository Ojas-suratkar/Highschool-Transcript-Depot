import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

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
}

interface ViewStudentDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  transcript: Transcript;
}

export function ViewStudentDialog({
  open,
  onOpenChange,
  transcript,
}: ViewStudentDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Student Information</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Student Header */}
          <div className="flex items-center justify-between">
            <div>
              <div className="text-2xl font-bold">{transcript.studentName}</div>
              <div className="text-sm text-muted-foreground mt-1">{transcript.email}</div>
            </div>
            <Badge className="text-lg px-3 py-1">
              {transcript.status === 'processed' && 'Processed'}
              {transcript.status === 'failed' && 'Manual Review'}
              {transcript.status === 'queue' && 'In Queue'}
            </Badge>
          </div>

          {/* Basic Information */}
          <Card>
            <CardHeader className="bg-muted/30 border-b">
              <CardTitle className="text-base">Basic Information</CardTitle>
            </CardHeader>
            <CardContent className="pt-6">
              <div className="grid grid-cols-2 gap-6">
                <div>
                  <div className="text-sm text-muted-foreground">School</div>
                  <div className="text-lg font-semibold mt-1">{transcript.school || '—'}</div>
                </div>
                <div>
                  <div className="text-sm text-muted-foreground">Upload Date</div>
                  <div className="text-lg font-semibold mt-1">{transcript.uploadDate}</div>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Academic Information */}
          {(transcript.gpa !== undefined || transcript.ucMatch !== undefined) && (
            <Card>
              <CardHeader className="bg-muted/30 border-b">
                <CardTitle className="text-base">Academic Information</CardTitle>
              </CardHeader>
              <CardContent className="pt-6">
                <div className="grid grid-cols-2 gap-6">
                  {transcript.gpa !== undefined && (
                    <div>
                      <div className="text-sm text-muted-foreground">GPA</div>
                      <div className="text-lg font-semibold mt-1">{transcript.gpa.toFixed(2)}</div>
                    </div>
                  )}
                  {transcript.ucMatch !== undefined && (
                    <div>
                      <div className="text-sm text-muted-foreground">UC Match</div>
                      <div className="text-lg font-semibold mt-1">
                        {transcript.ucMatch ? (
                          <span className="text-green-600">✓ Yes</span>
                        ) : (
                          <span className="text-red-600">✗ No</span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Status Information */}
          {transcript.status === 'failed' && transcript.reviewReason && (
            <Card className="border-amber-200 bg-amber-50">
              <CardHeader className="bg-amber-100 border-b border-amber-200">
                <CardTitle className="text-base text-amber-900">Review Reason</CardTitle>
              </CardHeader>
              <CardContent className="pt-6">
                <div className="text-amber-900">{transcript.reviewReason}</div>
              </CardContent>
            </Card>
          )}

          {transcript.status === 'queue' && transcript.position !== undefined && (
            <Card>
              <CardHeader className="bg-muted/30 border-b">
                <CardTitle className="text-base">Queue Information</CardTitle>
              </CardHeader>
              <CardContent className="pt-6">
                <div>
                  <div className="text-sm text-muted-foreground">Position</div>
                  <div className="text-lg font-semibold mt-1">#{transcript.position}</div>
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
