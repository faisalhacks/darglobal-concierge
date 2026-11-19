"use client";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { safeImage } from "@/lib/api";
import { hasArabic } from "@/lib/format";
import { isolate } from "@/lib/bidi";
import type { CompareEvent, Lang } from "@/lib/types";
import { cardCopy } from "./copy";
import { Footnotes } from "./Footnotes";
import { Photo } from "./Media";
import { useProjectDetails } from "./useProjectDetail";
import s from "./cards.module.css";

const blank = (v: string | null | undefined) => v == null || String(v).trim() === "";
const key = (v: string | null | undefined) => String(v ?? "").trim().toLowerCase().replace(/\s+/g, " ");

/** A row differs when at least two columns publish a value and those values are not all the same. Computed from the
 * table cells only (lane E may send the same flag as `differs`; its value wins). */
export function rowDiffers(values: (string | null)[]): boolean {
  const vals = values.filter((v) => !blank(v)).map(key);
  return vals.length >= 2 && new Set(vals).size > 1;
}

/** Comparison as one table: verdict line above (code-built), project names (with a thumbnail when a collected image
 * loads) in the header, a sticky label column, differing cells tinted and marked for screen readers, licence text as
 * footnotes under the table. Below a 760px container the table scrolls inside its own frame with an edge cue. */
export function CompareTable({ c, lang = "en" }: { c: CompareEvent; lang?: Lang; t?: unknown }) {
  const cc = cardCopy(lang);
  const capId = useId();
  const details = useProjectDetails(c.columns.map((col) => col.slug || col.id));
  const flags = c.rows.map((r) => (typeof r.differs === "boolean" ? r.differs : rowDiffers(r.values)));
  const differing = c.rows.filter((_, i) => flags[i]).map((r) => r.label);
  const sep = lang === "ar" ? "، " : ", ";
  const verdict = (c.verdict ?? "").trim() || (c.rows.length ? (differing.length ? cc.verdictDiffer(differing.join(sep)) : cc.verdictSame) : "");

  const ref = useRef<HTMLDivElement>(null);
  const [more, setMore] = useState(false);
  const measure = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    const max = el.scrollWidth - el.clientWidth;
    setMore(max > 4 && Math.abs(el.scrollLeft) < max - 4);
  }, []);
  useEffect(() => {
    measure();
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, [measure]);

  return (
    <figure className={`${s.scope} ${s.compare}`} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"} aria-labelledby={capId}>
      <figcaption className={s.caption} id={capId}>{cc.compareCaption}</figcaption>
      {verdict && <p className={s.verdict}>{isolate(verdict, lang)}</p>}
      <div className={s.scroller} ref={ref} onScroll={measure} data-more={more ? "true" : "false"}
        tabIndex={more ? 0 : undefined} role="region" aria-labelledby={capId}>
        <table className={s.table}>
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">{cc.compareField}</span></th>
              {c.columns.map((col, i) => {
                const img = safeImage(col.image_url) ?? (details[i]?.image_urls ?? []).map(safeImage).find(Boolean) ?? null;
                return (
                  <th scope="col" key={col.id}>
                    <Photo src={img} alt={cc.thumbAlt(col.name)} ratio="16 / 10" className={s.thumb} />
                    <span className={s.colName} lang={hasArabic(col.name) ? "ar" : "en"} dir="auto">{col.name}</span>
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {c.rows.map((r, ri) => (
              <tr key={`${r.label}-${ri}`}>
                <th scope="row">
                  {r.label}
                  {flags[ri] && <span className="sr-only"> ({cc.compareDiffers})</span>}
                </th>
                {c.columns.map((col, i) => {
                  const v = r.values[i];
                  return (
                    <td key={col.id} data-differs={flags[ri] && !blank(v) ? "true" : undefined}>
                      {blank(v)
                        ? <span className={s.none}>{cc.notPublished}</span>
                        : <bdi lang={hasArabic(String(v)) ? "ar" : lang === "ar" ? "en" : undefined} dir="auto">{v}</bdi>}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Footnotes items={c.footnotes ?? []} slugs={c.columns.map((col) => col.slug || col.id)} lang={lang} />
    </figure>
  );
}
