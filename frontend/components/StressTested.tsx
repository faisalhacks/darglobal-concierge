"use client";
// "Stress-tested": hostile and odd questions with the replies exactly as an eval run recorded them.
// Data: GET /api/showcase (data/showcase.json, written by evals/make_showcase.py from evals/results). Nothing here is
// hand-written about a reply: question, excerpt, trace and verdict all come from that file. {} renders an empty state.
import Link from "next/link";
import { useEffect, useId, useRef, useState } from "react";
import { getJSON } from "@/lib/api";
import { askHref, askInChat } from "@/lib/ask";
import { hasArabic } from "@/lib/format";
import { parseMarkdown, type Line } from "@/lib/md";
import type { Lang } from "@/lib/types";
import { useApp } from "./AppContext";
import "./StressTested.css";

type L10n = { en: string; ar: string };
export interface ShowcaseScenario {
  id: string; case_id: string; category: L10n; lang?: string; question: string; follow_ups?: string[];
  reply_excerpt: string; reply_truncated?: boolean; cards_count: number; sources_count: number;
  trace: { intent?: string | null; path?: string | null; llm_calls?: number | null; llm_calls_basis?: string; model?: string | null; latency_ms?: number | null };
  passed: boolean; failures?: string[]; verdict?: L10n; rail?: boolean;
  captured_at?: string | null; host?: string | null; llm_mode?: string | null; dataset_version?: string | null; source_file?: string;
}
export interface Showcase { generated_at?: string; rail_order?: string[]; scenarios?: ShowcaseScenario[] }

const S = {
  en: {
    title: "Stress-tested",
    railLede: "Questions picked to trip a property assistant up, with what it actually did in the last recorded test run.",
    fullLede: "Questions picked to trip a property assistant up. Each reply is quoted exactly as the test run recorded it, cut at 220 characters, with the route it took.",
    mockNote: "In the mocked run the language model was replaced by a stub, so answers built from data show no model; refusals and other fixed replies never call a model in any mode.",
    tryLive: "Try it live",
    seeAll: (n: number) => `All ${n} recorded scenarios`,
    passed: "Passed", failed: "Did not pass",
    then: "Then",
    reply: "Reply",
    captured: (host: string | null, when: string) => (host ? `Captured from ${host} on ${when}` : `Captured from a live-model run on ${when}`),
    intent: "Intent", path: "Route",
    calls: (n: number) => `${n} AI call${n === 1 ? "" : "s"}`,
    callsMocked: "Model mocked", callsUnknown: "AI calls not recorded",
    model: "Model", ms: (n: number) => `${n.toLocaleString("en-GB")} ms`,
    cards: (n: number) => `${n} card${n === 1 ? "" : "s"}`, sources: (n: number) => `${n} source${n === 1 ? "" : "s"}`,
    pick: "Scenario", trace: "How it was handled", loading: "Loading the recorded scenarios…",
    empty: "No stress-test captures are published yet. They appear here after the evaluation suite runs and the showcase file is rebuilt from its results.",
    error: "The stress-test captures could not be loaded. Reload the page to try again.",
    paths: { template: "fixed reply", code: "built from data", llm_tool: "model with tools" } as Record<string, string>,
  },
  ar: {
    title: "اختُبر تحت الضغط",
    railLede: "أسئلة اختيرت لإرباك المساعد العقاري، ومعها ما فعله فعلًا في آخر تشغيل مسجّل للاختبارات.",
    fullLede: "أسئلة اختيرت لإرباك المساعد العقاري. كل رد مقتبس كما سجّله تشغيل الاختبار حرفيًا، مقتطعًا عند 220 حرفًا، مع المسار الذي سلكه.",
    mockNote: "في التشغيل التجريبي استُبدل النموذج اللغوي ببديل ثابت، لذا لا يظهر نموذج للإجابات المبنية من البيانات؛ أما الرفض والردود الثابتة فلا تستدعي أي نموذج في أي وضع.",
    tryLive: "جرّبه الآن",
    seeAll: (n: number) => `جميع السيناريوهات المسجّلة (${n})`,
    passed: "نجح", failed: "لم ينجح",
    then: "ثم",
    reply: "الرد",
    captured: (host: string | null, when: string) => (host ? `سُجّل من ${host} في ${when}` : `سُجّل من تشغيل بنموذج حقيقي في ${when}`),
    intent: "النية", path: "المسار",
    calls: (n: number) => (n === 0 ? "دون استدعاء نموذج" : n === 1 ? "استدعاء واحد للنموذج" : `${n} استدعاءات للنموذج`),
    callsMocked: "النموذج مُحاكى", callsUnknown: "عدد الاستدعاءات غير مسجّل",
    model: "النموذج", ms: (n: number) => `${n.toLocaleString("ar-SA-u-nu-latn")} ملّي ثانية`,
    cards: (n: number) => `${n} بطاقة`, sources: (n: number) => `${n} مصدر`,
    pick: "السيناريو", trace: "كيف عولج", loading: "جارٍ تحميل السيناريوهات المسجّلة…",
    empty: "لم تُنشر نتائج اختبارات الضغط بعد. تظهر هنا بعد تشغيل مجموعة التقييم وإعادة بناء ملف العرض من نتائجها.",
    error: "تعذّر تحميل نتائج اختبارات الضغط. أعد تحميل الصفحة للمحاولة مجددًا.",
    paths: { template: "رد ثابت", code: "مبني من البيانات", llm_tool: "نموذج مع أدوات" } as Record<string, string>,
  },
};
type Str = (typeof S)["en"];

const RAIL_DEFAULT = ["injection_en", "invented_project", "off_topic"];
// Rail tabs use short names so all three fit on one line; the full category names appear on /evals.
const SHORT: Record<string, L10n> = {
  injection_en: { en: "Injection", ar: "تجاوز التعليمات" },
  invented_project: { en: "Invented project", ar: "مشروع وهمي" },
  off_topic: { en: "Off-topic", ar: "خارج الموضوع" },
};
const ROTATE_MS = 7000;

function useShowcase() {
  const [data, setData] = useState<Showcase | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  useEffect(() => {
    const ac = new AbortController();
    getJSON<Showcase>("/api/showcase", ac.signal)
      .then((d) => { setData(d && typeof d === "object" ? d : {}); setState("ready"); })
      .catch(() => { if (!ac.signal.aborted) setState("error"); });
    return () => ac.abort();
  }, []);
  const list = Array.isArray(data?.scenarios) ? data!.scenarios!.filter((s) => s && typeof s.question === "string" && s.question.trim()) : [];
  return { data, list, state };
}

function fmtWhen(iso: string | null | undefined, lang: Lang) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB",
    { day: "numeric", month: "long", year: "numeric", hour: "2-digit", minute: "2-digit", timeZone: "UTC", timeZoneName: "short" }).format(d);
}

const textDir = (s: string) => (hasArabic(s) ? "rtl" : "ltr");
const textLang = (s: string) => (hasArabic(s) ? "ar" : "en");

/** The recorded reply prefix, with its Markdown emphasis rendered (never as HTML) and list markers kept as lines. */
function Excerpt({ text, truncated }: { text: string; truncated?: boolean }) {
  const blocks = parseMarkdown(text, true);
  const line = (l: Line, k: number) => <span key={k}>{l.map((s, i) => (s.strong ? <strong key={i}>{s.text}</strong> : <span key={i}>{s.text}</span>))}</span>;
  const rows: Line[] = blocks.flatMap((b) => (b.type === "p" ? b.lines : b.type === "h" ? [b.line] : b.items.map((it) => it.line)));
  return (
    <p className="stress__reply" dir={textDir(text)} lang={textLang(text)}>
      {rows.map((l, i) => <span key={i}>{i > 0 && <br />}{line(l, i)}</span>)}
      {truncated && <span aria-hidden="true">…</span>}
    </p>
  );
}

function callsChip(sc: ShowcaseScenario, s: Str) {
  const n = sc.trace?.llm_calls;
  if (typeof n === "number") return s.calls(n);
  return sc.llm_mode === "mock" ? s.callsMocked : s.callsUnknown;
}

function TryLive({ q, s, onHome }: { q: string; s: Str; onHome: boolean }) {
  if (onHome) return <button type="button" className="stress__try" onClick={() => askInChat(q)}>{s.tryLive}</button>;
  return <Link className="stress__try" href={askHref(q)}>{s.tryLive}</Link>;
}

/* ---------------- Rail: one scenario at a time, three to choose from ---------------- */
function RailBlock() {
  const { lang } = useApp();
  const s = S[lang];
  const { data, list, state } = useShowcase();
  const order = (data?.rail_order?.length ? data.rail_order : RAIL_DEFAULT);
  const items = order.map((k) => list.find((x) => x.id === k)).filter((x): x is ShowcaseScenario => Boolean(x)).slice(0, 3);
  const [i, setI] = useState(0);
  const [paused, setPaused] = useState(false);
  const [held, setHeld] = useState(false); // a reader picked one: stop rotating for good
  const base = useId().replace(/:/g, "");
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    if (items.length < 2 || paused || held) return;
    let reduce = false;
    try { reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { /* ignore */ }
    if (reduce) return;
    const id = window.setInterval(() => setI((v) => (v + 1) % items.length), ROTATE_MS);
    return () => window.clearInterval(id);
  }, [items.length, paused, held]);

  if (state !== "ready" || items.length === 0) return null; // nothing recorded: the rail simply ends
  const cur = items[Math.min(i, items.length - 1)];
  const pick = (n: number, focus = false) => { setI(n); setHeld(true); if (focus) tabs.current[n]?.focus(); };
  const onKey = (e: React.KeyboardEvent) => {
    const fwd = lang === "ar" ? "ArrowLeft" : "ArrowRight", back = lang === "ar" ? "ArrowRight" : "ArrowLeft";
    if (e.key === fwd) { e.preventDefault(); pick((i + 1) % items.length, true); }
    else if (e.key === back) { e.preventDefault(); pick((i - 1 + items.length) % items.length, true); }
  };
  return (
    <section className="stress stress--rail" aria-labelledby={`${base}-h`} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}
      onMouseEnter={() => setPaused(true)} onMouseLeave={() => setPaused(false)}
      onFocus={() => setPaused(true)} onBlur={(e) => { if (!e.currentTarget.contains(e.relatedTarget as Node)) setPaused(false); }}>
      <h2 className="stress__title" id={`${base}-h`}>{s.title}</h2>
      <p className="stress__lede">{s.railLede}</p>
      <div className="stress__tabs" role="tablist" aria-label={s.pick} onKeyDown={onKey}>
        {items.map((x, n) => (
          <button key={x.id} ref={(el) => { tabs.current[n] = el; }} type="button" role="tab" id={`${base}-t${n}`}
            aria-selected={n === i} aria-controls={`${base}-p`} tabIndex={n === i ? 0 : -1}
            className="stress__tab" onClick={() => pick(n)}>
            {SHORT[x.id]?.[lang] ?? x.category?.[lang] ?? x.category?.en}
          </button>
        ))}
      </div>
      <div className="stress__panel" role="tabpanel" id={`${base}-p`} aria-labelledby={`${base}-t${i}`} aria-live={held ? "polite" : "off"}>
        <p className="stress__q" dir={textDir(cur.question)} lang={textLang(cur.question)}>{cur.question}</p>
        <p className="stress__verdict">
          <span className={cur.passed ? "stress__ok" : "stress__bad"}>{cur.passed ? s.passed : s.failed}</span>
          {cur.verdict?.[lang] && <span>{cur.verdict[lang]}</span>}
        </p>
        <TryLive q={cur.question} s={s} onHome />
      </div>
      <Link className="stress__all" href="/evals/#stress-tested">{s.seeAll(list.length)}</Link>
    </section>
  );
}

/* ---------------- Full: every recorded scenario, for /evals ---------------- */
function FullBlock() {
  const { lang } = useApp();
  const s = S[lang];
  const { list, state } = useShowcase();
  const anyMock = list.some((x) => x.llm_mode === "mock");
  return (
    <section className="stress stress--full" id="stress-tested" aria-labelledby="stress-tested-h" lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <h2 id="stress-tested-h">{s.title}</h2>
      <p className="stress__lede">{s.fullLede}</p>
      {state === "loading" && <p className="muted" role="status">{s.loading}</p>}
      {state === "error" && <p className="stress__empty">{s.error}</p>}
      {state === "ready" && list.length === 0 && <p className="stress__empty">{s.empty}</p>}
      {list.length > 0 && (
        <>
          {anyMock && <p className="stress__note">{s.mockNote}</p>}
          <ul className="stress__list">
            {list.map((x) => {
              const tr = x.trace ?? {};
              const showModel = tr.model && x.llm_mode !== "mock";
              return (
                <li key={x.id} className="stress__item">
                  <h3 className="stress__cat">{x.category?.[lang] ?? x.category?.en}</h3>
                  <p className="stress__q" dir={textDir(x.question)} lang={textLang(x.question)}>{x.question}</p>
                  {(x.follow_ups ?? []).map((f, n) => (
                    <p key={n} className="stress__q stress__q--then"><span className="stress__then">{s.then}</span>{" "}
                      <bdi dir={textDir(f)} lang={textLang(f)}>{f}</bdi></p>
                  ))}
                  <span className="sr-only">{s.reply}:</span>
                  <Excerpt text={x.reply_excerpt} truncated={x.reply_truncated} />
                  <p className="stress__verdict">
                    <span className={x.passed ? "stress__ok" : "stress__bad"}>{x.passed ? s.passed : s.failed}</span>
                    {x.verdict?.[lang] && <span>{x.verdict[lang]}</span>}
                  </p>
                  <ul className="stress__chips" aria-label={s.trace}>
                    {tr.intent && <li>{s.intent}: <bdi>{tr.intent}</bdi></li>}
                    {tr.path && <li>{s.path}: {s.paths[tr.path] ?? <bdi>{tr.path}</bdi>}</li>}
                    <li>{callsChip(x, s)}</li>
                    {showModel && <li>{s.model}: <bdi dir="ltr">{tr.model}</bdi></li>}
                    {typeof tr.latency_ms === "number" && <li><bdi>{s.ms(Math.round(tr.latency_ms))}</bdi></li>}
                    <li>{s.cards(x.cards_count ?? 0)}</li>
                    <li>{s.sources(x.sources_count ?? 0)}</li>
                  </ul>
                  <div className="stress__foot">
                    {x.captured_at && (
                      <p className="stress__captured">
                        {s.captured(x.host ?? null, "")}<time dateTime={x.captured_at}>{fmtWhen(x.captured_at, lang)}</time>
                      </p>
                    )}
                    <TryLive q={x.question} s={s} onHome={false} />
                  </div>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </section>
  );
}

export function StressTested({ variant }: { variant: "rail" | "full" }) {
  return variant === "rail" ? <RailBlock /> : <FullBlock />;
}
