"use client";
import type { Lang, Source } from "@/lib/types";
import { isolate } from "@/lib/bidi";
import { cardCopy } from "./copy";
import s from "./cards.module.css";

/** The answer that holds a chip or a source row: the assistant turn, or an explicit [data-cite-scope]. */
const scopeOf = (el: Element): ParentNode => el.closest("[data-cite-scope], .turn--assistant, li.turn, article") ?? document;

/** Two-way highlight: every chip [n] and source row n in the same answer get data-hl while one of them is hovered or
 * focused. Pure DOM attributes, so chips (in the prose) and rows (in the sources list) need no shared React state. */
export function highlightCite(from: Element, n: number | null) {
  const scope = scopeOf(from);
  scope.querySelectorAll("[data-hl]").forEach((x) => x.removeAttribute("data-hl"));
  if (n == null) return;
  scope.querySelectorAll(`[data-cite-n="${n}"], [data-src-n="${n}"]`).forEach((x) => x.setAttribute("data-hl", ""));
}

/** Source n of an answer: the one whose backend number matches, else position n-1. */
export function sourceFor(sources: Source[], n: number): Source | undefined {
  return sources.find((x) => x.n === n) ?? (sources.some((x) => typeof x.n === "number") ? undefined : sources[n - 1]);
}

/** Number shown for a source row: the backend's n when present, else its position. */
export const numberOf = (src: Source, i: number) => (typeof src.n === "number" ? src.n : i + 1);

const reduced = () => typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

/** One [n] marker: a superscript-style button. Hover/focus highlights source row n; click scrolls to it and moves
 * focus to its link so the keyboard lands where the eye goes. */
export function Cite({ n, src, lang }: { n: number; src: Source; lang: Lang }) {
  const c = cardCopy(lang);
  const go = (e: React.MouseEvent<HTMLButtonElement>) => {
    const scope = scopeOf(e.currentTarget);
    const row = scope.querySelector<HTMLElement>(`[data-src-n="${n}"]`);
    if (!row) return;
    row.scrollIntoView({ behavior: reduced() ? "auto" : "smooth", block: "nearest" });
    row.querySelector<HTMLElement>("a, [tabindex]")?.focus({ preventScroll: true });
    highlightCite(e.currentTarget, n);
  };
  return (
    <button
      type="button"
      className={s.cite}
      data-cite-n={n}
      aria-label={c.citeLabel(n, src.title || src.site)}
      onClick={go}
      onMouseEnter={(e) => highlightCite(e.currentTarget, n)}
      onMouseLeave={(e) => highlightCite(e.currentTarget, null)}
      onFocus={(e) => highlightCite(e.currentTarget, n)}
      onBlur={(e) => highlightCite(e.currentTarget, null)}
    >
      {n}
    </button>
  );
}

const MARK = /(\[\d{1,2}\](?:\s?\[\d{1,2}\])*)/;

/** Text with [n] markers turned into cite chips. A marker with no matching source stays as plain text; a half-arrived
 * "[1" while streaming is plain text until it closes. Adjacent markers "[1][2]" become two chips. */
export function Cited({ text, sources, lang }: { text: string; sources: Source[]; lang: Lang }) {
  if (!sources.length || !/\[\d{1,2}\]/.test(text)) return <>{isolate(text, lang)}</>;
  const parts = text.split(MARK);
  return (
    <>
      {parts.map((part, i) => {
        if (!MARK.test(part) || !/^\[/.test(part)) return <span key={i}>{isolate(part, lang)}</span>;
        const nums = [...part.matchAll(/\[(\d{1,2})\]/g)].map((m) => Number(m[1]));
        return (
          <span key={i}>
            {nums.map((n, k) => {
              const src = sourceFor(sources, n);
              return src ? <Cite key={k} n={n} src={src} lang={lang} /> : <span key={k}>[{n}]</span>;
            })}
          </span>
        );
      })}
    </>
  );
}
