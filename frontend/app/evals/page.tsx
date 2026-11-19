"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { PageShell } from "@/components/PageShell";
import { getJSON } from "@/lib/api";

type J = Record<string, unknown>;
const isObj = (v: unknown): v is J => typeof v === "object" && v !== null && !Array.isArray(v);
const isScalar = (v: unknown) => v === null || ["string", "number", "boolean"].includes(typeof v);
const label = (k: string) => k.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());
const pct = (n: number) => (n <= 1 ? Math.round(n * 1000) / 10 : Math.round(n * 10) / 10);

function fmt(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : String(Math.round(v * 1000) / 1000);
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "string") return v;
  return JSON.stringify(v);
}

function scoreOf(o: J): number | null {
  for (const k of ["score", "pass_rate", "accuracy", "value", "rate"]) if (typeof o[k] === "number") return o[k] as number;
  return null;
}

function ScoreTable({ data }: { data: J }) {
  const rows = Object.entries(data);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr><th>Measure</th><th className="num">Result</th><th className="num">Target</th><th className="num">n</th><th>Status</th></tr></thead>
        <tbody>
          {rows.map(([k, v]) => {
            const o = isObj(v) ? v : { score: v };
            const s = scoreOf(o);
            const target = typeof o.target === "number" ? (o.target as number) : null;
            const passed = typeof o.passed === "boolean" ? (o.passed as boolean) : s != null && target != null ? s >= target : null;
            return (
              <tr key={k}>
                <td>{label(k)}</td>
                <td className="num">
                  {s != null && s <= 1 && <span className="meter" style={{ ["--w" as string]: `${Math.round(s * 100)}%` }} aria-hidden="true" />}
                  {s != null ? (s <= 1 ? `${pct(s)}%` : fmt(s)) : fmt(v)}
                </td>
                <td className="num">{target != null ? (target <= 1 ? `${pct(target)}%` : fmt(target)) : "—"}</td>
                <td className="num">{fmt(o.n ?? o.count ?? o.total ?? null)}</td>
                <td>{passed == null ? "—" : passed ? <span className="pass">Meets target</span> : <span className="fail">Below target</span>}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function RowsTable({ rows }: { rows: J[] }) {
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).filter((c) => rows.every((r) => isScalar(r[c]) || r[c] === undefined)).slice(0, 7);
  return (
    <div className="table-wrap">
      <table className="data-table">
        <thead><tr>{cols.map((c) => <th key={c}>{label(c)}</th>)}</tr></thead>
        <tbody>{rows.slice(0, 50).map((r, i) => <tr key={i}>{cols.map((c) => <td key={c}>{fmt(r[c])}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

function Section({ name, value }: { name: string; value: unknown }) {
  if (isObj(value)) {
    const vals = Object.values(value);
    const scoreLike = vals.length > 0 && vals.every((v) => typeof v === "number" || (isObj(v) && scoreOf(v) != null));
    if (scoreLike) return (<section><h2>{label(name)}</h2><ScoreTable data={value} /></section>);
    const scalars = Object.entries(value).filter(([, v]) => isScalar(v));
    const nested = Object.entries(value).filter(([, v]) => !isScalar(v));
    return (
      <section>
        <h2>{label(name)}</h2>
        {scalars.length > 0 && <dl className="deflist">{scalars.map(([k, v]) => (<div key={k} style={{ display: "contents" }}><dt>{label(k)}</dt><dd>{fmt(v)}</dd></div>))}</dl>}
        {nested.map(([k, v]) => <Sub key={k} name={k} value={v} />)}
      </section>
    );
  }
  if (Array.isArray(value) && value.length && value.every(isObj)) return (<section><h2>{label(name)}</h2><RowsTable rows={value as J[]} /></section>);
  return null;
}
function Sub({ name, value }: { name: string; value: unknown }) {
  if (isObj(value)) {
    const vals = Object.values(value);
    if (vals.length && vals.every((v) => typeof v === "number" || (isObj(v) && scoreOf(v) != null))) return (<><h3>{label(name)}</h3><ScoreTable data={value} /></>);
  }
  if (Array.isArray(value) && value.length && value.every(isObj)) return (<><h3>{label(name)}</h3><RowsTable rows={value as J[]} /></>);
  return null;
}

export default function Evals() {
  const [data, setData] = useState<J | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    getJSON<J>("/api/evals").then((d) => { setData(isObj(d) ? d : {}); setState("ready"); }).catch(() => setState("error"));
  }, []);
  const empty = state === "ready" && data && Object.keys(data).length === 0;
  const topScalars = data ? Object.entries(data).filter(([, v]) => isScalar(v)) : [];
  const sections = data ? Object.entries(data).filter(([, v]) => !isScalar(v)) : [];

  return (
    <PageShell>
      <div lang="en" dir="ltr">
        <h1>Evaluation results</h1>
        <p className="lede">The latest run of the evaluation suite against this deployment, as recorded. Numbers are shown as measured, including the ones below target.</p>

        {state === "loading" && <p className="muted" role="status">Loading the latest report…</p>}
        {state === "error" && (
          <div className="empty"><h2>The report could not be loaded</h2><p>The evaluation endpoint did not respond. Reload the page to try again.</p></div>
        )}
        {empty && (
          <div className="empty">
            <h2>No evaluation run has been published yet</h2>
            <p>Results appear here after the suite runs: the reviewer questions, factual accuracy, Arabic quality, hallucination traps, injection attempts and calculations, each against its target.</p>
            <Link href="/how-it-works/">Read how answers are built</Link>
          </div>
        )}
        {data && !empty && (
          <>
            {topScalars.length > 0 && (
              <dl className="deflist">{topScalars.map(([k, v]) => (<div key={k} style={{ display: "contents" }}><dt>{label(k)}</dt><dd>{fmt(v)}</dd></div>))}</dl>
            )}
            {sections.map(([k, v]) => <Section key={k} name={k} value={v} />)}
            <details className="raw"><summary>Raw report JSON</summary><pre>{JSON.stringify(data, null, 2)}</pre></details>
          </>
        )}
      </div>
    </PageShell>
  );
}
