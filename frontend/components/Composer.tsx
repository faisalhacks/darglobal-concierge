"use client";
import Link from "next/link";
import { useLayoutEffect, type Ref, type RefObject } from "react";
import { CONV } from "@/lib/conversation-strings";
import type { Lang } from "@/lib/types";
import s from "./Composer.module.css";

export const MAX_CHARS = 1000;
const MAX_LINES = 6;

/** The question box. Docked at the bottom of the chat column in every state (it never moves on first send):
 * auto-grows 1-6 lines and then scrolls, Send becomes Stop in the same place and size while an answer is
 * generating, and a rate limit shows a live countdown above it with Send aria-disabled (the typed text stays). */
export function Composer({
  lang, value, onChange, onSend, onStop, busy, rateLeft, placeholder, active, footer, inputRef, footReserve = 0, alwaysFoot = false,
}: {
  lang: Lang;
  value: string;
  onChange: (v: string) => void;
  onSend: () => void;
  onStop: () => void;
  busy: boolean;
  /** Seconds left on a rate limit, 0 when none. */
  rateLeft: number;
  placeholder: string;
  /** A conversation exists: show the one-line legal note under the box (the page footer is hidden then). */
  active: boolean;
  /** Extra controls under the box (the embed's "New conversation"). */
  footer?: React.ReactNode;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  /** Height (px) of the page footer that disappears once a conversation starts. The line under the box takes exactly
   * that space, so the box itself does not move on first send. */
  footReserve?: number;
  /** Keep the line under the box in every state (the embed, which has no page footer). */
  alwaysFoot?: boolean;
}) {
  const c = CONV[lang];
  const tooLong = value.length > MAX_CHARS;
  const showCounter = value.length > MAX_CHARS - 200;
  const limited = rateLeft > 0;
  const empty = !value.trim();
  const sendBlocked = empty || tooLong || limited;

  // Auto-grow: height follows the content up to six lines, then the textarea scrolls.
  useLayoutEffect(() => {
    const ta = inputRef.current;
    if (!ta) return;
    const cs = window.getComputedStyle(ta);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.5;
    const pad = parseFloat(cs.paddingBlockStart || cs.paddingTop) + parseFloat(cs.paddingBlockEnd || cs.paddingBottom);
    const max = Math.ceil(lh * MAX_LINES + pad);
    ta.style.height = "auto";
    // Empty box: one line (a long placeholder is cut with an ellipsis instead of growing the box).
    const h = value ? Math.min(ta.scrollHeight, max) : Math.ceil(lh + pad);
    ta.style.height = `${h}px`;
    ta.style.overflowY = ta.scrollHeight > max ? "auto" : "hidden";
  }, [value, inputRef, lang]);

  const describedBy = [limited ? "composer-rate" : "", showCounter ? "composer-count" : ""].filter(Boolean).join(" ") || undefined;

  return (
    <form
      className={`composer ${s.composer}`}
      onSubmit={(e) => { e.preventDefault(); if (!sendBlocked && !busy) onSend(); }}
    >
      <div className={s.inner}>
        {limited && (
          <p id="composer-rate" className={`${s.note} ${s.noteWarn}`} role="status" aria-live="polite">
            {c.rateLimited(rateLeft)}
          </p>
        )}
        {tooLong && <p className={`${s.note} ${s.noteWarn}`} role="alert">{c.tooLong}</p>}
        <div className={s.row}>
          <label htmlFor="composer-input" className="sr-only">{c.composerLabel}</label>
          <textarea
            id="composer-input"
            className={s.input}
            ref={inputRef as Ref<HTMLTextAreaElement>}
            rows={1}
            value={value}
            // Empty: follow the interface language so the placeholder starts at the right edge; typed text: auto.
            dir={value ? "auto" : lang === "ar" ? "rtl" : "ltr"}
            placeholder={placeholder}
            maxLength={MAX_CHARS + 200}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (!busy && !sendBlocked) onSend();
              }
            }}
            aria-describedby={describedBy}
          />
          {busy ? (
            <button type="button" className={`${s.btn} ${s.btnStop}`} onClick={onStop} aria-label={c.stopLabel}>
              <svg className={s.icon} viewBox="0 0 24 24" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor" /></svg>
              <span>{c.stop}</span>
            </button>
          ) : (
            <button
              type="submit"
              className={`${s.btn} ${s.btnSend}`}
              aria-disabled={sendBlocked || undefined}
              aria-describedby={limited ? "composer-rate" : undefined}
            >
              <svg className={`${s.icon} ${s.iconDir}`} viewBox="0 0 24 24" aria-hidden="true">
                <path d="M5 12h13M13 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span>{c.send}</span>
            </button>
          )}
        </div>
        {/* During a conversation the page footer is hidden and this line takes its exact height, so the box sits in the
            same place before and after the first send. On the empty state the page footer carries the disclaimer. */}
        {(active || alwaysFoot || showCounter) && (
          <div className={s.foot} style={active && footReserve > 0 ? { minBlockSize: `${footReserve}px` } : undefined}>
            {showCounter
              ? <span id="composer-count" className={tooLong ? s.warn : undefined}>{c.charsLeft(Math.max(0, MAX_CHARS - value.length))}</span>
              : active ? <span className={s.legal}>{c.legalLine} <Link href="/privacy/">{c.privacy}</Link></span> : <span />}
            {footer}
          </div>
        )}
      </div>
    </form>
  );
}
