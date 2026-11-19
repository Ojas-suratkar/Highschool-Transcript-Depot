import * as React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Input } from '@/components/ui/input';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { IconButton } from '@/components/shared/IconButton';
import { Star, Search, ArrowUp, ArrowDown, ChevronsUpDown, Filter } from 'lucide-react';
import { useFlags } from '@/lib/flags';

export type StdAlign = 'left' | 'center' | 'right';

export interface StdColumn<T> {
  key: string;
  header: string;
  /** Custom cell renderer. Falls back to the `value` as truncated text. */
  cell?: (row: T) => React.ReactNode;
  /** Underlying value used for searching / filtering (and sorting if `sortValue` is absent). */
  value?: (row: T) => string | number | null | undefined;
  /** Value used only for sorting — e.g. a timestamp for a date column. */
  sortValue?: (row: T) => string | number | null | undefined;
  /** Defaults to true when `value` or `sortValue` is provided. */
  sortable?: boolean;
  /** Show a filter dropdown of this column's distinct values (needs `value`). */
  filterable?: boolean;
  align?: StdAlign;
  /** Fixed px width (also the minimum). Omit for a flexible, equidistant column. */
  width?: number;
}

export interface StandardTableProps<T> {
  columns: StdColumn<T>[];
  data: T[];
  rowKey: (row: T) => string;
  /** When provided, a star/flag column is shown, keyed by this id. */
  flagId?: (row: T) => string;
  search?: boolean;
  searchPlaceholder?: string;
  emptyMessage?: string;
  maxHeight?: string;
  /** Persists per-column widths across sessions when set. */
  storageKey?: string;
  toolbarRight?: React.ReactNode;
  onRowClick?: (row: T) => void;
}

const STAR_W = 52;
const MIN_GROW = 130;
const ALL = '__all__';
const STAR_KEY = '__star__';

function alignClass(a?: StdAlign) {
  return a === 'center' ? 'text-center' : a === 'right' ? 'text-right' : 'text-left';
}

/**
 * One standardized table used across every list in the app: equidistant default
 * columns, drag-to-resize columns (minimum width = the default, double-click to
 * reset), click-to-sort headers, per-column filters, a search box, and an
 * optional star/flag column — all with a single consistent style.
 */
export function StandardTable<T>({
  columns,
  data,
  rowKey,
  flagId,
  search = false,
  searchPlaceholder = 'Search…',
  emptyMessage = 'No records.',
  maxHeight = 'calc(100vh - 230px)',
  storageKey,
  toolbarRight,
  onRowClick,
}: StandardTableProps<T>) {
  const { isFlagged, toggleFlag } = useFlags();
  const hasStar = !!flagId;

  const [query, setQuery] = useState('');
  const [flaggedOnly, setFlaggedOnly] = useState(false);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [sort, setSort] = useState<{ key: string; dir: 'asc' | 'desc' } | null>(null);

  // ── Container measurement → equidistant default widths ──────────────────────
  const containerRef = useRef<HTMLDivElement>(null);
  const [containerW, setContainerW] = useState(0);
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setContainerW(e.contentRect.width);
    });
    ro.observe(el);
    setContainerW(el.clientWidth);
    return () => ro.disconnect();
  }, []);

  const baseWidths = useMemo(() => {
    const fixedSum =
      columns.reduce((s, c) => s + (c.width ?? 0), 0) + (hasStar ? STAR_W : 0);
    const growCount = columns.filter((c) => c.width == null).length;
    const avail = Math.max(0, containerW - fixedSum - 2);
    // Every flexible column gets an equal share of the width, so columns are
    // evenly spaced across the whole table (no trailing gap / spacer).
    const per = growCount ? Math.max(MIN_GROW, Math.floor(avail / growCount)) : MIN_GROW;
    const map: Record<string, number> = {};
    columns.forEach((c) => {
      map[c.key] = c.width ?? per;
    });
    return map;
  }, [columns, containerW, hasStar]);

  // ── User width overrides (persisted) ────────────────────────────────────────
  const [overrides, setOverrides] = useState<Record<string, number>>(() => {
    if (!storageKey) return {};
    try {
      const raw = localStorage.getItem(`${storageKey}:cols`);
      return raw ? (JSON.parse(raw) as Record<string, number>) : {};
    } catch {
      return {};
    }
  });
  useEffect(() => {
    if (!storageKey) return;
    try {
      localStorage.setItem(`${storageKey}:cols`, JSON.stringify(overrides));
    } catch {
      /* ignore */
    }
  }, [overrides, storageKey]);

  const widthOf = useCallback(
    (key: string) => overrides[key] ?? baseWidths[key] ?? MIN_GROW,
    [overrides, baseWidths],
  );
  const minOf = useCallback((key: string) => baseWidths[key] ?? MIN_GROW, [baseWidths]);

  // ── Drag-to-resize ──────────────────────────────────────────────────────────
  const drag = useRef<{ key: string; startX: number; startW: number } | null>(null);
  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!drag.current) return;
      const { key, startX, startW } = drag.current;
      const w = Math.max(minOf(key), Math.round(startW + (e.clientX - startX)));
      setOverrides((prev) => ({ ...prev, [key]: w }));
    };
    const onUp = () => {
      drag.current = null;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => {
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
  }, [minOf]);

  const startResize = (key: string, e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    drag.current = { key, startX: e.clientX, startW: widthOf(key) };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
  };
  const resetCol = (key: string) =>
    setOverrides((prev) => {
      const n = { ...prev };
      delete n[key];
      return n;
    });

  // ── Filters ─────────────────────────────────────────────────────────────────
  const filterCols = useMemo(() => columns.filter((c) => c.filterable && c.value), [columns]);
  const filterOptions = useMemo(() => {
    const m: Record<string, string[]> = {};
    filterCols.forEach((c) => {
      const set = new Set<string>();
      data.forEach((r) => {
        const v = c.value!(r);
        const s = v == null ? '' : String(v);
        if (s && s !== '—') set.add(s);
      });
      m[c.key] = [...set].sort((a, b) => a.localeCompare(b));
    });
    return m;
  }, [filterCols, data]);

  // ── Search + filter + flag + sort ───────────────────────────────────────────
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    let out = data.filter((r) => {
      if (hasStar && flaggedOnly && !isFlagged(flagId!(r))) return false;
      for (const c of filterCols) {
        const f = filters[c.key];
        if (f && f !== ALL && String(c.value!(r) ?? '') !== f) return false;
      }
      if (!q) return true;
      return columns.some((c) => c.value && String(c.value(r) ?? '').toLowerCase().includes(q));
    });
    if (sort) {
      const col = columns.find((c) => c.key === sort.key);
      out = [...out].sort((a, b) => {
        let cmp = 0;
        if (sort.key === STAR_KEY) {
          cmp = Number(isFlagged(flagId!(a))) - Number(isFlagged(flagId!(b)));
        } else if (col?.sortValue || col?.value) {
          const getV = col.sortValue ?? col.value!;
          const av = getV(a);
          const bv = getV(b);
          if (typeof av === 'number' && typeof bv === 'number') cmp = av - bv;
          else
            cmp = String(av ?? '').localeCompare(String(bv ?? ''), undefined, {
              numeric: true,
              sensitivity: 'base',
            });
        }
        return sort.dir === 'asc' ? cmp : -cmp;
      });
    }
    return out;
  }, [data, query, flaggedOnly, filters, sort, columns, filterCols, hasStar, isFlagged, flagId]);

  const toggleSort = (key: string) =>
    setSort((prev) =>
      prev && prev.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' },
    );

  const totalWidth =
    (hasStar ? STAR_W : 0) + columns.reduce((s, c) => s + widthOf(c.key), 0);
  const showToolbar = search || hasStar || filterCols.length > 0 || !!toolbarRight;

  return (
    <div className="space-y-3">
      {showToolbar && (
        <div className="flex flex-wrap items-center gap-3">
          {search && (
            <div className="relative min-w-[220px] max-w-md flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={searchPlaceholder}
                className="pl-9"
              />
            </div>
          )}

          {filterCols.map((c) => (
            <div key={c.key} className="flex items-center gap-2">
              <Filter className="h-4 w-4 text-slate-400" />
              <Select
                value={filters[c.key] ?? ALL}
                onValueChange={(v) => setFilters((prev) => ({ ...prev, [c.key]: v }))}
              >
                <SelectTrigger className="w-[180px]">
                  <SelectValue placeholder={`All ${c.header}`} />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={ALL}>All {c.header}</SelectItem>
                  {(filterOptions[c.key] ?? []).map((o) => (
                    <SelectItem key={o} value={o}>
                      {o}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          ))}

          {hasStar && (
            <button
              type="button"
              onClick={() => setFlaggedOnly((v) => !v)}
              className={`inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm font-medium transition-colors ${
                flaggedOnly
                  ? 'border-amber-300 bg-amber-50 text-amber-700'
                  : 'border-slate-200 text-slate-600 hover:bg-slate-50'
              }`}
            >
              <Star className={`h-4 w-4 ${flaggedOnly ? 'fill-amber-400 text-amber-500' : ''}`} />
              Flagged only
            </button>
          )}

          {toolbarRight}

          <span className="ml-auto text-sm tabular-nums text-slate-500">
            {rows.length} of {data.length}
          </span>
        </div>
      )}

      <div
        ref={containerRef}
        className="overflow-auto rounded-[12px] border border-[var(--dline)] bg-[var(--panel)] shadow-[var(--sh-sm)]"
        style={{ maxHeight }}
      >
        {data.length === 0 ? (
          <p className="px-5 py-12 text-center text-sm text-muted-foreground">{emptyMessage}</p>
        ) : (
          <table className="border-collapse text-sm" style={{ width: totalWidth, tableLayout: 'fixed' }}>
            <colgroup>
              {hasStar && <col style={{ width: STAR_W }} />}
              {columns.map((c) => (
                <col key={c.key} style={{ width: widthOf(c.key) }} />
              ))}
            </colgroup>

            <thead className="sticky top-0 z-10 bg-[var(--panel-2)] shadow-[inset_0_-1px_0_var(--dline)]">
              <tr className="text-[11px] font-semibold uppercase tracking-wide text-[var(--ink-3)]">
                {hasStar && (
                  <th className="px-3 py-3 text-center">
                    <button
                      type="button"
                      onClick={() => toggleSort(STAR_KEY)}
                      className="inline-flex items-center hover:text-amber-500"
                      aria-label="Sort by flagged"
                    >
                      <Star
                        className={`h-4 w-4 ${sort?.key === STAR_KEY ? 'text-amber-500' : 'text-slate-400'}`}
                      />
                    </button>
                  </th>
                )}
                {columns.map((c) => {
                  const sortable = c.sortable ?? (!!c.value || !!c.sortValue);
                  const active = sort?.key === c.key;
                  return (
                    <th key={c.key} className={`relative px-4 py-3 ${alignClass(c.align)}`}>
                      {sortable ? (
                        <button
                          type="button"
                          onClick={() => toggleSort(c.key)}
                          className={`group inline-flex items-center gap-1.5 hover:text-blue-600 ${
                            c.align === 'center' ? 'justify-center' : c.align === 'right' ? 'justify-end' : ''
                          }`}
                        >
                          {c.header}
                          {active ? (
                            sort!.dir === 'asc' ? (
                              <ArrowUp className="h-3.5 w-3.5 text-blue-600" />
                            ) : (
                              <ArrowDown className="h-3.5 w-3.5 text-blue-600" />
                            )
                          ) : (
                            <ChevronsUpDown className="h-3.5 w-3.5 text-slate-300 group-hover:text-slate-400" />
                          )}
                        </button>
                      ) : (
                        c.header
                      )}
                      <span
                        onMouseDown={(e) => startResize(c.key, e)}
                        onDoubleClick={() => resetCol(c.key)}
                        title="Drag to resize · double-click to reset"
                        className="absolute right-0 top-0 h-full w-1.5 cursor-col-resize select-none hover:bg-blue-200"
                      />
                    </th>
                  );
                })}
              </tr>
            </thead>

            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td
                    colSpan={(hasStar ? 1 : 0) + columns.length}
                    className="px-5 py-12 text-center text-sm text-muted-foreground"
                  >
                    No matches. Try a different search or filter.
                  </td>
                </tr>
              ) : (
                rows.map((r) => {
                  const id = rowKey(r);
                  const fid = hasStar ? flagId!(r) : '';
                  return (
                    <tr
                      key={id}
                      className={`border-t border-[var(--line-2)] text-[var(--ink)] transition-colors hover:bg-[var(--panel-2)] ${
                        onRowClick ? 'cursor-pointer' : ''
                      }`}
                      onClick={onRowClick ? () => onRowClick(r) : undefined}
                    >
                      {hasStar && (
                        <td className="px-3 py-3 text-center" onClick={(e) => e.stopPropagation()}>
                          <IconButton
                            tooltip={isFlagged(fid) ? 'Remove flag' : 'Flag for reference'}
                            onClick={() => toggleFlag(fid)}
                          >
                            <Star
                              className={`h-4 w-4 ${
                                isFlagged(fid) ? 'fill-amber-400 text-amber-500' : 'text-slate-300'
                              }`}
                            />
                          </IconButton>
                        </td>
                      )}
                      {columns.map((c) => (
                        <td key={c.key} className={`px-4 py-3 align-middle ${alignClass(c.align)}`}>
                          {c.cell ? (
                            c.cell(r)
                          ) : (
                            <span className="block truncate" title={String(c.value?.(r) ?? '')}>
                              {(() => {
                                const v = c.value?.(r);
                                return v == null || v === '' ? '—' : String(v);
                              })()}
                            </span>
                          )}
                        </td>
                      ))}
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
