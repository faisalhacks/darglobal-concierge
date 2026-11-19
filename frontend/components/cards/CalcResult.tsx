"use client";
import { fmtNumber } from "@/lib/format";
import { formula, isolate } from "@/lib/bidi";
import { STRINGS, type Strings } from "@/lib/i18n";
import type { CalcEvent, Lang } from "@/lib/types";

// Calc card: kept as it was (UI spec §4 "Calc card: keep as is"); moved here from Parts.tsx unchanged.
function kv(o: Record<string, unknown>, t: Strings, lang: Lang, rawCur?: string | null) {
  // Arabic shows the closed-vocabulary currency label (SAR -> ر.س); other codes stay as published.
  const cur = lang === "ar" && rawCur === "SAR" ? "ر.س" : rawCur;
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
        <div><dt>{t.calcFormula}</dt><dd><code>{formula(c.formula)}</code></dd></div>
      </dl>
      <p className="calc__disclaimer">{isolate(c.disclaimer, lang)}</p>
    </section>
  );
}

