import { useEffect, useMemo, useRef, useState } from 'react';

import { PageHeader } from '@/components/shared/PageHeader';
import {
  getClassifierSchoolTypes,
  startSchoolTypeSetup,
  transcriptDetectorFileUrl,
  type TranscriptSchoolType,
  type TranscriptSchoolTypeSample,
} from '@/lib/api/classifierTraining';

/**
 * Needs Setup = schools found by clustering but not yet fully added.
 *
 * This page behaves like a folder browser:
 * - main view shows only folders + setup progress
 * - clicking Open Folder switches into that folder
 * - folder view shows transcript table with file name, term, detected school, eye button
 * - no dropdown expansion
 *
 * Important:
 * A school here is waiting for both extractor setup and classifier setup.
 *
 * New behavior:
 * - If sample_count >= required_sample_count, the row automatically moves to In Setup.
 * - No Start Setup button is shown to the user.
 */

const CACHE_KEY = 'needs_setup_school_types_cache_v3';
const DEFAULT_REQUIRED_SAMPLE_COUNT = 15;

function readCachedSchoolTypes(): TranscriptSchoolType[] {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeCachedSchoolTypes(rows: TranscriptSchoolType[]) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(rows));
  } catch {
    // Ignore cache write errors.
  }
}

function formatDate(value?: string | null) {
  if (!value) return '—';

  try {
    return new Date(value).toLocaleDateString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
    });
  } catch {
    return value;
  }
}

function getFolderNameFromGcsPrefix(prefix?: string | null) {
  if (!prefix) return '—';

  const clean = prefix.endsWith('/') ? prefix.slice(0, -1) : prefix;
  const parts = clean.split('/');
  return parts[parts.length - 1] || prefix;
}

function getProgressPercent(sampleCount: number, requiredCount: number) {
  if (!requiredCount || requiredCount <= 0) return 0;
  return Math.min(100, Math.round((sampleCount / requiredCount) * 100));
}

function getRequiredSampleCount(schoolType: TranscriptSchoolType) {
  return schoolType.required_sample_count || DEFAULT_REQUIRED_SAMPLE_COUNT;
}

function hasEnoughSamples(schoolType: TranscriptSchoolType) {
  return schoolType.sample_count >= getRequiredSampleCount(schoolType);
}

function shouldAutoMoveToInSetup(schoolType: TranscriptSchoolType) {
  return schoolType.status === 'needs_setup' && hasEnoughSamples(schoolType);
}

function getTermSummary(samples?: TranscriptSchoolTypeSample[]) {
  if (!samples || samples.length === 0) return '—';

  const terms = Array.from(
    new Set(
      samples
        .map((sample) => sample.semester)
        .filter((term): term is string => Boolean(term))
    )
  ).sort();

  if (terms.length === 0) return '—';
  if (terms.length <= 3) return terms.join(', ');

  return `${terms.slice(0, 3).join(', ')} +${terms.length - 3} more`;
}

function openTranscript(sample: TranscriptSchoolTypeSample) {
  if (!sample.blob_name) return;

  window.open(
    transcriptDetectorFileUrl(sample.blob_name),
    '_blank',
    'noopener,noreferrer'
  );
}

function FolderProgressBar({
  sampleCount,
  requiredCount,
}: {
  sampleCount: number;
  requiredCount: number;
}) {
  const percent = getProgressPercent(sampleCount, requiredCount);
  const complete = sampleCount >= requiredCount;

  return (
    <div className="w-full max-w-sm">
      <div className="mb-1 flex items-center justify-between text-[11px] text-slate-500">
        <span>Progress</span>

        <span className="font-semibold text-slate-700">
          {sampleCount} / {requiredCount}
        </span>
      </div>

      <div className="h-2 overflow-hidden rounded-full bg-slate-200">
        <div
          className={
            complete
              ? 'h-full rounded-full bg-green-500'
              : 'h-full rounded-full bg-blue-500'
          }
          style={{ width: `${percent}%` }}
        />
      </div>
    </div>
  );
}

function SetupStatusAction({
  schoolType,
  isAutoMoving,
}: {
  schoolType: TranscriptSchoolType;
  isAutoMoving: boolean;
}) {
  const ready = hasEnoughSamples(schoolType);

  if (ready) {
    return (
      <div className="rounded-md border border-green-200 bg-green-50 px-3 py-1.5 text-center text-xs font-medium text-green-700">
        {isAutoMoving ? 'Moving to In Setup...' : 'Auto-moving to In Setup'}
      </div>
    );
  }

  return (
    <div className="cursor-not-allowed rounded-md bg-slate-200 px-3 py-1.5 text-center text-xs font-medium text-slate-500">
      Need More Samples
    </div>
  );
}

function NeedsSetupFolderRow({
  schoolType,
  onOpenFolder,
  autoMovingIds,
}: {
  schoolType: TranscriptSchoolType;
  onOpenFolder: (id: number) => void;
  autoMovingIds: number[];
}) {
  const ready = hasEnoughSamples(schoolType);
  const isAutoMoving = autoMovingIds.includes(schoolType.id);
  const folderName = getFolderNameFromGcsPrefix(schoolType.gcs_raw_prefix);
  const requiredCount = getRequiredSampleCount(schoolType);

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="min-w-0 flex-1">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-yellow-50 text-lg">
              📁
            </div>

            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <h3 className="truncate text-sm font-semibold text-slate-900">
                  {schoolType.display_name}
                </h3>

                <span className="inline-flex rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-700">
                  Needs Setup
                </span>

                {ready ? (
                  <span className="inline-flex rounded-full border border-green-200 bg-green-50 px-2 py-0.5 text-[11px] font-medium text-green-700">
                    Ready for setup
                  </span>
                ) : (
                  <span className="inline-flex rounded-full border border-yellow-200 bg-yellow-50 px-2 py-0.5 text-[11px] font-medium text-yellow-700">
                    Collecting samples
                  </span>
                )}
              </div>

              <div className="mt-1 text-xs text-slate-500">
                Folder:{' '}
                <span className="font-medium text-slate-700">
                  {folderName}
                </span>
              </div>
            </div>
          </div>

          <div className="mt-3">
            <FolderProgressBar
              sampleCount={schoolType.sample_count}
              requiredCount={requiredCount}
            />
          </div>
        </div>

        <div className="flex shrink-0 flex-col gap-2 sm:flex-row lg:flex-col">
          <button
            type="button"
            onClick={() => onOpenFolder(schoolType.id)}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Open Folder
          </button>

          <SetupStatusAction
            schoolType={schoolType}
            isAutoMoving={isAutoMoving}
          />
        </div>
      </div>
    </div>
  );
}

function FolderDetailView({
  schoolType,
  onBack,
  autoMovingIds,
}: {
  schoolType: TranscriptSchoolType;
  onBack: () => void;
  autoMovingIds: number[];
}) {
  const samples = schoolType.samples || [];
  const folderName = getFolderNameFromGcsPrefix(schoolType.gcs_raw_prefix);
  const requiredCount = getRequiredSampleCount(schoolType);
  const isAutoMoving = autoMovingIds.includes(schoolType.id);

  return (
    <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            ← Back
          </button>

          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-yellow-50 text-lg">
            📁
          </div>

          <div className="min-w-0">
            <h2 className="truncate text-base font-semibold text-slate-900">
              {schoolType.display_name}
            </h2>

            <p className="mt-0.5 text-xs text-slate-500">
              {folderName} · {samples.length} transcript
              {samples.length === 1 ? '' : 's'} · Terms:{' '}
              {getTermSummary(samples)}
            </p>
          </div>
        </div>

        <SetupStatusAction
          schoolType={schoolType}
          isAutoMoving={isAutoMoving}
        />
      </div>

      <div className="border-b border-slate-200 px-4 py-3">
        <FolderProgressBar
          sampleCount={schoolType.sample_count}
          requiredCount={requiredCount}
        />
      </div>

      <div className="px-4 py-3">
        <div className="mb-3 grid gap-3 text-xs sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Classifier Label
            </div>

            <div className="mt-1 truncate font-mono text-slate-800">
              {schoolType.classifier_label}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Folder
            </div>

            <div className="mt-1 truncate text-slate-800">{folderName}</div>
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Samples
            </div>

            <div className="mt-1 font-semibold text-slate-900">
              {schoolType.sample_count} / {requiredCount}
            </div>
          </div>

          <div>
            <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
              Updated
            </div>

            <div className="mt-1 text-slate-800">
              {formatDate(schoolType.updated_at)}
            </div>
          </div>
        </div>

        {samples.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-300 p-4 text-xs text-slate-500">
            No transcript files are linked yet.
          </div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-200">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-slate-200">
                <thead className="bg-slate-50">
                  <tr>
                    <th className="w-16 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      S.No
                    </th>

                    <th className="px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Transcript File Name
                    </th>

                    <th className="w-40 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Term
                    </th>

                    <th className="w-56 px-3 py-2 text-left text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      Detected School
                    </th>

                    <th className="w-20 px-3 py-2 text-center text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                      View
                    </th>
                  </tr>
                </thead>

                <tbody className="divide-y divide-slate-200 bg-white">
                  {samples.map((sample, index) => (
                    <tr key={sample.id} className="hover:bg-slate-50">
                      <td className="px-3 py-2 text-xs text-slate-700">
                        {index + 1}
                      </td>

                      <td className="px-3 py-2">
                        <div className="max-w-xl truncate text-xs font-medium text-slate-900">
                          {sample.file_name}
                        </div>
                      </td>

                      <td className="px-3 py-2 text-xs text-slate-700">
                        {sample.semester || '—'}
                      </td>

                      <td className="px-3 py-2 text-xs text-slate-700">
                        {sample.detected_school_name || schoolType.display_name}
                      </td>

                      <td className="px-3 py-2 text-center">
                        <button
                          type="button"
                          disabled={!sample.blob_name}
                          onClick={() => openTranscript(sample)}
                          className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-slate-300 bg-white text-xs text-slate-700 hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-50"
                          title="View transcript"
                          aria-label={`View transcript ${sample.file_name}`}
                        >
                          👁
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function TranscriptTypesNeedSetup() {
  const cachedRows = useMemo(() => readCachedSchoolTypes(), []);

  const autoStartedIdsRef = useRef<Set<number>>(new Set());

  const [schoolTypes, setSchoolTypes] =
    useState<TranscriptSchoolType[]>(cachedRows);
  const [loading, setLoading] = useState(cachedRows.length === 0);
  const [refreshing, setRefreshing] = useState(false);
  const [autoMovingIds, setAutoMovingIds] = useState<number[]>([]);
  const [selectedFolderId, setSelectedFolderId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function autoMoveReadyRows(rows: TranscriptSchoolType[]) {
    const readyRows = rows.filter((row) => {
      if (!shouldAutoMoveToInSetup(row)) return false;
      return !autoStartedIdsRef.current.has(row.id);
    });

    if (readyRows.length === 0) return;

    const ids = readyRows.map((row) => row.id);

    ids.forEach((id) => autoStartedIdsRef.current.add(id));

    setAutoMovingIds((current) => Array.from(new Set([...current, ...ids])));

    const results = await Promise.allSettled(
      readyRows.map((row) => startSchoolTypeSetup(row.id))
    );

    const failedCount = results.filter(
      (result) => result.status === 'rejected'
    ).length;

    setAutoMovingIds((current) => current.filter((id) => !ids.includes(id)));

    if (failedCount > 0) {
      ids.forEach((id) => autoStartedIdsRef.current.delete(id));

      setError(
        `${failedCount} transcript type(s) were ready, but automatic move to In Setup failed. Refresh or check backend logs.`
      );
    }

    await loadSchoolTypes({
      silent: true,
      skipAutoMove: true,
    });
  }

  async function loadSchoolTypes(options?: {
    silent?: boolean;
    skipAutoMove?: boolean;
  }) {
    const silent = options?.silent ?? false;
    const skipAutoMove = options?.skipAutoMove ?? false;

    setError(null);

    if (silent) {
      setRefreshing(true);
    } else if (schoolTypes.length === 0) {
      setLoading(true);
    } else {
      setRefreshing(true);
    }

    try {
      const rows = await getClassifierSchoolTypes('needs_setup');

      setSchoolTypes(rows);
      writeCachedSchoolTypes(rows);

      if (
        selectedFolderId !== null &&
        !rows.some((row) => row.id === selectedFolderId)
      ) {
        setSelectedFolderId(null);
      }

      if (!skipAutoMove) {
        void autoMoveReadyRows(rows);
      }
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load transcript types that need setup.'
      );
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadSchoolTypes({ silent: cachedRows.length > 0 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadSchoolTypes({ silent: true });
    }, 30000);

    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sortedSchoolTypes = useMemo(() => {
    return [...schoolTypes].sort((a, b) => {
      const aReady = hasEnoughSamples(a) ? 1 : 0;
      const bReady = hasEnoughSamples(b) ? 1 : 0;

      if (aReady !== bReady) return bReady - aReady;

      return a.display_name.localeCompare(b.display_name);
    });
  }, [schoolTypes]);

  const selectedFolder = useMemo(() => {
    if (selectedFolderId === null) return null;
    return schoolTypes.find((row) => row.id === selectedFolderId) || null;
  }, [schoolTypes, selectedFolderId]);

  return (
    <div className="mx-auto max-w-5xl space-y-4 px-1">
      <PageHeader
        title="Needs Setup"
        subtitle="Unrecognized transcript types pending extractor and classifier setup."
      />

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="mb-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Extractor and Classifier Setup Queue
            </h2>

            <p className="mt-1 text-xs text-slate-500">
              Schools found by clustering. Folders with enough transcripts move
              to In Setup automatically.
            </p>
          </div>

          <button
            type="button"
            onClick={() => loadSchoolTypes({ silent: true })}
            disabled={refreshing}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>
        </div>

        {refreshing && !loading && (
          <div className="mb-3 rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-xs text-blue-700">
            Updating setup queue...
          </div>
        )}

        {autoMovingIds.length > 0 && (
          <div className="mb-3 rounded-md border border-green-100 bg-green-50 px-3 py-2 text-xs text-green-700">
            Moving {autoMovingIds.length} transcript type
            {autoMovingIds.length === 1 ? '' : 's'} to In Setup...
          </div>
        )}

        {error && (
          <div className="mb-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="rounded-md border border-dashed border-slate-300 p-4 text-xs text-slate-500">
            Loading setup queue...
          </div>
        ) : selectedFolder ? (
          <FolderDetailView
            schoolType={selectedFolder}
            onBack={() => setSelectedFolderId(null)}
            autoMovingIds={autoMovingIds}
          />
        ) : sortedSchoolTypes.length === 0 ? (
          <div className="rounded-md border border-dashed border-slate-300 p-4 text-xs text-slate-500">
            No new transcript types found by clustering yet.
          </div>
        ) : (
          <div className="grid gap-3">
            {sortedSchoolTypes.map((schoolType) => (
              <NeedsSetupFolderRow
                key={schoolType.id}
                schoolType={schoolType}
                onOpenFolder={setSelectedFolderId}
                autoMovingIds={autoMovingIds}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
