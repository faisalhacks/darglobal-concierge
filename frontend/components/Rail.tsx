"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { getJSON, safeImage, safeUrl } from "@/lib/api";
import { fmtDate } from "@/lib/format";
import type { ProjectCard } from "@/lib/types";
import { useApp } from "./AppContext";

/** One real DarGlobal project photograph, hot-linked from the dataset, captioned with name and source. */
function RailPhoto() {
  const { t, lang, meta } = useApp();
  const [p, setP] = useState<ProjectCard | null>(null);
  const [failed, setFailed] = useState(false);
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  useEffect(() => {
    if (!dg) return;
    const ac = new AbortController();
    getJSON<ProjectCard[]>(`/api/projects?site=DarGlobal&lang=${lang}`, ac.signal)
      .then((rows) => {
        const list = Array.isArray(rows) ? rows : [];
        const pick = list.find((r) => r.detail !== "index" && safeImage(r.image_url)) ?? null;
        setP(pick);
        setFailed(false);
      })
      .catch(() => { /* keep the placeholder */ });
    return () => ac.abort();
  }, [dg, lang]);
  if (!dg) return null;
  const src = safeImage(p?.image_url);
  const href = safeUrl(p?.source_url);
  return (
    <figure className="rail-photo">
      <div className="rail-photo__frame">
        {src && !failed ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={src} alt={p?.name ?? ""} decoding="async" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        ) : (
          <div className="rail-photo__placeholder" aria-hidden="true">
            <svg viewBox="0 0 120 80" preserveAspectRatio="xMidYMid meet">
              <path d="M0 64h120M18 64V30l22-12 22 12v34M62 64V40h40v24M30 64V44h8v20M74 48h6v6h-6zM88 48h6v6h-6z" fill="none" stroke="currentColor" strokeWidth=".8" />
            </svg>
          </div>
        )}
      </div>
      {p && (
        <figcaption>
          {href ? <a href={href} target="_blank" rel="noopener noreferrer">{t.photoCaption(p.name)}</a> : t.photoCaption(p.name)}
        </figcaption>
      )}
    </figure>
  );
}

export function Rail() {
  const { t, lang, meta, metaState } = useApp();
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  const both = dg > 0;
  const loading = metaState === "loading";
  return (
    <aside className="rail">
      {/* While /api/meta loads, the copy is laid out but hidden, so nothing shifts and no unverified claim shows. */}
      <h1 className="rail__headline" style={loading ? { visibility: "hidden" } : undefined}>{loading || both ? t.railHeadlineBoth : t.railHeadline}</h1>
      <p className="rail__lede" style={loading ? { visibility: "hidden" } : undefined}>{loading || both ? t.railLedeBoth : t.railLede}</p>
      <RailPhoto />
      <div className="rail__foot">
        {meta?.data_as_of && (
          <p className="rail__asof">
            {t.statAsOf} <time dateTime={meta.data_as_of}>{fmtDate(meta.data_as_of, lang)}</time>
          </p>
        )}
        <Link href="/how-it-works/" className="rail__link">{t.railHow}</Link>
      </div>
    </aside>
  );
}
