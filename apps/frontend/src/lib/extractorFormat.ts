// FORMAT vs SCHOOL are two different things:
//   • School  = the actual high school on the transcript (varies per student —
//     Cabrillo, Wilson, Millikan …).
//   • Format  = which extractor handles that transcript type. Only three
//     extractors exist today — LBUSD / Mayfair / St. Anthony — and MANY schools
//     map to one format (every LBUSD member → "LBUSD"). For a transcript whose
//     extractor we DON'T have yet, there is no format name to show, so we show
//     the school name directly instead of an invented label.
//
// The label is derived from the FILE NAME (the one signal that is identical on
// every page — Classify, Extract, Completed, Decisions), so the same transcript
// can never show two different formats on two different pages. This mirrors the
// backend's filename-first detection (_detect_classifier_name).

// LBUSD member schools (kept in sync with the backend `_lbusd_schools`). CAMS is
// an LBUSD member — the backend routes it to the LBUSD extractor — so it is
// tagged LBUSD, never a standalone format. Do NOT add a school here unless the
// LBUSD extractor actually processes it.
const LBUSD_MEMBERS = [
  'lbusd',
  'long beach unified',
  'cabrillo',
  'millikan',
  'sato',
  'jordan',
  'wilson',
  'mcbride',
  'avalon',
  'lakewood',
  'browning',
  'california academy',
  'cams',
];

/** School name parsed from a "Student_School.pdf" file name (the part after the
 *  last underscore). The one page-independent signal, so Format detection is
 *  identical everywhere. */
export function schoolFromFileName(fileName?: string | null): string {
  const base = String(fileName ?? '').replace(/\.[Pp][Dd][Ff]$/, '').trim();
  const idx = base.lastIndexOf('_');
  const raw = idx > 0 && idx < base.length - 1 ? base.slice(idx + 1).trim() : '';
  return raw;
}

/** Title-case a school name for display, preserving short all-caps acronyms
 *  (LBUSD, CAMS, PHS). */
function prettySchool(raw?: string | null): string {
  const t = String(raw ?? '').replace(/[_-]+/g, ' ').replace(/\s+/g, ' ').trim();
  if (!t) return '';
  if (/^[A-Z0-9]{2,6}$/.test(t)) return t;
  return t.replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Detect a KNOWN extractor format from a piece of text (a school name or a
 *  classifier folder). Returns 'LBUSD' | 'Mayfair' | 'St. Anthony' | ''. */
function detectExtractor(text?: string | null): string {
  const s = String(text ?? '').toLowerCase();
  if (!s) return '';
  if (s.includes('mayfair')) return 'Mayfair';
  if (s.includes('anthony')) return 'St. Anthony';
  if (LBUSD_MEMBERS.some((m) => s.includes(m))) return 'LBUSD';
  return '';
}

/**
 * Canonicalize a backend format/classifier string to a display label. Real
 * extractors collapse to LBUSD / Mayfair / St. Anthony; "others"/"unknown"/empty
 * are treated as no-format; anything else is a genuinely new classifier-trained
 * format shown by its (prettified) name.
 */
export function canonicalFormat(raw?: string | null): string {
  const s = String(raw ?? '').toLowerCase().replace(/[_-]+/g, ' ').trim();
  if (!s || s === '—' || s === 'others' || s === 'other' || s === 'unknown') return '';
  const known = detectExtractor(s);
  if (known) return known;
  return prettySchool(s);
}

/**
 * The single source of truth for a transcript's FORMAT tag, shared by every page
 * (Classify, Extract, Completed, Decisions). The `format` comes straight from the
 * backend — the extractor/classifier that actually handled the file — so it's the
 * same on every page:
 *
 *   1. Known / trained extractor (LBUSD / Mayfair / St. Anthony, or a classifier
 *      that's been trained and given its own name) → the extractor's name. Many
 *      schools map to one format.
 *   2. No extractor for it ("others"/none) → show the SCHOOL NAME directly (never
 *      an invented "Others").
 */
export function resolveFormat(school?: string | null, format?: string | null): string {
  const byFormat = canonicalFormat(format);
  if (byFormat) return byFormat;
  return prettySchool(school) || '—';
}
