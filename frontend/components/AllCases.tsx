"use client";
// "All measured cases": every case of every evaluation suite and every turn of every conversation run, as recorded.
// Data: /evals-all.json (static file written by evals/make_showcase.py from evals/results). Nothing is hand-written.
import Link from "next/link";
import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { getJSON } from "@/lib/api";
import { askHref } from "@/lib/ask";
import { applyFilters, countBy, NO_FILTERS, parseAll, prettify, totalsOf, type AllData, type AllEntry, type Filters, type ResultFilter } from "@/lib/evalsAll";
import { hasArabic } from "@/lib/format";
import { parseMarkdown, type Line } from "@/lib/md";
import { useApp } from "./AppContext";
import "./AllCases.css";

const PAGE = 24;
const S = {
  en: {
    title: "Every measured case",
    lede: "Every case of the evaluation suites and every turn of the conversation runs, as recorded: nothing is picked, nothing is hand-written. Failures are listed first and show the checks that failed.",
    loading: "Loading every recorded case…", error: "The full list could not be loaded. Reload the page to try again.",
    empty: "No recorded cases were found.",
    total: (n: number, p: number, f: number, k: number) => `${n.toLocaleString("en-GB")} measured · ${p.toLocaleString("en-GB")} passed · ${f.toLocaleString("en-GB")} failed${k ? ` · ${k} skipped` : ""}`,
    bySource: "Totals per source", source: "Source", run: "Run", measured: "Measured", passed: "Passed", failed: "Failed", skipped: "Skipped", rate: "Pass rate",
    filters: "Filters", fSource: "Source", fCategory: "Category", fPersona: "Persona", fResult: "Result", fAnswered: "Answered by", search: "Search questions and replies",
    searchPh: "Search, e.g. Trump, yield, injection", all: "All", noPersona: "No persona (suites and the 30 conversations)", clear: "Clear filters",
    results: { all: "All results", passed: "Passed", failed: "Failed", skipped: "Skipped" } as Record<ResultFilter, string>,
    showing: (a: number, b: number) => `Showing ${a.toLocaleString("en-GB")} of ${b.toLocaleString("en-GB")} matching`,
    more: (n: number) => `Show ${n} more`, none: "No case matches these filters.",
    then: "Then", reply: "Reply", pass: "Passed", fail: "Did not pass", skip: "Skipped", failedChecks: "Failed checks", checksOk: (n: number) => `All ${n} checks passed`,
    route: "Route", model: "Model", calls: (n: number) => `${n} AI call${n === 1 ? "" : "s"}`, judge: "Judge (1 to 5)",
    jDims: ["helpful", "honest", "tone", "fit"], capturedFrom: "Source", tryLive: "Try it live", firstTurn: "Sends the first question",
    paths: { template: "fixed reply", code: "built from data", llm_tool: "model with tools", llm_understanding: "model with tools" } as Record<string, string>,
    personas: { buyer: "Buyer", investor: "Investor", sales: "DarGlobal sales team", recruiter: "Recruiter / HR", ai_lead: "Head of AI" } as Record<string, string>,
    runs: (name: string) => name, stopped: "Stopped early",
    srcLabels: { "live model via NVIDIA": "live model via NVIDIA", "live model via OpenRouter": "live model via OpenRouter", "model mocked": "model mocked", "built by code": "built by code" } as Record<string, string>,
  },
  ar: {
    title: "كل حالة جرى قياسها",
    lede: "كل حالة في مجموعات التقييم وكل دور في محادثات الاختبار كما سُجّلت: لا انتقاء ولا كتابة يدوية. تظهر الإخفاقات أولًا مع الفحوص التي لم تُجتز.",
    loading: "جارٍ تحميل كل الحالات المسجّلة…", error: "تعذّر تحميل القائمة الكاملة. أعد تحميل الصفحة للمحاولة مجددًا.",
    empty: "لم تُعثر على حالات مسجّلة.",
    total: (n: number, p: number, f: number, k: number) => `${n.toLocaleString("en-GB")} حالة قيست · ${p.toLocaleString("en-GB")} اجتازت · ${f.toLocaleString("en-GB")} لم تجتز${k ? ` · ${k} تُخطّيت` : ""}`,
    bySource: "المجاميع حسب المصدر", source: "المصدر", run: "التشغيل", measured: "المقاسة", passed: "اجتازت", failed: "لم تجتز", skipped: "تُخطّيت", rate: "نسبة النجاح",
    filters: "التصفية", fSource: "المصدر", fCategory: "الفئة", fPersona: "الشخصية", fResult: "النتيجة", fAnswered: "كُتبت الإجابة بواسطة", search: "ابحث في الأسئلة والردود",
    searchPh: "ابحث، مثل: Trump أو yield أو injection", all: "الكل", noPersona: "بلا شخصية (المجموعات والمحادثات الثلاثون)", clear: "مسح التصفية",
    results: { all: "كل النتائج", passed: "اجتازت", failed: "لم تجتز", skipped: "تُخطّيت" } as Record<ResultFilter, string>,
    showing: (a: number, b: number) => `يُعرض ${a.toLocaleString("en-GB")} من ${b.toLocaleString("en-GB")} مطابقة`,
    more: (n: number) => `اعرض ${n} أخرى`, none: "لا توجد حالة تطابق هذه التصفية.",
    then: "ثم", reply: "الرد", pass: "اجتازت", fail: "لم تجتز", skip: "تُخطّيت", failedChecks: "الفحوص التي لم تُجتز", checksOk: (n: number) => `اجتازت كل الفحوص (${n})`,
    route: "المسار", model: "النموذج", calls: (n: number) => (n === 1 ? "استدعاء واحد للنموذج" : `${n} استدعاءات للنموذج`), judge: "المُحكِّم (من 1 إلى 5)",
    jDims: ["مفيد", "صادق", "النبرة", "الملاءمة"], capturedFrom: "المصدر", tryLive: "جرّبه مباشرة", firstTurn: "يرسل السؤال الأول",
    paths: { template: "رد ثابت", code: "مبني من البيانات", llm_tool: "نموذج بأدوات", llm_understanding: "نموذج بأدوات" } as Record<string, string>,
    personas: { buyer: "مشترٍ", investor: "مستثمر", sales: "فريق مبيعات دار جلوبال", recruiter: "مسؤول توظيف", ai_lead: "رئيس الذكاء الاصطناعي" } as Record<string, string>,
    runs: (name: string) => name, stopped: "توقف مبكرًا",
    srcLabels: { "live model via NVIDIA": "نموذج حقيقي عبر NVIDIA", "live model via OpenRouter": "نموذج حقيقي عبر OpenRouter", "model mocked": "نموذج مُحاكى", "built by code": "بُني بالشيفرة" } as Record<string, string>,
  },
};

const textDir = (s: string) => (hasArabic(s) ? "rtl" : "ltr");
const textLang = (s: string) => (hasArabic(s) ? "ar" : "en");
const day = (iso: string | null | undefined, lang: "en" | "ar") => {
  const d = iso ? new Date(iso) : null;
  return d && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" }).format(d) : "";
};
const rate = (p: number, n: number) => (n ? `${Math.round((p / n) * 1000) / 10}%` : "-");

function Reply({ text, truncated }: { text: string; truncated?: boolean }) {
  const rows: Line[] = parseMarkdown(text, true).flatMap((b) => (b.type === "p" ? b.lines : b.type === "h" ? [b.line] : b.items.map((it) => it.line)));
  return (
    <p className="stress__reply" dir={textDir(text)} lang={textLang(text)}>
      {rows.map((l, i) => (
        <span key={i}>{i > 0 && <br />}{l.map((s, k) => (s.strong ? <strong key={k}>{s.text}</strong> : <span key={k}>{s.text}</span>))}</span>
      ))}
      {truncated && <span aria-hidden="true">…</span>}
    </p>
  );
}

function Card({ e, d, s, lang }: { e: AllEntry; d: AllData; s: (typeof S)["en"]; lang: "en" | "ar" }) {
  const src = d.sources.find((x) => x.key === e.s);
  const label = s.srcLabels[e.src] ?? e.src;
  const first = e.q[0];
  return (
    <li className="gal__card ac__card">
      <div className="gal__head">
        <h3 className="stress__cat"><bdi>{e.i}</bdi> · {prettify(e.c ?? "case")}{e.p && <> · {s.personas[e.p] ?? prettify(e.p)}</>}</h3>
        <span className={e.ok === 1 ? "stress__ok" : e.ok === 0 ? "stress__bad" : "ac__skip"}>{e.ok === 1 ? s.pass : e.ok === 0 ? s.fail : s.skip}</span>
      </div>
      {e.q.map((q, n) => (
        <p key={n} className={n === e.q.length - 1 ? "stress__q" : "stress__q stress__q--then"} dir={textDir(q)} lang={textLang(q)}>
          {n > 0 && <><span className="stress__then">{s.then}</span>{" "}</>}<bdi dir={textDir(q)}>{q.trim() ? q : "(blank)"}</bdi>
        </p>
      ))}
      {e.a ? <><span className="sr-only">{s.reply}:</span><Reply text={e.a} truncated={e.t} /></> : <p className="muted small">{e.fd}</p>}
      {e.ok === 0 && e.f.length > 0 && (
        <div className="ac__fails">
          <p className="gal__sub">{s.failedChecks}</p>
          <ul className="gal__list">{e.f.map((k) => <li key={k} className="gal__no"><code>{k}</code></li>)}</ul>
          {e.fd && <p className="ac__why" dir="ltr" lang="en">{e.fd}</p>}
        </div>
      )}
      {e.ok === 1 && typeof e.x === "number" && e.x > 0 && <p className="stress__captured">{s.checksOk(e.x)}</p>}
      <ul className="stress__chips">
        <li className="ac__src">{label}</li>
        {e.r && <li>{s.route}: {s.paths[e.r] ?? <bdi>{e.r}</bdi>}</li>}
        {typeof e.n === "number" && <li>{s.calls(e.n)}</li>}
        {e.m && <li>{s.model}: <bdi dir="ltr">{e.m}</bdi></li>}
        {e.j && <li>{s.judge}: {e.j.map((v, i) => (v == null ? null : <span key={i} className="ac__j">{s.jDims[i]} {v}</span>))}</li>}
      </ul>
      <div className="stress__foot">
        <p className="stress__captured">{s.capturedFrom}: <bdi>{src?.name ?? e.s}</bdi>{src?.run_at ? <>, {day(src.run_at, lang)}</> : null}</p>
        {first && first.trim() && (
          <span className="gal__try"><Link className="stress__try" href={askHref(first)}>{s.tryLive}</Link>{e.q.length > 1 && <span className="stress__captured">{s.firstTurn}</span>}</span>
        )}
      </div>
    </li>
  );
}

function Select({ id, label, value, onChange, children }: { id: string; label: string; value: string; onChange: (v: string) => void; children: React.ReactNode }) {
  return (
    <div className="ac__field">
      <label htmlFor={id}>{label}</label>
      <select id={id} value={value} onChange={(ev) => onChange(ev.target.value)}>{children}</select>
    </div>
  );
}

export function AllCases() {
  const { lang } = useApp();
  const s = S[lang];
  const [data, setData] = useState<AllData | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [f, setF] = useState<Filters>(NO_FILTERS);
  const [limit, setLimit] = useState(PAGE);
  const q = useDeferredValue(f.query);

  useEffect(() => {
    const ac = new AbortController();
    getJSON<unknown>("/evals-all.json", ac.signal)
      .then((raw) => { const p = parseAll(raw); if (p) { setData(p); setState("ready"); } else setState("error"); })
      .catch(() => { if (!ac.signal.aborted) setState("error"); });
    return () => ac.abort();
  }, []);

  const set = (patch: Partial<Filters>) => { setF((v) => ({ ...v, ...patch })); setLimit(PAGE); };
  const matches = useMemo(() => (data ? applyFilters(data.entries, { ...f, query: q }) : []), [data, f, q]);
  const totals = useMemo(() => (data ? totalsOf(data.sources) : null), [data]);
  const cats = useMemo(() => (data ? countBy(data.entries, (e) => e.c) : []), [data]);
  const answered = useMemo(() => (data ? countBy(data.entries, (e) => e.src) : []), [data]);
  const personas = useMemo(() => (data ? countBy(data.entries, (e) => e.p) : []), [data]);
  const dirty = JSON.stringify(f) !== JSON.stringify(NO_FILTERS);

  return (
    <section className="stress stress--full ac" id="all-cases" aria-labelledby="all-cases-h" lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <h2 id="all-cases-h">{s.title}</h2>
      <p className="stress__lede">{s.lede}</p>
      {state === "loading" && <p className="muted" role="status">{s.loading}</p>}
      {state === "error" && <p className="stress__empty">{s.error}</p>}
      {state === "ready" && data && data.entries.length === 0 && <p className="stress__empty">{s.empty}</p>}
      {state === "ready" && data && totals && data.entries.length > 0 && (
        <>
          <p className="gal__summary ac__total">{s.total(totals.n, totals.passed, totals.failed, totals.skipped)}</p>
          <div className="table-wrap">
            <table className="data-table data-table--stack ac__table">
              <caption className="sr-only">{s.bySource}</caption>
              <thead><tr><th>{s.source}</th><th>{s.run}</th><th className="num">{s.measured}</th><th className="num">{s.passed}</th><th className="num">{s.failed}</th><th className="num">{s.skipped}</th><th className="num">{s.rate}</th></tr></thead>
              <tbody>
                {data.sources.map((x) => (
                  <tr key={x.key}>
                    <td><button type="button" className="ac__link" onClick={() => set({ source: x.key })}>{x.name}</button>
                      {x.stop_reason && <span className="ac__stop muted small"> ({s.stopped}: {x.stop_reason})</span>}</td>
                    <td data-label={s.run}>{day(x.run_at, lang)}</td>
                    <td className="num" data-label={s.measured}>{x.n}</td><td className="num" data-label={s.passed}>{x.passed}</td>
                    <td className="num" data-label={s.failed}>{x.failed}</td><td className="num" data-label={s.skipped}>{x.skipped}</td>
                    <td className="num" data-label={s.rate}>{rate(x.passed, x.n - x.skipped)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <form className="ac__filters" role="search" aria-label={s.filters} onSubmit={(ev) => ev.preventDefault()}>
            <div className="ac__field ac__field--search">
              <label htmlFor="ac-q">{s.search}</label>
              <input id="ac-q" type="search" value={f.query} placeholder={s.searchPh} onChange={(ev) => set({ query: ev.target.value })} autoComplete="off" />
            </div>
            <Select id="ac-src" label={s.fSource} value={f.source} onChange={(v) => set({ source: v })}>
              <option value="all">{s.all}</option>
              {data.sources.map((x) => <option key={x.key} value={x.key}>{x.name} ({x.n})</option>)}
            </Select>
            <Select id="ac-cat" label={s.fCategory} value={f.category} onChange={(v) => set({ category: v })}>
              <option value="all">{s.all}</option>
              {cats.map(([k, n]) => <option key={k} value={k}>{prettify(k)} ({n})</option>)}
            </Select>
            <Select id="ac-per" label={s.fPersona} value={f.persona} onChange={(v) => set({ persona: v })}>
              <option value="all">{s.all}</option>
              <option value="none">{s.noPersona}</option>
              {personas.map(([k, n]) => <option key={k} value={k}>{s.personas[k] ?? prettify(k)} ({n})</option>)}
            </Select>
            <Select id="ac-res" label={s.fResult} value={f.result} onChange={(v) => set({ result: v as ResultFilter })}>
              {(Object.keys(s.results) as ResultFilter[]).map((k) => <option key={k} value={k}>{s.results[k]}</option>)}
            </Select>
            <Select id="ac-ans" label={s.fAnswered} value={f.answered} onChange={(v) => set({ answered: v })}>
              <option value="all">{s.all}</option>
              {answered.map(([k, n]) => <option key={k} value={k}>{s.srcLabels[k] ?? k} ({n})</option>)}
            </Select>
            {dirty && <button type="button" className="gal__chip ac__clear" onClick={() => { setF(NO_FILTERS); setLimit(PAGE); }}>{s.clear}</button>}
          </form>

          <p className="gal__summary" role="status" aria-live="polite">{s.showing(Math.min(limit, matches.length), matches.length)}</p>
          {matches.length === 0 ? <p className="stress__empty">{s.none}</p> : (
            <ul className="gal__grid">
              {matches.slice(0, limit).map((e) => <Card key={`${e.s}|${e.i}`} e={e} d={data} s={s} lang={lang} />)}
            </ul>
          )}
          {matches.length > limit && (
            <button type="button" className="stress__try ac__more" onClick={() => setLimit((v) => v + PAGE)}>{s.more(Math.min(PAGE, matches.length - limit))}</button>
          )}
        </>
      )}
    </section>
  );
}
