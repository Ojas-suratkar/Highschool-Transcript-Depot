import { useState } from 'react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { Badge } from '@/components/ui/badge';

interface DetectedFormat {
  id: string;
  studentName: string;
  school: string;
  detected: string;
  detectedDate: string;
  status: string;
}

interface ReviewAndTrainDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  format: DetectedFormat;
  onAssignTemplate: (format: DetectedFormat, template: string) => void;
}

export function ReviewAndTrainDialog({
  open,
  onOpenChange,
  format,
  onAssignTemplate,
}: ReviewAndTrainDialogProps) {
  const [selectedTemplate, setSelectedTemplate] = useState('');

  const existingTemplates = [
    'Lincoln HS - V2',
    'Washington HS - V1',
    'Jefferson HS - V3',
    'Roosevelt HS - V1',
  ];

  const handleAssign = () => {
    if (selectedTemplate) {
      onAssignTemplate(format, selectedTemplate);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>Review & Train</DialogTitle>
        </DialogHeader>

        <div className="space-y-6">
          {/* Format Information Grid */}
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-sm text-muted-foreground">Student</div>
              <Badge className="mt-1">{format.studentName}</Badge>
            </div>
            <div>
              <div className="text-sm text-muted-foreground">School</div>
              <Badge className="mt-1" variant="outline">{format.school}</Badge>
            </div>
            <div>
              <div className="text-sm text-muted-foreground">Detected Date</div>
              <Badge variant="secondary" className="mt-1">{format.detectedDate}</Badge>
            </div>
          </div>

          {/* Preview Placeholder */}
          <div className="border rounded-lg p-6 bg-muted/30 min-h-[200px] flex items-center justify-center">
            <div className="text-center text-muted-foreground">
              <div className="text-sm mb-2">PDF Preview</div>
              <div className="text-xs">{format.detected}</div>
            </div>
          </div>

          {/* Template Selection */}
          <div className="space-y-3">
            <div className="text-sm font-semibold">Template Assignment</div>
            <Select value={selectedTemplate} onValueChange={setSelectedTemplate}>
              <SelectTrigger>
                <SelectValue placeholder="Select a template" />
              </SelectTrigger>
              <SelectContent>
                {existingTemplates.map((template) => (
                  <SelectItem key={template} value={template}>
                    {template}
                  </SelectItem>
                ))}
                <SelectItem value="new-template">— New Template —</SelectItem>
              </SelectContent>
            </Select>

            {selectedTemplate === 'new-template' && (
              <div className="p-3 bg-blue-50 border border-blue-200 rounded-lg">
                <div className="text-sm font-medium text-blue-900">Create New Template</div>
                <div className="text-xs text-blue-700 mt-1">
                  A new template will be created based on this format
                </div>
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="flex gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={handleAssign} disabled={!selectedTemplate}>
            Assign & Start Training
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
