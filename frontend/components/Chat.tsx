"use client";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { API_BASE, safeUrl } from "@/lib/api";
import { fmtDate, hasArabic } from "@/lib/format";
import { CONV } from "@/lib/conversation-strings";
import { STRINGS } from "@/lib/i18n";
import { parseMarkdown, type Span as MdSpan } from "@/lib/md";
import { readSSE } from "@/lib/sse";
import { ASK_EVENT, ASK_PARAM } from "@/lib/ask"; // showcase "Try it live"
import type {
  CalcEvent, CardsEvent, Chip, CompareEvent, ErrorEvent, HandoffEvent, HistoryItem, Lang, MetaEvent, Source,
  SpotlightEvent, TraceEvent,
} from "@/lib/types";
import { useApp } from "./AppContext";
import css from "./Chat.module.css";
import { Composer, MAX_CHARS } from "./Composer";
import { JumpLatest } from "./JumpLatest";
import { AnswerBlocks, answerSources, Chips, Cited as CiteChips } from "./Parts";
import { isolate } from "@/lib/bidi";
import { Mark } from "./SiteHeader";
import { TurnActions, type Rating } from "./TurnActions";
import { Welcome } from "./Welcome";

type UserTurn = { id: string; role: "user"; text: string; lang: Lang };
type AssistantTurn = {
  id: string; role: "assistant"; forText: string; lang: Lang; text: string;
  status: "waiting" | "streaming" | "done" | "error" | "stopped";
  meta?: MetaEvent; cards?: CardsEvent; compare?: CompareEvent; calc?: CalcEvent;
  sources?: Source[]; chips?: Chip[]; trace?: TraceEvent;
  /** Set by a `status {step:"writing"}` event: a model is about to write the prose (shown until the first token). */
  writing?: boolean;
  error?: { code: ErrorEvent["code"] | "NETWORK"; message?: string };
  /** Optional events (lane E): advisor handoff and off-topic spotlight; rendered by lane D's cards. */
  handoff?: HandoffEvent; spotlight?: SpotlightEvent;
  /** Helpful / Not helpful: kept in this tab only, never sent. */
  rating?: Rating;
};
type Turn = UserTurn | AssistantTurn;

const uid = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** [n] markers become lane D's cite chips (components/cards/Cite.tsx): hover/focus highlights source row n and back,
 * click scrolls to the row; a marker with no matching source stays as plain text. */
const Cited = CiteChips;

/** One parsed line: emphasis spans as <strong>/<em> (Arabic emphasis is never italic, see globals.css), text as React
 * text nodes (escaped), [n] markers as citation chips. */
function MdLine({ line, sources, lang }: { line: MdSpan[]; sources: Source[]; lang: Lang }) {
  return (
    <>
      {line.map((s, k) => {
        let node: React.ReactNode = <Cited text={s.text} sources={sources} lang={lang} />;
        if (s.em) node = <em>{node}</em>;
        if (s.strong) node = <strong>{node}</strong>;
        return <span key={k}>{node}</span>;
      })}
    </>
  );
}

/** Safe minimal Markdown (lib/md.ts): bold, emphasis, bulleted and numbered lists, headings as bold lines, line breaks.
 * Model prose never carries links or HTML (SPEC §18); [n] markers become citation chips that point at the answer's own
 * sources list. While streaming, half-arrived "**" is hidden instead of flashing. */
function Prose({ text, sources = [], lang, streaming = false }: { text: string; sources?: Source[]; lang: Lang; streaming?: boolean }) {
  const blocks = parseMarkdown(text, streaming);
  return (
    <>
      {blocks.map((b, i) => {
        if (b.type === "h") return <p key={i} className="prose__head"><strong><MdLine line={b.line} sources={sources} lang={lang} /></strong></p>;
        if (b.type === "p") return <p key={i}>{b.lines.map((l, j) => (<span key={j}>{j > 0 && <br />}<MdLine line={l} sources={sources} lang={lang} /></span>))}</p>;
        const items = b.items.map((it, j) => (
          <li key={j}>
            <MdLine line={it.line} sources={sources} lang={lang} />
            {it.sub && <ul>{it.sub.map((l, k) => <li key={k}><MdLine line={l} sources={sources} lang={lang} /></li>)}</ul>}
          </li>
        ));
        return b.type === "ol" ? <ol key={i} start={b.start !== 1 ? b.start : undefined}>{items}</ol> : <ul key={i}>{items}</ul>;
      })}
    </>
  );
}

/** Plain text of an answer for Copy: the prose (markdown removed, [n] markers kept), the comparison as a plain-text
 * table, the cards by name and link, and the numbered source URLs. */
function plainText(a: AssistantTurn): string {
  const t = STRINGS[a.lang] ?? STRINGS.en;
  const c = CONV[a.lang] ?? CONV.en;
  const lineText = (l: MdSpan[]) => l.map((x) => x.text).join("");
  const out: string[] = [];
  for (const b of parseMarkdown(a.text)) {
    if (b.type === "h") out.push(lineText(b.line));
    else if (b.type === "p") out.push(b.lines.map(lineText).join("\n"));
    else {
      out.push(b.items.map((it, i) => {
        const head = `${b.type === "ol" ? `${(b.start ?? 1) + i}.` : "-"} ${lineText(it.line)}`;
        return it.sub?.length ? [head, ...it.sub.map((l) => `   - ${lineText(l)}`)].join("\n") : head;
      }).join("\n"));
    }
  }
  if (a.compare && a.compare.columns?.length) {
    const cmp = a.compare;
    const rows: string[][] = [["", ...cmp.columns.map((x) => x.name)], ...cmp.rows.map((r) => [r.label, ...r.values.map((v) => v ?? "-")])];
    const widths = rows[0].map((_, i) => Math.max(...rows.map((r) => (r[i] ?? "").length)));
    const fmtRow = (r: string[]) => `| ${r.map((v, i) => (v ?? "").padEnd(widths[i])).join(" | ")} |`;
    const table = [fmtRow(rows[0]), `|${widths.map((w) => "-".repeat(w + 2)).join("|")}|`, ...rows.slice(1).map(fmtRow)];
    if (cmp.verdict) out.push(cmp.verdict);
    out.push(table.join("\n"));
  }
  const cardLines = [
    ...(a.cards?.projects ?? []).map((p) => `- ${p.name}${p.source_url ? `: ${p.source_url}` : ""}`),
    ...(a.cards?.listings ?? []).map((l) => `- ${l.title}${l.source_url ? `: ${l.source_url}` : ""}`),
  ];
  if (cardLines.length) out.push(cardLines.join("\n"));
  const srcs = [...(a.sources ?? [])];
  for (const s of a.compare?.sources ?? []) if (!srcs.some((x) => x.url === s.url)) srcs.push(s);
  if (srcs.length) out.push([`${c.copySources ?? t.sources}:`, ...srcs.map((s, i) => `[${i + 1}] ${s.title || s.site} (${s.site}): ${s.url}`)].join("\n"));
  if (srcs.length && a.meta?.data_as_of) out.push(`${c.dataAsOf} ${fmtDate(a.meta.data_as_of, a.lang)}`);
  return out.filter(Boolean).join("\n\n");
}

const prefersReducedMotion = () => {
  try { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
};

/** Progressive reveal at a fixed short cadence, also for code-built answers that arrive in one piece; instant under
 * prefers-reduced-motion. Returns how many characters to show; it only ever grows toward the full text. */
function useReveal(text: string, enabled: boolean) {
  const [n, setN] = useState(() => (enabled ? 0 : text.length));
  const nRef = useRef(n);
  const target = useRef(text.length);
  target.current = text.length;
  useEffect(() => {
    if (!enabled || prefersReducedMotion()) { nRef.current = text.length; setN(text.length); return; }
    if (nRef.current >= text.length) return;
    let raf = 0;
    let last = performance.now();
    const tick = (now: number) => {
      const dt = Math.min(64, Math.max(0, now - last));
      last = now;
      const backlog = target.current - nRef.current;
      // ~900 chars/s, faster when far behind, so the reveal never trails the stream by more than ~1.5 s
      const perMs = Math.max(0.9, backlog / 1500);
      nRef.current = Math.min(target.current, nRef.current + Math.max(1, Math.round(perMs * dt)));
      setN(nRef.current);
      if (nRef.current < target.current) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [text.length, enabled]);
  return Math.min(n, text.length);
}

/** Top of `el` inside the scroll container's content box. */
const topWithin = (el: HTMLElement, box: HTMLElement) => el.getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
const PIN_GAP = 16; // the pinned question sits this far below the top of the scroll area (acceptance: <= 24px)

export function Chat({ embedded = false }: { embedded?: boolean }) {
  const { t, lang, setResetChat } = useApp();
  const c = CONV[lang];
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [rateUntil, setRateUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [announce, setAnnounce] = useState("");
  const sessionId = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const [showJump, setShowJump] = useState(false);
  const [pinMin, setPinMin] = useState(0);
  /** The user turn currently pinned to the top (cleared once the reader scrolls on their own). */
  const pinnedRef = useRef<string | null>(null);
  /** scrollTop the app itself last set, so its own scroll events are not mistaken for the reader's. */
  const progTopRef = useRef<number | null>(null);
  /** First visible turn and its offset from the top, kept so a resize or rotation keeps the same turn in view. */
  const anchorRef = useRef<{ id: string; off: number } | null>(null);
  const atBottomRef = useRef(false);
  /** Last time the reader touched the scroll area (wheel, touch, key, pointer): only then is a scroll "theirs". */
  const intentRef = useRef(0);
  const markIntent = () => { intentRef.current = Date.now(); };

  useEffect(() => { sessionId.current = uid(); }, []);

  const resetConversation = useCallback(() => {
    setTurns([]); setInput(""); sessionId.current = uid(); pinnedRef.current = null; setShowJump(false); taRef.current?.focus();
  }, []);

  // "New conversation" lives in the header once a conversation exists.
  const hasTurns = turns.length > 0;
  useEffect(() => {
    if (embedded) return;
    setResetChat(hasTurns && !busy ? resetConversation : null);
  }, [hasTurns, busy, embedded, setResetChat, resetConversation]);
  useEffect(() => () => setResetChat(null), [setResetChat]);

  // Rate-limit countdown
  useEffect(() => {
    if (rateUntil <= Date.now()) return;
    setNow(Date.now());
    const id = window.setInterval(() => {
      const n = Date.now();
      setNow(n);
      if (n >= rateUntil) { window.clearInterval(id); setAnnounce(CONV[lang].rateLimitedDone); }
    }, 1000);
    return () => window.clearInterval(id);
  }, [rateUntil, lang]);
  const rateLeft = Math.max(0, Math.ceil((rateUntil - now) / 1000));

  // ---------- scroll behaviour ----------
  const setTop = useCallback((top: number, smooth = false) => {
    const el = scrollRef.current;
    if (!el) return;
    const max = Math.max(0, el.scrollHeight - el.clientHeight);
    const v = Math.max(0, Math.min(top, max));
    if (Math.abs(el.scrollTop - v) < 1) return; // already there: no scroll event will follow
    progTopRef.current = v;
    el.scrollTo({ top: v, behavior: smooth && !prefersReducedMotion() ? "smooth" : ("instant" as ScrollBehavior) });
  }, []);

  const recordAnchor = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 4;
    const boxTop = el.getBoundingClientRect().top;
    const items = el.querySelectorAll<HTMLElement>("[data-turn]");
    anchorRef.current = null;
    for (const it of items) {
      const r = it.getBoundingClientRect();
      if (r.bottom > boxTop + 1) { anchorRef.current = { id: it.dataset.turn ?? "", off: r.top - boxTop }; break; }
    }
  }, []);

  const updateJump = useCallback(() => {
    const el = scrollRef.current;
    // Shown only when the end of the thread is more than one viewport away.
    setShowJump(Boolean(el && el.scrollHeight - el.scrollTop - el.clientHeight > el.clientHeight));
  }, []);

  /** Height the last turn pair must fill so the newest question can sit at the top of the scroll area. */
  const measurePin = useCallback(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el || !content) return;
    const users = el.querySelectorAll<HTMLElement>(".turn--user");
    const q = users[users.length - 1];
    if (!q) { setPinMin(0); return; }
    const cs = window.getComputedStyle(content);
    const padEnd = parseFloat(cs.paddingBlockEnd || cs.paddingBottom) || 0;
    const log = q.parentElement;
    const gap = log ? parseFloat(window.getComputedStyle(log).rowGap) || 0 : 0;
    setPinMin(Math.max(0, Math.floor(el.clientHeight - PIN_GAP - q.offsetHeight - gap - padEnd)));
  }, []);

  const pinTo = useCallback((userId: string) => {
    const el = scrollRef.current;
    const q = el?.querySelector<HTMLElement>(`[data-turn="${CSS.escape(userId)}"]`);
    if (!el || !q) return;
    setTop(topWithin(q, el) - PIN_GAP);
  }, [setTop]);

  // On send: pin the new question to the top. Runs after layout so the min-height is in place first.
  const lastUserId = [...turns].reverse().find((x) => x.role === "user")?.id ?? null;
  useLayoutEffect(() => {
    if (!lastUserId) { pinnedRef.current = null; setPinMin(0); return; }
    pinnedRef.current = lastUserId;
    measurePin();
  }, [lastUserId, measurePin]);
  useLayoutEffect(() => {
    if (pinnedRef.current) pinTo(pinnedRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pinMin, lastUserId]);

  // Size changes: the viewport (resize, rotation) or the content (cards, images, streaming text).
  useEffect(() => {
    const el = scrollRef.current;
    const content = contentRef.current;
    if (!el || !content || typeof ResizeObserver === "undefined") return;
    let lastW = el.clientWidth, lastH = el.clientHeight;
    const ro = new ResizeObserver(() => {
      const viewportChanged = el.clientWidth !== lastW || el.clientHeight !== lastH;
      lastW = el.clientWidth; lastH = el.clientHeight;
      if (viewportChanged) measurePin();
      if (pinnedRef.current) pinTo(pinnedRef.current);
      else if (viewportChanged) {
        if (atBottomRef.current) setTop(el.scrollHeight);
        else if (anchorRef.current) {
          const a = el.querySelector<HTMLElement>(`[data-turn="${CSS.escape(anchorRef.current.id)}"]`);
          if (a) setTop(topWithin(a, el) - anchorRef.current.off);
        }
      }
      updateJump();
    });
    ro.observe(el);
    ro.observe(content);
    // Images that finish loading above the pinned question would push it down: re-pin.
    const onLoad = (e: Event) => { if ((e.target as HTMLElement)?.tagName === "IMG" && pinnedRef.current) pinTo(pinnedRef.current); };
    el.addEventListener("load", onLoad, true);
    return () => { ro.disconnect(); el.removeEventListener("load", onLoad, true); };
  }, [measurePin, pinTo, setTop, updateJump]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const own = progTopRef.current !== null && Math.abs(el.scrollTop - progTopRef.current) < 2;
    progTopRef.current = null;
    // Scrolls the app caused (its own pin, clamping, layout changes) never unpin the question or show the jump button.
    if (own || Date.now() - intentRef.current > 1200) { recordAnchor(); return; }
    // The reader moved the view: stop holding the question in place for them.
    pinnedRef.current = null;
    recordAnchor();
    updateJump();
  };
  const jumpLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    pinnedRef.current = null;
    setTop(el.scrollHeight, true);
    setShowJump(false);
    progTopRef.current = null; // a smooth scroll fires many events; let them update the anchor normally
  };

  const patch = useCallback((id: string, fn: (a: AssistantTurn) => AssistantTurn) => {
    setTurns((ts) => ts.map((x) => (x.id === id && x.role === "assistant" ? fn(x) : x)));
  }, []);

  const buildHistory = (ts: Turn[]): HistoryItem[] =>
    ts
      .filter((x) => x.role === "user" || (x.role === "assistant" && x.status === "done" && x.text))
      .map((x) => ({ role: x.role, content: x.text.slice(0, MAX_CHARS) }))
      .slice(-8);

  const run = useCallback(async (message: string, prior: Turn[]) => {
    const msgLang: Lang = hasArabic(message) ? "ar" : lang;
    const aId = uid();
    const userTurn: UserTurn = { id: uid(), role: "user", text: message, lang: hasArabic(message) ? "ar" : "en" };
    const history = buildHistory(prior);
    setTurns([...prior, userTurn, { id: aId, role: "assistant", forText: message, lang: msgLang, text: "", status: "waiting" }]);
    setBusy(true);
    setAnnounce(STRINGS[lang].thinking);

    const ac = new AbortController();
    abortRef.current = ac;
    let finished = false;
    try {
      const res = await fetch(`${API_BASE}/api/chat/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({ session_id: sessionId.current, message, history, lang: "auto" }),
        signal: ac.signal,
      });
      if (!res.ok || !res.body || !(res.headers.get("content-type") ?? "").includes("text/event-stream")) {
        let body: Partial<ErrorEvent> = {};
        try { const j = await res.json(); body = j?.error ?? j ?? {}; } catch { /* not JSON */ }
        const code: ErrorEvent["code"] = res.status === 429 ? "RATE_LIMITED" : res.status === 400 || res.status === 422 ? "BAD_INPUT" : (body.code as ErrorEvent["code"]) ?? "INTERNAL";
        const retry = Number(body.retry_after_s ?? res.headers.get("Retry-After") ?? 0);
        if (code === "RATE_LIMITED") {
          // Nothing was answered: one message only (the countdown above the composer) and the typed text is kept.
          setRateUntil(Date.now() + Math.max(retry || 30, 1) * 1000);
          setInput((v) => v || message);
          setTurns(prior);
        } else {
          patch(aId, (a) => ({ ...a, status: "error", error: { code, message: body.message } }));
        }
        finished = true;
        return;
      }
      await readSSE(res.body, ({ event, data }) => {
        let d: unknown;
        try { d = JSON.parse(data); } catch { return; }
        switch (event) {
          case "meta": patch(aId, (a) => ({ ...a, meta: d as MetaEvent, lang: (d as MetaEvent).lang ?? a.lang })); break;
          case "token": patch(aId, (a) => ({ ...a, status: "streaming", text: a.text + ((d as { t: string }).t ?? "") })); break;
          case "cards": patch(aId, (a) => ({ ...a, cards: d as CardsEvent })); break;
          case "compare": patch(aId, (a) => ({ ...a, compare: d as CompareEvent })); break;
          case "calc": patch(aId, (a) => ({ ...a, calc: d as CalcEvent })); break;
          case "handoff": patch(aId, (a) => ({ ...a, handoff: d as HandoffEvent })); break;
          case "spotlight": patch(aId, (a) => ({ ...a, spotlight: d as SpotlightEvent })); break;
          case "sources": patch(aId, (a) => ({ ...a, sources: d as Source[] })); break;
          case "chips": patch(aId, (a) => ({ ...a, chips: d as Chip[] })); break;
          case "trace": patch(aId, (a) => ({ ...a, trace: d as TraceEvent })); break;
          // Stream order (backend): meta, cards?, compare?, calc?, sources, status?, token*, chips, trace, done.
          // Cards and sources render as they arrive; tokens then stream into the bubble. Unknown events are ignored.
          case "status":
            if ((d as { step?: string })?.step === "writing") {
              patch(aId, (a) => ({ ...a, writing: true }));
              setAnnounce(STRINGS[lang].writing);
            }
            break;
          default: break;
          case "done":
            finished = true;
            patch(aId, (a) => ({ ...a, status: "done" }));
            break;
          case "error": {
            const e = d as ErrorEvent;
            finished = true;
            if (e.code === "RATE_LIMITED") setRateUntil(Date.now() + Math.max(e.retry_after_s ?? 30, 1) * 1000);
            patch(aId, (a) => ({ ...a, status: "error", error: { code: e.code, message: e.message } }));
            break;
          }
        }
      });
      if (!finished) patch(aId, (a) => ({ ...a, status: "error", error: { code: "NETWORK" } }));
    } catch (err) {
      if (ac.signal.aborted) patch(aId, (a) => ({ ...a, status: "stopped" }));
      else patch(aId, (a) => ({ ...a, status: "error", error: { code: "NETWORK" } }));
      console.warn(err);
    } finally {
      abortRef.current = null;
      setBusy(false);
      setAnnounce((s) => (s === STRINGS[lang].thinking || s === STRINGS[lang].writing ? "" : s));
    }
  }, [lang, patch]);

  const canSend = !busy && rateLeft === 0;

  const send = (text: string) => {
    const msg = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim();
    if (!msg || msg.length > MAX_CHARS || !canSend) return;
    setInput("");
    void run(msg, turns);
  };

  // --- showcase "Try it live" (lib/ask.ts): a question from the Stress-tested block, or from /?ask= on arrival, is sent
  // exactly as written. While an answer is still streaming it is put in the composer instead of being dropped.
  const askRef = useRef<(q: string) => void>(() => {});
  askRef.current = (q: string) => {
    if (!canSend) { setInput(q); taRef.current?.focus(); return; }
    send(q);
  };
  useEffect(() => {
    const onAsk = (e: Event) => { const q = (e as CustomEvent<string>).detail; if (typeof q === "string" && q.trim()) askRef.current(q); };
    window.addEventListener(ASK_EVENT, onAsk);
    let q: string | null = null;
    try { q = new URLSearchParams(window.location.search).get(ASK_PARAM); } catch { /* ignore */ }
    if (q && q.trim()) {
      try {
        const u = new URL(window.location.href);
        u.searchParams.delete(ASK_PARAM);
        window.history.replaceState(window.history.state, "", u.pathname + u.search + u.hash); // a reload does not resend
      } catch { /* ignore */ }
      askRef.current(q);
    }
    return () => window.removeEventListener(ASK_EVENT, onAsk);
  }, []);
  // --- end showcase ---

  /** Retry a failed answer or regenerate the latest one: the pair is replaced, the composer is left as it is. */
  const retry = (a: AssistantTurn) => {
    if (!canSend) return;
    const idx = turns.findIndex((x) => x.id === a.id);
    const prior = turns.slice(0, Math.max(0, idx - 1));
    void run(a.forText, prior);
  };
  const rate = (id: string, r: Rating) => patch(id, (a) => ({ ...a, rating: r }));

  const pickChip = (ch: Chip) => send(ch.message);

  const lastAssistant = [...turns].reverse().find((x): x is AssistantTurn => x.role === "assistant");
  // Index of the last successful answer: error turns before it collapse to a muted "Not answered" line.
  const lastDoneIdx = turns.reduce((acc, x, i) => (x.role === "assistant" && x.status === "done" ? i : acc), -1);

  const errorText = (code: string, message?: string) => {
    switch (code) {
      case "NETWORK": return t.networkError;
      case "MODEL_UNAVAILABLE": return t.modelUnavailable;
      case "BAD_INPUT": return message || t.badInput;
      case "RATE_LIMITED": return rateLeft > 0 ? t.rateLimitedShort : t.rateLimitedDone;
      default: return t.internal;
    }
  };

  const active = turns.length > 0;
  // Height of the page footer on the empty state (it is hidden during a conversation): the line under the composer
  // takes the same height then, so the composer does not move on first send.
  const [footH, setFootH] = useState(0);
  useEffect(() => {
    if (active || embedded || typeof ResizeObserver === "undefined") return;
    const f = document.querySelector<HTMLElement>(".site-footer");
    if (!f) return;
    const upd = () => {
      const cs = window.getComputedStyle(f);
      if (cs.display === "none") return;
      const h = f.getBoundingClientRect().height + (parseFloat(cs.marginBlockStart) || 0) + (parseFloat(cs.marginBlockEnd) || 0);
      if (h > 0) setFootH(h);
    };
    upd();
    const ro = new ResizeObserver(upd);
    ro.observe(f);
    return () => ro.disconnect();
  }, [active, embedded]);
  return (
    <main className={`chat ${css.root}${embedded ? " chat--embedded" : ""}${active ? " chat--active" : ""}`} aria-label={t.concierge}>
      <div className={css.scroll} ref={scrollRef} onScroll={onScroll} id="main" tabIndex={-1}
        onWheel={markIntent} onTouchStart={markIntent} onTouchMove={markIntent} onKeyDown={markIntent} onPointerDown={markIntent}>
        <div className={css.inner} ref={contentRef}>
          {!active ? (
            <Welcome onPick={pickChip} disabled={!canSend} />
          ) : (
            <>
              <h2 className="sr-only">{t.concierge}</h2>
              <ol className={`log ${css.log}`} role="log" aria-live="polite" aria-relevant="additions" aria-label={t.concierge}>
                {turns.map((x, i) =>
                  x.role === "user" ? (
                    <li key={x.id} data-turn={x.id} className="turn turn--user" lang={x.lang} dir={x.lang === "ar" ? "rtl" : "ltr"}>
                      <span className="sr-only">{t.you}: </span>
                      <div className="bubble">{isolate(x.text, x.lang)}</div>
                    </li>
                  ) : (
                    <AssistantView
                      key={x.id}
                      a={x}
                      isLast={x.id === lastAssistant?.id}
                      collapsed={x.status === "error" && i < lastDoneIdx}
                      minHeight={x.id === lastAssistant?.id ? pinMin : 0}
                      canSend={canSend}
                      onChip={pickChip}
                      onRetry={() => retry(x)}
                      onRate={(r) => rate(x.id, r)}
                      onAnnounce={setAnnounce}
                      errorText={errorText}
                    />
                  ),
                )}
              </ol>
            </>
          )}
        </div>
      </div>

      {showJump && active && <JumpLatest label={c.jumpLatest} onJump={jumpLatest} />}
      <Composer
        lang={lang}
        value={input}
        onChange={setInput}
        onSend={() => send(input)}
        onStop={() => { abortRef.current?.abort(); taRef.current?.focus(); }}
        busy={busy}
        rateLeft={rateLeft}
        placeholder={t.composerPlaceholder}
        active={active && !embedded}
        alwaysFoot={embedded}
        footReserve={footH}
        inputRef={taRef}
        footer={embedded && active && !busy
          ? <button type="button" className="linkish" onClick={resetConversation}>{t.newChat}</button>
          : undefined}
      />
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
    </main>
  );
}

function AssistantView({
  a, isLast, collapsed, minHeight, canSend, onChip, onRetry, onRate, onAnnounce, errorText,
}: {
  a: AssistantTurn; isLast: boolean; collapsed: boolean; minHeight: number; canSend: boolean;
  onChip: (c: Chip) => void; onRetry: () => void; onRate: (r: Rating) => void; onAnnounce: (s: string) => void;
  errorText: (code: string, message?: string) => string;
}) {
  const { lang: uiLang } = useApp();
  const t = STRINGS[a.lang] ?? STRINGS[uiLang];
  const cv = CONV[a.lang] ?? CONV[uiLang];
  const dir = a.lang === "ar" ? "rtl" : "ltr";
  // Reveal only answers that are arriving now; a finished answer re-rendered (language switch, retry) shows whole.
  const [animate] = useState(() => a.status === "waiting" || a.status === "streaming");
  const shown = useReveal(a.text, animate);
  const revealing = shown < a.text.length;
  const text = revealing ? a.text.slice(0, shown) : a.text;
  const complete = a.status === "done" && !revealing;

  // "Answer ready" is announced once, when the reveal has finished.
  const announced = useRef(false);
  useEffect(() => {
    if (complete && animate && !announced.current) { announced.current = true; onAnnounce(cv.answerReady); }
  }, [complete, animate, cv.answerReady, onAnnounce]);

  // One numbered source list per answer (lane D); none for handoff, calc, greeting and refusals.
  const blocks = { lang: a.lang, intent: a.meta?.intent, cards: a.cards, compare: a.compare, calc: a.calc,
    handoff: a.handoff, spotlight: a.spotlight, sources: a.sources };
  const nSources = answerSources(blocks).length;
  const matched = [
    ...(a.compare?.columns ?? []).map((x) => x.name),
    ...(a.cards?.projects ?? []).slice(0, 3).map((x) => x.name),
    ...(a.spotlight?.project ? [a.spotlight.project.name] : []),
  ].filter((v, i, arr) => v && arr.indexOf(v) === i);
  const midStream = a.status === "error" && a.text.length > 0;
  const busyNow = a.status === "waiting" || a.status === "streaming" || revealing;

  if (collapsed) {
    return (
      <li data-turn={a.id} className={`turn turn--assistant turn--collapsed ${css.collapsed}`} lang={a.lang} dir={dir}>
        <span className="turn__mark" aria-hidden="true"><Mark size={14} /></span>
        <p className={css.notAnswered}>{cv.notAnswered}</p>
      </li>
    );
  }

  return (
    <li
      data-turn={a.id}
      className={`turn turn--assistant${a.status === "error" ? " turn--error" : ""}`}
      lang={a.lang}
      dir={dir}
      aria-busy={busyNow || undefined}
      style={minHeight > 0 ? { minBlockSize: `${minHeight}px` } : undefined}
    >
      <span className="turn__mark" aria-hidden="true"><Mark size={14} /></span>
      <div className="turn__body">
        <span className="sr-only">{t.concierge}: </span>

        {a.status === "waiting" && (
          <div className="skeleton" aria-label={a.writing ? t.writing : t.thinking}>
            <span className="skeleton__label">{a.writing ? t.writing : t.thinking}</span>
            <span className="skeleton__line" /><span className="skeleton__line" /><span className="skeleton__line skeleton__line--short" />
          </div>
        )}

        {text && (
          <div className={`prose${a.status === "streaming" || revealing ? " prose--streaming" : ""}`}>
            {/* Sources arrive before the text, so [n] chips resolve while it streams (a half-arrived "[1" stays text). */}
            <Prose text={text} sources={a.sources ?? []} lang={a.lang} streaming={a.status === "streaming" || revealing} />
          </div>
        )}

        {/* Lane D: one rich block (cards OR compare OR calc OR handoff OR spotlight), its footnotes, then sources. */}
        <AnswerBlocks a={blocks} />


        {a.status === "stopped" && (
          <div className="alert alert--rate" role="status">
            <p>{a.text ? t.incomplete : t.stopped}</p>
            <button type="button" className="btn-quiet" onClick={onRetry} disabled={!canSend}>{t.retry}</button>
          </div>
        )}
        {a.status === "error" && a.error && (
          <div className={`alert alert--${a.error.code === "RATE_LIMITED" ? "rate" : "error"}`} role="alert">
            <p>{midStream ? `${t.incomplete} ${errorText(a.error.code, a.error.message)}` : errorText(a.error.code, a.error.message)}</p>
            {a.error.code !== "RATE_LIMITED" && a.error.code !== "BAD_INPUT" && (
              <button type="button" className="btn-quiet" onClick={onRetry} disabled={!canSend}>{t.retry}</button>
            )}
          </div>
        )}

        {complete && (a.text || a.cards || a.compare || a.calc || a.handoff || a.spotlight) && (
          <TurnActions
            lang={a.lang}
            copyText={() => plainText(a)}
            onRetry={onRetry}
            canRetry={canSend}
            showRetry={isLast}
            rating={a.rating ?? null}
            onRate={onRate}
            trace={a.trace}
            nSources={nSources}
            matched={matched}
            dataAsOf={a.meta?.data_as_of}
            onAnnounce={onAnnounce}
          />
        )}
        {isLast && complete && a.chips && a.chips.length > 0 && <Chips chips={a.chips} onPick={onChip} disabled={!canSend} />}
      </div>
    </li>
  );
}
