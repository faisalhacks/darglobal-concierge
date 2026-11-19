"use client";
import { safeUrl } from "@/lib/api";
import { fmtDate, hasArabic, hostOf, publisherName } from "@/lib/format";
import type { Lang, Source } from "@/lib/types";
import { cardCopy } from "./copy";
import { highlightCite, numberOf } from "./Cite";
import s from "./cards.module.css";

/** One numbered source: publisher (localised) above the page title, then host and collection date in the UI
 * language. The whole row is the link (one 44px+ target), so long hostnames wrap instead of overlapping. */
function SourceRow({ src, n, lang }: { src: Source; n: number; lang: Lang }) {
  const c = cardCopy(lang);
  const href = safeUrl(src.url);
  const host = hostOf(src.url);
  const pub = publisherName(src.site, lang);
  const title = src.title || host || src.url;
  const inner = (
    <>
      <span className={s.srcNum} aria-hidden="true">{n}</span>
      <span className={s.srcPub}>{pub.latin ? <bdi lang="en" dir="ltr">{pub.text}</bdi> : pub.text}</span>
      <span className={s.srcTitle} lang={hasArabic(title) ? "ar" : "en"} dir="auto">{title}</span>
      {(host || src.scraped_at) && (
        <span className={s.srcMeta}>
          {host && <bdi lang="en" dir="ltr">{host}</bdi>}
          {host && src.scraped_at && <span aria-hidden="true"> · </span>}
          {src.scraped_at && <>{c.collected} <time dateTime={src.scraped_at}>{fmtDate(src.scraped_at, lang)}</time></>}
        </span>
      )}
    </>
  );
  const on = (el: Element) => highlightCite(el, n);
  const off = (el: Element) => highlightCite(el, null);
  return (
    <li className={s.src} id={undefined} data-src-n={n}
      onMouseEnter={(e) => on(e.currentTarget)} onMouseLeave={(e) => off(e.currentTarget)}
      onFocus={(e) => on(e.currentTarget)} onBlur={(e) => off(e.currentTarget)}>
      <span className="sr-only">{n}. </span>
      {href
        ? <a className={s.srcA} href={href} target="_blank" rel="noopener noreferrer">{inner}</a>
        : <span className={s.srcStatic} tabIndex={-1}>{inner}</span>}
    </li>
  );
}

/** Ordered sources numbered to match the [n] chips. Hidden entirely when the answer used no corpus data. The count in
 * the heading is the number of rows listed. `t` is accepted for the old call signature and not used. */
export function SourceList({ sources, lang = "en", asOf }: { sources: Source[]; lang?: Lang; asOf?: string | null; t?: unknown }) {
  if (!sources?.length) return null;
  const c = cardCopy(lang);
  const rows = sources.map((src, i) => ({ src, n: numberOf(src, i) })).sort((a, b) => a.n - b.n);
  return (
    <section className={`${s.scope} ${s.sources}`} aria-label={c.sources(rows.length)}>
      <p className={s.sourcesHead}>
        {c.sources(rows.length)}
        {asOf && <span> · {lang === "ar" ? "البيانات بتاريخ" : "Data as of"} <time dateTime={asOf}>{fmtDate(asOf, lang)}</time></span>}
      </p>
      <ol className={s.sourcesList}>
        {rows.map(({ src, n }) => <SourceRow key={`${n}-${src.url}`} src={src} n={n} lang={lang} />)}
      </ol>
    </section>
  );
}
