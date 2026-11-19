import { PageHeader } from '@/components/shared/PageHeader';
import { IconButton } from '@/components/shared/IconButton';
import { Avatar } from '@/components/shared/Avatar';
import { Badge } from '@/components/ui/badge';
import { StandardTable, StdColumn } from '@/components/shared/StandardTable';
import { resolveFormat } from '@/lib/extractorFormat';
import { Eye, FolderOpen } from 'lucide-react';
import { useMemo, useState } from 'react';
import { useTerm } from '@/contexts/TermContext';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { useStaleData } from '@/lib/useStaleData';

// ── Shared row shape across all three tabs ────────────────────────────────────
type ClassifyRow = {
  id: string;
  student: string;
  school: string;
  format: string;
  fileName: string;
  blobName: string;
  fileUrl: string;
};

type TabKey = 'ready' | 'ai' | 'not';

const TABS: { key: TabKey; label: string }[] = [
  { key: 'ready', label: 'Ready to Process' },
  { key: 'ai', label: 'Needs AI Extractor' },
  { key: 'not', label: 'Not a Transcript' },
];

// ── Backend shapes (mirror the detector endpoints) ────────────────────────────
type DetectorFile = { id: string; name: string; file_name: string; blob_name: string };
type ExistingGroup = { semester: string; types: { type: string; count: number; files: DetectorFile[] }[] };
type NewGroup = { semester: string; folders: { folder_name: string; count: number; files: DetectorFile[] }[] };
type UnknownGroup = { semester: string; count: number; files: DetectorFile[] };

// ── Parsing helpers ───────────────────────────────────────────────────────────
function splitNameSchool(fileName: string): { student: string; school: string } {
  const base = fileName.replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  if (idx > 0 && idx < base.length - 1) {
    return { student: base.slice(0, idx).trim(), school: base.slice(idx + 1).trim() };
  }
  return { student: base, school: '' };
}

const fileUrlFor = (endpoint: string, blobName: string) =>
  `/api/transcript-detector/${endpoint}/file?blob_name=${encodeURIComponent(blobName)}`;

function toRow(f: DetectorFile, format: string, endpoint: string): ClassifyRow {
  const fileName = f.name || f.file_name || '';
  const { student, school } = splitNameSchool(fileName);
  // Format = what the classifier decided. Known extractors show their name
  // (LBUSD/Mayfair/St. Anthony); an unrecognized school in "Needs AI Extractor"
  // shows the school name obtained during classification (the type-to-be) rather
  // than a placeholder.
  return {
    id: f.id,
    student: student || f.name,
    school,
    format: resolveFormat(school, format),
    fileName,
    blobName: f.blob_name,
    fileUrl: fileUrlFor(endpoint, f.blob_name),
  };
}

export default function TranscriptClassify() {
  const { currentTerm, terms } = useTerm();
  const termName = terms.find((t) => t.id === currentTerm)?.term_name;

  const [activeTab, setActiveTab] = useState<TabKey>('ready');
  const [preview, setPreview] = useState<{ open: boolean; url?: string; title?: string }>({ open: false });

  // Fetch all three buckets so tab counts are always accurate.
  const { data: existingGroups } = useStaleData<ExistingGroup[]>(
    `classify-existing:${termName ?? ''}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(`/api/transcript-detector/existing?semester=${encodeURIComponent(termName)}`);
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
    [termName],
    { refreshIntervalMs: 20000 },
  );

  const { data: newGroups } = useStaleData<NewGroup[]>(
    `classify-new:${termName ?? ''}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(`/api/transcript-detector/new?semester=${encodeURIComponent(termName)}`);
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
    [termName],
    { refreshIntervalMs: 20000 },
  );

  const { data: unknownGroups } = useStaleData<UnknownGroup[]>(
    `classify-unknown:${termName ?? ''}`,
    async () => {
      if (!termName) return [];
      const res = await fetch(`/api/transcript-detector/unknown?semester=${encodeURIComponent(termName)}`);
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
    [termName],
    { refreshIntervalMs: 20000 },
  );

  const rowsByTab = useMemo(() => {
    const ready = (existingGroups ?? []).flatMap((g) =>
      g.types.flatMap((t) => t.files.map((f) => toRow(f, t.type, 'existing'))),
    );
    const ai = (newGroups ?? []).flatMap((g) =>
      g.folders.flatMap((fol) => fol.files.map((f) => toRow(f, fol.folder_name, 'new'))),
    );
    const not = (unknownGroups ?? []).flatMap((g) =>
      g.files.map((f) => ({ ...toRow(f, '', 'unknown'), format: '—' })),
    );
    return { ready, ai, not };
  }, [existingGroups, newGroups, unknownGroups]);

  const activeRows = rowsByTab[activeTab];
  const openFile = (row: ClassifyRow) => setPreview({ open: true, url: row.fileUrl, title: row.fileName });

  // Standardized column order shared with Extract: Student · School · Format · View.
  const columns: StdColumn<ClassifyRow>[] = useMemo(
    () => [
      {
        key: 'student',
        header: 'Student',
        value: (r) => r.student,
        cell: (r) => (
          <div className="flex items-center gap-3">
            <Avatar name={r.student} />
            <span className="min-w-0 flex-1 truncate font-medium text-slate-800" title={r.student}>
              {r.student}
            </span>
          </div>
        ),
      },
      {
        key: 'school',
        header: 'School',
        value: (r) => r.school,
        cell: (r) => (
          <span className="block truncate text-slate-600" title={r.school}>
            {r.school || '—'}
          </span>
        ),
      },
      {
        key: 'format',
        header: 'Format',
        value: (r) => r.format,
        filterable: true,
        cell: (r) =>
          r.format && r.format !== '—' ? (
            <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-200">
              {r.format}
            </span>
          ) : (
            <span className="text-slate-400">—</span>
          ),
      },
      {
        key: 'view',
        header: 'View',
        align: 'center',
        width: 80,
        sortable: false,
        cell: (r) => (
          <IconButton tooltip="View transcript" onClick={() => openFile(r)}>
            <Eye className="h-4 w-4" />
          </IconButton>
        ),
      },
    ],
    [],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title="Classify"
        icon={FolderOpen}
        iconColor="text-emerald-600"
        subtitle={
          termName
            ? `${termName} — review how each uploaded transcript was sorted`
            : 'Select a term from the top-right to view classified transcripts'
        }
      />

      {/* Tabs */}
      <div className="flex flex-wrap items-center gap-1 border-b border-slate-200">
        {TABS.map((tab) => {
          const active = tab.key === activeTab;
          return (
            <button
              key={tab.key}
              type="button"
              onClick={() => setActiveTab(tab.key)}
              className={`relative -mb-px flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition-colors ${
                active
                  ? 'border-b-2 border-blue-600 text-blue-700'
                  : 'border-b-2 border-transparent text-slate-500 hover:text-slate-800'
              }`}
            >
              {tab.label}
              <Badge
                variant="secondary"
                className={`tabular-nums ${active ? 'bg-blue-100 text-blue-700' : 'bg-slate-100 text-slate-500'}`}
              >
                {rowsByTab[tab.key].length}
              </Badge>
            </button>
          );
        })}
      </div>

      {!termName ? (
        <div className="rounded-2xl border bg-white p-12 text-center text-sm text-muted-foreground shadow-sm">
          Select a term to view classified transcripts.
        </div>
      ) : (
        <StandardTable
          columns={columns}
          data={activeRows}
          rowKey={(r) => r.id}
          flagId={(r) => r.blobName}
          search
          searchPlaceholder="Search students, schools, files…"
          storageKey={`classify:${activeTab}`}
          emptyMessage={`No transcripts in this bucket for ${termName}.`}
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
