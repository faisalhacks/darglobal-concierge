import type { Lang, Money } from "./types";

const loc = (lang: Lang) => (lang === "ar" ? "ar-SA-u-nu-latn" : "en-GB");

/** Numbers stay in Latin digits in both languages for consistency with source prices. */
export function fmtNumber(n: number, lang: Lang) {
  return new Intl.NumberFormat(loc(lang), { maximumFractionDigits: 2 }).format(n);
}
export function fmtMoney(m: Money | null, lang: Lang): string | null {
  if (!m || typeof m.amount !== "number") return null;
  return `${m.currency} ${fmtNumber(m.amount, lang)}`;
}
export function fmtDate(iso: string | null | undefined, lang: Lang) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return new Intl.DateTimeFormat(loc(lang), { day: "numeric", month: "long", year: "numeric" }).format(d);
}
export const hasArabic = (s: string) => /[؀-ۿݐ-ݿࢠ-ࣿ]/.test(s);
