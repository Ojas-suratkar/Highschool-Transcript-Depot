import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Eye, Trash2, ArrowLeft, Folder, BookOpen, Loader2 } from 'lucide-react';

import { useMemo, useState } from 'react';
import { useTerm } from '@/contexts/TermContext';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { useStaleData } from '@/lib/useStaleData';

type ExistingFile = {
  id: string;
  name: string;
  file_name: string;
  blob_name: string;
};

type ExistingTypeRow = {
  type: string;
  count: number;
  files: ExistingFile[];
};

type ExistingGroup = {
  semester: string;
  types: ExistingTypeRow[];
};

function flattenTypes(groups: ExistingGroup[]): ExistingTypeRow[] {
  return groups.flatMap((g) => g.types);
}

export default function DetectorExisting() {
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [refreshSeed, setRefreshSeed] = useState(0);
  const [selectedType, setSelectedType] = useState<ExistingTypeRow | null>(null);
  const [deletingFolder, setDeletingFolder] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ open: boolean; url?: string; title?: string }>({ open: false });

  const { data: rawGroups, refreshing } = useStaleData<ExistingGroup[]>(
    `detector-existing:${termName ?? ''}:${refreshSeed}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(
        `/api/transcript-detector/existing?semester=${encodeURIComponent(termName)}`
      );
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
    [termName, refreshSeed],
  );

  const allTypes = useMemo(() => flattenTypes(rawGroups ?? []), [rawGroups]);
  const totalFiles = allTypes.reduce((s, t) => s + t.count, 0);

  const openFile = (blobName: string, fileName: string) => {
    setPreview({
      open: true,
      url: `/api/transcript-detector/existing/file?blob_name=${encodeURIComponent(blobName)}`,
      title: fileName,
    });
  };

  const deleteFolder = async (transcriptType: string) => {
    if (!confirm(`Delete all files and remove "${transcriptType}"? This cannot be undone.`)) return;
    if (!termName) return;
    setDeletingFolder(transcriptType);
    try {
      const res = await fetch('/api/transcript-detector/existing/delete-folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ semester: termName, transcript_type: transcriptType }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.detail || 'Failed to delete type');
      }
      setRefreshSeed((n) => n + 1);
      setSelectedType(null);
    } catch (error) {
      alert(error instanceof Error ? error.message : 'Failed to delete type');
    } finally {
      setDeletingFolder(null);
    }
  };

  // ── Detail view ─────────────────────────────────────────────────────────────
  if (selectedType) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="Existing Transcript Type"
          subtitle={`${termName} — ${selectedType.type}`}
        />

        <div className="rounded-2xl border bg-white shadow-sm">
          {/* Card header */}
          <div className="flex items-start justify-between px-5 py-4 border-b">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                className="gap-1 px-2"
                onClick={() => setSelectedType(null)}
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              <div>
                <p className="font-semibold text-base leading-tight">{selectedType.type}</p>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {termName} • {selectedType.count} file(s)
                </p>
              </div>
            </div>
            <Button
              variant="ghost"
              size="icon"
              disabled={deletingFolder === selectedType.type}
              onClick={() => deleteFolder(selectedType.type)}
            >
              {deletingFolder === selectedType.type ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Trash2 className="h-4 w-4" />
              )}
            </Button>
          </div>

          {/* Files table */}
          {selectedType.files.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">
              No files stored for this transcript type.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b">
                  <th className="w-14 px-5 py-3 text-left font-semibold">S.No</th>
                  <th className="px-5 py-3 text-left font-semibold">Transcript File Name</th>
                  <th className="w-20 px-5 py-3 text-center font-semibold">View</th>
                </tr>
              </thead>
              <tbody>
                {selectedType.files.map((file, i) => (
                  <tr key={file.id} className="border-b last:border-0">
                    <td className="px-5 py-3 font-normal">{i + 1}</td>
                    <td className="px-5 py-3">{file.name}</td>
                    <td className="px-5 py-3 text-center">
                      <Button variant="ghost" size="icon" onClick={() => openFile(file.blob_name, file.name)}>
                        <Eye className="h-4 w-4" />
                      </Button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <PdfPreviewDialog
          open={preview.open}
          onOpenChange={(open) => setPreview((p) => ({ ...p, open }))}
          title={preview.title}
          url={preview.url}
        />
      </div>
    );
  }

  // ── Root view ────────────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      <PageHeader
        title="Existing Transcript Type"
        subtitle={
          refreshing && allTypes.length === 0
            ? 'Loading…'
            : termName
              ? `${termName} — existing transcript folders (total files: ${totalFiles})`
              : 'Select a term from the top-right to view types'
        }
      />

      {!termName ? null : refreshing && allTypes.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Loading existing transcript types…
        </div>
      ) : allTypes.length === 0 ? (
        <div className="rounded-2xl border bg-white p-12 text-center shadow-sm">
          <BookOpen className="mx-auto mb-3 h-8 w-8 text-muted-foreground/30" />
          <p className="text-sm font-medium text-muted-foreground">
            No existing transcript types for {termName}
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border bg-white shadow-sm">
          {/* Section header */}
          <div className="px-5 py-4 border-b">
            <p className="font-semibold text-base">{termName}</p>
          </div>

          {/* Folder rows */}
          {allTypes.map((typeRow, idx) => (
            <div
              key={typeRow.type}
              className={`flex cursor-pointer items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors ${idx > 0 ? 'border-t' : ''}`}
              onClick={() => setSelectedType(typeRow)}
            >
              <Folder className="h-5 w-5 shrink-0 text-gray-500" />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm leading-snug">{typeRow.type}</p>
                <p className="text-xs text-muted-foreground">{typeRow.count} file(s)</p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                className="shrink-0"
                disabled={deletingFolder === typeRow.type}
                onClick={(e) => {
                  e.stopPropagation();
                  deleteFolder(typeRow.type);
                }}
              >
                {deletingFolder === typeRow.type ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <Trash2 className="h-4 w-4" />
                )}
              </Button>
            </div>
          ))}
        </div>
      )}

      <PdfPreviewDialog
        open={preview.open}
        onOpenChange={(open) => setPreview((p) => ({ ...p, open }))}
        title={preview.title}
        url={preview.url}
      />
    </div>
  );
}
