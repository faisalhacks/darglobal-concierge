"use client";
import Link from "next/link";
import { useEffect, useRef } from "react";
import { fmtDate } from "@/lib/format";
import { isolate } from "@/lib/bidi";
import { shellT } from "@/lib/shellStrings";
import { useApp } from "./AppContext";

const FOCUSABLE = 'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * About/sources: the rail's copy for screens where the rail is not inline (< 900px) and for the collapsed strip.
 * A native modal <dialog> (bottom sheet on phone, inline-start side sheet on tablet and desktop): the rest of the page
 * is inert, Tab cycles inside, Esc and the backdrop close it, focus returns to whatever opened it.
 * Its title is an h2: the page h1 stays in the rail (visually hidden below 900px), so there is always exactly one h1.
 */
export function AboutSheet() {
  const { t, lang, meta, aboutOpen, closeAbout, aboutTrigger } = useApp();
  const ref = useRef<HTMLDialogElement | null>(null);
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  const both = dg > 0;

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (aboutOpen && !d.open) {
      try { d.showModal(); } catch { d.setAttribute("open", ""); }
      d.querySelector<HTMLElement>(".about-sheet__close")?.focus();
    } else if (!aboutOpen && d.open) {
      d.close();
    }
  }, [aboutOpen]);

  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    const onClose = () => {
      closeAbout();
      const trg = aboutTrigger.current;
      // The trigger may live in a menu that has since closed; fall back to the menu button that is still there.
      if (trg && trg.isConnected) trg.focus();
    };
    d.addEventListener("close", onClose);
    return () => d.removeEventListener("close", onClose);
  }, [closeAbout, aboutTrigger]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLDialogElement>) => {
    if (e.key !== "Tab") return;
    const items = Array.from(e.currentTarget.querySelectorAll<HTMLElement>(FOCUSABLE)).filter((el) => el.offsetParent !== null);
    if (!items.length) return;
    const first = items[0], last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
    else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
  };
  // A click on the backdrop lands on the <dialog> element itself (the panel fills its content box).
  const onClick = (e: React.MouseEvent<HTMLDialogElement>) => { if (e.target === e.currentTarget) e.currentTarget.close(); };

  const titleId = "about-sheet-title";
  return (
    <dialog ref={ref} className="about-sheet" aria-labelledby={titleId} onKeyDown={onKeyDown} onClick={onClick}>
      <div className="about-sheet__panel">
        <div className="about-sheet__head">
          <h2 id={titleId} className="about-sheet__title">{both ? t.railHeadlineBoth : t.railHeadline}</h2>
          <button type="button" className="hdr-icon about-sheet__close" aria-label={shellT(t, lang, "aboutClose")}
            onClick={() => ref.current?.close()}>
            <svg className="icon" width="20" height="20" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M6 6l12 12M18 6 6 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
            </svg>
          </button>
        </div>
        <p className="about-sheet__lede">{isolate(both ? t.railLedeBoth : t.railLede, lang)}</p>
        {meta?.data_as_of && (
          <p className="about-sheet__asof">
            {t.statAsOf} <time dateTime={meta.data_as_of}>{fmtDate(meta.data_as_of, lang)}</time>
          </p>
        )}
        <ul className="about-sheet__links">
          <li><Link href="/how-it-works/" onClick={() => ref.current?.close()}>{t.railHow}</Link></li>
          <li><Link href="/evals/" onClick={() => ref.current?.close()}>{shellT(t, lang, "railGuardrails")}</Link></li>
          <li><Link href="/privacy/" onClick={() => ref.current?.close()}>{t.navPrivacy}</Link></li>
        </ul>
        <p className="about-sheet__legal">{t.brandSub}</p>
      </div>
    </dialog>
  );
}
