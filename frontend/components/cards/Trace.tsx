"use client";
import { useId, useState } from "react";
import { fmtLatency } from "@/lib/format";
import { isolate } from "@/lib/bidi";
import { STRINGS } from "@/lib/i18n";
import type { Lang, TraceEvent } from "@/lib/types";
import { cardCopy } from "./copy";
import { ChevronIcon } from "./Media";
import s from "./cards.module.css";

/** Plain-language steps only. Model ids, cache flags, raw scores and score bars are diagnostics and live on /evals. */
export function traceSteps(tr: TraceEvent, lang: Lang, nSources: number, names: string[] = []): string[] {
  const c = cardCopy(lang);
  const t = STRINGS[lang];
  const steps: string[] = [];
  const clean = [...new Set(names.map((x) => x.trim()).filter(Boolean))];
  if (clean.length === 1 && (tr.intent === "project_info" || tr.intent === "brand_partner")) steps.push(c.stepMatchedOne(`⁨${clean[0]}⁩`));
  else if (clean.length >= 2 && clean.length <= 4) steps.push(c.stepMatched(clean.map((x) => `⁨${x}⁩`).join(c.and)));
  else {
    const label = t.intentLabels[tr.intent];
    if (label) steps.push(c.stepUnderstood(label));
  }
  if (nSources > 0) steps.push(c.stepRead(nSources));
  const tool = tr.tool ? t.toolLabels[tr.tool] : null;
  if (tool) steps.push(c.stepTool(tool));
  if (tr.llm_calls > 0) steps.push(c.stepWorded);
  if (tr.provider === "nvidia-backup") steps.push(c.stepBackup);
  else if (tr.degraded || tr.degraded_reason) steps.push(c.stepFallback);
  else if (tr.path === "template") steps.push(c.stepTemplate);
  else steps.push(c.stepCode);
  steps.push(c.stepTime(fmtLatency(tr.latency_ms, lang)));
  return steps;
}

/** "How I found this": a collapsed one-line disclosure (counts and time), expanding to numbered plain steps. Shown only
 * when the answer used sources (calc, greeting and refusal answers have none). */
export function Trace({ tr, nSources = 0, lang, names = [] }: { tr: TraceEvent; nSources?: number; lang?: Lang; names?: string[]; t?: unknown }) {
  const lg: Lang = lang ?? "en";
  const c = cardCopy(lg);
  const [open, setOpen] = useState(false);
  const id = useId();
  if (!nSources) return null;
  const steps = traceSteps(tr, lg, nSources, names);
  return (
    <div className={`${s.scope} ${s.trace}`} lang={lg} dir={lg === "ar" ? "rtl" : "ltr"}>
      <button type="button" className={s.traceBtn} aria-expanded={open} aria-controls={id} onClick={() => setOpen((v) => !v)}>
        <span className={s.traceChev}><ChevronIcon /></span>
        <span>{c.howFound}</span>
        <span className={s.traceCounts}>{c.traceCounts(nSources, fmtLatency(tr.latency_ms, lg))}</span>
      </button>
      <ol className={s.steps} id={id} hidden={!open}>
        {steps.map((x, i) => <li key={i}>{isolate(x, lg)}</li>)}
      </ol>
    </div>
  );
}
