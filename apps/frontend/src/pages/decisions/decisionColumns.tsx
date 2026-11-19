import { Avatar } from '@/components/shared/Avatar';
import { IconButton } from '@/components/shared/IconButton';
import { StdColumn } from '@/components/shared/StandardTable';
import { resolveFormat } from '@/lib/extractorFormat';
import { Eye } from 'lucide-react';
import type { TranscriptRecord } from '@/components/dialogs/TranscriptDetailDialog';

export type DecisionRow = TranscriptRecord & { school?: string | null; serial?: number };

function schoolFromFileName(fileName?: string | null): string {
  const base = String(fileName ?? '').replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  const raw = idx > 0 && idx < base.length - 1 ? base.slice(idx + 1).trim() : '';
  if (!raw) return '';
  const up = raw.toUpperCase();
  if (up === 'LBUSD' || up === 'CAMS') return up;
  return raw.replace(/\b\w/g, (c) => c.toUpperCase());
}

// Actual high school (distinct from the extractor `format`).
export function schoolOf(s: any): string {
  return s?.final_school || s?.school || s?.school_name || schoolFromFileName(s?.file_name) || '';
}

// The standardized decision-table columns — same format & chronology as Extract:
// Student · School · Format · Courses · View, with sorters + a Format filter.
export function decisionColumns(openView: (r: DecisionRow) => void): StdColumn<DecisionRow>[] {
  return [
    {
      key: 'student',
      header: 'Student',
      value: (r) => r.studentName || `Unknown Student ${r.studentId ?? r.id}`,
      cell: (r) => {
        const name = r.studentName || `Unknown Student ${r.studentId ?? r.id}`;
        return (
          <div className="flex items-center gap-3">
            <Avatar name={name} />
            <div className="min-w-0">
              <div className="truncate font-semibold text-slate-900" title={name}>
                {name}
              </div>
              <div className="truncate text-xs text-slate-400">{r.studentId ?? r.id ?? '—'}</div>
            </div>
          </div>
        );
      },
    },
    {
      key: 'school',
      header: 'School',
      value: (r) => r.school ?? '',
      cell: (r) => (
        <span className="block truncate text-slate-600" title={String(r.school ?? '')}>
          {r.school || '—'}
        </span>
      ),
    },
    {
      key: 'format',
      header: 'Format',
      value: (r) => resolveFormat(r.school, r.format),
      filterable: true,
      cell: (r) => {
        const fmt = resolveFormat(r.school, r.format);
        return fmt && fmt !== '—' ? (
          <span className="inline-flex items-center rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-200">
            {fmt}
          </span>
        ) : (
          <span className="text-slate-400">—</span>
        );
      },
    },
    {
      key: 'view',
      header: 'View',
      align: 'center',
      width: 80,
      sortable: false,
      cell: (r) => (
        <IconButton tooltip="View transcript" onClick={() => openView(r)}>
          <Eye className="h-4 w-4" />
        </IconButton>
      ),
    },
  ];
}
