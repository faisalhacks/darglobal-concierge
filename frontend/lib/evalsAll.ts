// Pure logic for the /evals "All cases" explorer (no React, unit-tested in tests/evalsAll.test.mjs).
// Data: /evals-all.json, written by evals/make_showcase.py from every file in evals/results.

export interface AllSource {
  key: string; set: string; name: string; file?: string; run_at?: string | null; llm_mode?: string | null;
  provider?: string | null; model?: string | null; n: number; passed: number; failed: number; skipped: number;
  stop_reason?: string | null; llm_calls?: number | null; judge?: { model?: string | null; means?: Record<string, number | null> | null };
}
export interface AllEntry {
  i: string; s: string; c?: string | null; p?: string | null; l?: string | null; q: string[]; a: string; t?: boolean;
  ok: 1 | 0 | -1; f: string[]; fd?: string; x?: number; r?: string | null; m?: string | null; n?: number | null;
  src: string; j?: (number | null)[];
}
export interface AllData { generated_at?: string; sources: AllSource[]; categories?: string[]; personas?: string[]; entries: AllEntry[]; note?: string }

export type ResultFilter = "all" | "passed" | "failed" | "skipped";
export interface Filters { source: string; category: string; persona: string; result: ResultFilter; answered: string; query: string }
export const NO_FILTERS: Filters = { source: "all", category: "all", persona: "all", result: "all", answered: "all", query: "" };

export const prettify = (k: string) => k.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

/** Validates the file shape; anything unexpected becomes an empty, honest "nothing loaded" state. */
export function parseAll(raw: unknown): AllData | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Partial<AllData>;
  if (!Array.isArray(o.entries) || !Array.isArray(o.sources)) return null;
  const entries = o.entries.filter((e): e is AllEntry => !!e && typeof e.i === "string" && Array.isArray(e.q) && typeof e.a === "string" && (e.ok === 1 || e.ok === 0 || e.ok === -1));
  return { ...o, sources: o.sources, entries } as AllData;
}

const RESULT: Record<ResultFilter, number | null> = { all: null, passed: 1, failed: 0, skipped: -1 };

export function applyFilters(entries: AllEntry[], f: Filters): AllEntry[] {
  const q = f.query.trim().toLowerCase();
  const want = RESULT[f.result];
  const out = entries.filter((e) => {
    if (f.source !== "all" && e.s !== f.source) return false;
    if (f.category !== "all" && e.c !== f.category) return false;
    if (f.persona !== "all" && (f.persona === "none" ? !!e.p : e.p !== f.persona)) return false;
    if (want !== null && e.ok !== want) return false;
    if (f.answered !== "all" && e.src !== f.answered) return false;
    if (q) {
      const hay = `${e.i} ${e.c ?? ""} ${e.p ?? ""} ${e.q.join(" ")} ${e.a} ${e.f.join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  // failures first (an honest default), then the recorded order
  const rank = (e: AllEntry) => (e.ok === 0 ? 0 : e.ok === -1 ? 1 : 2);
  return out.map((e, n) => [e, n] as const).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([e]) => e);
}

export interface Totals { n: number; passed: number; failed: number; skipped: number }
export function totalsOf(sources: AllSource[]): Totals {
  return sources.reduce((t, s) => ({ n: t.n + s.n, passed: t.passed + s.passed, failed: t.failed + s.failed, skipped: t.skipped + s.skipped }), { n: 0, passed: 0, failed: 0, skipped: 0 });
}

/** Counts per option, so each dropdown can show how many cards it would give. */
export function countBy(entries: AllEntry[], pick: (e: AllEntry) => string | null | undefined): [string, number][] {
  const m = new Map<string, number>();
  for (const e of entries) { const k = pick(e); if (k) m.set(k, (m.get(k) ?? 0) + 1); }
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
}
