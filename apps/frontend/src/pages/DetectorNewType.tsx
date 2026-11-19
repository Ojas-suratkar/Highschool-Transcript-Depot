import { PageHeader } from '@/components/shared/PageHeader';
import { Button } from '@/components/ui/button';
import { Eye, ArrowLeft, Folder, Sparkles } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTerm } from '@/contexts/TermContext';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { useStaleData } from '@/lib/useStaleData';

type NewFile = {
  id: string;
  name: string;
  file_name: string;
  blob_name: string;
};

type NewFolderRow = {
  folder_name: string;
  count: number;
  files: NewFile[];
};

type NewGroup = {
  semester: string;
  folders: NewFolderRow[];
};

function flattenFolders(groups: NewGroup[]): NewFolderRow[] {
  return groups.flatMap((g) => g.folders);
}

export default function DetectorNewType() {
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [refreshSeed] = useState(0);
  const [selectedFolder, setSelectedFolder] = useState<NewFolderRow | null>(null);
  const [preview, setPreview] = useState<{ open: boolean; url?: string; title?: string }>({ open: false });

  const { data: rawGroups, refreshing } = useStaleData<NewGroup[]>(
    `detector-new-type:${termName ?? ''}:${refreshSeed}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(
        `/api/transcript-detector/new?semester=${encodeURIComponent(termName)}`
      );
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
    [termName, refreshSeed],
  );

  const allFolders = useMemo(() => flattenFolders(rawGroups ?? []), [rawGroups]);
  const totalFiles = allFolders.reduce((s, f) => s + f.count, 0);

  const openFile = (blobName: string, fileName: string) => {
    setPreview({
      open: true,
      url: `/api/transcript-detector/new/file?blob_name=${encodeURIComponent(blobName)}`,
      title: fileName,
    });
  };

  // ── Detail view ─────────────────────────────────────────────────────────────
  if (selectedFolder) {
    return (
      <div className="space-y-6">
        <PageHeader
          title="New Transcript Type"
          subtitle={`${termName} — ${selectedFolder.folder_name}`}
        />

        <div className="rounded-2xl border bg-white shadow-sm">
          {/* Card header */}
          <div className="flex items-start justify-between px-5 py-4 border-b">
            <div className="flex items-center gap-4">
              <Button
                variant="ghost"
                size="sm"
                className="gap-1 px-2"
                onClick={() => setSelectedFolder(null)}
              >
                <ArrowLeft className="h-4 w-4" />
                Back
              </Button>
              <div>
                <p className="font-semibold text-base leading-tight">{selectedFolder.folder_name}</p>
                <p className="text-sm text-muted-foreground mt-0.5">
                  {termName} • {selectedFolder.count} file(s)
                </p>
              </div>
            </div>
          </div>

          {/* Files table */}
          {selectedFolder.files.length === 0 ? (
            <p className="px-5 py-8 text-center text-sm text-muted-foreground">
              No files in this folder.
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
                {selectedFolder.files.map((file, i) => (
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
        title="New Transcript Type"
        subtitle={
          refreshing && allFolders.length === 0
            ? 'Loading…'
            : termName
              ? `${termName} — new transcript folders (total files: ${totalFiles})`
              : 'Select a term from the top-right to view files'
        }
      />

      {!termName ? null : refreshing && allFolders.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">
          Loading new transcript types…
        </div>
      ) : allFolders.length === 0 ? (
        <div className="rounded-2xl border bg-white p-12 text-center shadow-sm">
          <Sparkles className="mx-auto mb-3 h-8 w-8 text-muted-foreground/30" />
          <p className="text-sm font-medium text-muted-foreground">
            No new transcript types for {termName}
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border bg-white shadow-sm">
          {/* Section header */}
          <div className="px-5 py-4 border-b">
            <p className="font-semibold text-base">{termName}</p>
          </div>

          {/* Folder rows */}
          {allFolders.map((folder, idx) => (
            <div
              key={folder.folder_name}
              className={`flex cursor-pointer items-center gap-4 px-5 py-4 hover:bg-gray-50 transition-colors ${idx > 0 ? 'border-t' : ''}`}
              onClick={() => setSelectedFolder(folder)}
            >
              <Folder className="h-5 w-5 shrink-0 text-gray-500" />
              <div className="flex-1 min-w-0">
                <p className="font-medium text-sm leading-snug">{folder.folder_name}</p>
                <p className="text-xs text-muted-foreground">{folder.count} file(s)</p>
              </div>
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
