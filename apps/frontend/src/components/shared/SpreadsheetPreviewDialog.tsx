import { FileSpreadsheet } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { ParsedSheet, formatFileSize } from '@/lib/excel';

/**
 * Read-only preview of an uploaded spreadsheet — file metadata plus the parsed
 * grid — mirroring the transcript preview experience elsewhere in the app.
 */
export function SpreadsheetPreviewDialog({
  open,
  onOpenChange,
  sheet,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sheet: ParsedSheet | null;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
            {sheet?.fileName || 'Uploaded file'}
          </DialogTitle>
        </DialogHeader>

        {!sheet ? (
          <p className="text-sm text-muted-foreground">No file uploaded yet.</p>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-500">
              <span>Sheet: <span className="font-medium text-slate-700">{sheet.sheetName || '—'}</span></span>
              <span>{sheet.rows.length} row{sheet.rows.length === 1 ? '' : 's'}</span>
              <span>{sheet.headers.length} column{sheet.headers.length === 1 ? '' : 's'}</span>
              <span>{formatFileSize(sheet.fileSize)}</span>
            </div>

            <div className="max-h-[60vh] overflow-auto rounded-md border">
              <table className="w-full border-collapse text-sm">
                <thead className="sticky top-0 bg-slate-50">
                  <tr>
                    <th className="border-b px-3 py-2 text-left text-xs font-semibold text-slate-500">#</th>
                    {sheet.headers.map((h) => (
                      <th key={h} className="border-b px-3 py-2 text-left font-semibold text-slate-700 whitespace-nowrap">
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sheet.rows.map((row, i) => (
                    <tr key={i} className="odd:bg-white even:bg-slate-50/50">
                      <td className="px-3 py-1.5 text-xs text-slate-400">{i + 1}</td>
                      {sheet.headers.map((h) => (
                        <td key={h} className="px-3 py-1.5 text-slate-800 whitespace-nowrap">
                          {row[h] || ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                  {sheet.rows.length === 0 && (
                    <tr>
                      <td colSpan={sheet.headers.length + 1} className="px-3 py-6 text-center text-sm text-muted-foreground">
                        No data rows found in this file.
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
