"use client";
import { useId, useState } from "react";
import { safeUrl } from "@/lib/api";
import { hostOf } from "@/lib/format";
import type { HandoffEvent, Lang, Source } from "@/lib/types";
import { cardCopy } from "./copy";
import { ExternalIcon } from "./Media";
import s from "./cards.module.css";

/** The two official contact pages collected in the dataset (data/concierge.sqlite, pages with page_type "contact").
 * Used only when the answer itself carries no contact link for that brand. */
const OFFICIAL_CONTACT = {
  DarGlobal: "https://darglobal.co.uk/get-in-touch",
  Wasalt: "https://wasalt.sa/en/corporate",
} as const;

const isBrand = (site: string | undefined, url: string, brand: "DarGlobal" | "Wasalt") =>
  (site ?? "").toLowerCase().replace(/\s+/g, "") === brand.toLowerCase() || hostOf(url).endsWith(brand === "DarGlobal" ? "darglobal.co.uk" : "wasalt.sa");

/** Advisor / sales / viewing intent: heading, an optional context line, two primary links to the official pages (new
 * tab), and one line saying nothing typed here is passed on. No form, nothing stored, no callback promised. */
export function HandoffCard({ handoff, sources = [], lang }: { handoff?: HandoffEvent | null; sources?: Source[]; lang: Lang }) {
  const c = cardCopy(lang);
  const pool = [...(handoff?.links ?? []), ...sources];
  const pick = (brand: "DarGlobal" | "Wasalt") =>
    safeUrl(pool.find((x) => x?.url && isBrand(x.site, x.url, brand))?.url) ?? OFFICIAL_CONTACT[brand];
  const links = [
    { key: "dg", label: c.handoffDg, url: pick("DarGlobal") },
    { key: "ws", label: c.handoffWs, url: pick("Wasalt") },
  ];
  const project = handoff?.project?.trim();
  const hid = useId();
  const brief = c.brief(project ? (lang === "ar" ? `⁨${project}⁩` : project) : null);
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(brief.replace(/[⁨⁩]/g, ""));
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch { /* clipboard blocked: the note stays visible to select by hand */ }
  };
  return (
    <section className={`${s.scope} ${s.handoff}`} lang={lang} dir={lang === "ar" ? "rtl" : "ltr"} aria-labelledby={hid}>
      <h3 className={s.handoffTitle} id={hid}>{c.handoffTitle}</h3>
      <p className={s.handoffText}>
        {project && <>{c.handoffContext("").replace(/[.。]\s*$/, "")}<bdi>{project}</bdi>{". "}</>}
        {c.handoffBody}
      </p>
      <div className={s.actions}>
        {links.map((l) => (
          <a key={l.key} className={s.primary} href={l.url} target="_blank" rel="noopener noreferrer">
            <span>{l.label}</span>
            <ExternalIcon />
            <span className="sr-only">{c.newTab}</span>
          </a>
        ))}
      </div>
      <div className={s.brief}>
        <p className={s.briefLabel} id={`${hid}-b`}>{c.briefLabel}</p>
        <p className={s.briefText} aria-labelledby={`${hid}-b`}>{brief}</p>
        <button type="button" className={s.more} onClick={copy}>{copied ? c.copiedBrief : c.copyBrief}</button>
        <span className="sr-only" role="status" aria-live="polite">{copied ? c.copiedBrief : ""}</span>
      </div>
      <p className={s.privacy}>{c.handoffPrivacy}</p>
    </section>
  );
}
