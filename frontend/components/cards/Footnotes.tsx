"use client";
import { safeUrl } from "@/lib/api";
import { hasArabic, hostOf } from "@/lib/format";
import type { Footnote, Lang } from "@/lib/types";
import { cardCopy } from "./copy";
import { useProjectDetails } from "./useProjectDetail";
import s from "./cards.module.css";

type Note = { text: string; url: string | null; lang: Lang };

const norm = (f: Footnote): Note | null => {
  const text = (typeof f === "string" ? f : f?.text ?? "").trim();
  if (!text) return null;
  const url = typeof f === "string" ? null : f.url ?? null;
  const lang: Lang = typeof f !== "string" && f.lang ? f.lang : hasArabic(text) ? "ar" : "en";
  return { text, url, lang };
};

/** Licence and legal lines as numbered footnotes under the rich block, full width, at the legal size. Verbatim text
 * only (from the payload or the project's own licence row); nothing is written here. In an Arabic answer an English
 * note gets an Arabic summary line and its original under a "النص الأصلي" disclosure. */
export function Footnotes({ items = [], slugs = [], lang }: { items?: Footnote[]; slugs?: string[]; lang: Lang }) {
  const c = cardCopy(lang);
  const details = useProjectDetails(slugs);
  const notes: Note[] = [];
  const seen = new Set<string>();
  const add = (n: Note | null) => {
    if (!n || seen.has(n.text)) return;
    seen.add(n.text);
    notes.push(n);
  };
  items.forEach((f) => add(norm(f)));
  details.forEach((d) => d?.licence_note && add({ text: d.licence_note, url: d.licence_url, lang: hasArabic(d.licence_note) ? "ar" : "en" }));
  if (!notes.length) return null;
  return (
    <section className={`${s.scope} ${s.notes}`} aria-label={c.notes}>
      <p className={s.notesHead}>{c.notes}</p>
      <ol>
        {notes.map((n, i) => {
          const href = safeUrl(n.url);
          const link = href ? <> <a href={href} target="_blank" rel="noopener noreferrer"><bdi lang="en" dir="ltr">{hostOf(href)}</bdi></a></> : null;
          if (lang === "ar" && n.lang === "en") {
            return (
              <li key={i}>
                {c.legalSummary}
                <details>
                  <summary>{c.original}</summary>
                  <p lang="en" dir="ltr" style={{ margin: 0 }}>{n.text}{link}</p>
                </details>
              </li>
            );
          }
          return <li key={i} lang={n.lang} dir={n.lang === "ar" ? "rtl" : "ltr"}>{n.text}{link}</li>;
        })}
      </ol>
    </section>
  );
}
