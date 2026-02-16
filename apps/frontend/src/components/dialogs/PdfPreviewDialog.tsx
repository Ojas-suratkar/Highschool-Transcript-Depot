// React import not required with the new JSX transform
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface PdfPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  idLabel?: string;
}

export default function PdfPreviewDialog({ open, onOpenChange, title = 'PDF Preview', idLabel }: PdfPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>

        <div className="border rounded-lg p-6 bg-muted/30 min-h-[320px] flex items-center justify-center">
          <div className="text-center text-muted-foreground">
            <div className="text-sm mb-2">PDF Preview Placeholder</div>
            {idLabel ? <div className="text-xs">{idLabel}</div> : null}
            <div className="mt-4 text-xs text-muted-foreground">(Replace with embedded PDF or viewer later)</div>
          </div>
        </div>

        <DialogFooter>
          <Button onClick={() => onOpenChange(false)}>Close</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
