"use client";
import { useEffect, useId, useRef, useState } from "react";
import { CONV } from "@/lib/conversation-strings";
import { fmtDate } from "@/lib/format";
import type { Lang, TraceEvent } from "@/lib/types";
import { traceSteps } from "./cards/Trace";
import s from "./TurnActions.module.css";

export type Rating = "up" | "down" | null;

function shortDate(iso: string, lang: Lang) {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB", { day: "numeric", month: "short", year: "numeric" }).format(d);
}

const Icon = {
  copy: <path d="M9 9h10v10H9zM5 15V5h10" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinejoin="round" />,
  check: <path d="M5 12.5l4.5 4.5L19 7.5" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />,
  retry: <path d="M19 12a7 7 0 1 1-2.05-4.95M19 4.5V9h-4.5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />,
  up: <path d="M8 11v8H5v-8zM8 11l4-7c1.4 0 2.2 1 2 2.3L13.5 10H18a2 2 0 0 1 2 2.3l-1 5.2A2 2 0 0 1 17 19H8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />,
  down: <path d="M8 13V5H5v8zM8 13l4 7c1.4 0 2.2-1 2-2.3l-.5-3.7H18a2 2 0 0 0 2-2.3l-1-5.2A2 2 0 0 0 17 5H8" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />,
  found: <path d="M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM15.2 15.2 20 20" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" />,
};

function IconButton({ label, onClick, pressed, expanded, controls, children, disabled }: {
  label: string; onClick: () => void; pressed?: boolean; expanded?: boolean; controls?: string; children: React.ReactNode; disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className={s.btn}
      onClick={disabled ? undefined : onClick}
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-controls={controls}
      aria-disabled={disabled || undefined}
    >
      <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">{children}</svg>
    </button>
  );
}

/** One action row per completed answer (<= 48px): Copy, Ask again (latest answer only), Helpful / Not helpful
 * (kept in this browser only), How I found this (only when sources were used), and "Data as of" at the inline-end,
 * also only when sources were used. */
export function TurnActions({
  lang, copyText, onRetry, canRetry, showRetry, rating, onRate, trace, nSources, matched, dataAsOf, onAnnounce,
}: {
  lang: Lang;
  copyText: () => string;
  onRetry: () => void;
  canRetry: boolean;
  showRetry: boolean;
  rating: Rating;
  onRate: (r: Rating) => void;
  trace?: TraceEvent;
  nSources: number;
  matched: string[];
  dataAsOf?: string;
  onAnnounce: (msg: string) => void;
}) {
  const c = CONV[lang];
  const [copied, setCopied] = useState(false);
  const [open, setOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);
  const panelId = `found${useId().replace(/:/g, "")}`;
  useEffect(() => () => window.clearTimeout(timer.current), []);
  const usedSources = nSources > 0;
  const list = usedSources && trace ? traceSteps(trace, lang, nSources, matched) : [];

  const copy = async () => {
    const text = copyText();
    let ok = false;
    try { await navigator.clipboard.writeText(text); ok = true; } catch {
      // Clipboard API blocked (insecure context, permissions): fall back to a hidden textarea.
      try {
        const ta = document.createElement("textarea");
        ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
        document.body.appendChild(ta); ta.select(); ok = document.execCommand("copy"); ta.remove();
      } catch { ok = false; }
    }
    if (!ok) return;
    setCopied(true);
    onAnnounce(c.copied);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 2000);
  };

  return (
    <div className={s.wrap}>
      <div className={`turn__actions ${s.row}`} role="group" aria-label={c.actionsLabel}>
        <IconButton label={copied ? c.copied : c.copy} onClick={copy}>{copied ? Icon.check : Icon.copy}</IconButton>
        {showRetry && <IconButton label={c.retry} onClick={onRetry} disabled={!canRetry}>{Icon.retry}</IconButton>}
        <IconButton label={c.helpful} pressed={rating === "up"} onClick={() => { const r = rating === "up" ? null : "up"; onRate(r); if (r) onAnnounce(c.feedbackLocal); }}>{Icon.up}</IconButton>
        <IconButton label={c.notHelpful} pressed={rating === "down"} onClick={() => { const r = rating === "down" ? null : "down"; onRate(r); if (r) onAnnounce(c.feedbackLocal); }}>{Icon.down}</IconButton>
        {usedSources && list.length > 0 && (
          <IconButton label={c.howFound} expanded={open} controls={panelId} onClick={() => setOpen((v) => !v)}>{Icon.found}</IconButton>
        )}
        {usedSources && dataAsOf && (
          <span className={s.asof}>
            <span className={s.asofLong}>{c.dataAsOf} <time dateTime={dataAsOf}>{fmtDate(dataAsOf, lang)}</time></span>
            <span className={s.asofShort} aria-hidden="true">{c.dataAsOf} {shortDate(dataAsOf, lang)}</span>
          </span>
        )}
      </div>
      {usedSources && list.length > 0 && (
        <div id={panelId} className={s.panel} hidden={!open}>
          <p className={s.panelHead}>{c.howFound}</p>
          <ol className={s.steps}>{list.map((x) => <li key={x}>{x}</li>)}</ol>
        </div>
      )}
    </div>
  );
}
