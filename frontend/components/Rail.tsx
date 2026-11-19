"use client";
import Link from "next/link";
import { fmtDate, fmtNumber } from "@/lib/format";
import { useApp } from "./AppContext";

export function Rail() {
  const { t, lang, meta, metaState } = useApp();
  const stats = meta
    ? [
        { k: t.statProjects, v: fmtNumber(meta.counts?.projects ?? 0, lang) },
        { k: t.statListings, v: fmtNumber(meta.counts?.listings ?? 0, lang) },
        { k: t.statPages, v: fmtNumber(meta.counts?.pages ?? 0, lang) },
      ]
    : [];
  return (
    <aside className="rail">
      <h1 className="rail__headline">{t.railHeadline}</h1>
      <p className="rail__lede">{t.railLede}</p>
      <div className="placard" aria-busy={metaState === "loading"}>
        {metaState === "loading" && <p className="placard__state">{t.statLoading}</p>}
        {metaState === "error" && <p className="placard__state">{t.statUnavailable}</p>}
        {meta && (
          <>
            {meta.counts_by_site && (
              <p className="placard__sites">
                {t.statBySite(fmtNumber(meta.counts_by_site.DarGlobal?.projects ?? 0, lang),
                  fmtNumber(meta.counts_by_site.Wasalt?.projects ?? 0, lang))}
              </p>
            )}
            <dl className="placard__stats">
              {stats.map((s) => (
                <div key={s.k}><dd>{s.v}</dd><dt>{s.k}</dt></div>
              ))}
            </dl>
            <p className="placard__asof">
              {t.statAsOf} <time dateTime={meta.data_as_of}>{fmtDate(meta.data_as_of, lang)}</time>
              <span className="placard__version" dir="ltr">{meta.dataset_version}</span>
            </p>
          </>
        )}
      </div>
      <Link href="/how-it-works/" className="rail__link">{t.railHow}</Link>
    </aside>
  );
}
