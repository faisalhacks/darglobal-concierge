"use client";
import { fmtMoney, fmtNumber, implausibleArea } from "@/lib/format";
import { STRINGS } from "@/lib/i18n";
import type { Lang, ListingCard as LC } from "@/lib/types";
import { cardCopy } from "./copy";
import { Photo } from "./Media";
import { Iso, SourceLink, placeOf } from "./ProjectCard";
import s from "./cards.module.css";

/** "Apartment 175.24 SQM with 1 Bedroom" -> "Apartment": the numbers are shown once, in the facts row. */
function listingType(title: string, lang: Lang): string | null {
  const m = /^\s*([A-Za-z][A-Za-z\s-]*?)\s+(?:\d|for\b|with\b|in\b)/i.exec(title || "");
  const word = (m?.[1] ?? "").trim();
  if (!word) return null;
  return STRINGS[lang].propertyTypes[word.toLowerCase()] ?? (lang === "ar" ? null : word);
}

/** Wasalt listing: 4:3 photo (portrait originals letterboxed), sans title, facts (beds, area, price). An area that is
 * implausible for the bedroom count is shown with a check note instead of as fact. */
export function ListingCard({ l, lang }: { l: LC; lang: Lang; t?: unknown }) {
  const c = cardCopy(lang);
  const t = STRINGS[lang];
  const price = fmtMoney(l.price, lang);
  const flagged = Boolean(l.area_flag) || implausibleArea(l.area_m2, l.beds);
  const type = listingType(l.title, lang);
  const city = placeOf({ city: l.city, city_display: l.city_display }, lang);
  const place = l.district || city;
  const facts = [
    l.beds != null ? t.beds(l.beds) : null,
    l.baths != null ? t.baths(l.baths) : null,
    l.area_m2 != null && !flagged ? `${fmtNumber(l.area_m2, lang)} m²` : null,
  ].filter(Boolean) as string[];
  const title = type && place ? <>{t.inArea(type, "")}<Iso text={place} /></> : <Iso text={l.title} />;
  const sub = l.district && city ? city : null;
  return (
    <article className={s.card} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <Photo src={l.image_url} alt={c.photoAlt(l.title)} ratio="4 / 3" letterbox />
      <div className={s.body}>
        <div className={s.top}>
          <span className={s.badge}>{lang === "ar" ? "وصلت" : <bdi lang="en" dir="ltr">Wasalt</bdi>}</span>
          <span className={s.tenure}>{l.listing_type === "rent" ? t.forRent : t.forSale}</span>
        </div>
        <h3 className={s.titleSm}>{title}</h3>
        {sub && <p className={s.place}><Iso text={sub} /></p>}
        {facts.length > 0 && <ul className={s.factList}>{facts.map((f) => <li key={f}><bdi>{f}</bdi></li>)}</ul>}
        {flagged && l.area_m2 != null && (
          <p className={s.check}><bdi dir="ltr">{`${fmtNumber(l.area_m2, lang)} m²`}</bdi> · {c.areaCheck}</p>
        )}
        <p className={s.price}>
          {price ? <bdi className={s.priceAmount}>{price}</bdi> : <span className={s.priceNone}>{c.priceOnRequest}</span>}
          {/* MARKED EDIT (USD display): shown only when the API sends price_usd_approx (SAR/AED/... via the official peg) */}
          {price && l.price_usd_approx != null && (
            <> <bdi dir="ltr" className={s.check}>{`≈ $${fmtNumber(l.price_usd_approx, lang)}`}</bdi></>
          )}
        </p>
        {price && l.listing_type === "rent" && <p className={s.check}>{t.rentNoPeriod}</p>}
        <SourceLink url={l.source_url} lang={lang} />
      </div>
    </article>
  );
}
