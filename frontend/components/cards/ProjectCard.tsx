"use client";
import { safeImage, safeUrl } from "@/lib/api";
import { fmtAreaRange, fmtMoney, hasArabic, hostOf, lookup, publisherName } from "@/lib/format";
import { STRINGS } from "@/lib/i18n";
import type { Lang, ProjectCard as PC } from "@/lib/types";
import { cardCopy } from "./copy";
import { ExternalIcon, Photo } from "./Media";
import { useProjectDetail, type ProjectDetail } from "./useProjectDetail";
import s from "./cards.module.css";

/** Place in the card language: the backend's display value, else the closed AR glossary, else the published value
 * (isolated by the caller, so a Latin place inside an Arabic card keeps its own direction). */
export function placeOf(p: { city?: string | null; country?: string | null; city_display?: string | null; country_display?: string | null }, lang: Lang) {
  const t = STRINGS[lang];
  const one = (display: string | null | undefined, raw: string | null | undefined) => {
    if (lang !== "ar") return display ?? raw ?? null;
    if (display && display !== raw) return display;
    return lookup(raw, t.places)?.mapped ? lookup(raw, t.places)!.text : (raw ?? null);
  };
  const parts = [one(p.city_display, p.city), one(p.country_display, p.country)].filter(Boolean) as string[];
  return [...new Set(parts)].join(lang === "ar" ? "، " : ", ");
}

export function statusOf(v: string | null | undefined, lang: Lang): { text: string; lang: Lang } | null {
  if (!v) return null;
  const hit = lang === "ar" ? lookup(v, STRINGS.ar.statusLabels) : null;
  return hit?.mapped ? { text: hit.text, lang: "ar" } : { text: v, lang: hasArabic(v) ? "ar" : "en" };
}

/** Text that may be Latin inside an Arabic card is isolated with its own lang. */
export function Iso({ text, className }: { text: string; className?: string }) {
  const ar = hasArabic(text);
  return <bdi className={className} lang={ar ? "ar" : "en"} dir={ar ? "rtl" : "ltr"}>{text}</bdi>;
}

/** Merge the facts the card carries with the record's detail (card values win; nothing is invented). */
export function projectFacts(p: PC, d: ProjectDetail | null) {
  const units = Array.isArray(p.unit_types) ? p.unit_types : typeof p.unit_types === "string" && p.unit_types ? [p.unit_types] : d?.unit_types ?? [];
  return {
    units: units.join(", "),
    area: [p.area_min_m2 ?? d?.area_min_m2 ?? null, p.area_max_m2 ?? d?.area_max_m2 ?? null] as const,
    handover: p.handover_year != null && p.handover_year !== "" ? String(p.handover_year) : d?.handover_year ?? null,
    image: safeImage(p.image_url) ?? (d?.image_urls ?? []).map(safeImage).find(Boolean) ?? null,
  };
}

export function SourceLink({ url, lang }: { url: string | null | undefined; lang: Lang }) {
  const href = safeUrl(url);
  if (!href) return null;
  const c = cardCopy(lang);
  const host = hostOf(href);
  return (
    <a className={s.srcLink} href={href} target="_blank" rel="noopener noreferrer">
      <span>{c.openOn("")}<bdi lang="en" dir="ltr">{host}</bdi></span>
      <ExternalIcon />
      <span className="sr-only">{c.newTab}</span>
    </a>
  );
}

/** DarGlobal project with a collected page. Order (spec §4): photo, source badge, title, place, fact strip, price,
 * source link. Content-height; licence and provenance notes live in the footnotes under the block, never here. */
export function ProjectCard({ p, lang }: { p: PC; lang: Lang; t?: unknown }) {
  const c = cardCopy(lang);
  const needDetail = p.unit_types == null || p.area_min_m2 === undefined || p.handover_year === undefined;
  const d = useProjectDetail(p.slug || p.id, !needDetail && Boolean(p.image_url));
  const f = projectFacts(p, d);
  const place = placeOf(p, lang);
  const status = statusOf(p.status, lang);
  const area = fmtAreaRange(f.area[0], f.area[1], lang);
  const price = fmtMoney(p.price_from, lang);
  const pub = publisherName(p.source_site || p.site, lang);
  return (
    <article className={s.card} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <Photo src={f.image} alt={c.photoAlt(p.name)} ratio="16 / 10" />
      <div className={s.body}>
        <div className={s.top}><span className={s.badge}>{pub.latin ? <bdi lang="en" dir="ltr">{pub.text}</bdi> : pub.text}</span></div>
        <h3 className={s.title} lang={hasArabic(p.name) ? "ar" : "en"} dir="auto">{p.name}</h3>
        {place && <p className={s.place}><Iso text={place} /></p>}
        {(f.units || area || status || f.handover) && (
          <dl className={s.facts}>
            {f.units && <><dt>{c.factUnits}</dt><dd><Iso text={f.units} /></dd></>}
            {area && <><dt>{c.factArea}</dt><dd><bdi dir="ltr">{area}</bdi></dd></>}
            {status && <><dt>{c.factStatus}</dt><dd lang={status.lang}>{status.lang === "en" && lang === "ar" ? <Iso text={status.text} /> : status.text}</dd></>}
            {f.handover && <><dt>{c.factHandover}</dt><dd><bdi>{f.handover}</bdi></dd></>}
          </dl>
        )}
        <p className={s.price}>
          {price
            ? <><span className={s.priceLabel}>{c.priceFrom}</span> <bdi className={s.priceAmount}>{price}</bdi></>
            : <span className={s.priceNone}>{c.priceOnRequest}</span>}
        </p>
        <SourceLink url={p.source_url} lang={lang} />
      </div>
    </article>
  );
}
