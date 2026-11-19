"use client";
import { useState } from "react";
import { safeImage, safeUrl } from "@/lib/api";
import { fmtDate, fmtMoney, fmtNumber } from "@/lib/format";
import { STRINGS, type Strings } from "@/lib/i18n";
import type {
  CalcEvent, Chip, CompareEvent, Lang, ListingCard as LC, ProjectCard as PC, Source, TraceEvent,
} from "@/lib/types";

function Img({ src, alt, t }: { src: string | null; alt: string; t: Strings }) {
  const safe = safeImage(src);
  const [failed, setFailed] = useState(false);
  return (
    <div className="card__media">
      {safe && !failed ? (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={safe} alt={alt} loading="lazy" decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
      ) : (
        <div className="card__placeholder" role="img" aria-label={t.imageMissing}>
          <svg viewBox="0 0 120 80" aria-hidden="true" preserveAspectRatio="xMidYMid slice">
            <path d="M0 64h120M18 64V30l22-12 22 12v34M62 64V40h40v24M30 64V44h8v20M74 48h6v6h-6zM88 48h6v6h-6z" fill="none" stroke="currentColor" strokeWidth=".8" />
          </svg>
        </div>
      )}
    </div>
  );
}

function SiteBadge({ site }: { site: string }) {
  return <span className={`badge badge--${site === "Wasalt" ? "wasalt" : "darglobal"}`}>{site}</span>;
}

function SourceLink({ url, site, t }: { url: string; site: string; t: Strings }) {
  const href = safeUrl(url);
  if (!href) return null;
  return (
    <a className="card__source" href={href} target="_blank" rel="noopener noreferrer">
      {t.viewSource} {site}
    </a>
  );
}

export function ProjectCard({ p, t, lang }: { p: PC; t: Strings; lang: Lang }) {
  const price = fmtMoney(p.price_from, lang);
  return (
    <article className="card">
      <Img src={p.image_url} alt={p.name} t={t} />
      <div className="card__body">
        <div className="card__top"><SiteBadge site={p.site} />{p.status && <span className="card__status">{p.status}</span>}</div>
        <h3 className="card__title">{p.name}</h3>
        <p className="card__place">{[p.city, p.country].filter(Boolean).join(", ")}</p>
        <p className="card__price">
          {price ? (<><span className="card__price-label">{t.priceFrom}</span> <bdi>{price}</bdi></>) : <span className="muted">{t.priceOnRequest}</span>}
        </p>
        <SourceLink url={p.source_url} site={p.site} t={t} />
      </div>
    </article>
  );
}

export function ListingCard({ l, t, lang }: { l: LC; t: Strings; lang: Lang }) {
  const price = fmtMoney(l.price, lang);
  const facts = [
    l.beds != null ? t.beds(l.beds) : null,
    l.baths != null ? t.baths(l.baths) : null,
    l.area_m2 != null ? `${fmtNumber(l.area_m2, lang)} m²` : null,
  ].filter(Boolean) as string[];
  return (
    <article className="card card--listing">
      <Img src={l.image_url} alt={l.title} t={t} />
      <div className="card__body">
        <div className="card__top"><SiteBadge site={l.site} /><span className="card__status">{l.listing_type === "rent" ? t.forRent : t.forSale}</span></div>
        <h3 className="card__title card__title--sm">{l.title}</h3>
        <p className="card__place">{[l.district, l.city].filter(Boolean).join(", ")}</p>
        {facts.length > 0 && <ul className="card__facts">{facts.map((f) => <li key={f}><bdi>{f}</bdi></li>)}</ul>}
        <p className="card__price">{price ? <><bdi>{price}</bdi>{l.listing_type === "rent" && <span className="card__price-label"> · {t.rentNoPeriod}</span>}</> : <span className="muted">{t.priceOnRequest}</span>}</p>
        <SourceLink url={l.source_url} site={l.site} t={t} />
      </div>
    </article>
  );
}

export function CardRail({ projects, listings, t, lang }: { projects: PC[]; listings: LC[]; t: Strings; lang: Lang }) {
  if (!projects.length && !listings.length) return null;
  return (
    <div className="card-rail" role="list">
      {projects.map((p) => <div role="listitem" key={`p-${p.id}`}><ProjectCard p={p} t={t} lang={lang} /></div>)}
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
                {r.values.map((v, i) => <td key={i}>{v == null || v === "" ? <span className="muted">{t.notPublished}</span> : v}</td>)}
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
      <p className="calc__kind">{t.calcKinds[c.kind] ?? c.kind}</p>
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

export function SourceList({ sources, t, asOf, lang }: { sources: Source[]; t: Strings; asOf?: string; lang?: Lang }) {
  if (!sources.length && !asOf) return null;
  return (
    <div className="sources">
      <p className="sources__head">
        <span>{sources.length > 0 ? t.sources : ""}</span>
        {asOf && <span className="sources__asof">{t.dataAsOf} {fmtDate(asOf, lang ?? "en")}</span>}
      </p>
      {sources.length > 0 && <ol>
        {sources.map((s, i) => {
          const href = safeUrl(s.url);
          return (
            <li key={`${s.url}-${i}`}>
              <span className="sources__site">{s.site}</span>
              {href ? <a href={href} target="_blank" rel="noopener noreferrer">{s.title || href}</a> : <span>{s.title}</span>}
            </li>
          );
        })}
      </ol>}
    </div>
  );
}

export function Chips({ chips, onPick, disabled, trapLabel }: { chips: Chip[]; onPick: (c: Chip) => void; disabled?: boolean; trapLabel?: string }) {
  if (!chips.length) return null;
  return (
    <div className="chips" role="list">
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

export function Trace({ tr, t }: { tr: TraceEvent; t: Strings }) {
  const max = Math.max(1e-9, ...(tr.retrieved ?? []).map((r) => r.score));
  return (
    <details className="trace">
      <summary>{t.howFound}</summary>
      <dl className="trace__grid">
        <div><dt>{t.traceIntent}</dt><dd><code>{tr.intent}</code></dd></div>
        <div><dt>{t.tracePath}</dt><dd>{t.pathLabels[tr.path] ?? tr.path}</dd></div>
        <div><dt>{t.traceTool}</dt><dd><code>{tr.tool ?? t.traceNone}</code></dd></div>
        <div><dt>{t.traceModel}</dt><dd><code dir="ltr">{tr.model ?? t.traceNone}</code></dd></div>
        <div><dt>{t.traceCalls}</dt><dd>{tr.llm_calls}</dd></div>
        <div><dt>{t.traceLatency}</dt><dd dir="ltr">{tr.latency_ms} ms</dd></div>
        <div><dt>{t.traceCache}</dt><dd>{tr.cache_hit ? t.traceHit : t.traceMiss}</dd></div>
      </dl>
      {tr.retrieved?.length > 0 && (
        <div className="trace__retrieved">
          <p>{t.traceRetrieved}</p>
          <ol dir="ltr">
            {tr.retrieved.slice(0, 8).map((r) => (
              <li key={r.id}>
                <code>{r.id}</code>
                <span className="trace__bar" style={{ ["--w" as string]: `${Math.max(4, Math.min(100, (r.score / max) * 100))}%` }} aria-hidden="true" />
                <span>{r.score.toFixed(3)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </details>
  );
}
