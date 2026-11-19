"use client";
import { useEffect, useState } from "react";
import { getJSON, safeImage, safeUrl } from "@/lib/api";
import { fmtDate, fmtMoney, fmtNumber, hasArabic, lookup } from "@/lib/format";
import { STRINGS, type Strings } from "@/lib/i18n";
import type {
  CalcEvent, Chip, CompareEvent, Lang, ListingCard as LC, ProjectCard as PC, Source, TraceEvent,
} from "@/lib/types";

/** The photo, or nothing: a card without a usable photo is a compact text card, never a large empty placeholder. */
function Img({ src, alt }: { src: string | null; alt: string }) {
  const safe = safeImage(src);
  const [failed, setFailed] = useState(false);
  if (!safe || failed) return null;
  return (
    <div className="card__media">
      {/* eslint-disable-next-line @next/next/no-img-element */}
      <img src={safe} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
    </div>
  );
}

/** Brand badge. Both brands share the neutral style: gold is reserved for the primary action, prices and focus. */
function SiteBadge({ site }: { site: string }) {
  return <span className="badge" lang="en" dir="ltr">{site}</span>;
}

/** Optional fields a card may carry; when the card lacks them they are read once from /api/projects/{slug}. */
type ProjectExtra = { brand_partner?: string | null; scraped_at?: string | null; licence_note?: string | null; licence_url?: string | null };
const detailCache = new Map<string, Promise<ProjectExtra | null>>();
function fetchDetail(slug: string): Promise<ProjectExtra | null> {
  let pr = detailCache.get(slug);
  if (!pr) {
    pr = getJSON<Record<string, unknown>>(`/api/projects/${encodeURIComponent(slug)}`)
      .then((d) => ({
        brand_partner: (d.brand_partner as string) ?? null,
        scraped_at: (d.scraped_at as string) ?? null,
        // Verbatim licence wording, only when the dataset row holds it (data lane). Never written here.
        licence_note: ((d.licence_note ?? d.license_note) as string) ?? null,
        licence_url: ((d.licence_url ?? d.license_url) as string) ?? null,
      }))
      .catch(() => null);
    detailCache.set(slug, pr);
  }
  return pr;
}
function useProjectExtra(p: PC): ProjectExtra {
  const own = p as PC & ProjectExtra;
  const complete = "brand_partner" in own && "scraped_at" in own;
  const [extra, setExtra] = useState<ProjectExtra | null>(null);
  useEffect(() => {
    if (complete || !p.slug) return;
    let live = true;
    fetchDetail(p.slug).then((d) => { if (live) setExtra(d); });
    return () => { live = false; };
  }, [p.slug, complete]);
  return {
    brand_partner: own.brand_partner ?? extra?.brand_partner ?? null,
    scraped_at: own.scraped_at ?? extra?.scraped_at ?? null,
    licence_note: own.licence_note ?? extra?.licence_note ?? null,
    licence_url: own.licence_url ?? extra?.licence_url ?? null,
  };
}

/** Place and status in the card language: closed-vocabulary lookup only; unmapped values stay as published. */
function placeText(display: string | null | undefined, raw: string | null | undefined, t: Strings, lang: Lang) {
  if (lang !== "ar") return display ?? raw ?? null;
  if (display && display !== raw) return display;
  return lookup(raw, t.places)?.text ?? null;
}
function Status({ v, t, lang }: { v: string | null; t: Strings; lang: Lang }) {
  if (!v) return null;
  const hit = lang === "ar" ? lookup(v, t.statusLabels) : null;
  if (hit?.mapped) return <span className="card__status">{hit.text}</span>;
  return <span className="card__status" lang="en" dir="auto">{v}</span>;
}

/** "Source: <origin> · collected <date>", the origin linking to the page it came from. */
function SourceLine({ url, origin, date, t, lang }: { url: string; origin: string; date?: string | null; t: Strings; lang: Lang }) {
  const href = safeUrl(url);
  const label = <>{t.cardSource("")}<bdi>{origin}</bdi></>;
  return (
    <p className="card__source">
      {href ? <a href={href} target="_blank" rel="noopener noreferrer">{label}</a> : <span>{label}</span>}
      {date && <span className="card__collected"><span className="card__sep" aria-hidden="true"> · </span>{t.collected} <time dateTime={date}>{fmtDate(date, lang)}</time></span>}
    </p>
  );
}

export function ProjectCard({ p, t, lang }: { p: PC; t: Strings; lang: Lang }) {
  const price = fmtMoney(p.price_from, lang);
  const indexOnly = p.detail === "index";
  const thirdParty = p.detail === "thirdparty";
  const srcSite = indexOnly ? t.srcIndex : (p.source_site || p.site);
  const extra = useProjectExtra(p);
  const photo = Boolean(safeImage(p.image_url));
  const place = [placeText(p.city_display, p.city, t, lang), placeText(p.country_display, p.country, t, lang)]
    .filter(Boolean).join(lang === "ar" ? "، " : ", ");
  // The note links only to the page it was collected from; never to a different source.
  const noteHref = safeUrl(extra.licence_url);
  return (
    <article className={`card${photo ? "" : " card--type"}`}>
      <Img src={p.image_url} alt={p.name} />
      <div className="card__body">
        <div className="card__top"><SiteBadge site={p.site} /><Status v={p.status} t={t} lang={lang} /></div>
        <h3 className="card__title" lang={hasArabic(p.name) ? "ar" : "en"} dir="auto">{p.name}</h3>
        {place && <p className="card__place">{place}</p>}
        {extra.brand_partner && (
          <p className="card__brand"><span className="card__brand-label">{t.brandPartner}</span> <bdi lang="en" dir="ltr">{extra.brand_partner}</bdi></p>
        )}
        <p className="card__price">
          {price
            ? (<><span className="card__price-label">{t.priceFrom}</span> <bdi>{price}</bdi></>)
            : <span className="card__price-none">{lang === "ar" ? t.priceOnRequest : (p.price_label || t.priceOnRequest)}</span>}
        </p>
        {indexOnly && <p className="card__note">{t.listedOnIndex}</p>}
        {thirdParty && <p className="card__note">{t.fromThirdParty(p.source_site || p.site)}</p>}
        {extra.licence_note && (
          <p className="card__licence" lang="en" dir="ltr">
            {extra.licence_note}
            {noteHref && <> <a href={noteHref} target="_blank" rel="noopener noreferrer">{hostOf(noteHref)}</a></>}
          </p>
        )}
        <SourceLine url={p.source_url} origin={srcSite} date={extra.scraped_at} t={t} lang={lang} />
      </div>
    </article>
  );
}

/** "Apartment 175.24 SQM with 1 Bedroom" -> "Apartment": the numbers are shown once, in the facts row. */
function listingType(title: string, t: Strings): string | null {
  const m = /^\s*([A-Za-z][A-Za-z\s-]*?)\s+(?:\d|for\b|with\b|in\b)/i.exec(title || "");
  const word = (m?.[1] ?? "").trim();
  if (!word) return null;
  const key = word.toLowerCase();
  return t.propertyTypes[key] ?? word;
}

export function ListingCard({ l, t, lang }: { l: LC; t: Strings; lang: Lang }) {
  const price = fmtMoney(l.price, lang);
  const facts = [
    l.beds != null ? t.beds(l.beds) : null,
    l.baths != null ? t.baths(l.baths) : null,
    l.area_m2 != null ? `${fmtNumber(l.area_m2, lang)} m²` : null,
  ].filter(Boolean) as string[];
  const type = listingType(l.title, t);
  const city = placeText(l.city_display, l.city, t, lang);
  const place = l.district || city;
  // District names are published in Latin script only; they are shown as published (isolated), never transliterated.
  const title = type && place ? <>{t.inArea(type, "")}<bdi lang={l.district ? "en" : undefined}>{place}</bdi></> : l.title;
  const sub = l.district && l.city ? city : null;
  return (
    <article className={`card card--listing${safeImage(l.image_url) ? "" : " card--text"}`}>
      <Img src={l.image_url} alt={l.title} />
      <div className="card__body">
        <div className="card__top"><SiteBadge site={l.site} /><span className="card__status">{l.listing_type === "rent" ? t.forRent : t.forSale}</span></div>
        <h3 className="card__title card__title--sm">{title}</h3>
        {sub && <p className="card__place">{sub}</p>}
        {facts.length > 0 && <ul className="card__facts">{facts.map((f) => <li key={f}><bdi>{f}</bdi></li>)}</ul>}
        <p className="card__price">{price ? <bdi>{price}</bdi> : <span className="card__price-none">{t.priceOnRequest}</span>}</p>
        {price && l.listing_type === "rent" && <p className="card__note">{t.rentNoPeriod}</p>}
        <SourceLine url={l.source_url} origin={l.site} date={(l as LC & { scraped_at?: string }).scraped_at} t={t} lang={lang} />
      </div>
    </article>
  );
}

/** Projects with a photo and their own hand-read page first, then other official pages, third-party records, index rows. */
const rank = (p: PC) => (p.detail === "page" || !p.detail ? 0 : p.detail === "thirdparty" ? 2 : 3) - (safeImage(p.image_url) ? 1 : 0);

export function CardRail({ projects, listings, t, lang }: { projects: PC[]; listings: LC[]; t: Strings; lang: Lang }) {
  // Every project is a card: a photo card where the extract holds a photo, otherwise a typographic card. No drawings.
  const ordered = projects.map((p, i) => [p, i] as const).sort((a, b) => rank(a[0]) - rank(b[0]) || a[1] - b[1]).map(([p]) => p);
  const n = ordered.length + listings.length;
  if (!n) return null;
  return (
    // Up to three cards sit in a grid; only a longer set scrolls sideways (with snap and a themed thin scrollbar).
    <div className={`card-rail${n > 3 ? " card-rail--scroll" : ""}`} role="list" data-count={n} tabIndex={n > 3 ? 0 : undefined}>
      {ordered.map((p) => <div role="listitem" key={`p-${p.id}`}><ProjectCard p={p} t={t} lang={lang} /></div>)}
      {listings.map((l) => <div role="listitem" key={`l-${l.id}`}><ListingCard l={l} t={t} lang={lang} /></div>)}
    </div>
  );
}

export function CompareTable({ c, t }: { c: CompareEvent; t: Strings }) {
  return (
    <figure className="compare">
      <figcaption className="compare__caption">{t.compareTitle}</figcaption>
      <div className="compare__scroll" tabIndex={0} role="region" aria-label={t.compareTitle}>
        <table>
          <thead>
            <tr>
              <th scope="col"><span className="sr-only">Field</span></th>
              {c.columns.map((col) => (
                <th scope="col" key={col.id}><span className="compare__name">{col.name}</span><SiteBadge site={col.site} /></th>
              ))}
            </tr>
          </thead>
          <tbody>
            {c.rows.map((r) => (
              <tr key={r.label}>
                <th scope="row">{r.label}</th>
                {r.values.map((v, i) => <td key={i}>{v == null || v === "" ? <span className="muted compare__none">{t.notPublished}</span> : v}</td>)}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {c.sources?.length > 0 && <SourceList sources={c.sources} t={t} />}
    </figure>
  );
}

function kv(o: Record<string, unknown>, t: Strings, lang: Lang, cur?: string | null) {
  return Object.entries(o ?? {})
    .filter(([k, v]) => !["currency", "approximate"].includes(k) && v != null && typeof v !== "object")
    .map(([k, v]) => {
      const label = t.calcLabels[k] ?? k.replace(/_/g, " ");
      let shown = String(v);
      if (typeof v === "number") {
        const money = !/percent|^n$|instal|rate|area/.test(k) || /per_instal|per_m2/.test(k);
        shown = fmtNumber(v, lang) + (k.includes("percent") ? "%" : money && cur ? ` ${cur}` : "");
      }
      return [label, shown] as const;
    });
}

export function CalcResult({ c, t }: { c: CalcEvent; t: Strings }) {
  const lang: Lang = t === STRINGS.ar ? "ar" : "en";
  const r = (c.result ?? {}) as Record<string, unknown>;
  const inp = (c.inputs ?? {}) as Record<string, unknown>;
  const cur = (r.currency ?? inp.currency ?? null) as string | null;
  const inCur = (inp.currency ?? inp.from ?? null) as string | null;
  const results = kv(r, t, lang, cur);
  return (
    <section className="calc" aria-label={t.calcKinds[c.kind] ?? c.kind}>
      {/* Dedupe by result key, not label text: a "down_payment" result already heads the card in any language. */}
      {!Object.keys(r).includes(c.kind) && (
        <p className="calc__kind">{t.calcKinds[c.kind] ?? c.kind}</p>
      )}
      <dl className="calc__result">
        {results.map(([k, v]) => (<div key={k}><dt>{k}</dt><dd><bdi>{v}</bdi></dd></div>))}
      </dl>
      <dl className="calc__meta">
        <div><dt>{t.calcInputs}</dt><dd>{kv(inp, t, lang, inCur).map(([k, v]) => <span key={k}>{k}: <bdi>{v}</bdi></span>)}</dd></div>
        <div><dt>{t.calcFormula}</dt><dd><code dir="ltr">{c.formula}</code></dd></div>
      </dl>
      <p className="calc__disclaimer">{c.disclaimer}</p>
    </section>
  );
}

const isListingUrl = (u: string) => /wasalt\.(sa|com)\/(?:[a-z]{2}\/)?property\//i.test(u);

function hostOf(url: string): string {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

/** One source: who published it, the page title, and a small preview line (host and collection date). */
function SourceRow({ s, lang }: { s: Source; lang: Lang }) {
  const href = safeUrl(s.url);
  const host = hostOf(s.url);
  return (
    <li>
      <span className="sources__site" lang="en" dir="ltr">{s.site}</span>
      <span className="sources__body">
        {href ? <a href={href} target="_blank" rel="noopener noreferrer">{s.title || href}</a> : <span>{s.title}</span>}
        {(host || s.scraped_at) && (
          <span className="sources__meta">
            {host && <bdi lang="en" dir="ltr">{host}</bdi>}
            {host && s.scraped_at && " · "}
            {s.scraped_at && <time dateTime={s.scraped_at}>{fmtDate(s.scraped_at, lang)}</time>}
          </span>
        )}
      </span>
    </li>
  );
}

export function SourceList({ sources, t, asOf, lang }: { sources: Source[]; t: Strings; asOf?: string; lang?: Lang }) {
  if (!sources.length && !asOf) return null;
  // Listing pages are near-identical titles: group two or more of them behind one expandable row.
  const listing = sources.filter((s) => isListingUrl(s.url));
  const grouped = listing.length >= 2;
  const rest = grouped ? sources.filter((s) => !isListingUrl(s.url)) : sources;
  return (
    <div className="sources">
      <p className="sources__head">
        <span>{sources.length > 0 ? t.sources : ""}</span>
        {asOf && <span className="sources__asof">{t.dataAsOf} {fmtDate(asOf, lang ?? "en")}</span>}
      </p>
      {sources.length > 0 && <ol>
        {rest.map((s, i) => <SourceRow key={`${s.url}-${i}`} s={s} lang={lang ?? "en"} />)}
        {grouped && (
          <li className="sources__group">
            <details>
              <summary><span className="sources__site" lang="en" dir="ltr">Wasalt</span><span>{t.listingSources(listing.length)}</span></summary>
              <ol>{listing.map((s, i) => <SourceRow key={`${s.url}-${i}`} s={s} lang={lang ?? "en"} />)}</ol>
            </details>
          </li>
        )}
      </ol>}
    </div>
  );
}

export function Chips({ chips, onPick, disabled, trapLabel, label }: { chips: Chip[]; onPick: (c: Chip) => void; disabled?: boolean; trapLabel?: string; label?: string }) {
  if (!chips.length) return null;
  return (
    <div className="chips" role="list" aria-label={label}>
      {chips.map((c) => (
        <button
          role="listitem"
          type="button"
          key={c.label}
          className={`chip${trapLabel && c.label === trapLabel ? " chip--trap" : ""}`}
          onClick={() => onPick(c)}
          disabled={disabled}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}

const human = (v: string) => v.replace(/[_-]+/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export function Trace({ tr, t, nSources = 0 }: { tr: TraceEvent; t: Strings; nSources?: number }) {
  const max = Math.max(1e-9, ...(tr.retrieved ?? []).map((r) => r.score));
  return (
    <details className="trace">
      <summary>{t.howFound}<span className="trace__counts">{t.traceSummary(nSources, tr.latency_ms / 1000)}</span></summary>
      <dl className="trace__grid">
        <div><dt>{t.traceIntent}</dt><dd>{t.intentLabels[tr.intent] ?? human(tr.intent)}</dd></div>
        <div><dt>{t.tracePath}</dt><dd>{t.pathLabels[tr.path] ?? tr.path}</dd></div>
        <div><dt>{t.traceTool}</dt><dd>{tr.tool ? (t.toolLabels[tr.tool] ?? human(tr.tool)) : t.traceNone}</dd></div>
        {tr.llm_calls > 0 && tr.model
          ? <div><dt>{t.traceModel}</dt><dd><code dir="ltr">{tr.model}</code></dd></div>
          : (tr.degraded || tr.degraded_reason)
            ? <div><dt>{t.traceModel}</dt><dd>{t.degradedReasons[tr.degraded_reason ?? "no_model"] ?? t.degradedReasons.no_model}</dd></div>
            : null}
        {typeof tr.fallback_hops === "number" && tr.fallback_hops > 0 && <div><dt>{t.traceHops}</dt><dd>{tr.fallback_hops}</dd></div>}
        <div><dt>{t.traceCalls}</dt><dd>{tr.llm_calls}</dd></div>
        <div><dt>{t.traceLatency}</dt><dd dir="ltr">{tr.latency_ms} ms</dd></div>
        <div><dt>{t.traceCache}</dt><dd>{tr.cache_hit ? t.traceHit : t.traceMiss}</dd></div>
      </dl>
      {tr.retrieved?.length > 0 && (
        <div className="trace__retrieved">
          <p>{t.traceRetrieved}</p>
          <ol>
            {tr.retrieved.slice(0, 8).map((r) => (
              <li key={r.id}>
                <span className="trace__title"><bdi>{r.title || r.site || "-"}</bdi>{r.section && <span className="muted"> · <bdi>{r.section}</bdi></span>}</span>
                <span className="trace__bar" style={{ ["--w" as string]: `${Math.max(4, Math.min(100, (r.score / max) * 100))}%` }} aria-hidden="true" />
                <span dir="ltr">{r.score.toFixed(3)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </details>
  );
}
