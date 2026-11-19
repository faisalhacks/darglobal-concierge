"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getJSON, safeImage, safeUrl } from "@/lib/api";
import { fmtDate, hasArabic } from "@/lib/format";
import { isolate } from "@/lib/bidi";
import { shellT } from "@/lib/shellStrings";
import type { ProjectCard } from "@/lib/types";
import { useApp, useRail } from "./AppContext";
import { Icon } from "./SiteHeader";
import { StressTested } from "./StressTested"; // showcase block, last in the rail

/**
 * One real DarGlobal project photograph, hot-linked from its collected project page (owner decision, SPEC D5).
 * No image collected, or the request fails: a typographic block with the project's own name and place instead of a
 * drawing, and no caption. The caption link is a mouse convenience; it stays out of the tab order (the same page is
 * reachable from any answer's sources).
 */
function RailPhoto() {
  const { t, lang, meta } = useApp();
  const [p, setP] = useState<ProjectCard | null>(null);
  const [failed, setFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  useEffect(() => {
    if (!dg) return;
    const ac = new AbortController();
    getJSON<ProjectCard[]>(`/api/projects?site=DarGlobal&lang=${lang}`, ac.signal)
      .then((rows) => {
        const list = Array.isArray(rows) ? rows : [];
        const pick = list.find((r) => r.detail !== "index" && safeImage(r.image_url)) ?? list.find((r) => r.detail !== "index") ?? null;
        setP(pick);
        setFailed(false);
        setLoaded(false);
      })
      .catch(() => { /* nothing to show: the block stays out */ });
    return () => ac.abort();
  }, [dg, lang]);
  if (!dg || !p) return null;
  const src = safeImage(p.image_url);
  const href = safeUrl(p.source_url);
  const parts = [p.city_display ?? p.city, p.country_display ?? p.country].filter(Boolean) as string[];
  // Arabic comma only between Arabic place names; Latin values (not yet localised) keep the Latin comma, isolated.
  const place = parts.join(parts.every(hasArabic) ? "، " : ", ");
  if (!src || failed) {
    return (
      <div className="rail-photo rail-photo--type">
        <p className="rail-photo__name"><bdi>{p.name}</bdi></p>
        {place && <p className="rail-photo__place"><bdi>{place}</bdi></p>}
      </div>
    );
  }
  return (
    <figure className="rail-photo" data-loaded={loaded ? "1" : undefined}>
      <div className="rail-photo__frame">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={src} alt={p.name} decoding="async" referrerPolicy="no-referrer"
          onLoad={() => setLoaded(true)} onError={() => setFailed(true)} />
      </div>
      <figcaption className="rail-photo__caption">
        {href
          ? <a href={href} target="_blank" rel="noopener noreferrer" tabIndex={-1}><bdi>{p.name}</bdi>{" · "}{shellT(t, lang, "railPhotoFrom")}</a>
          : <><bdi>{p.name}</bdi>{" · "}{shellT(t, lang, "railPhotoFrom")}</>}
      </figcaption>
    </figure>
  );
}

/** Collapsed: a 56px strip with About/sources, How it works and Expand; the corpus date rides in the About tooltip. */
function RailStrip() {
  const { t, lang, meta, openAbout } = useApp();
  const rail = useRail();
  const asof = meta?.data_as_of ? `${t.statAsOf} ${fmtDate(meta.data_as_of, lang)}` : undefined;
  const about = shellT(t, lang, "aboutSources");
  const expand = shellT(t, lang, "railExpand");
  return (
    <div className="rail__strip">
      <button type="button" className="hdr-icon" aria-label={asof ? `${about}. ${asof}` : about} title={asof ? `${about}\n${asof}` : about}
        onClick={(e) => openAbout(e.currentTarget)}>
        <Icon name="info" />
      </button>
      <Link href="/how-it-works/" className="hdr-icon" aria-label={t.railHow} title={t.railHow}>
        <Icon name="book" />
      </Link>
      <button type="button" className="hdr-icon" aria-label={expand} title={expand} aria-controls="rail" aria-expanded={false}
        onClick={() => rail.setCollapsed(false)}>
        <Icon name="sidebar" />
      </button>
    </div>
  );
}

export function Rail() {
  const { t, lang, meta, metaState } = useApp();
  const rail = useRail();
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  const both = dg > 0;
  const loading = metaState === "loading";
  const hide = loading ? { visibility: "hidden" as const } : undefined;
  return (
    <aside id="rail" className="rail" aria-labelledby="rail-title" data-collapsed={rail.collapsed ? "1" : undefined}>
      {/* The page's only h1. Below 900px and in the collapsed strip it is visually hidden but stays in the DOM. */}
      <h1 id="rail-title" className="rail__headline" style={hide}>{loading || both ? t.railHeadlineBoth : t.railHeadline}</h1>
      <div className="rail__body">
        <p className="rail__lede" style={hide}>{isolate(loading || both ? t.railLedeBoth : t.railLede, lang)}</p>
        <RailPhoto />
        <StressTested variant="rail" />{/* showcase: last in the rail body; the photo shrinks to make room */}
      </div>
      <div className="rail__foot">
        {meta?.data_as_of && (
          <p className="rail__asof">
            {t.statAsOf} <time dateTime={meta.data_as_of}>{fmtDate(meta.data_as_of, lang)}</time>
          </p>
        )}
        <Link href="/how-it-works/" className="rail__link">{t.railHow}</Link>
        <Link href="/evals/" className="rail__link rail__link--quiet">{shellT(t, lang, "railGuardrails")}</Link>
      </div>
      <RailStrip />
    </aside>
  );
}
