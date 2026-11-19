import { useEffect, useMemo, useState } from 'react';

import { PageHeader } from '@/components/shared/PageHeader';
import {
  getClassifierSchoolTypes,
  runReadySchoolTypeSetup,
  startSchoolTypeSetup,
  type TranscriptSchoolType,
} from '@/lib/api/classifierTraining';

const CACHE_KEY = 'classifier_in_setup_school_types_cache_v4';

type StepStatus = 'done' | 'active' | 'waiting' | 'problem';

interface SetupStep {
  label: string;
  status: StepStatus;
  detail?: string;
}

function readCachedRows(): TranscriptSchoolType[] {
  try {
    const raw = sessionStorage.getItem(CACHE_KEY);
    if (!raw) return [];

    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeCachedRows(rows: TranscriptSchoolType[]) {
  try {
    sessionStorage.setItem(CACHE_KEY, JSON.stringify(rows));
  } catch {
    // Ignore cache write errors.
  }
}

function mergeSchoolTypes(rows: TranscriptSchoolType[]) {
  const byId = new Map<number, TranscriptSchoolType>();

  rows.forEach((row) => {
    byId.set(row.id, row);
  });

  return Array.from(byId.values());
}

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

function shortOperationName(value?: string | null) {
  if (!value) return '—';

  if (value.startsWith('existing_trained_version:')) {
    return 'Existing trained';
  }

  if (value.startsWith('manual_')) {
    return 'Manual';
  }

  if (value.startsWith('manual_or_existing_deployed_version:')) {
    return 'Existing deployed';
  }

  const parts = value.split('/');
  const last = parts[parts.length - 1] || value;

  if (last.length > 10) {
    return `${last.slice(0, 10)}...`;
  }

  return last;
}

function shortValue(value?: string | null, length = 10) {
  if (!value) return '—';
  if (value.length <= length) return value;
  return `${value.slice(0, length)}...`;
}

function formatRunResult(result: Record<string, unknown> | undefined) {
  if (!result) return 'Classifier setup finished.';

  const processed = result.processed ?? 0;
  const inProgress = result.in_progress ?? 0;
  const ready = result.ready ?? 0;
  const failed = result.failed ?? 0;
  const skipped = result.skipped ?? 0;

  return `processed: ${processed} · in progress: ${inProgress} · ready: ${ready} · failed: ${failed} · skipped: ${skipped}`;
}

function getRequiredSampleCount(row: TranscriptSchoolType) {
  return row.required_sample_count || 10;
}

function getSamplePercent(row: TranscriptSchoolType) {
  const required = getRequiredSampleCount(row);

  if (required <= 0) return 0;

  return Math.min(100, Math.round((row.sample_count / required) * 100));
}

function hasEnoughSamples(row: TranscriptSchoolType) {
  return row.sample_count >= getRequiredSampleCount(row);
}

function hasProblemMessage(row: TranscriptSchoolType) {
  const message = (row.error_message || '').toLowerCase();

  return (
    row.status === 'failed' ||
    message.includes('failed') ||
    message.includes('error') ||
    message.includes('invalid') ||
    message.includes('unable to finish') ||
    message.includes('training stopped')
  );
}

function getClassifierSteps(row: TranscriptSchoolType): SetupStep[] {
  const message = (row.error_message || '').toLowerCase();

  const enoughSamples = hasEnoughSamples(row);
  const hasProblem = hasProblemMessage(row);

  const importDone =
    Boolean(row.import_operation_name) ||
    Boolean(row.document_ai_processor_version_id) ||
    message.includes('imported') ||
    message.includes('import complete');

  const trainingDone =
    Boolean(row.document_ai_processor_version_id) ||
    Boolean(row.training_operation_name?.startsWith('existing_trained_version:')) ||
    message.includes('trained');

  const deployDone =
    Boolean(row.deploy_operation_name) ||
    message.includes('deployed');

  const defaultDone =
    message.includes('set as default') ||
    message.includes('default version');

  return [
    {
      label: 'Samples',
      status: enoughSamples ? 'done' : 'waiting',
      detail: `${row.sample_count}/${getRequiredSampleCount(row)}`,
    },
    {
      label: 'Import',
      status: importDone ? 'done' : enoughSamples ? 'active' : 'waiting',
      detail: shortOperationName(row.import_operation_name),
    },
    {
      label: 'Train',
      status: trainingDone
        ? 'done'
        : hasProblem && importDone
          ? 'problem'
          : importDone
            ? 'active'
            : 'waiting',
      detail: row.document_ai_processor_version_id
        ? shortValue(row.document_ai_processor_version_id)
        : shortOperationName(row.training_operation_name),
    },
    {
      label: 'Deploy',
      status: deployDone
        ? 'done'
        : hasProblem && trainingDone
          ? 'problem'
          : trainingDone
            ? 'active'
            : 'waiting',
      detail: shortOperationName(row.deploy_operation_name),
    },
    {
      label: 'Default',
      status: defaultDone
        ? 'done'
        : hasProblem && deployDone
          ? 'problem'
          : deployDone
            ? 'active'
            : 'waiting',
      detail: defaultDone ? 'Set' : 'Pending',
    },
  ];
}

function getStepProgress(steps: SetupStep[]) {
  const doneCount = steps.filter((step) => step.status === 'done').length;
  return Math.round((doneCount / steps.length) * 100);
}

function getClassifierStatus(row: TranscriptSchoolType) {
  const steps = getClassifierSteps(row);
  const progress = getStepProgress(steps);
  const hasProblem = hasProblemMessage(row) || steps.some((step) => step.status === 'problem');

  if (hasProblem) {
    return {
      done: false,
      problem: true,
      label: 'Needs attention',
      className: 'border-red-200 bg-red-50 text-red-700',
    };
  }

  if (progress === 100) {
    return {
      done: true,
      problem: false,
      label: 'Classifier done',
      className: 'border-green-200 bg-green-50 text-green-700',
    };
  }

  if (
    row.import_operation_name ||
    row.training_operation_name ||
    row.deploy_operation_name ||
    row.document_ai_processor_version_id
  ) {
    return {
      done: false,
      problem: false,
      label: 'Classifier running',
      className: 'border-blue-200 bg-blue-50 text-blue-700',
    };
  }

  return {
    done: false,
    problem: false,
    label: 'Queued',
    className: 'border-yellow-200 bg-yellow-50 text-yellow-700',
  };
}

function getExtractorStatus(row: TranscriptSchoolType) {
  const profile = row.extractor_profile || 'generic_transcript';

  const extractorDone =
    row.status === 'ready' ||
    Boolean(profile && profile !== 'generic_transcript');

  if (extractorDone) {
    return {
      done: true,
      label: 'Extractor done',
      detail: profile,
      className: 'border-green-200 bg-green-50 text-green-700',
    };
  }

  return {
    done: false,
    label: 'Waiting for extractor',
    detail: profile,
    className: 'border-slate-200 bg-slate-50 text-slate-600',
  };
}

function StatusBadge({
  label,
  className,
}: {
  label: string;
  className: string;
}) {
  return (
    <span
      className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-medium ${className}`}
    >
      {label}
    </span>
  );
}

function StepDot({ status }: { status: StepStatus }) {
  if (status === 'done') {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-green-100 text-[9px] font-bold text-green-700">
        ✓
      </span>
    );
  }

  if (status === 'active') {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-blue-100 text-[9px] font-bold text-blue-700">
        …
      </span>
    );
  }

  if (status === 'problem') {
    return (
      <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-red-100 text-[9px] font-bold text-red-700">
        !
      </span>
    );
  }

  return (
    <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[9px] font-bold text-slate-400">
      ○
    </span>
  );
}

function SamplesProgress({ row }: { row: TranscriptSchoolType }) {
  const percent = getSamplePercent(row);
  const complete = hasEnoughSamples(row);

  return (
    <div className="w-full">
      <div className="mb-1 flex justify-between text-[10px] text-slate-500">
        <span>Samples</span>
        <span className="font-semibold text-slate-700">
          {row.sample_count} / {getRequiredSampleCount(row)}
        </span>
      </div>

      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200">
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

function ClassifierProgress({ row }: { row: TranscriptSchoolType }) {
  const steps = getClassifierSteps(row);
  const percent = getStepProgress(steps);
  const classifierStatus = getClassifierStatus(row);

  return (
    <div className="w-full">
      <div className="mb-1.5 flex items-center justify-between gap-2">
        <StatusBadge
          label={classifierStatus.label}
          className={classifierStatus.className}
        />

        <span className="text-[10px] font-semibold text-slate-600">
          {percent}%
        </span>
      </div>

      <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div
          className={
            percent === 100 && !classifierStatus.problem
              ? 'h-full rounded-full bg-green-500'
              : classifierStatus.problem
                ? 'h-full rounded-full bg-red-400'
                : 'h-full rounded-full bg-blue-500'
          }
          style={{ width: `${percent}%` }}
        />
      </div>

      <div className="grid grid-cols-5 gap-1">
        {steps.map((step) => (
          <div key={step.label} className="min-w-0">
            <div className="flex items-center gap-1">
              <StepDot status={step.status} />

              <span className="truncate text-[10px] font-medium text-slate-700">
                {step.label}
              </span>
            </div>

            {step.detail && step.detail !== '—' && (
              <div className="mt-0.5 truncate text-[9px] text-slate-400">
                {step.detail}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function ExtractorProgress({ row }: { row: TranscriptSchoolType }) {
  const status = getExtractorStatus(row);

  return (
    <div className="w-full">
      <div className="mb-1.5">
        <StatusBadge label={status.label} className={status.className} />
      </div>

      <div className="flex items-center gap-1.5">
        <StepDot status={status.done ? 'done' : 'waiting'} />

        <div className="min-w-0">
          <div className="text-[10px] font-medium text-slate-700">
            Extractor profile
          </div>

          <div className="truncate font-mono text-[9px] text-slate-500">
            {status.detail}
          </div>
        </div>
      </div>

      <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-200">
        <div
          className={
            status.done
              ? 'h-full w-full rounded-full bg-green-500'
              : 'h-full w-1/4 rounded-full bg-slate-400'
          }
        />
      </div>
    </div>
  );
}

function getClassifierButtonLabel(row: TranscriptSchoolType) {
  const classifierStatus = getClassifierStatus(row);

  if (classifierStatus.problem || row.status === 'failed') {
    return 'Retry Classifier';
  }

  if (
    row.import_operation_name ||
    row.training_operation_name ||
    row.deploy_operation_name ||
    row.document_ai_processor_version_id
  ) {
    return 'Continue Classifier';
  }

  return 'Start Classifier';
}

function InSetupCard({
  schoolType,
  runningSchoolTypeId,
  onRunClassifierSetup,
}: {
  schoolType: TranscriptSchoolType;
  runningSchoolTypeId: number | null;
  onRunClassifierSetup: (schoolType: TranscriptSchoolType) => void;
}) {
  const classifierStatus = getClassifierStatus(schoolType);
  const extractorStatus = getExtractorStatus(schoolType);

  const classifierDone = classifierStatus.done;
  const isRunning = runningSchoolTypeId === schoolType.id;

  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr_1.7fr_1.15fr_0.75fr] xl:items-start">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-slate-900">
            {schoolType.display_name}
          </div>

          <div className="mt-1 truncate font-mono text-[11px] text-slate-500">
            {schoolType.classifier_label}
          </div>

          {schoolType.error_message && (
            <div
              className={
                classifierStatus.problem
                  ? 'mt-2 max-w-[280px] rounded-md border border-red-200 bg-red-50 px-2 py-1.5 text-[10px] leading-snug text-red-700'
                  : 'mt-2 max-w-[280px] rounded-md border border-yellow-200 bg-yellow-50 px-2 py-1.5 text-[10px] leading-snug text-yellow-800'
              }
            >
              {schoolType.error_message}
            </div>
          )}
        </div>

        <SamplesProgress row={schoolType} />

        <ClassifierProgress row={schoolType} />

        <ExtractorProgress row={schoolType} />

        <div className="flex flex-col gap-2 xl:items-end">
          <div className="text-[11px] text-slate-500">Updated</div>

          <div className="text-xs font-medium text-slate-700">
            {formatDate(schoolType.updated_at)}
          </div>

          {classifierDone && !extractorStatus.done ? (
            <button
              type="button"
              disabled
              title="Extractor setup is still required before moving to Ready."
              className="mt-1 cursor-not-allowed rounded-md bg-slate-200 px-3 py-1.5 text-[11px] font-medium text-slate-500"
            >
              Waiting for Extractor
            </button>
          ) : classifierDone && extractorStatus.done ? (
            <button
              type="button"
              disabled
              className="mt-1 cursor-not-allowed rounded-md bg-green-100 px-3 py-1.5 text-[11px] font-medium text-green-700"
            >
              Ready to Move
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onRunClassifierSetup(schoolType)}
              disabled={isRunning}
              className={
                classifierStatus.problem || schoolType.status === 'failed'
                  ? 'mt-1 rounded-md border border-red-200 bg-red-50 px-3 py-1.5 text-[11px] font-medium text-red-700 hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60'
                  : 'mt-1 rounded-md border border-blue-200 bg-blue-50 px-3 py-1.5 text-[11px] font-medium text-blue-700 hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-60'
              }
            >
              {isRunning ? 'Running...' : getClassifierButtonLabel(schoolType)}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

function ClassifierInSetupSection() {
  const cachedRows = useMemo(() => readCachedRows(), []);

  const [schoolTypes, setSchoolTypes] =
    useState<TranscriptSchoolType[]>(cachedRows);
  const [loading, setLoading] = useState(cachedRows.length === 0);
  const [refreshing, setRefreshing] = useState(false);
  const [runningAll, setRunningAll] = useState(false);
  const [runningSchoolTypeId, setRunningSchoolTypeId] = useState<number | null>(
    null
  );
  const [error, setError] = useState<string | null>(null);
  const [lastResult, setLastResult] = useState<string | null>(null);

  async function loadSchoolTypes(options?: { silent?: boolean }) {
    const silent = options?.silent ?? false;

    setError(null);

    if (silent || schoolTypes.length > 0) {
      setRefreshing(true);
    } else {
      setLoading(true);
    }

    try {
      const [inSetupRows, failedRows] = await Promise.all([
        getClassifierSchoolTypes('in_setup'),
        getClassifierSchoolTypes('failed'),
      ]);

      const rows = mergeSchoolTypes([...inSetupRows, ...failedRows]);

      setSchoolTypes(rows);
      writeCachedRows(rows);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to load setup progress.'
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

  async function runWorkerAndRefresh() {
    const response = await runReadySchoolTypeSetup();

    setLastResult(formatRunResult(response.result));

    await loadSchoolTypes({ silent: true });
  }

  async function handleRunAllActiveSetup() {
    setRunningAll(true);
    setError(null);
    setLastResult(null);

    try {
      await runWorkerAndRefresh();
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to run classifier setup.'
      );

      await loadSchoolTypes({ silent: true });
    } finally {
      setRunningAll(false);
    }
  }

  async function handleRunClassifierSetup(schoolType: TranscriptSchoolType) {
    setRunningSchoolTypeId(schoolType.id);
    setError(null);
    setLastResult(null);

    try {
      const classifierStatus = getClassifierStatus(schoolType);

      if (schoolType.status === 'failed' || classifierStatus.problem) {
        await startSchoolTypeSetup(schoolType.id);
      }

      const response = await runReadySchoolTypeSetup();

      setLastResult(formatRunResult(response.result));

      await loadSchoolTypes({ silent: true });
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : 'Failed to continue classifier setup.'
      );

      await loadSchoolTypes({ silent: true });
    } finally {
      setRunningSchoolTypeId(null);
    }
  }

  const sortedSchoolTypes = useMemo(() => {
    return [...schoolTypes].sort((a, b) => {
      const aProblem = hasProblemMessage(a) ? 1 : 0;
      const bProblem = hasProblemMessage(b) ? 1 : 0;

      if (aProblem !== bProblem) {
        return bProblem - aProblem;
      }

      const aClassifierPercent = getStepProgress(getClassifierSteps(a));
      const bClassifierPercent = getStepProgress(getClassifierSteps(b));

      if (aClassifierPercent !== bClassifierPercent) {
        return bClassifierPercent - aClassifierPercent;
      }

      return a.display_name.localeCompare(b.display_name);
    });
  }, [schoolTypes]);

  const activeCount = sortedSchoolTypes.filter(
    (row) => row.status === 'in_setup'
  ).length;

  const failedCount = sortedSchoolTypes.filter(
    (row) => row.status === 'failed' || hasProblemMessage(row)
  ).length;

  return (
    <div className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">
            Extractor and Classifier Setup Progress
          </h2>

          <p className="mt-1 text-xs text-slate-500">
            Track each transcript type until both classifier and extractor setup
            are complete. Failed rows stay here and can be retried.
          </p>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            onClick={() => loadSchoolTypes({ silent: true })}
            disabled={refreshing || runningAll || runningSchoolTypeId !== null}
            className="rounded-md border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {refreshing ? 'Refreshing...' : 'Refresh'}
          </button>

          <button
            type="button"
            onClick={handleRunAllActiveSetup}
            disabled={
              runningAll ||
              runningSchoolTypeId !== null ||
              activeCount === 0
            }
            className="rounded-md bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {runningAll ? 'Running...' : 'Continue Active'}
          </button>
        </div>
      </div>

      <div className="border-b border-slate-100 px-4 py-2 text-[11px] text-slate-500">
        Active: {activeCount} · Needs attention: {failedCount}
      </div>

      {lastResult && (
        <div className="mx-4 mt-3 rounded-md border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-700">
          {lastResult}
        </div>
      )}

      {error && (
        <div className="mx-4 mt-3 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
          {error}
        </div>
      )}

      {refreshing && !loading && (
        <div className="mx-4 mt-3 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
          Updating setup progress...
        </div>
      )}

      {loading ? (
        <div className="px-4 py-5 text-sm text-slate-500">
          Loading setup progress...
        </div>
      ) : sortedSchoolTypes.length === 0 ? (
        <div className="px-4 py-5 text-sm text-slate-500">
          No transcript types are currently in setup.
        </div>
      ) : (
        <div className="grid gap-3 p-4">
          {sortedSchoolTypes.map((schoolType) => (
            <InSetupCard
              key={schoolType.id}
              schoolType={schoolType}
              runningSchoolTypeId={runningSchoolTypeId}
              onRunClassifierSetup={handleRunClassifierSetup}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function TranscriptTypesInSetup() {
  return (
    <div className="space-y-5">
      <PageHeader
        title="In Setup"
        subtitle="Extractor and classifier setup currently in progress."
      />

      <ClassifierInSetupSection />
    </div>
  );
}
