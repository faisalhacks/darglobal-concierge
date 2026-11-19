"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { safeImage } from "@/lib/api";
import { hasArabic } from "@/lib/format";
import type { Footnote, Lang, ListingCard as LC, ProjectCard as PC } from "@/lib/types";
import { cardCopy } from "./copy";
import { Footnotes } from "./Footnotes";
import { ListingCard } from "./ListingCard";
import { ChevronIcon } from "./Media";
import { Iso, ProjectCard, SourceLink, placeOf, statusOf } from "./ProjectCard";
import s from "./cards.module.css";

const VISIBLE = 3;

/** Rich = a project with its own collected page (shown as a card). Index-only and third-party records are rows. */
export const isRich = (p: PC) => !p.detail || p.detail === "page";

type Item = { kind: "p"; p: PC } | { kind: "l"; l: LC };

/** Cards in a wrapping grid when the chat column is >= 760px (container query), else a snap carousel with an end
 * fade and a 44px chevron. At most three rich cards show until "Show all N" (N = every result in this answer, rich
 * cards plus compact rows, so it matches the count the prose states). */
export function CardRail({
  projects, listings, indexOnly = [], footnotes = [], lang,
}: { projects: PC[]; listings: LC[]; indexOnly?: PC[]; footnotes?: Footnote[]; lang: Lang; t?: unknown }) {
  const c = cardCopy(lang);
  const all = [...projects, ...indexOnly.filter((x) => !projects.some((p) => p.id === x.id))];
  // DarGlobal projects first, photo-bearing first among them; listing order is the search order.
  const rich = all.map((p, i) => [p, i] as const).filter(([p]) => isRich(p))
    .sort((a, b) => Number(!safeImage(a[0].image_url)) - Number(!safeImage(b[0].image_url)) || a[1] - b[1]).map(([p]) => p);
  const rows = all.filter((p) => !isRich(p));
  const items: Item[] = [...rich.map((p) => ({ kind: "p" as const, p })), ...listings.map((l) => ({ kind: "l" as const, l }))];
  const total = items.length + rows.length;
  const [open, setOpen] = useState(false);
  const hiding = items.length > VISIBLE;
  const shown = hiding && !open ? items.slice(0, VISIBLE) : items;
  const showRows = rows.length > 0 && (!hiding || open);
  const rowsId = useId();
  const trackId = `${rowsId}-track`;

  const trackRef = useRef<HTMLUListElement>(null);
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const el = trackRef.current;
    if (!el) return;
    const scrollable = getComputedStyle(el).display === "flex" && el.scrollWidth - el.clientWidth > 4;
    setMore(scrollable && Math.abs(el.scrollLeft) < el.scrollWidth - el.clientWidth - 4);
  }, []);
  useEffect(() => {
    measure();
    const el = trackRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure, shown.length]);
  const next = () => {
    const el = trackRef.current;
    if (!el) return;
    const step = (el.querySelector<HTMLElement>(`.${s.item}`)?.offsetWidth ?? 280) + 12;
    const rtl = getComputedStyle(el).direction === "rtl";
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    el.scrollBy({ left: rtl ? -step : step, behavior: reduced ? "auto" : "smooth" });
  };

  if (!total) return null;
  const slugs = rich.map((p) => p.slug || p.id).filter(Boolean);
  return (
    <div className={`${s.scope} ${s.block}`} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      {items.length > 0 && (
        <div className={s.trackWrap}>
          <ul className={s.track} ref={trackRef} id={trackId} data-more={more ? "true" : "false"} onScroll={measure}>
            {shown.map((it) => (
              <li className={s.item} key={it.kind === "p" ? `p-${it.p.id}` : `l-${it.l.id}`}>
                {it.kind === "p" ? <ProjectCard p={it.p} lang={lang} /> : <ListingCard l={it.l} lang={lang} />}
              </li>
            ))}
          </ul>
          {more && (
            <button type="button" className={s.chevron} onClick={next} aria-controls={trackId} aria-label={c.moreCards}>
              <ChevronIcon />
            </button>
          )}
        </div>
      )}
      {showRows && (
        <section aria-labelledby={`${rowsId}-h`}>
          <h3 className={s.rowsHead} id={`${rowsId}-h`}>{c.alsoListed(rows.length)}</h3>
          <ul className={s.rows}>
            {rows.map((p) => {
              const place = placeOf(p, lang);
              const st = statusOf(p.status, lang);
              return (
                <li className={s.row} key={p.id}>
                  <span className={s.rowName} lang={hasArabic(p.name) ? "ar" : "en"} dir="auto">{p.name}</span>
                  <span className={s.rowMeta}>
                    {place && <Iso text={place} />}
                    {place && st && <span aria-hidden="true"> · </span>}
                    {st && <Iso text={st.text} />}
                  </span>
                  <SourceLink url={p.source_url} lang={lang} />
                </li>
              );
            })}
          </ul>
        </section>
      )}
      {hiding && (
        <button type="button" className={s.more} aria-expanded={open} aria-controls={trackId} onClick={() => setOpen((v) => !v)}>
          {open ? c.showFewer : c.showAll(total)}
        </button>
      )}
      <Footnotes items={footnotes} slugs={slugs} lang={lang} />
    </div>
  );
}
