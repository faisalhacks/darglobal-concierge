import type { Lang, Money } from "./types";

const AR_CURRENCY: Record<string, string> = { SAR: "ر.س" };

const loc = (lang: Lang) => (lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB");

/** Numbers stay in Latin digits in both languages for consistency with source prices. */
export function fmtNumber(n: number, lang: Lang) {
  return new Intl.NumberFormat(loc(lang), { maximumFractionDigits: 2 }).format(n);
}
export function fmtMoney(m: Money | null, lang: Lang): string | null {
  if (!m || typeof m.amount !== "number") return null;
  // Arabic shows the closed-vocabulary currency label (SAR -> ر.س) after the number; other codes stay as published.
  if (lang === "ar" && AR_CURRENCY[m.currency]) return `${fmtNumber(m.amount, lang)} ${AR_CURRENCY[m.currency]}`;
  return `${m.currency} ${fmtNumber(m.amount, lang)}`;
}
export function fmtDate(iso: string | null | undefined, lang: Lang) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(loc(lang), { day: "numeric", month: "long", year: "numeric" }).format(d);
}
export const hasArabic = (s: string) => /[؀-ۿݐ-ݿࢠ-ࣿ]/.test(s);

/** Closed-vocabulary lookup (place names, status values): the mapped label, or the published value unchanged. */
export function lookup(v: string | null | undefined, table: Record<string, string>): { text: string; mapped: boolean } | null {
  if (!v) return null;
  const hit = table[v.trim().toLowerCase()];
  return hit ? { text: hit, mapped: true } : { text: v, mapped: false };
}

/** "70–365 m²" (or one value when both ends match); null when neither end is published. */
export function fmtAreaRange(lo: number | null | undefined, hi: number | null | undefined, lang: Lang): string | null {
  const a = typeof lo === "number" && lo > 0 ? lo : null;
  const b = typeof hi === "number" && hi > 0 ? hi : null;
  if (a == null && b == null) return null;
  if (a != null && b != null && a !== b) return `${fmtNumber(a, lang)}–${fmtNumber(b, lang)} m²`;
  return `${fmtNumber((a ?? b) as number, lang)} m²`;
}

/** Elapsed time for people: "<0.1 s" under 100 ms, else one decimal ("0.4 s"). Never "0.0 s". */
export function fmtLatency(ms: number | null | undefined, lang: Lang): string {
  const unit = lang === "ar" ? "ثانية" : "s";
  if (typeof ms !== "number" || !Number.isFinite(ms) || ms < 100) return `<${fmtNumber(0.1, lang)} ${unit}`;
  return `${new Intl.NumberFormat(lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB", { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(ms / 1000)} ${unit}`;
}

/** Readable publisher name in the UI language. Third-party labels stay as the dataset wrote them. */
const PUBLISHERS: Record<string, { en: string; ar: string }> = {
  darglobal: { en: "DarGlobal", ar: "دار\u00a0جلوبال" },
  wasalt: { en: "Wasalt", ar: "وصلت" },
};
export function publisherName(site: string | null | undefined, lang: Lang): { text: string; latin: boolean } {
  const key = (site ?? "").trim().toLowerCase().replace(/\s+/g, "");
  const hit = PUBLISHERS[key];
  if (hit) return { text: hit[lang], latin: lang === "en" };
  return { text: (site ?? "").trim(), latin: !hasArabic(site ?? "") };
}

/** Area per bedroom outside 12–250 m² is not presented as fact (e.g. a 2-bed listed at 1,590 m²). */
export function implausibleArea(area: number | null | undefined, beds: number | null | undefined): boolean {
  if (typeof area !== "number" || !(area > 0)) return false;
  if (typeof beds !== "number" || beds < 1) return area > 3000;
  const per = area / beds;
  return per > 250 || per < 12;
}

/** Hostname without "www." (empty when the URL does not parse). */
export function hostOf(url: string | null | undefined): string {
  try { return new URL(url ?? "").hostname.replace(/^www\./, ""); } catch { return ""; }
}
