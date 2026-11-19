"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { getJSON } from "@/lib/api";

type J = Record<string, unknown>;
type Cat = { passed: number; failed: number; skipped: number; rate: number | null };
type Target = { target: number; op: string; actual: number | null; met?: boolean; note?: string };
type Case = { id: string; category: string; lang?: string; status: string; failures?: string[]; skip_reason?: string; reason?: string };

const isObj = (v: unknown): v is J => typeof v === "object" && v !== null && !Array.isArray(v);
const label = (k: string) => k.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const pct = (n: number) => `${Math.round(n * 1000) / 10}%`;
const ms = (n: unknown) => (typeof n === "number" ? `${Math.round(n).toLocaleString("en-GB")} ms` : "Not measured");

function fmtWhen(iso: unknown): string {
  if (typeof iso !== "string") return "Not recorded";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short", timeZone: "UTC" }) + " UTC";
}

/** Which headline target, if any, a category is measured against. */
const CAT_TARGET: Record<string, string> = {
  factual: "factual_rate", trap: "trap_rate", injection: "injection_rate", arabic: "arabic_rate",
};

const CAT_NOTES: Record<string, string> = {
  reviewer: "The failed reviewer questions ask about DarGlobal (for example, projects in Oman). DarGlobal pages could not be collected, so the honest answer is “no verified information” and these cases fail by design of the data, not of the code.",
  factual: "Factual cases check that the answer cites a source for a fact present in the database. The three skipped cases bind to DarGlobal rows, which do not exist in this dataset.",
  live_sample: "Sampled from the local database built from the live sites. The runner never contacts the live sites, so this is not a live-site verification.",
  arabic: "Scored by rules (language, direction, citation). The Arabic LLM judge was not used in this run.",
  injection: "The planted-chunk case (indirect injection through retrieved text) needs a model and was skipped.",
};

function metText(t: Target | undefined, rate: number | null): React.ReactNode {
  if (!t || rate == null) return <span className="muted">No target</span>;
  const met = t.op === "<=" ? rate <= t.target : rate >= t.target;
  return met ? <span className="pass">Meets target</span> : <span className="fail">Below target</span>;
}

export default function Evals() {
  const [data, setData] = useState<J | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    getJSON<J>("/api/evals").then((d) => { setData(isObj(d) ? d : {}); setState("ready"); }).catch(() => setState("error"));
  }, []);
  const empty = state === "ready" && data && Object.keys(data).length === 0;
  const totals = (data?.totals ?? {}) as { passed?: number; failed?: number; skipped?: number; by_category?: Record<string, Cat> };
  const targets = (data?.targets ?? {}) as Record<string, Target>;
  const latency = (data?.latency ?? {}) as Record<string, number>;
  const ctx = (data?.run_context ?? {}) as J;
  const cases = (Array.isArray(data?.cases) ? data?.cases : []) as Case[];
  const notOk = cases.filter((c) => c.status !== "passed");

  return (
    <PageShell>
      <div lang="en" dir="ltr">
        <h1>Evaluation results</h1>
        <p className="lede">The latest run of the evaluation suite, as recorded. Numbers are shown as measured, including the ones below target.</p>

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
              <dt>Dataset</dt><dd><code>{String(data.dataset_version ?? "unknown")}</code>, data as of {fmtWhen(data.data_as_of)}</dd>
              <dt>Cases</dt><dd>{totals.passed ?? 0} passed, {totals.failed ?? 0} failed, {totals.skipped ?? 0} skipped</dd>
              <dt>Language model</dt><dd>{ctx.llm_available ? "Configured" : "Not configured: every answer used the code-built (degraded) path"}</dd>
              <dt>LLM judge</dt><dd>{ctx.judge_used ? "Used" : "Not used in this run"}</dd>
            </dl>

            <section>
              <h2>Headline targets</h2>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Measure</th><th className="num">Result</th><th className="num">Target</th><th>Status</th></tr></thead>
                  <tbody>
                    {Object.entries(targets).map(([k, t]) => {
                      const isMs = k.endsWith("_ms");
                      const isRate = k.endsWith("_rate");
                      const show = (v: number | null) => v == null ? "Not measured" : isMs ? ms(v) : isRate ? pct(v) : String(v);
                      return (
                        <tr key={k}>
                          <td>{label(k.replace(/_ms$/, ""))}</td>
                          <td className="num">{show(t.actual)}</td>
                          <td className="num">{t.op === "<=" ? "≤" : "≥"} {show(t.target)}</td>
                          <td>{t.actual == null ? <span className="muted">{t.note ?? "Not measured"}</span> : metText(t, t.actual)}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </section>

            <section>
              <h2>By category</h2>
              <div className="table-wrap">
                <table className="data-table">
                  <thead><tr><th>Category</th><th className="num">Pass rate</th><th className="num">n</th><th className="num">Skipped</th><th>Target</th></tr></thead>
                  <tbody>
                    {Object.entries(totals.by_category ?? {}).map(([k, c]) => (
                      <tr key={k}>
                        <td>{label(k)}</td>
                        <td className="num">{c.rate == null ? "—" : pct(c.rate)}</td>
                        <td className="num">{c.passed + c.failed}</td>
                        <td className="num">{c.skipped}</td>
                        <td>{CAT_TARGET[k] ? metText(targets[CAT_TARGET[k]], c.rate) : <span className="muted">No target</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="small">
                {Object.keys(totals.by_category ?? {}).filter((k) => CAT_NOTES[k]).map((k) => <li key={k}><strong>{label(k)}:</strong> {CAT_NOTES[k]}</li>)}
              </ul>
            </section>

            <section>
              <h2>Latency</h2>
              <p className="muted small">Measured locally against the code-built path (no model), over {latency.n ?? 0} requests. Times with a real model will be higher.</p>
              <dl className="deflist">
                <dt>Median total</dt><dd>{ms(latency.p50)}</dd>
                <dt>95th percentile total</dt><dd>{ms(latency.p95)}</dd>
                <dt>Median first token</dt><dd>{ms(latency.ttft_p50)}</dd>
                <dt>95th percentile first token</dt><dd>{ms(latency.ttft_p95)}</dd>
              </dl>
            </section>

            {notOk.length > 0 && (
              <section>
                <h2>Failed and skipped cases</h2>
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Case</th><th>Category</th><th>Lang</th><th>Status</th><th>Why</th></tr></thead>
                    <tbody>
                      {notOk.map((c) => (
                        <tr key={c.id}>
                          <td><code>{c.id}</code></td><td>{label(c.category)}</td><td>{c.lang ?? ""}</td>
                          <td className={c.status === "failed" ? "fail" : "muted"}>{c.status}</td>
                          <td className="small">{(c.failures ?? []).join("; ") || c.skip_reason || c.reason || ""}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </section>
            )}
            <details className="raw"><summary>Raw report JSON</summary><pre>{JSON.stringify({ ...data, base_url: undefined }, null, 2)}</pre></details>
          </>
        )}
      </div>
    </PageShell>
  );
}
