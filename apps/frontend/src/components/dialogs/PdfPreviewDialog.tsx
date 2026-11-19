import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { FileText } from 'lucide-react';

interface PdfPreviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title?: string;
  url?: string;
  /** @deprecated use url instead */
  idLabel?: string;
}

export default function PdfPreviewDialog({
  open,
  onOpenChange,
  title = 'PDF Preview',
  url,
  idLabel,
}: PdfPreviewDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="!max-w-4xl w-[90vw] p-0 overflow-hidden">
        <DialogHeader className="px-5 pt-4 pb-3 border-b">
          <DialogTitle className="text-base font-semibold truncate">{title}</DialogTitle>
        </DialogHeader>

        <div className="h-[78vh]">
          {url ? (
            <iframe
              key={url}
              title={title}
              src={`${url}#zoom=page-width`}
              className="h-full w-full border-0"
            />
          ) : (
            <div className="flex h-full flex-col items-center justify-center gap-3 text-gray-400">
              <FileText className="h-10 w-10" />
              <p className="text-sm">{idLabel ?? 'No file selected'}</p>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
