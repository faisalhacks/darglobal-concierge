"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { StressTested } from "@/components/StressTested"; // showcase: follows the interface language
import { getJSON } from "@/lib/api";

type J = Record<string, unknown>;
type Cat = { passed: number; failed: number; skipped: number; rate: number | null };
type Target = { target: number; op: string; actual: number | null; met?: boolean | null; note?: string; n?: number; ci95?: [number, number] };
type Case = { id: string; category: string; lang?: string; status: string; failures?: string[]; skip_reason?: string; reason?: string };
type LangRow = { passed: number; failed: number; rate: number | null; ci95?: [number, number] };
type Live = { run_at?: string; llm_calls?: number; n?: number; passed?: number; failed?: number; models_answered?: Record<string, number>; cases?: Case[] };

const NM = "Not measured";
const isObj = (v: unknown): v is J => typeof v === "object" && v !== null && !Array.isArray(v);
const isNum = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const NAMES: Record<string, string> = {
  ttft_p95_ms: "First token, 95th percentile", false_refusal_rate: "False refusals", citation_rate: "Answers with a source",
  factual_rate: "Factual accuracy", trap_rate: "Traps handled", injection_rate: "Injections refused", arabic_rate: "Arabic",
  crashes: "Crashes", lighthouse_mobile: "Lighthouse, mobile",
};
const label = (k: string) => NAMES[k] ?? k.replace(/_rate$/, "").replace(/_ms$/, "").replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const pct = (n: number) => `${Math.round(n * 1000) / 10}%`;
const ms = (n: unknown) => (isNum(n) ? `${Math.round(n).toLocaleString("en-GB")} ms` : NM);
const LANGS: Record<string, string> = { en: "English", ar: "Arabic", mixed: "Mixed" };

function fmtWhen(iso: unknown): string {
  if (typeof iso !== "string") return "Not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) return d.toLocaleDateString("en-GB", { dateStyle: "medium", timeZone: "UTC" });
  return d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

function showValue(k: string, v: number | null | undefined) {
  if (!isNum(v)) return NM;
  if (k.endsWith("_ms")) return ms(v);
  if (k.endsWith("_rate")) return pct(v);
  return v.toLocaleString("en-GB");
}
const ci = (c: unknown, asPct = true) =>
  Array.isArray(c) && c.length === 2 && isNum(c[0]) && isNum(c[1]) ? (asPct ? `${pct(c[0])} to ${pct(c[1])}` : `${c[0]} to ${c[1]}`) : NM;

function Met({ t }: { t: Target }) {
  if (!isNum(t.actual)) return <span className="muted">{t.note ? `${NM}: ${t.note}` : NM}</span>;
  const met = typeof t.met === "boolean" ? t.met : t.op === "<=" ? t.actual <= t.target : t.actual >= t.target;
  return met ? <span className="pass">Met</span> : <span className="fail">Not met</span>;
}

function why(c: Case) { return (c.failures ?? []).join("; ") || c.skip_reason || c.reason || ""; }

function CasesTable({ cases }: { cases: Case[] }) {
  const rank = (s: string) => (s === "failed" ? 0 : s === "skipped" ? 1 : 2);
  const sorted = [...cases].sort((a, b) => rank(a.status) - rank(b.status));
  const notOk = sorted.filter((c) => c.status !== "passed");
  const [all, setAll] = useState(false);
  const rows = all ? sorted : notOk;
  return (
    <>
      {rows.length > 0 ? (
        <div className="table-wrap">
          <table className="data-table data-table--wrap">
            <thead><tr><th>Case</th><th>Category</th><th>Language</th><th>Result</th><th>Why</th></tr></thead>
            <tbody>
              {rows.map((c) => (
                <tr key={c.id}>
                  <td>{c.id}</td><td>{label(c.category)}</td><td>{LANGS[c.lang ?? ""] ?? c.lang ?? ""}</td>
                  <td className={c.status === "failed" ? "fail" : c.status === "skipped" ? "muted" : "pass"}>{label(c.status)}</td>
                  <td className="small">{why(c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : <p>Every case passed.</p>}
      {sorted.length > notOk.length && (
        <button type="button" className="btn-quiet evals__more" aria-expanded={all} onClick={() => setAll((v) => !v)}>
          {all ? "Show failures and skips only" : `Show all ${sorted.length} cases`}
        </button>
      )}
    </>
  );
}

/** Walks nested E1-style results down to rows of numeric metrics: {path: {metric: value}}. */
function flatten(o: unknown, path: string[] = [], out: { path: string[]; vals: Record<string, number> }[] = []) {
  if (!isObj(o)) return out;
  const nums = Object.entries(o).filter(([, v]) => isNum(v));
  if (nums.length && nums.length === Object.keys(o).length) { out.push({ path, vals: Object.fromEntries(nums) as Record<string, number> }); return out; }
  for (const [k, v] of Object.entries(o)) if (isObj(v)) flatten(v, [...path, k], out);
  return out;
}

function Retrieval({ r }: { r: unknown }) {
  const src = isObj(r) && isObj(r.results) ? r.results : r;
  const rows = flatten(src);
  if (!rows.length) return <p className="muted">{NM}</p>;
  const depth = Math.max(...rows.map((x) => x.path.length));
  const metrics = [...new Set(rows.flatMap((x) => Object.keys(x.vals)))].filter((m) => rows.some((x) => isNum(x.vals[m])));
  const heads = depth === 3 ? ["Variant", "Method", "Query set"] : depth === 2 ? ["Method", "Query set"] : Array.from({ length: depth }, (_, i) => (i === 0 ? "Group" : ""));
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr>{heads.map((h, i) => <th key={i}>{h}</th>)}{metrics.map((m) => <th key={m} className="num">{m === "ms_per_query" ? "ms per query" : m}</th>)}</tr></thead>
        <tbody>
          {rows.map((x) => (
            <tr key={x.path.join("/")}>
              {x.path.map((p, i) => <td key={i}>{p.replace(/_/g, " ")}</td>)}
              {metrics.map((m) => <td key={m} className="num">{isNum(x.vals[m]) ? (m === "n" ? x.vals[m] : Number(x.vals[m].toFixed(3))) : ""}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Confusion({ c }: { c: Record<string, Record<string, number>> }) {
  const expected = Object.keys(c);
  const predicted = [...new Set([...expected, ...expected.flatMap((e) => Object.keys(c[e] ?? {}))])];
  return (
    <div className="table-wrap">
      <table className="data-table matrix">
        <caption className="sr-only">Rows are the expected intent, columns the intent the planner chose</caption>
        <thead>
          <tr><th scope="col">Expected, then chosen</th>{predicted.map((p) => <th scope="col" key={p} className="num">{label(p)}</th>)}</tr>
        </thead>
        <tbody>
          {expected.map((e) => (
            <tr key={e}>
              <th scope="row">{label(e)}</th>
              {predicted.map((p) => {
                const v = c[e]?.[p] ?? 0;
                return <td key={p} className={`num${v ? (p === e ? " matrix__hit" : " matrix__miss") : " matrix__zero"}`}>{v || ""}</td>;
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Evals() {
  const [data, setData] = useState<J | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    getJSON<J>("/api/evals").then((d) => { setData(isObj(d) ? d : {}); setState("ready"); }).catch(() => setState("error"));
  }, []);
  const empty = state === "ready" && data && Object.keys(data).length === 0;
  const totals = (data?.totals ?? {}) as { passed?: number; failed?: number; skipped?: number; by_category?: Record<string, Cat> };
  const targets = (isObj(data?.targets) ? data?.targets : {}) as Record<string, Target>;
  const latency = (isObj(data?.latency) ? data?.latency : {}) as Record<string, number>;
  const ctx = (isObj(data?.run_context) ? data?.run_context : {}) as J;
  const cases = (Array.isArray(data?.cases) ? data?.cases : []) as Case[];
  const byLang = (isObj(data?.by_language) ? data?.by_language : null) as Record<string, LangRow> | null;
  const live = (isObj(data?.live_subset) ? data?.live_subset : null) as Live | null;
  const confusion = (isObj(data?.confusion) ? data?.confusion : null) as Record<string, Record<string, number>> | null;
  const tRows = Object.entries(targets);
  const hasCi = tRows.some(([, t]) => Array.isArray(t.ci95));
  const hasN = tRows.some(([, t]) => isNum(t.n));
  const cats = Object.entries(totals.by_category ?? {});
  const anySkipped = cats.some(([, c]) => c.skipped > 0);
  const langCi = byLang ? Object.values(byLang).some((r) => Array.isArray(r.ci95)) : false;
  const mode = typeof ctx.llm_mode === "string" ? ctx.llm_mode : ctx.llm_available ? "live" : "mock";

  return (
    <PageShell englishOnly>
      <div lang="en" dir="ltr">
        <h1>Evaluation results</h1>
        <p className="lede">The latest run of the evaluation suite, as recorded. Results below target are shown as they were measured.</p>
        <StressTested variant="full" />

        {state === "loading" && <p className="muted" role="status">Loading the latest report…</p>}
        {state === "error" && (
          <div className="empty"><h2>The report could not be loaded</h2><p>The evaluation endpoint did not respond. Reload the page to try again.</p></div>
        )}
        {empty && (
          <div className="empty">
            <h2>No evaluation run has been published yet</h2>
            <p>Results appear here after the suite runs.</p>
            <Link href="/how-it-works/">Read how answers are built</Link>
          </div>
        )}
        {data && !empty && (
          <>
            <dl className="deflist">
              <dt>Run at</dt><dd>{fmtWhen(data.run_at)}</dd>
              <dt>Dataset</dt><dd><span dir="ltr">{String(data.dataset_version ?? "unknown")}</span>, data as of {fmtWhen(data.data_as_of)}</dd>
              <dt>Cases</dt><dd>{totals.passed ?? 0} passed, {totals.failed ?? 0} failed, {totals.skipped ?? 0} skipped</dd>
              <dt>How the suite ran</dt>
              <dd>{mode === "live" ? "Against a real free model." : "With the language model mocked, so every answer took the code-built path. Real-model results are in their own section below."}</dd>
              <dt>Arabic scoring</dt><dd>{ctx.judge_used ? "An LLM judge was used." : "Deterministic checks (language, direction, citation) plus the owner's spot check. No LLM judge."}</dd>
            </dl>

            <section>
              <h2>Scores against targets</h2>
              {tRows.length ? (
                <div className="table-wrap">
                  <table className="data-table data-table--stack">
                    <thead><tr>
                      <th>Measure</th><th className="num">Result</th><th className="num">Target</th>
                      {hasCi && <th className="num">95% interval</th>}{hasN && <th className="num">Cases</th>}<th>Met</th>
                    </tr></thead>
                    <tbody>
                      {tRows.map(([k, t]) => (
                        <tr key={k}>
                          <td>{label(k)}</td>
                          <td className="num" data-label="Result">{showValue(k, t.actual)}</td>
                          <td className="num" data-label="Target">{t.op === "<=" ? "≤" : "≥"} {showValue(k, t.target)}</td>
                          {hasCi && <td className="num" data-label="95% interval">{ci(t.ci95, k.endsWith("_rate"))}</td>}
                          {hasN && <td className="num" data-label="Cases">{isNum(t.n) ? t.n : NM}</td>}
                          <td data-label="Met"><Met t={t} /></td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="muted">{NM}</p>}
            </section>

            <section>
              <h2>By language</h2>
              {byLang ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Language</th><th className="num">Passed</th><th className="num">Failed</th><th className="num">Pass rate</th>{langCi && <th className="num">95% interval</th>}</tr></thead>
                    <tbody>
                      {Object.entries(byLang).map(([k, r]) => (
                        <tr key={k}>
                          <td>{LANGS[k] ?? k}</td><td className="num">{r.passed}</td><td className="num">{r.failed}</td>
                          <td className="num">{isNum(r.rate) ? pct(r.rate) : NM}</td>{langCi && <td className="num">{ci(r.ci95)}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="muted">{NM}</p>}
            </section>

            <section>
              <h2>By category</h2>
              {cats.length ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Category</th><th className="num">Pass rate</th><th className="num">Passed</th><th className="num">Failed</th>{anySkipped && <th className="num">Skipped</th>}</tr></thead>
                    <tbody>
                      {cats.map(([k, c]) => (
                        <tr key={k}>
                          <td>{label(k)}</td>
                          <td className="num">{isNum(c.rate) ? pct(c.rate) : NM}</td>
                          <td className="num">{c.passed}</td><td className="num">{c.failed}</td>
                          {anySkipped && <td className="num">{c.skipped}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : <p className="muted">{NM}</p>}
            </section>

            <section>
              <h2>Real-model subset</h2>
              {live ? (
                <>
                  <p>
                    {live.n ?? 0} cases sent to a real free model on {fmtWhen(live.run_at)}, using {live.llm_calls ?? 0} model calls:
                    {" "}{live.passed ?? 0} passed, {live.failed ?? 0} failed.
                    {live.models_answered && Object.keys(live.models_answered).length > 0 && (
                      <> Answered by {Object.entries(live.models_answered).map(([m, n], i, a) => (
                        <span key={m}><span dir="ltr">{m}</span> ({n}){i < a.length - 1 ? ", " : "."}</span>
                      ))}</>
                    )}
                  </p>
                  {Array.isArray(live.cases) && live.cases.length > 0 && <CasesTable cases={live.cases} />}
                </>
              ) : <p className="muted">{NM}: no real-model run is recorded in this report.</p>}
            </section>

            <section>
              <h2>Intent routing</h2>
              <p className="muted small">Each row is the intent a case expected; each column is the intent the planner chose. Off-diagonal numbers are misroutes.</p>
              {confusion && Object.keys(confusion).length ? <Confusion c={confusion} /> : <p className="muted">{NM}</p>}
            </section>

            <section>
              <h2>Retrieval (experiment E1)</h2>
              {data.retrieval ? <Retrieval r={data.retrieval} /> : <p className="muted">{NM}</p>}
            </section>

            <section>
              <h2>Latency</h2>
              <p className="muted small">Measured locally over {isNum(latency.n) ? latency.n : 0} requests{mode === "live" ? "" : " on the code-built path; times with a real model are higher"}.</p>
              <dl className="deflist">
                <dt>Median total</dt><dd>{ms(latency.p50)}</dd>
                <dt>95th percentile total</dt><dd>{ms(latency.p95)}</dd>
                <dt>Median first token</dt><dd>{ms(latency.ttft_p50)}</dd>
                <dt>95th percentile first token</dt><dd>{ms(latency.ttft_p95)}</dd>
              </dl>
            </section>

            <section>
              <h2>Cases</h2>
              {cases.length ? <CasesTable cases={cases} /> : <p className="muted">{NM}</p>}
            </section>
            <details className="raw"><summary>Raw report JSON</summary><pre>{JSON.stringify({ ...data, base_url: undefined, run_context: isObj(data.run_context) ? { ...data.run_context, db_path: undefined } : data.run_context }, null, 2)}</pre></details>
          </>
        )}
      </div>
    </PageShell>
  );
}
