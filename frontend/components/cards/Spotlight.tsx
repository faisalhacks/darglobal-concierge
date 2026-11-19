"use client";
import { fmtAreaRange, hasArabic, publisherName } from "@/lib/format";
import type { Lang, ProjectCard as PC } from "@/lib/types";
import { cardCopy } from "./copy";
import { Photo } from "./Media";
import { Iso, SourceLink, placeOf, projectFacts, statusOf } from "./ProjectCard";
import { useProjectDetail } from "./useProjectDetail";
import s from "./cards.module.css";

/** Off-topic / refusal pivot: one real project from the corpus, compact (photo when it loads, name, place, one or two
 * published facts, source link). The scope sentence is the answer prose above it; the chips follow the answer. */
export function SpotlightCard({ p, lang }: { p: PC; lang: Lang }) {
  const c = cardCopy(lang);
  const d = useProjectDetail(p.slug || p.id);
  const f = projectFacts(p, d);
  const place = placeOf(p, lang);
  const status = statusOf(p.status, lang);
  const area = fmtAreaRange(f.area[0], f.area[1], lang);
  const pub = publisherName(p.source_site || p.site, lang);
  const bits = [
    status ? <Iso key="s" text={status.text} /> : null,
    f.handover ? <span key="h">{c.factHandover} <bdi>{f.handover}</bdi></span> : null,
    area ? <bdi key="a" dir="ltr">{area}</bdi> : null,
  ].filter(Boolean);
  return (
    <div className={`${s.scope} ${s.block}`} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"}>
      <article className={s.spot} aria-label={c.spotlightLabel(p.name)}>
        <Photo src={f.image} alt={c.photoAlt(p.name)} ratio="4 / 3" />
        <div className={s.body}>
          <div className={s.top}><span className={s.badge}>{pub.latin ? <bdi lang="en" dir="ltr">{pub.text}</bdi> : pub.text}</span></div>
          <h3 className={s.title} lang={hasArabic(p.name) ? "ar" : "en"} dir="auto">{p.name}</h3>
          {place && <p className={s.place}><Iso text={place} /></p>}
          {bits.length > 0 && (
            <p className={s.check}>
              {bits.map((b, i) => <span key={i}>{i > 0 && <span aria-hidden="true"> · </span>}{b}</span>)}
            </p>
          )}
          <SourceLink url={p.source_url} lang={lang} />
        </div>
      </article>
    </div>
  );
}
