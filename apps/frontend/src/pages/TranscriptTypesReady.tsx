import { useEffect, useMemo, useState } from 'react';

import { PageHeader } from '@/components/shared/PageHeader';
import {
  getClassifierSchoolTypes,
  moveSchoolTypeToExisting,
  type TranscriptSchoolType,
} from '@/lib/api/classifierTraining';

/**
 * Ready = transcript types where both setup parts are complete:
 *
 * 1. Classifier is trained, deployed, and set as default.
 * 2. Extractor setup is complete.
 *
 * From here, the user can move the transcript type to Existing.
 * Existing is global and should not be semester-specific.
 */

function formatDate(value?: string | null) {
  if (!value) return '—';

  try {
    return new Date(value).toLocaleString(undefined, {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
    });
  } catch {
    return value;
  }
}

function shortValue(value?: string | null, length = 16) {
  if (!value) return '—';
  if (value.length <= length) return value;
  return `${value.slice(0, length)}...`;
}

function getFolderNameFromGcsPrefix(prefix?: string | null) {
  if (!prefix) return '—';

  const clean = prefix.endsWith('/') ? prefix.slice(0, -1) : prefix;
  const parts = clean.split('/');

  return parts[parts.length - 1] || prefix;
}

function isClassifierReady(schoolType: TranscriptSchoolType) {
  const message = (schoolType.error_message || '').toLowerCase();

  return (
    Boolean(schoolType.document_ai_processor_version_id) &&
    (Boolean(schoolType.deploy_operation_name) ||
      message.includes('deployed') ||
      message.includes('set as default'))
  );
}

function isExtractorReady(schoolType: TranscriptSchoolType) {
  const profile = schoolType.extractor_profile || 'generic_transcript';

  return Boolean(profile && profile !== 'generic_transcript');
}

function isReadyForExisting(schoolType: TranscriptSchoolType) {
  return (
    schoolType.status === 'ready' &&
    isClassifierReady(schoolType) &&
    isExtractorReady(schoolType)
  );
}

function StatusBadge({
  label,
  tone,
}: {
  label: string;
  tone: 'green' | 'yellow' | 'red' | 'slate' | 'blue';
}) {
  const className =
    tone === 'green'
      ? 'border-green-200 bg-green-50 text-green-700'
      : tone === 'yellow'
        ? 'border-yellow-200 bg-yellow-50 text-yellow-700'
        : tone === 'red'
          ? 'border-red-200 bg-red-50 text-red-700'
          : tone === 'blue'
            ? 'border-blue-200 bg-blue-50 text-blue-700'
            : 'border-slate-200 bg-slate-50 text-slate-600';

  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[11px] font-medium ${className}`}
    >
      {label}
    </span>
  );
}

function StepCheck({
  done,
  label,
  detail,
}: {
  done: boolean;
  label: string;
  detail?: string | null;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="flex items-center gap-2">
        <span
          className={
            done
              ? 'flex h-5 w-5 items-center justify-center rounded-full bg-green-100 text-[11px] font-bold text-green-700'
              : 'flex h-5 w-5 items-center justify-center rounded-full bg-yellow-100 text-[11px] font-bold text-yellow-700'
          }
        >
          {done ? '✓' : '!'}
        </span>

        <div className="min-w-0">
          <div className="text-xs font-semibold text-slate-800">{label}</div>

          {detail && (
            <div className="mt-0.5 truncate font-mono text-[10px] text-slate-500">
              {detail}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ReadyCard({
  schoolType,
  movingId,
  onMoveToExisting,
}: {
  schoolType: TranscriptSchoolType;
  movingId: number | null;
  onMoveToExisting: (schoolTypeId: number) => void;
}) {
  const classifierReady = isClassifierReady(schoolType);
  const extractorReady = isExtractorReady(schoolType);
  const readyForExisting = isReadyForExisting(schoolType);
  const isMoving = movingId === schoolType.id;

  const folderName = getFolderNameFromGcsPrefix(schoolType.gcs_raw_prefix);
  const extractorProfile = schoolType.extractor_profile || 'generic_transcript';

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr_1fr_0.8fr_0.9fr] xl:items-start">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-900">
              {schoolType.display_name}
            </h3>

            <StatusBadge label="Ready" tone="green" />
          </div>

          <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
            {schoolType.classifier_label}
          </div>

          <div className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
            <span className="font-medium text-slate-700">Folder:</span>{' '}
            {folderName}
          </div>

          {schoolType.error_message && (
            <div className="mt-2 max-w-sm rounded-md border border-blue-100 bg-blue-50 px-3 py-2 text-[11px] leading-snug text-blue-700">
              {schoolType.error_message}
            </div>
          )}
        </div>

        <StepCheck
          done={classifierReady}
          label="Classifier"
          detail={
            classifierReady
              ? `Version ${shortValue(
                  schoolType.document_ai_processor_version_id
                )}`
              : 'Missing classifier version'
          }
        />

        <StepCheck
          done={extractorReady}
          label="Extractor"
          detail={
            extractorReady
              ? extractorProfile
              : 'Extractor setup still missing'
          }
        />

        <div>
          <div className="text-[11px] font-semibold uppercase tracking-wide text-slate-400">
            Updated
          </div>

          <div className="mt-1 text-xs font-medium text-slate-700">
            {formatDate(schoolType.updated_at)}
          </div>

          <div className="mt-2 text-[11px] leading-snug text-slate-500">
            Moving to Existing applies this type to all semesters.
          </div>
        </div>

        <div className="xl:text-right">
          <button
            type="button"
            disabled={!readyForExisting || isMoving}
            onClick={() => onMoveToExisting(schoolType.id)}
            className={
              readyForExisting
                ? 'rounded-lg bg-blue-600 px-4 py-2 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60'
                : 'cursor-not-allowed rounded-lg bg-slate-200 px-4 py-2 text-xs font-medium text-slate-500'
            }
          >
            {isMoving ? 'Moving...' : 'Move to Existing'}
          </button>

          {!readyForExisting && (
            <div className="mt-2 text-[10px] leading-snug text-slate-500">
              Classifier and extractor must both be ready first.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function TranscriptTypesReady() {
  const [schoolTypes, setSchoolTypes] = useState<TranscriptSchoolType[]>([]);
  const [loading, setLoading] = useState(true);
  const [movingId, setMovingId] = useState<number | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadReadyTypes() {
    setError(null);

    try {
      const rows = await getClassifierSchoolTypes('ready');
      setSchoolTypes(rows);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load ready transcript types.'
      );
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadReadyTypes();
  }, []);

  async function handleMoveToExisting(schoolTypeId: number) {
    setMovingId(schoolTypeId);
    setMessage(null);
    setError(null);

    try {
      const response = await moveSchoolTypeToExisting(schoolTypeId);

      setMessage(
        response.message ||
          'Transcript type moved to Existing and activated for all semesters.'
      );

      await loadReadyTypes();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to move transcript type to Existing.'
      );

      await loadReadyTypes();
    } finally {
      setMovingId(null);
    }
  }

  const readyRows = useMemo(() => {
    return [...schoolTypes]
      .filter((row) => row.status === 'ready')
      .sort((a, b) => a.display_name.localeCompare(b.display_name));
  }, [schoolTypes]);

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader
        title="Ready"
        subtitle="Transcript types where classifier and extractor setup are complete."
      />

      <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
        <div className="flex flex-col gap-3 border-b border-slate-200 px-5 py-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h2 className="text-base font-semibold text-slate-900">
              Ready to Move to Existing
            </h2>

            <p className="mt-1 text-sm text-slate-500">
              These transcript types are ready to become global existing
              transcript types for all semesters.
            </p>
          </div>

          <button
            type="button"
            onClick={loadReadyTypes}
            className="rounded-lg border border-slate-300 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Refresh
          </button>
        </div>

        {message && (
          <div className="mx-5 mt-4 rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-700">
            {message}
          </div>
        )}

        {error && (
          <div className="mx-5 mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {error}
          </div>
        )}

        {loading ? (
          <div className="px-5 py-6 text-sm text-slate-500">
            Loading ready transcript types...
          </div>
        ) : readyRows.length === 0 ? (
          <div className="px-5 py-6 text-sm text-slate-500">
            No transcript types are ready yet. Once both classifier and extractor
            setup are complete, they will appear here.
          </div>
        ) : (
          <div className="grid gap-4 p-5">
            {readyRows.map((schoolType) => (
              <ReadyCard
                key={schoolType.id}
                schoolType={schoolType}
                movingId={movingId}
                onMoveToExisting={handleMoveToExisting}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
