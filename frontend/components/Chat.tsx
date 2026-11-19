"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { API_BASE, safeUrl } from "@/lib/api";
import { fmtDate, hasArabic } from "@/lib/format";
import { DEFAULT_CHIPS, STRINGS, TRAP_CHIP } from "@/lib/i18n";
import { readSSE } from "@/lib/sse";
import type {
  CalcEvent, CardsEvent, Chip, CompareEvent, ErrorEvent, HistoryItem, Lang, MetaEvent, Source, TraceEvent,
} from "@/lib/types";
import { useApp } from "./AppContext";
import { CalcResult, CardRail, Chips, CompareTable, SourceList, Trace } from "./Parts";
import { Mark } from "./SiteHeader";

const MAX_CHARS = 1000;

type UserTurn = { id: string; role: "user"; text: string; lang: Lang };
type AssistantTurn = {
  id: string; role: "assistant"; forText: string; lang: Lang; text: string;
  status: "waiting" | "streaming" | "done" | "error" | "stopped";
  meta?: MetaEvent; cards?: CardsEvent; compare?: CompareEvent; calc?: CalcEvent;
  sources?: Source[]; chips?: Chip[]; trace?: TraceEvent;
  error?: { code: ErrorEvent["code"] | "NETWORK"; message?: string };
};
type Turn = UserTurn | AssistantTurn;

const uid = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);

/** One [n] marker in the prose: a small chip that opens source n (who published it, title, collection date, link). */
function Cite({ n, src, lang }: { n: number; src: Source; lang: Lang }) {
  const t = STRINGS[lang];
  const [open, setOpen] = useState(false);
  const href = safeUrl(src.url);
  const id = `cite${useId().replace(/:/g, "")}`;
  return (
    <span className="cite">
      <button type="button" className="cite__chip" aria-expanded={open} aria-controls={id} aria-label={t.citeLabel(n)}
        onClick={() => setOpen((v) => !v)} onKeyDown={(e) => { if (e.key === "Escape") setOpen(false); }}>{n}</button>
      {open && (
        <span className="cite__pop" id={id} role="note">
          <span className="cite__site"><bdi>{src.site}</bdi></span>
          {href
            ? <a className="cite__title" href={href} target="_blank" rel="noopener noreferrer"><bdi>{src.title || href}</bdi></a>
            : <span className="cite__title"><bdi>{src.title}</bdi></span>}
          {src.scraped_at && <span className="cite__date">{t.dataAsOf} <time dateTime={src.scraped_at}>{fmtDate(src.scraped_at, lang)}</time></span>}
        </span>
      )}
    </span>
  );
}

/** Text with [n] markers turned into citation chips; a marker with no matching source stays as plain text. */
function Cited({ text, sources, lang }: { text: string; sources: Source[]; lang: Lang }) {
  if (!sources.length || !/\[\d{1,2}\]/.test(text)) return <>{text}</>;
  const parts = text.split(/(\[\d{1,2}\])/);
  return (
    <>
      {parts.map((part, i) => {
        const m = /^\[(\d{1,2})\]$/.exec(part);
        const src = m ? sources[Number(m[1]) - 1] : undefined;
        return m && src ? <Cite key={i} n={Number(m[1])} src={src} lang={lang} /> : <span key={i}>{part}</span>;
      })}
    </>
  );
}

/** Plain-text renderer: paragraphs and simple dash lists. Model prose never carries links (SPEC §18); [n] markers
 * become citation chips that point at the answer's own sources list. */
function Prose({ text, sources = [], lang }: { text: string; sources?: Source[]; lang: Lang }) {
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/);
  return (
    <>
      {blocks.map((b, i) => {
        const lines = b.split("\n").filter((l) => l.trim());
        if (lines.length && lines.every((l) => /^\s*[-•*]\s+/.test(l))) {
          return <ul key={i}>{lines.map((l, j) => <li key={j}><Cited text={l.replace(/^\s*[-•*]\s+/, "")} sources={sources} lang={lang} /></li>)}</ul>;
        }
        return <p key={i}>{lines.map((l, j) => (<span key={j}>{j > 0 && <br />}<Cited text={l} sources={sources} lang={lang} /></span>))}</p>;
      })}
    </>
  );
}

/** The first message: one sentence. Corpus counts live on How it works (read from /api/meta there). */
function Greeting() {
  const { t, meta } = useApp();
  return <p>{meta ? t.greetingLead : t.greetingNoMeta}</p>;
}

export function Chat({ embedded = false }: { embedded?: boolean }) {
  const { t, lang, meta, setResetChat } = useApp();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [rateUntil, setRateUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());
  const [announce, setAnnounce] = useState("");
  const sessionId = useRef<string>("");
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const taRef = useRef<HTMLTextAreaElement>(null);
  const [showJump, setShowJump] = useState(false);

  useEffect(() => { sessionId.current = uid(); }, []);

  // "New conversation" lives in the header once a conversation exists.
  const hasTurns = turns.length > 0;
  useEffect(() => {
    if (embedded) return;
    setResetChat(hasTurns && !busy ? () => { setTurns([]); setInput(""); sessionId.current = uid(); taRef.current?.focus(); } : null);
  }, [hasTurns, busy, embedded, setResetChat]);
  useEffect(() => () => setResetChat(null), [setResetChat]);

  // Rate-limit countdown
  useEffect(() => {
    if (rateUntil <= Date.now()) return;
    const id = window.setInterval(() => {
      const n = Date.now();
      setNow(n);
      if (n >= rateUntil) { window.clearInterval(id); setAnnounce(STRINGS[lang].rateLimitedDone); }
    }, 1000);
    return () => window.clearInterval(id);
  }, [rateUntil, lang]);
  const rateLeft = Math.max(0, Math.ceil((rateUntil - now) / 1000));

  // On send, bring the new question to the top of the message area. While the answer streams, follow it only
  // as long as the whole answer still fits below the question; never jump past the start of the answer.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !stickRef.current) return;
    const users = el.querySelectorAll<HTMLElement>(".turn--user");
    const q = users[users.length - 1];
    if (!q) return;
    const top = q.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - 8;
    const bottom = el.scrollHeight - el.clientHeight;
    el.scrollTo({ top: Math.max(0, Math.min(top, bottom)), behavior: "instant" as ScrollBehavior });
  }, [turns]);
  // "Jump to latest" appears whenever the end of the conversation is below the fold (DESIGN_BAR chat rules).
  const updateJump = useCallback(() => {
    const el = scrollRef.current;
    setShowJump(Boolean(el && el.scrollHeight - el.scrollTop - el.clientHeight > 120));
  }, []);
  useEffect(() => { updateJump(); }, [turns, updateJump]);
  const jumpLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    stickRef.current = false;
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };
  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    updateJump();
    const users = el.querySelectorAll<HTMLElement>(".turn--user");
    const q = users[users.length - 1];
    // the reader scrolled away from the latest question: stop moving the view for them
    const qTop = q ? q.getBoundingClientRect().top - el.getBoundingClientRect().top + el.scrollTop - 8 : 0;
    if (q && Math.abs(el.scrollTop - Math.max(0, qTop)) > 40 && el.scrollHeight - el.scrollTop - el.clientHeight > 4) {
      stickRef.current = false;
    }
  };

  // Auto-grow composer
  useEffect(() => {
    const ta = taRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 180)}px`;
  }, [input]);

  const patch = useCallback((id: string, fn: (a: AssistantTurn) => AssistantTurn) => {
    setTurns((ts) => ts.map((x) => (x.id === id && x.role === "assistant" ? fn(x) : x)));
  }, []);

  const buildHistory = (ts: Turn[]): HistoryItem[] =>
    ts
      .filter((x) => x.role === "user" || (x.role === "assistant" && x.status === "done" && x.text))
      .map((x) => ({ role: x.role, content: (x.role === "user" ? x.text : x.text).slice(0, MAX_CHARS) }))
      .slice(-8);

  const run = useCallback(async (message: string, prior: Turn[]) => {
    const msgLang: Lang = hasArabic(message) ? "ar" : lang;
    const aId = uid();
    const userTurn: UserTurn = { id: uid(), role: "user", text: message, lang: hasArabic(message) ? "ar" : "en" };
    const history = buildHistory(prior);
    stickRef.current = true;
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
        setInput((v) => v || message);
        if (code === "RATE_LIMITED") {
          // One message only: the countdown sits at the composer and the question is back in the box.
          setRateUntil(Date.now() + Math.max(retry || 30, 1) * 1000);
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
          case "sources": patch(aId, (a) => ({ ...a, sources: d as Source[] })); break;
          case "chips": patch(aId, (a) => ({ ...a, chips: d as Chip[] })); break;
          case "trace": patch(aId, (a) => ({ ...a, trace: d as TraceEvent })); break;
          case "done":
            finished = true;
            patch(aId, (a) => {
              const first = (a.text.split(/(?<=[.!?؟])\s/)[0] ?? "").slice(0, 160);
              setAnnounce(`${STRINGS[a.lang]?.answerReady ?? STRINGS[lang].answerReady} ${first}`);
              return { ...a, status: "done" };
            });
            break;
          case "error": {
            const e = d as ErrorEvent;
            finished = true;
            setInput((v) => v || message);
            if (e.code === "RATE_LIMITED") setRateUntil(Date.now() + Math.max(e.retry_after_s ?? 30, 1) * 1000);
            patch(aId, (a) => ({ ...a, status: "error", error: { code: e.code, message: e.message } }));
            break;
          }
        }
      });
      if (!finished) { setInput((v) => v || message); patch(aId, (a) => ({ ...a, status: "error", error: { code: "NETWORK" } })); }
    } catch (err) {
      if (ac.signal.aborted) patch(aId, (a) => ({ ...a, status: "stopped" }));
      else { setInput((v) => v || message); patch(aId, (a) => ({ ...a, status: "error", error: { code: "NETWORK" } })); }
      console.warn(err);
    } finally {
      abortRef.current = null;
      setBusy(false);
      setAnnounce((s) => (s === STRINGS[lang].thinking ? "" : s));
    }
  }, [lang, patch]);

  const canSend = !busy && rateLeft === 0;

  const send = (text: string) => {
    const msg = text.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F]/g, "").trim();
    if (!msg || msg.length > MAX_CHARS || !canSend) return;
    setInput("");
    void run(msg, turns);
  };

  const retry = (a: AssistantTurn) => {
    if (!canSend) return;
    setInput((v) => (v === a.forText ? "" : v));
    const idx = turns.findIndex((x) => x.id === a.id);
    // drop the failed pair (user + assistant) and resend the same message
    const prior = turns.slice(0, Math.max(0, idx - 1));
    void run(a.forText, prior);
  };

  const pickChip = (c: Chip) => send(c.message);
  const trap = TRAP_CHIP[lang];
  // Starter chips come from rows that exist (C2 meta.starter_chips, last one is the guardrail test); the local list
  // is a fallback only. A chip always sends exactly the text it shows.
  const served = meta?.starter_chips?.[lang]?.filter((x) => typeof x === "string" && x.trim()) ?? [];
  const defaultChips: Chip[] = served.length
    ? served.map((q) => ({ label: q, message: q }))
    : [...DEFAULT_CHIPS[lang].map((q) => ({ label: q, message: q })), { label: trap.label, message: trap.label }];
  const trapLabel = served.length ? served[served.length - 1] : trap.label;
  const pickDefault = (c: Chip) => send(c.message);

  const lastAssistant = [...turns].reverse().find((x): x is AssistantTurn => x.role === "assistant");
  const tooLong = input.length > MAX_CHARS;
  const showCounter = input.length > MAX_CHARS - 200;

  const errorText = (code: string, message?: string) => {
    switch (code) {
      case "NETWORK": return t.networkError;
      case "MODEL_UNAVAILABLE": return t.modelUnavailable;
      case "BAD_INPUT": return message || t.badInput;
      case "RATE_LIMITED": return rateLeft > 0 ? t.rateLimitedShort : t.rateLimitedDone;
      default: return t.internal;
    }
  };

  return (
    <main className={`chat${embedded ? " chat--embedded" : ""}${turns.length > 0 ? " chat--active" : ""}`} aria-label={t.concierge}>
      <div className="chat__scroll" ref={scrollRef} onScroll={onScroll} id="main" tabIndex={-1}>
        <div className="chat__inner">
          {turns.length === 0 ? (
            <div className="greeting">
              <div className="greeting__msg">
                <span className="turn__mark" aria-hidden="true"><Mark size={14} /></span>
                <div className="prose greeting__body">
                  <h2 className="sr-only">{t.concierge}</h2>
                  <Greeting />
                </div>
              </div>
              <Chips chips={defaultChips} onPick={pickDefault} disabled={!canSend} trapLabel={trapLabel} label={t.greetingTry} />
            </div>
          ) : (
            <>
            <h2 className="sr-only">{t.concierge}</h2>
            <ol className="log" aria-label={t.concierge}>
              {turns.map((x) =>
                x.role === "user" ? (
                  <li key={x.id} className="turn turn--user" lang={x.lang} dir={x.lang === "ar" ? "rtl" : "ltr"}>
                    <span className="sr-only">{t.you}: </span>
                    <div className="bubble">{x.text}</div>
                  </li>
                ) : (
                  <AssistantView
                    key={x.id}
                    a={x}
                    isLast={x.id === lastAssistant?.id}
                    canSend={canSend}
                    onChip={pickChip}
                    onRetry={() => retry(x)}
                    errorText={errorText}
                  />
                ),
              )}
            </ol>
            </>
          )}
        </div>
      </div>

      {showJump && (
        <button type="button" className="jump-latest" onClick={jumpLatest}>
          <svg width="14" height="14" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5v14M6 13l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></svg>
          {t.jumpLatest}
        </button>
      )}
      <form
        className="composer"
        onSubmit={(e) => { e.preventDefault(); send(input); }}
      >
        {rateLeft > 0 && <p className="composer__note composer__note--warn" role="status">{t.rateLimited(rateLeft)}</p>}
        {tooLong && <p className="composer__note composer__note--warn" role="alert">{t.tooLong}</p>}
        <div className="composer__row">
          <label htmlFor="composer-input" className="sr-only">{t.composerLabel}</label>
          <textarea
            id="composer-input"
            ref={taRef}
            rows={1}
            value={input}
            dir="auto"
            placeholder={t.composerPlaceholder}
            maxLength={MAX_CHARS + 200}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(input); }
            }}
            aria-describedby={showCounter ? "composer-count" : undefined}
          />
          {busy ? (
            <button type="button" className="composer__btn composer__btn--stop" onClick={() => { abortRef.current?.abort(); taRef.current?.focus(); }}>
              {t.stop}
            </button>
          ) : (
            <button type="submit" className="composer__btn" disabled={!input.trim() || tooLong || rateLeft > 0}>
              {t.send}
            </button>
          )}
        </div>
        {(showCounter || embedded) && (
          <div className="composer__foot">
            {showCounter ? <span id="composer-count" className={tooLong ? "warn" : ""}>{t.charsLeft(Math.max(0, MAX_CHARS - input.length))}</span> : <span />}
            {embedded && turns.length > 0 && !busy && (
              <button type="button" className="linkish" onClick={() => { setTurns([]); sessionId.current = uid(); }}>{t.newChat}</button>
            )}
          </div>
        )}
      </form>
      <p className="sr-only" role="status" aria-live="polite">{announce}</p>
    </main>
  );
}

function AssistantView({
  a, isLast, canSend, onChip, onRetry, errorText,
}: {
  a: AssistantTurn; isLast: boolean; canSend: boolean; onChip: (c: Chip) => void; onRetry: () => void;
  errorText: (code: string, message?: string) => string;
}) {
  const { lang: uiLang } = useApp();
  const t = STRINGS[a.lang] ?? STRINGS[uiLang];
  const dir = a.lang === "ar" ? "rtl" : "ltr";
  // Sources already listed under a comparison table are not repeated below the answer.
  const inCompare = new Set((a.compare?.sources ?? []).map((x) => x.url));
  const msgSources = (a.sources ?? []).filter((x) => !inCompare.has(x.url));
  const showSources = msgSources.length > 0 || (a.status === "done" && a.meta?.data_as_of);
  const [copied, setCopied] = useState(false);
  const midStream = a.status === "error" && a.text.length > 0;
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(a.text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch { /* clipboard blocked: nothing to do */ }
  };
  return (
    <li className={`turn turn--assistant${a.status === "error" ? " turn--error" : ""}`} lang={a.lang} dir={dir}>
      <span className="turn__mark" aria-hidden="true"><Mark size={14} /></span>
      <div className="turn__body">
        <span className="sr-only">{t.concierge}: </span>

        {a.status === "waiting" && (
          <div className="skeleton" aria-label={t.thinking}>
            <span className="skeleton__label">{t.thinking}</span>
            <span className="skeleton__line" /><span className="skeleton__line" /><span className="skeleton__line skeleton__line--short" />
          </div>
        )}

        {a.text && (
          <div className={`prose${a.status === "streaming" ? " prose--streaming" : ""}`}>
            <Prose text={a.text} sources={a.status === "streaming" ? [] : (a.sources ?? [])} lang={a.lang} />
          </div>
        )}

        {a.cards && <CardRail projects={a.cards.projects ?? []} listings={a.cards.listings ?? []} t={t} lang={a.lang} />}
        {a.compare && <CompareTable c={a.compare} t={t} />}
        {a.calc && <CalcResult c={a.calc} t={t} />}
        {showSources && <SourceList sources={msgSources} t={t} asOf={a.meta?.data_as_of} lang={a.lang} />}

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

        {a.status === "done" && a.text && (
          <div className="turn__actions">
            <button type="button" className="btn-text" onClick={copy} aria-live="polite">{copied ? t.copied : t.copy}</button>
          </div>
        )}
        {a.trace && <Trace tr={a.trace} t={t} nSources={a.sources?.length ?? 0} />}
        {isLast && a.status === "done" && a.chips && a.chips.length > 0 && <Chips chips={a.chips} onPick={onChip} disabled={!canSend} />}
      </div>
    </li>
  );
}
