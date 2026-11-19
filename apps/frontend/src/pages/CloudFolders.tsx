import { useEffect, useMemo, useState } from 'react';
import { FileText, Loader2, Upload, FolderUp, Folder, Trash2, UploadCloud, ArrowUp, ArrowDown, ChevronsUpDown, Eye } from 'lucide-react';
import { useRef } from 'react';
import { Button } from '@/components/ui/button';
import { Checkbox } from '@/components/ui/checkbox';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { IconButton } from '@/components/shared/IconButton';
import PdfPreviewDialog from '@/components/dialogs/PdfPreviewDialog';
import { emitNotification } from '@/lib/notify';
import { useTerm } from '@/contexts/TermContext';
import { useExtractionJobs } from '@/contexts/ExtractionJobsContext';
import { useUploadJobs } from '@/contexts/UploadJobsContext';
import { toast } from 'sonner';
import { formatDateTimePST } from '@/lib/utils';

import {
  listCloudFolders,
  createCloudFolder,
  updateCloudFolder,
  purgeCloudFolder,
  listCloudFolderFiles,
  deleteFileFromFolder,
  deleteFolderPath,
  CloudFolderDTO,
  CloudFolderFileDTO,
} from '@/lib/api/cloudFolders';

import { useAuth } from "../contexts/AuthContext.tsx";

interface CloudFolder {
  serial?: number;
  id: string;
  label: string;
  // link: string;       // UI name
  semester: string;   // year_intake
  updated_at: string;      // created_at formatted
  lastPolled: string; // derived
}

interface CloudFolderFile {
  name: string;
  path: string;
  kind: string;
  size_bytes?: number | null;
  updated_at?: string | null;
}

// Detected school parsed from the file name (e.g. "Aguilar_Manuel_CABRILLO.pdf"
// → "Cabrillo"). The extractor/format is a separate concept shown later.
function schoolFromFileName(fileName?: string | null): string {
  const base = String(fileName ?? '').replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  const raw = idx > 0 && idx < base.length - 1 ? base.slice(idx + 1).trim() : '';
  if (!raw) return '';
  const up = raw.toUpperCase();
  if (up === 'LBUSD' || up === 'CAMS') return up;
  return raw.replace(/\b\w/g, (c) => c.toUpperCase());
}

function dtoToRow(dto: CloudFolderDTO): CloudFolder {
  return {
    id: dto.id,
    label: dto.label,
    // link: dto.url,
    semester: dto.year_intake ? dto.year_intake.charAt(0).toUpperCase() + dto.year_intake.slice(1) : dto.year_intake,
    updated_at: formatDateTimePST(dto.updated_at) || '',
    lastPolled: dto.last_polled ? formatDateTimePST(dto.last_polled) : 'Never',
  };
}

const addSerial = (rows: CloudFolder[]) => rows.map((r, idx) => ({ ...r, serial: idx + 1 }));

type SortKey = 'name' | 'school' | 'uploaded';
function SortableTh({
  label,
  col,
  sort,
  onSort,
  className,
}: {
  label: string;
  col: SortKey;
  sort: { key: SortKey; dir: 'asc' | 'desc' };
  onSort: (k: SortKey) => void;
  className?: string;
}) {
  const active = sort.key === col;
  return (
    <th className={className}>
      <button
        type="button"
        onClick={() => onSort(col)}
        className="group inline-flex items-center gap-1.5 hover:text-[var(--blue)]"
      >
        {label}
        {active ? (
          sort.dir === 'asc' ? (
            <ArrowUp className="h-3.5 w-3.5 text-[var(--blue)]" />
          ) : (
            <ArrowDown className="h-3.5 w-3.5 text-[var(--blue)]" />
          )
        ) : (
          <ChevronsUpDown className="h-3.5 w-3.5 text-[var(--ink-4)] group-hover:text-[var(--ink-3)]" />
        )}
      </button>
    </th>
  );
}

// const { terms, currentTerm } = useTerm();

// // store NAME in selectedTermId for this page
// const [selectedTermId, setSelectedTermId] = useState<string>("");


export default function CloudFolders() {
  console.log("CloudFolders rendered");

  const { user } = useAuth();
  const { terms, currentTerm, refreshTerms, removeTerm } = useTerm();
  const [error, setError] = useState<string | null>(null);
  const [folders, setFolders] = useState<CloudFolder[]>([]);
  const [loading, setLoading] = useState(false);
  const [selectedTermId, setSelectedTermId] = useState<string>('');

  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [editingFolder] = useState<CloudFolder | null>(null);
  const [viewingFolder, setViewingFolder] = useState<CloudFolder | null>(null);
  const [folderFiles, setFolderFiles] = useState<CloudFolderFile[]>([]);
  const [loadingFolderFiles, setLoadingFolderFiles] = useState(false);
  const [currentPath, setCurrentPath] = useState<string>('');
  // Bulk selection inside the Files dialog (keyed by path; cleared whenever the
  // listing changes so a stale selection can never be deleted).
  const [selectedPaths, setSelectedPaths] = useState<Set<string>>(new Set());
  const [isBulkDeleting, setIsBulkDeleting] = useState(false);
  const [formData, setFormData] = useState({
    label: '',
    // link: '',
    semester: '',
  });

  const [folderToPurge, setFolderToPurge] = useState<CloudFolder | null>(null);
  const [isPurging, setIsPurging] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const [uploadingToFolderId, setUploadingToFolderId] = useState<string | null>(null);
  const { startJob } = useExtractionJobs();
  const [preview, setPreview] = useState<{ open: boolean; url?: string; title?: string }>({ open: false });
  const { startUpload, isFolderUploading } = useUploadJobs();

  const handleUploadToFolder = async (folderId: string) => {
    if (!fileInputRef.current) return;
    setUploadingToFolderId(folderId);
    fileInputRef.current.value = '';
    fileInputRef.current.click();
  };

  const handleUploadFolderToFolder = async (folderId: string) => {
    if (!folderInputRef.current) return;
    setUploadingToFolderId(folderId);
    folderInputRef.current.value = '';
    folderInputRef.current.click();
  };

  const onFolderFilesSelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !uploadingToFolderId) return;
    try {
      const folder = folders.find((item) => item.id === uploadingToFolderId);
      if (!folder) throw new Error('Folder not found');

      await startUpload({
        folderId: uploadingToFolderId,
        folderLabel: folder.label,
        yearIntake: folder.semester,
        files: Array.from(files),
        buildFormData: (file) => {
          const form = new FormData();
          form.append('file', file);
          return form;
        },
        onComplete: async () => {
          await refresh();
          // Always reload the folder we just uploaded into so every new file
          // shows immediately (independent of the notifications UI).
          setViewingFolder(folder);
          await loadFolderListing(folder, '');
          emitNotification({
            kind: 'success',
            title: 'Upload complete',
            message: `Transcripts uploaded to “${folder.label}” · ${folder.semester}`,
          });
          emitNotification({
            kind: 'info',
            title: 'Classification started',
            message: `Sorting the uploaded transcripts for ${folder.semester}…`,
          });
          // Extraction now runs automatically once transcripts are classified —
          // kick off the folder job (it picks up the just-classified files and
          // extracts the known formats).
          try {
            await startJob({ id: folder.id, label: folder.label });
          } catch {
            /* a job may already be running for this folder */
          }
        },
      });
    } catch (err: any) {
      toast.error(err?.message || 'Upload failed');
    } finally {
      setUploadingToFolderId(null);
      e.target.value = '';
    }
  };

  const onFolderDirectorySelected = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0 || !uploadingToFolderId) return;
    try {
      const folder = folders.find((item) => item.id === uploadingToFolderId);
      if (!folder) throw new Error('Folder not found');

      // Only keep PDFs; derive course from relative path (excluding filename)
      const fileArray = Array.from(files).filter(f => f.type === 'application/pdf' || f.name.toLowerCase().endsWith('.pdf'));
      if (fileArray.length === 0) throw new Error('No PDF files in selected folder');

      await startUpload({
        folderId: uploadingToFolderId,
        folderLabel: folder.label,
        yearIntake: folder.semester,
        files: fileArray,
        buildFormData: (file) => {
          const form = new FormData();
          form.append('file', file);
          const relPath = (file as any).webkitRelativePath as string | undefined;
          let course: string | undefined;
          if (relPath) {
            const parts = relPath.split('/').filter(Boolean);
            // drop the top-level selected folder name to avoid duplicating it in the destination path
            course = parts.length > 1 ? parts.slice(1, -1).join('/') : undefined;
          }
          if (course) form.append('course', course);
          return form;
        },
        onComplete: async () => {
          await refresh();
          // Always reload the folder we just uploaded into so every new file
          // shows immediately (independent of the notifications UI).
          setViewingFolder(folder);
          await loadFolderListing(folder, '');
          emitNotification({
            kind: 'success',
            title: 'Upload complete',
            message: `Transcripts uploaded to “${folder.label}” · ${folder.semester}`,
          });
          emitNotification({
            kind: 'info',
            title: 'Classification started',
            message: `Sorting the uploaded transcripts for ${folder.semester}…`,
          });
          try {
            await startJob({ id: folder.id, label: folder.label });
          } catch {
            /* a job may already be running for this folder */
          }
        },
      });
    } catch (err: any) {
      toast.error(err?.message || 'Folder upload failed');
    } finally {
      setUploadingToFolderId(null);
      e.target.value = '';
    }
  };

  const loadFolderListing = async (folder: CloudFolder, path: string) => {
    setLoadingFolderFiles(true);
    setSelectedPaths(new Set());
    try {
      const files = await listCloudFolderFiles(folder.id, path || undefined);
      setFolderFiles(files.map((file: CloudFolderFileDTO) => ({
        name: file.name,
        path: file.path,
        kind: file.kind,
        size_bytes: file.size_bytes,
        updated_at: file.updated_at,
      })));
      setCurrentPath(path);
    } catch (e: any) {
      setFolderFiles([]);
      toast.error(e?.message ?? 'Failed to load cloud files');
    } finally {
      setLoadingFolderFiles(false);
    }
  };

  const handleEnterFolder = async (node: CloudFolderFile) => {
    if (!viewingFolder) return;
    const nextPath = currentPath ? `${currentPath}/${node.name}` : node.name;
    await loadFolderListing(viewingFolder, nextPath);
  };

  // Rows actually rendered: folders always, files de-duplicated by name. Shared
  // by the table, the header "select all" and the bulk delete so selection can
  // never include a row the user cannot see.
  const [sort, setSort] = useState<{ key: 'name' | 'school' | 'uploaded'; dir: 'asc' | 'desc' }>({
    key: 'uploaded',
    dir: 'desc',
  });

  // Show every distinct file (dedupe by full path, not name — same-named files in
  // different folders must all appear), then apply the active sort. Folders float
  // to the top so drill-in stays easy.
  const visibleFiles = useMemo(() => {
    const seen = new Set<string>();
    const deduped = folderFiles.filter((f) => {
      if (seen.has(f.path)) return false;
      seen.add(f.path);
      return true;
    });
    const dir = sort.dir === 'asc' ? 1 : -1;
    const val = (f: CloudFolderFile) => {
      if (sort.key === 'name') return f.name.toLowerCase();
      if (sort.key === 'school') return schoolFromFileName(f.name).toLowerCase();
      return f.updated_at ? new Date(f.updated_at).getTime() : 0;
    };
    return [...deduped].sort((a, b) => {
      if (a.kind !== b.kind) return a.kind === 'folder' ? -1 : 1; // folders first
      const av = val(a);
      const bv = val(b);
      if (typeof av === 'number' && typeof bv === 'number') return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [folderFiles, sort]);

  const toggleSort = (key: 'name' | 'school' | 'uploaded') =>
    setSort((prev) => (prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }));

  const allVisibleSelected =
    visibleFiles.length > 0 && visibleFiles.every((f) => selectedPaths.has(f.path));
  const someVisibleSelected = selectedPaths.size > 0 && !allVisibleSelected;

  const toggleSelectAll = () => {
    setSelectedPaths(allVisibleSelected ? new Set() : new Set(visibleFiles.map((f) => f.path)));
  };

  const toggleSelectOne = (path: string) => {
    setSelectedPaths((prev) => {
      const next = new Set(prev);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  // Deleting one item per request (reusing the single-item endpoints), a few at
  // a time so a large selection doesn't fire hundreds of parallel requests.
  const handleBulkDelete = async () => {
    if (!viewingFolder || selectedPaths.size === 0) return;
    const targets = visibleFiles.filter((f) => selectedPaths.has(f.path));
    const fileCount = targets.filter((t) => t.kind === 'file').length;
    const folderCount = targets.length - fileCount;
    const what = [
      fileCount ? `${fileCount} file${fileCount === 1 ? '' : 's'}` : '',
      folderCount ? `${folderCount} folder${folderCount === 1 ? '' : 's'} and all their contents` : '',
    ].filter(Boolean).join(' and ');
    if (!window.confirm(`Delete ${what}? This cannot be undone.`)) return;

    setIsBulkDeleting(true);
    const queue = [...targets];
    const failed: string[] = [];
    let deleted = 0;
    const worker = async () => {
      while (queue.length > 0) {
        const item = queue.shift();
        if (!item) break;
        try {
          if (item.kind === 'folder') {
            const targetPath = currentPath ? `${currentPath}/${item.name}` : item.name;
            await deleteFolderPath(viewingFolder.id, targetPath);
          } else {
            await deleteFileFromFolder(viewingFolder.id, item.path);
          }
          deleted += 1;
        } catch {
          failed.push(item.name);
        }
      }
    };
    try {
      await Promise.all(
        Array.from({ length: Math.min(5, targets.length) }, () => worker())
      );
    } finally {
      setIsBulkDeleting(false);
      await loadFolderListing(viewingFolder, currentPath);
      await refresh();
    }

    if (failed.length === 0) {
      toast.success(`Deleted ${deleted} item${deleted === 1 ? '' : 's'}`);
      emitNotification({
        kind: 'success',
        title: 'Files deleted',
        message: `${deleted} item${deleted === 1 ? '' : 's'} removed from “${viewingFolder.label}”`,
      });
    } else {
      toast.error(
        `Deleted ${deleted}, failed ${failed.length}: ${failed.slice(0, 3).join(', ')}${failed.length > 3 ? '…' : ''}`
      );
    }
  };

  const handleBreadcrumbClick = async (index: number) => {
    if (!viewingFolder) return;
    if (index === -1) {
      await loadFolderListing(viewingFolder, '');
      return;
    }
    const parts = currentPath.split('/').filter(Boolean).slice(0, index + 1);
    const target = parts.join('/');
    await loadFolderListing(viewingFolder, target);
  };

async function refresh() {
    if (!user?.institution?.id && !user?.institution_id) return;
    const activeTerm = selectedTermId || terms.find(t => t.id === currentTerm)?.term_name;
    if (!activeTerm) return;
    setLoading(true);
    try {
      const data = await listCloudFolders(activeTerm);
      setFolders(addSerial(data.map(dtoToRow)));
    } catch (e: any) {
      toast.error(e?.message ?? 'Failed to load cloud folders');
    } finally {
      setLoading(false);
    }
  }
// Sync with top-right term selector only
useEffect(() => {
  if (terms.length === 0) {
    setSelectedTermId('');
    return;
  }
  if (!currentTerm) return;
  const active = terms.find(t => t.id === currentTerm);
  if (!active) return;
  setSelectedTermId(active.term_name);
}, [currentTerm, terms]);

useEffect(() => {
  if (!user) return;
  refresh();
}, [selectedTermId, user]);


  const handleSaveFolder = async () => {
    setError(null);

    if (!formData.label.trim()) return setError("Label is required");
    if (!formData.semester){
      setError("Term is required");
      return toast.error('Please select a term');
    }

    try {

      if (editingFolder) {
        const updated = await updateCloudFolder(editingFolder.id, {
          label: formData.label.trim(),
          // url: formData.link.trim(),
          year_intake: formData.semester,
        });

        const updatedRow = dtoToRow(updated);
        setFolders(prev => addSerial(prev.map(f => (f.id === updatedRow.id ? updatedRow : f))));
        toast.success('Folder updated successfully');
      } else {
        const created = await createCloudFolder({
          label: formData.label.trim(),
          // url: formData.link.trim(),
          year_intake: formData.semester,
          // server will use current_user to set institution/user; do not override

        });

        const createdRow = dtoToRow(created);
        setFolders(prev => addSerial([createdRow, ...prev]));
        toast.success('Folder created successfully');
        await refresh();
      }

      setIsDialogOpen(false);
    } catch (e: any) {
      toast.error(e?.message ?? 'Failed to save folder');
    }
  };


  const handleConfirmPurge = async () => {
    if (!folderToPurge) return;
    setIsPurging(true);
    try {
      const result = await purgeCloudFolder(folderToPurge.id);
      setFolders(prev => addSerial(prev.filter(f => f.id !== folderToPurge.id)));
      emitNotification({
        kind: 'warn',
        title: 'Term data deleted',
        message: `Removed ${result.deleted_records} record(s) and ${result.deleted_objects} file(s) for ${folderToPurge.semester}`,
        term: folderToPurge.semester,
      });
      toast.success(
        `Deleted ${result.deleted_records} records and ${result.deleted_objects} GCS files for ${folderToPurge.semester}`
      );
      setFolderToPurge(null);
      // Also remove academic term from selector
      const matchedTerm = terms.find(t => t.term_name === folderToPurge.semester);
      if (matchedTerm) {
        await removeTerm(matchedTerm.id);
      } else {
        await refreshTerms();
      }
    } catch (e: any) {
      toast.error(e?.message ?? 'Failed to delete term data');
    } finally {
      setIsPurging(false);
    }
  };

  const activeFolder = viewingFolder;

  const openFolderInline = (folder: CloudFolder) => {
    setViewingFolder(folder);
    loadFolderListing(folder, '');
  };

  // Auto-select the first folder for the term and load its files inline.
  useEffect(() => {
    if (folders.length === 0) {
      setViewingFolder(null);
      setFolderFiles([]);
      return;
    }
    if (!viewingFolder || !folders.some((f) => f.id === viewingFolder.id)) {
      openFolderInline(folders[0]);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [folders]);

  const activeTermName = selectedTermId || terms.find((t) => t.id === currentTerm)?.term_name || '';

  const openCreateFolder = () => {
    setFormData({ label: activeTermName ? `${activeTermName} Transcripts` : '', semester: activeTermName });
    setIsDialogOpen(true);
  };
  const onChooseFiles = () => (activeFolder ? handleUploadToFolder(activeFolder.id) : openCreateFolder());
  const onConnectFolder = () => (activeFolder ? handleUploadFolderToFolder(activeFolder.id) : openCreateFolder());

  const fileCount = visibleFiles.filter((f) => f.kind === 'file').length;

  return (
    <div className="space-y-5">
      {/* hidden inputs */}
      <input ref={fileInputRef} type="file" accept=".pdf" multiple hidden onChange={onFolderFilesSelected} />
      <input
        ref={folderInputRef}
        type="file"
        accept=".pdf"
        multiple
        hidden
        {...({ webkitdirectory: 'true' } as Record<string, string>)}
        onChange={onFolderDirectorySelected}
      />

      {/* Header: breadcrumb + title + Continue to Review */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            className="grid h-10 w-10 shrink-0 place-items-center rounded-[10px]"
            style={{ background: 'var(--green-t)', color: '#059669' }}
          >
            <FileText className="h-5 w-5" />
          </span>
          <div>
            <h1 className="text-[19px] font-bold tracking-tight text-[var(--ink)]">Upload Transcripts</h1>
            <p className="mt-0.5 text-[13px] text-[var(--ink-2)]">
              Upload transcript files or an entire folder. Classification starts automatically.
            </p>
          </div>
        </div>
      </div>

      {/* Drop zone */}
      <div className="rounded-2xl border border-dashed border-[var(--dline)] bg-[var(--panel-2)] px-6 py-10 text-center">
        <div className="mx-auto mb-3 grid h-12 w-12 place-items-center rounded-xl bg-[var(--blue-t)] text-[#2563eb]">
          <UploadCloud className="h-6 w-6" />
        </div>
        <div className="text-[15px] font-bold text-[var(--ink)]">Drop transcript PDFs here</div>
        <p className="mt-1 text-[13px] text-[var(--ink-3)]">or upload a single file or an entire folder</p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          <Button
            onClick={onChooseFiles}
            disabled={activeFolder ? isFolderUploading(activeFolder.id) : false}
            className="gap-2"
          >
            {activeFolder && isFolderUploading(activeFolder.id) ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            Upload a file
          </Button>
          <Button variant="outline" onClick={onConnectFolder} className="gap-2">
            <FolderUp className="h-4 w-4" /> Upload a folder
          </Button>
        </div>
      </div>

      {/* Folder switcher (only when more than one) */}
      {folders.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {folders.map((f) => {
            const on = activeFolder?.id === f.id;
            return (
              <button
                key={f.id}
                type="button"
                onClick={() => openFolderInline(f)}
                className={`rounded-lg border px-3 py-1.5 text-[12.5px] font-medium transition-colors ${
                  on
                    ? 'border-[var(--blue)] bg-[var(--blue-t)] text-[var(--blue)]'
                    : 'border-[var(--dline)] text-[var(--ink-2)] hover:bg-[var(--panel-2)]'
                }`}
              >
                {f.label}
              </button>
            );
          })}
        </div>
      )}

      {/* Active folder — files inline */}
      {activeFolder ? (
        <div className="overflow-hidden rounded-2xl border border-[var(--dline)] bg-[var(--panel)] shadow-[var(--sh-sm)]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[var(--line-2)] px-4 py-3">
            <div className="flex items-center gap-2.5">
              <Folder className="h-5 w-5 text-amber-500" />
              <span className="font-semibold text-[var(--ink)]">{activeFolder.label}</span>
              <span className="rounded-full bg-[var(--panel-3)] px-2 py-0.5 text-[11px] font-medium text-[var(--ink-2)]">
                {fileCount} file{fileCount === 1 ? '' : 's'}
              </span>
            </div>
            <div className="flex items-center gap-2">
              {selectedPaths.size > 0 && (
                <Button variant="destructive" size="sm" className="h-8 gap-1.5" disabled={isBulkDeleting} onClick={handleBulkDelete}>
                  {isBulkDeleting ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                  Delete selected
                </Button>
              )}
              <IconButton
                tooltip="Delete everything for this term"
                className="h-8 w-8 text-red-600 hover:bg-red-50 hover:text-red-700"
                onClick={() => setFolderToPurge(activeFolder)}
              >
                <Trash2 className="h-4 w-4" />
              </IconButton>
            </div>
          </div>

          {currentPath && (
            <div className="flex flex-wrap items-center gap-2 border-b border-[var(--line-2)] bg-[var(--panel-2)] px-4 py-2 text-[12px] text-[var(--ink-3)]">
              <button className="hover:text-[var(--blue)]" onClick={() => handleBreadcrumbClick(-1)}>
                Root
              </button>
              {currentPath.split('/').filter(Boolean).map((part, idx) => (
                <span key={idx} className="flex items-center gap-2">
                  <span>/</span>
                  <button className="hover:text-[var(--blue)]" onClick={() => handleBreadcrumbClick(idx)}>
                    {part}
                  </button>
                </span>
              ))}
            </div>
          )}

          {loadingFolderFiles ? (
            <div className="px-4 py-10 text-center text-sm text-[var(--ink-3)]">Loading files…</div>
          ) : visibleFiles.length === 0 ? (
            <div className="px-4 py-12 text-center text-sm text-[var(--ink-3)]">
              No files uploaded yet. Drop PDFs above to get started.
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="border-b border-[var(--dline)] bg-[var(--panel-2)] text-left text-[11px] font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                  <tr>
                    <th className="w-[44px] px-4 py-3">
                      <Checkbox
                        checked={allVisibleSelected ? true : someVisibleSelected ? 'indeterminate' : false}
                        onCheckedChange={toggleSelectAll}
                        aria-label="Select all"
                      />
                    </th>
                    <SortableTh label="File Name" col="name" sort={sort} onSort={toggleSort} className="px-2 py-3" />
                    <SortableTh label="Detected School" col="school" sort={sort} onSort={toggleSort} className="px-4 py-3" />
                    <SortableTh label="Uploaded" col="uploaded" sort={sort} onSort={toggleSort} className="px-4 py-3" />
                    <th className="w-[110px] px-4 py-3 text-center">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleFiles.map((file) => (
                    <tr
                      key={file.path}
                      className={`border-b border-[var(--line-2)] last:border-0 hover:bg-[var(--panel-2)] ${
                        file.kind === 'folder' ? 'cursor-pointer' : ''
                      }`}
                      onClick={() => (file.kind === 'folder' ? handleEnterFolder(file) : undefined)}
                    >
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <Checkbox
                          checked={selectedPaths.has(file.path)}
                          onCheckedChange={() => toggleSelectOne(file.path)}
                          aria-label={`Select ${file.name}`}
                        />
                      </td>
                      <td className="px-2 py-3">
                        <div className="flex items-center gap-3">
                          {file.kind === 'folder' ? (
                            <Folder className="h-4 w-4 shrink-0 text-amber-500" />
                          ) : (
                            <FileText className="h-4 w-4 shrink-0 text-sky-600" />
                          )}
                          <span className="truncate font-mono text-[12.5px] text-[var(--ink)]" title={file.name}>
                            {file.name}
                          </span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-[var(--ink-2)]">
                        {file.kind === 'folder' ? '—' : schoolFromFileName(file.name) || '—'}
                      </td>
                      <td className="px-4 py-3 text-[var(--ink-2)]">
                        {file.updated_at ? formatDateTimePST(file.updated_at) : '—'}
                      </td>
                      <td className="px-4 py-3" onClick={(e) => e.stopPropagation()}>
                        <div className="flex items-center justify-center gap-1">
                          {file.kind !== 'folder' && (
                            <IconButton
                              tooltip="View file"
                              className="h-8 w-8"
                              onClick={(e) => {
                                e.stopPropagation();
                                if (!viewingFolder) return;
                                setPreview({
                                  open: true,
                                  title: file.name,
                                  url: `/api/cloud-folder-locations/${viewingFolder.id}/file?name=${encodeURIComponent(file.name)}`,
                                });
                              }}
                            >
                              <Eye className="h-4 w-4" />
                            </IconButton>
                          )}
                          <IconButton
                            tooltip={file.kind === 'folder' ? 'Delete folder and all contents' : 'Delete file'}
                            className="h-8 w-8 text-destructive"
                            onClick={async (e) => {
                              e.stopPropagation();
                              if (!viewingFolder) return;
                              if (file.kind === 'folder') {
                                const targetPath = currentPath ? `${currentPath}/${file.name}` : file.name;
                                if (!window.confirm(`Delete folder "${file.name}" and all contents?`)) return;
                                try {
                                  await deleteFolderPath(viewingFolder.id, targetPath);
                                  await loadFolderListing(viewingFolder, currentPath);
                                  await refresh();
                                  toast.success('Folder deleted');
                                } catch (err: any) {
                                  toast.error(err?.message || 'Failed to delete folder');
                                }
                              } else {
                                try {
                                  await deleteFileFromFolder(viewingFolder.id, file.path);
                                  await loadFolderListing(viewingFolder, currentPath);
                                  await refresh();
                                  toast.success('File deleted');
                                } catch (err: any) {
                                  toast.error(err?.message || 'Failed to delete file');
                                }
                              }
                            }}
                          >
                            <Trash2 className="h-4 w-4" />
                          </IconButton>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ) : (
        <div className="rounded-2xl border border-[var(--dline)] bg-[var(--panel)] p-10 text-center text-sm text-[var(--ink-3)] shadow-[var(--sh-sm)]">
          {loading ? 'Loading…' : 'No folder yet for this term. Use “Choose files” above to create one and upload.'}
        </div>
      )}

      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{editingFolder ? 'Edit Folder' : 'Create Folder'}</DialogTitle>
            <DialogDescription>
              {editingFolder ? 'Update the cloud folder details' : 'Create a new cloud folder to upload your transcripts'}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="label">Label</Label>
              <Input
                id="label"
                placeholder="e.g., Fall 2024 Transcripts"
                value={formData.label}
                onChange={(e) => setFormData({ ...formData, label: e.target.value })}
              />
            </div>

            {/* <div className="space-y-2">
              <Label htmlFor="url">URL</Label>
              <Input
                id="url"
                placeholder="https://drive.google.com/..."
                value={formData.link}
                onChange={(e) => setFormData({ ...formData, link: e.target.value })}
              />
            </div> */}

            <div className="space-y-2">
              <Label htmlFor="term">Term</Label>
              <select
                id="term"
                className="flex h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                value={formData.semester}
                onChange={(e) => setFormData({ ...formData, semester: e.target.value })}
                disabled={!!editingFolder}
              >
                <option value="">Select term</option>
                {terms.map((term) => (
                  <option key={term.id} value={term.term_name}>
                    {term.term_name}
                  </option>
                ))}
              </select>
            </div>

           
          </div>
          {error && (
          <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
            {error}
          </div>
        )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button onClick={handleSaveFolder}>
              {editingFolder ? 'Update' : 'Add'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Purge confirmation dialog ── */}
      <Dialog open={!!folderToPurge} onOpenChange={(open) => { if (!open && !isPurging) setFolderToPurge(null); }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="text-base font-semibold">
              Delete {folderToPurge?.semester}?
            </DialogTitle>
            <DialogDescription asChild>
              <div className="pt-1 space-y-3">
                <p className="text-sm text-muted-foreground">
                  All student data and transcripts for this term will be permanently removed.
                </p>
                <p className="text-sm font-medium text-foreground">This cannot be undone.</p>
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 pt-2">
            <Button variant="outline" onClick={() => setFolderToPurge(null)} disabled={isPurging}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={handleConfirmPurge} disabled={isPurging}>
              {isPurging && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              {isPurging ? 'Deleting...' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PdfPreviewDialog
        open={preview.open}
        onOpenChange={(o) => setPreview((p) => ({ ...p, open: o }))}
        url={preview.url}
        title={preview.title}
      />
    </div>
  );
}
