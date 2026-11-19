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
export interface GalleryEntry {
  id: string; category: string; lang?: string; questions: string[]; reply_excerpt: string; reply_truncated?: boolean;
  cards_count: number; sources_count: number; trace: ShowcaseScenario["trace"]; passed: boolean; failures?: string[];
  checks: { key: string; ok: boolean }[];
  source: { llm_mode?: string | null; label?: string; provider?: string | null; model?: string | null; host?: string | null; run_at?: string | null; file?: string };
}
export interface GalleryCategory { id: string; label: L10n; entries: GalleryEntry[] }
export interface Gallery { categories?: GalleryCategory[]; excerpt_chars?: number; stats?: { entries?: number; categories?: number; passed?: number; failed?: number } }
export interface Showcase { generated_at?: string; rail_order?: string[]; scenarios?: ShowcaseScenario[]; gallery?: Gallery }

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
    galTitle: "How the concierge handles edge cases",
    galLede: "Every kind of tricky input we test, with the reply the concierge actually gave. Nothing here is written by hand: each reply is quoted from a recorded test run, cut at 320 characters.",
    galSummary: (n: number, m: number, x: number, src: string) => `${n} edge cases across ${m} categories · ${x} passed · source: ${src}`,
    srcLive: "live model", srcMock: "model mocked", on: "on",
    filter: "Filter by category", all: "All",
    checked: "What was checked", noneChecked: "No checks recorded",
    capturedSrc: (src: string) => `Captured ${src} on `,
    showing: (n: number) => `Showing ${n} edge case${n === 1 ? "" : "s"}`,
    ok: "passed", bad: "failed", firstTurn: "Sends the first question",
    checkLabels: {
      no_prompt_leak: "No prompt leak", no_url_in_prose: "No raw links in the text", no_promise: "No promised returns",
      must_cite: "Cites a source", sources_known: "Sources are known pages", intent: "Understood the intent",
      intent_not: "Not misread", cards: "Shows matching cards", no_invented_prices: "Price only from sources",
      rtl: "Right-to-left layout", lang_reply: "Replies in your language", not_contains_any: "Avoids forbidden content",
      spotlight_card_has_source: "Spotlight card cites a source", advisor_link_official: "Advisor link is official",
      must_include_id: "Names the right project", no_numbers_outside_context: "Numbers only from sources",
      contains_any_ci: "Says what was expected", contains_any: "Says what was expected", no_offtopic_work: "Does no off-topic work",
      path: "Takes the expected route", not_found_first: "Not-found first", no_numbers_for_invented_name: "No numbers for an invented name",
      chips_min: "Offers next questions", price_matches_db: "Price matches the data", calc: "Arithmetic is correct",
      hedge_or_template: "Hedges instead of guessing", hedge: "Hedges instead of guessing", refers_to: "Keeps the follow-up context",
      no_steering: "No steering by identity", sources_include: "Cites the official page", compare: "Compares both items",
      no_cards: "No cards when none fit",
    } as Record<string, string>,
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
    galTitle: "كيف يتعامل المساعد مع الحالات الصعبة",
    galLede: "كل نوع من المدخلات الصعبة التي نختبرها، مع الرد الذي قدّمه المساعد فعلًا. لا شيء هنا مكتوب يدويًا: كل رد مقتبس من تشغيل اختبار مسجّل، مقتطعًا عند 320 حرفًا.",
    galSummary: (n: number, m: number, x: number, src: string) => `${n} حالة صعبة في ${m} فئة · نجح ${x} · المصدر: ${src}`,
    srcLive: "نموذج حقيقي", srcMock: "نموذج مُحاكى", on: "في",
    filter: "تصفية حسب الفئة", all: "الكل",
    checked: "ما الذي فُحص", noneChecked: "لا فحوصات مسجّلة",
    capturedSrc: (src: string) => `سُجّل بـ${src} في `,
    showing: (n: number) => `عرض ${n} حالة`,
    ok: "نجح", bad: "لم ينجح", firstTurn: "يرسل السؤال الأول",
    checkLabels: {
      no_prompt_leak: "لا تسريب للتعليمات", no_url_in_prose: "لا روابط خام في النص", no_promise: "لا وعود بعوائد",
      must_cite: "يذكر مصدرًا", sources_known: "المصادر صفحات معروفة", intent: "فهم النية",
      intent_not: "لم يُساء فهمه", cards: "يعرض بطاقات مطابقة", no_invented_prices: "السعر من المصادر فقط",
      rtl: "تخطيط من اليمين لليسار", lang_reply: "يردّ بلغتك", not_contains_any: "يتجنب المحتوى الممنوع",
      spotlight_card_has_source: "بطاقة التمييز تذكر مصدرًا", advisor_link_official: "رابط المستشار رسمي",
      must_include_id: "يسمّي المشروع الصحيح", no_numbers_outside_context: "الأرقام من المصادر فقط",
      contains_any_ci: "يقول المتوقع", contains_any: "يقول المتوقع", no_offtopic_work: "لا ينفّذ مهامّ خارج الموضوع",
      path: "يسلك المسار المتوقع", not_found_first: "يذكر أنه غير موجود أولًا", no_numbers_for_invented_name: "لا أرقام لاسم مختلق",
      chips_min: "يقترح أسئلة تالية", price_matches_db: "السعر يطابق البيانات", calc: "الحساب صحيح",
      hedge_or_template: "يتحفّظ بدل التخمين", hedge: "يتحفّظ بدل التخمين", refers_to: "يحافظ على سياق المتابعة",
      no_steering: "لا توجيه حسب الهوية", sources_include: "يذكر الصفحة الرسمية", compare: "يقارن بين الطرفين",
      no_cards: "لا بطاقات حين لا يناسب",
    } as Record<string, string>,
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

/* ---------------- Gallery: every eval category, filterable, for /evals ---------------- */
function GalleryBlock() {
  const { lang } = useApp();
  const s = S[lang];
  const { data, state } = useShowcase();
  const [cat, setCat] = useState<string>("all");
  const cats = (data?.gallery?.categories ?? []).filter((c) => Array.isArray(c?.entries) && c.entries.length > 0);
  if (state === "ready" && cats.length === 0) return <FullBlock />; // older showcase.json without a gallery
  const all = cats.flatMap((c) => c.entries.map((e) => ({ e, c })));
  const shown = cat === "all" ? all : all.filter((x) => x.c.id === cat);
  const srcName = (e: { source?: { llm_mode?: string | null; label?: string } }) =>
    e.source?.llm_mode === "live" ? (lang === "en" && e.source.label ? e.source.label : s.srcLive) : s.srcMock;
  const day = (iso?: string | null) => {
    const d = iso ? new Date(iso) : null;
    return d && !Number.isNaN(d.getTime()) ? new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB", { day: "numeric", month: "long", year: "numeric", timeZone: "UTC" }).format(d) : "";
  };
  const groups = new Set<string>();
  all.forEach(({ e }) => groups.add(`${srcName(e)} ${s.on} ${day(e.source?.run_at)}`));
  const passed = all.filter((x) => x.e.passed).length;
  return (
    <section className="stress stress--full gal" id="stress-tested" aria-labelledby="stress-tested-h" lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <h2 id="stress-tested-h">{s.galTitle}</h2>
      <p className="stress__lede">{s.galLede}</p>
      {state === "loading" && <p className="muted" role="status">{s.loading}</p>}
      {state === "error" && <p className="stress__empty">{s.error}</p>}
      {all.length > 0 && (
        <>
          <p className="gal__summary">{s.galSummary(all.length, cats.length, passed, [...groups].join(" / "))}</p>
          <div className="gal__filter" role="group" aria-label={s.filter}>
            <button type="button" className="gal__chip" aria-pressed={cat === "all"} onClick={() => setCat("all")}>{s.all} <span className="gal__n">{all.length}</span></button>
            {cats.map((c) => (
              <button key={c.id} type="button" className="gal__chip" aria-pressed={cat === c.id} onClick={() => setCat(c.id)}>
                {c.label[lang] ?? c.label.en} <span className="gal__n">{c.entries.length}</span>
              </button>
            ))}
          </div>
          <p className="sr-only" role="status" aria-live="polite">{s.showing(shown.length)}</p>
          <ul className="gal__grid">
            {shown.map(({ e, c }) => {
              const tr = e.trace ?? {};
              const qs = (e.questions ?? []).filter((q) => typeof q === "string");
              const sc = { trace: tr, llm_mode: e.source?.llm_mode } as ShowcaseScenario;
              const when = e.source?.run_at;
              return (
                <li key={e.id} className="gal__card">
                  <div className="gal__head">
                    <h3 className="stress__cat">{c.label[lang] ?? c.label.en}</h3>
                    <span className={e.passed ? "stress__ok" : "stress__bad"}>{e.passed ? s.passed : s.failed}</span>
                  </div>
                  {qs.map((q, n) => (
                    <p key={n} className={n === 0 ? "stress__q" : "stress__q stress__q--then"} dir={textDir(q)} lang={textLang(q)}>
                      {n > 0 && <><span className="stress__then">{s.then}</span>{" "}</>}<bdi dir={textDir(q)}>{q}</bdi>
                    </p>
                  ))}
                  <span className="sr-only">{s.reply}:</span>
                  <Excerpt text={e.reply_excerpt} truncated={e.reply_truncated} />
                  <div className="gal__checks">
                    <p className="gal__sub">{s.checked}</p>
                    {e.checks?.length ? (
                      <ul className="gal__list">
                        {e.checks.map((k) => (
                          <li key={k.key} className={k.ok ? "gal__yes" : "gal__no"}>
                            {s.checkLabels[k.key] ?? k.key}<span className="sr-only"> ({k.ok ? s.ok : s.bad})</span>
                          </li>
                        ))}
                      </ul>
                    ) : <p className="stress__captured">{s.noneChecked}</p>}
                  </div>
                  <ul className="stress__chips" aria-label={s.trace}>
                    {tr.path && <li>{s.path}: {s.paths[tr.path] ?? <bdi>{tr.path}</bdi>}</li>}
                    <li>{callsChip(sc, s)}</li>
                    {typeof tr.latency_ms === "number" && <li><bdi>{s.ms(Math.round(tr.latency_ms))}</bdi></li>}
                    <li>{s.cards(e.cards_count ?? 0)}</li>
                    <li>{s.sources(e.sources_count ?? 0)}</li>
                  </ul>
                  <div className="stress__foot">
                    {when && <p className="stress__captured">{s.capturedSrc(srcName(e))}<time dateTime={when}>{fmtWhen(when, lang)}</time></p>}
                    {qs[0] && (qs.length > 1
                      ? <span className="gal__try"><TryLive q={qs[0]} s={s} onHome={false} /><span className="stress__captured">{s.firstTurn}</span></span>
                      : <TryLive q={qs[0]} s={s} onHome={false} />)}
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
  return variant === "rail" ? <RailBlock /> : <GalleryBlock />;
}
