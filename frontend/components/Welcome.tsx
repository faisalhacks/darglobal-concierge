"use client";
import { useEffect, useState } from "react";
import { getJSON, safeImage } from "@/lib/api";
import { CONV } from "@/lib/conversation-strings";
import type { Chip, Lang, ProjectCard } from "@/lib/types";
import { useApp } from "./AppContext";
import s from "./Welcome.module.css";

const NARROW = "(max-width: 899.98px)";

function useNarrow() {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    let mq: MediaQueryList;
    try { mq = window.matchMedia(NARROW); } catch { return; }
    const on = () => setNarrow(mq.matches);
    on();
    mq.addEventListener?.("change", on);
    return () => mq.removeEventListener?.("change", on);
  }, []);
  return narrow;
}

/** Phone/tablet only (the rail carries the photo on desktop): one real DarGlobal photograph, hot-linked from the
 * collected project page (owner decision, SPEC D5). Rendered only when an image URL was collected and it loads;
 * otherwise nothing — the headline below is the typographic fallback, never a drawing. */
function HeroPhoto({ lang }: { lang: Lang }) {
  const { meta } = useApp();
  const narrow = useNarrow();
  const [p, setP] = useState<ProjectCard | null>(null);
  const [state, setState] = useState<"loading" | "ok" | "failed">("loading");
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  useEffect(() => {
    if (!narrow || !dg) return;
    const ac = new AbortController();
    getJSON<ProjectCard[]>(`/api/projects?site=DarGlobal&lang=${lang}`, ac.signal)
      .then((rows) => {
        const list = Array.isArray(rows) ? rows : [];
        setP(list.find((r) => r.detail !== "index" && safeImage(r.image_url)) ?? null);
        setState("loading");
      })
      .catch(() => { /* no photo: the typographic welcome stands on its own */ });
    return () => ac.abort();
  }, [narrow, dg, lang]);
  const src = safeImage(p?.image_url);
  if (!narrow || !p || !src || state === "failed") return null;
  return (
    <figure className={s.hero} data-state={state}>
      <div className={s.heroFrame}>
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          src={src}
          alt={p.name}
          decoding="async"
          referrerPolicy="no-referrer"
          onLoad={() => setState("ok")}
          onError={() => setState("failed")}
        />
      </div>
      <figcaption className={s.caption}>{CONV[lang].welcomePhotoCaption(p.name)}</figcaption>
    </figure>
  );
}

/** Empty state: one vertically centred block above the docked composer — headline stating the offer, one sentence
 * of scope, four starter chips. No guardrail chip here (it lives in the rail foot / About sheet and on /evals). */
export function Welcome({ onPick, disabled }: { onPick: (c: Chip) => void; disabled: boolean }) {
  const { t, lang, meta, metaState } = useApp();
  const c = CONV[lang];
  const dg = meta?.coverage?.DarGlobal?.projects ?? meta?.counts_by_site?.DarGlobal?.projects ?? 0;
  const loading = metaState === "loading";
  const chips: Chip[] = c.welcomeChips.map((q) => ({ label: q, message: q }));
  return (
    <section className={s.welcome} aria-labelledby="welcome-title">
      <div className={s.block}>
        <HeroPhoto lang={lang} />
        {/* While /api/meta loads the copy is laid out but hidden, so nothing shifts and no unverified claim shows. */}
        <h2 id="welcome-title" className={s.headline} style={loading ? { visibility: "hidden" } : undefined}>
          {loading || dg > 0 ? c.welcomeHeadline : c.welcomeHeadlineWasalt}
        </h2>
        <p className={s.scope} style={loading ? { visibility: "hidden" } : undefined}>{meta ? t.greetingLead : t.greetingNoMeta}</p>
        <ul className={s.chips} aria-label={c.welcomeChipsLabel}>
          {chips.map((ch) => (
            <li key={ch.label}>
              <button type="button" className={`chip ${s.chip}`} onClick={() => onPick(ch)} aria-disabled={disabled || undefined}>
                {ch.label}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
