import { PageHeader } from '@/components/shared/PageHeader';
import { DataTable, ColumnDef } from '@/components/shared/DataTable';
import { Button } from '@/components/ui/button';
import { Eye } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTerm } from '@/contexts/TermContext';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { useStaleData } from '@/lib/useStaleData';

type IncomingFile = {
  id: string;
  serial: number;
  name: string;
  blob_name: string;
};

type IncomingGroup = {
  semester: string;
  count: number;
  files: { id: string; name: string; file_name: string; blob_name: string }[];
};

function mapGroupsToRows(groups: IncomingGroup[]): IncomingFile[] {
  return groups
    .flatMap((g) => g.files)
    .map((f, i) => ({ id: f.id, serial: i + 1, name: f.name, blob_name: f.blob_name }));
}

export default function DetectorIncoming() {
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [preview, setPreview] = useState<{ open: boolean; url?: string; title?: string }>({ open: false });

  const { data: rawGroups, refreshing } = useStaleData<IncomingGroup[]>(
    `detector-incoming:${termName ?? ''}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(
        `/api/transcript-detector/incoming?semester=${encodeURIComponent(termName)}`
      );
      if (!res.ok) throw new Error('Failed to load');
      return res.json() as Promise<IncomingGroup[]>;
    },
    [termName],
  );

  const rows = useMemo(() => {
    if (!rawGroups) return [];
    return mapGroupsToRows(rawGroups);
  }, [rawGroups]);

  const openFile = (blobName: string, fileName: string) => {
    setPreview({
      open: true,
      url: `/api/transcript-detector/incoming/file?blob_name=${encodeURIComponent(blobName)}`,
      title: fileName,
    });
  };

  const columns: ColumnDef<IncomingFile>[] = [
    { header: 'S.No', accessor: 'serial', className: 'font-normal' },
    { header: 'File Name', accessor: 'name' },
    {
      header: 'Actions',
      accessor: (r) => (r as unknown) as React.ReactNode,
      cell: (_, row: IncomingFile) => (
        <Button variant="ghost" onClick={() => openFile(row.blob_name, row.name)}>
          <Eye className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <div className="space-y-6">
      <PageHeader
        title="Incoming Transcripts"
        subtitle={
          refreshing
            ? 'Loading…'
            : termName
              ? `${termName} · ${rows.length} file${rows.length !== 1 ? 's' : ''} awaiting processing`
              : 'Select a term from the top-right to view files'
        }
      />

      {!termName ? null : refreshing && rows.length === 0 ? (
        <div className="rounded-md border p-4 text-sm text-muted-foreground">Loading incoming transcripts…</div>
      ) : (
        <DataTable
          columns={columns}
          data={rows}
          keyExtractor={(r) => r.id}
          emptyMessage="No incoming transcripts for this term."
        />
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
