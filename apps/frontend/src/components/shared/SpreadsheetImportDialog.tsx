import { useEffect, useState } from 'react';
import { FileSpreadsheet, Upload } from 'lucide-react';
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { TermSelector } from '@/components/shared/TermSelector';
import { ParsedSheet, formatFileSize } from '@/lib/excel';

export interface ImportContext {
  term: string;
  college: string;
  department: string;
  major: string;
  notes: string;
}

/**
 * Collects the context an uploaded spreadsheet needs (which term / course the
 * numbers are for), previews the parsed rows, then hands both to the caller to
 * turn into records. Shared by the Enrollment Targets and Admission Yield pages.
 */
export function SpreadsheetImportDialog({
  open,
  onOpenChange,
  sheet,
  title,
  confirmLabel,
  onImport,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  sheet: ParsedSheet | null;
  title: string;
  confirmLabel: string;
  onImport: (sheet: ParsedSheet, ctx: ImportContext) => void;
}) {
  const [ctx, setCtx] = useState<ImportContext>({ term: '', college: '', department: '', major: '', notes: '' });

  // Reset context each time a new file is opened.
  useEffect(() => {
    if (open) setCtx({ term: '', college: '', department: '', major: '', notes: '' });
  }, [open, sheet?.fileName]);

  const previewRows = sheet?.rows.slice(0, 6) || [];

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <FileSpreadsheet className="h-5 w-5 text-emerald-600" />
            {title}
          </DialogTitle>
        </DialogHeader>

        <div className="space-y-4">
          {sheet && (
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 rounded-md border bg-slate-50 px-3 py-2 text-xs text-slate-600">
              <span className="font-medium text-slate-800">{sheet.fileName}</span>
              <span>{sheet.rows.length} row{sheet.rows.length === 1 ? '' : 's'}</span>
              <span>{formatFileSize(sheet.fileSize)}</span>
            </div>
          )}

          <div>
            <p className="mb-2 text-sm text-slate-600">
              Tell us what this file is for. These details apply to every row that doesn't already
              specify its own.
            </p>
            <div className="grid gap-3 sm:grid-cols-2">
              <TermSelector
                value={ctx.term}
                onValueChange={(v) => setCtx((c) => ({ ...c, term: v }))}
                label="Term"
                showAddButton={false}
              />
              <div>
                <Label>Major / Program</Label>
                <Input
                  className="mt-2"
                  placeholder="e.g., Computer Science (MS)"
                  value={ctx.major}
                  onChange={(e) => setCtx((c) => ({ ...c, major: e.target.value }))}
                />
              </div>
              <div>
                <Label>College</Label>
                <Input
                  className="mt-2"
                  placeholder="e.g., Engineering"
                  value={ctx.college}
                  onChange={(e) => setCtx((c) => ({ ...c, college: e.target.value }))}
                />
              </div>
              <div>
                <Label>Department</Label>
                <Input
                  className="mt-2"
                  placeholder="e.g., Computer Science"
                  value={ctx.department}
                  onChange={(e) => setCtx((c) => ({ ...c, department: e.target.value }))}
                />
              </div>
              <div className="sm:col-span-2">
                <Label>Notes</Label>
                <Input
                  className="mt-2"
                  placeholder="Optional notes"
                  value={ctx.notes}
                  onChange={(e) => setCtx((c) => ({ ...c, notes: e.target.value }))}
                />
              </div>
            </div>
          </div>

          {sheet && sheet.headers.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Preview {sheet.rows.length > previewRows.length ? `(first ${previewRows.length} of ${sheet.rows.length})` : ''}
              </p>
              <div className="max-h-56 overflow-auto rounded-md border">
                <table className="w-full border-collapse text-sm">
                  <thead className="sticky top-0 bg-slate-50">
                    <tr>
                      {sheet.headers.map((h) => (
                        <th key={h} className="border-b px-3 py-2 text-left font-semibold text-slate-700 whitespace-nowrap">
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {previewRows.map((row, i) => (
                      <tr key={i} className="odd:bg-white even:bg-slate-50/50">
                        {sheet.headers.map((h) => (
                          <td key={h} className="px-3 py-1.5 text-slate-800 whitespace-nowrap">
                            {row[h] || ''}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            disabled={!sheet || sheet.rows.length === 0}
            onClick={() => {
              if (sheet) onImport(sheet, ctx);
            }}
          >
            <Upload className="mr-2 h-4 w-4" />
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
