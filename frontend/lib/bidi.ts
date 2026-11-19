// Bidi isolation for mixed Arabic/Latin text (UI spec §7, build item 22).
//
// - In Arabic text, every Latin run (project names, domains, publisher names), every amount with its unit and every
//   formula is isolated, so a Latin name never drags neighbouring Arabic words or punctuation into its direction.
// - Formulas and numbers with operators are isolated left-to-right: "2,000,000 × 20% = 400,000" reads in that order.
// - Sentence punctuation stays outside the isolate (a run never starts or ends on ". , ، ؛ : ! ? ؟").
// - In English text the mirror case applies: Arabic runs are isolated.
// - FSI ... PDI pairs already present in a string (lib/i18n.ts iso()) become isolates too, without the marks.
//
// splitBidi() is pure (unit-tested); isolate() renders the runs as React nodes with <bdi>.
import { createElement, Fragment, type ReactNode } from "react";
import type { Lang } from "./types";

export const FSI = "⁨";
export const PDI = "⁩";
export const LRI = "⁦";

const AR = "؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿";
const AR_RE = new RegExp(`[${AR}]`);
const LATIN_RE = /[A-Za-zÀ-ɏ]/;

export const hasArabicText = (s: string) => AR_RE.test(s);
export const hasLatinText = (s: string) => LATIN_RE.test(s);

export type RunKind = "text" | "latin" | "arabic" | "amount" | "formula" | "isolate";
export interface Run { text: string; kind: RunKind }

const NUM = String.raw`\d[\d,]*(?:\.\d+)?`;
const CUR = String.raw`(?:SAR|USD|AED|EUR|GBP|OMR|QAR|BHD|ر\.س|ريال|درهم)`;
const UNIT = String.raw`(?:${CUR}|m²|m2|sqm|sq\s?ft|م²|%)`;
const OP = String.raw`[×x*÷/+\-−–=]`;
// A formula: a number, then one or more (operator number), each number optionally with % or a unit.
const FORMULA = String.raw`${NUM}%?(?:\s?${UNIT})?(?:\s?${OP}\s?${NUM}%?(?:\s?${UNIT})?)+`;
// An amount with its unit, either side: "SAR 2,000,000", "2,000,000 ر.س", "120 m²", "20%".
const AMOUNT = String.raw`(?:${CUR}\s?${NUM}|${NUM}\s?${UNIT}|${NUM}(?:\s?[–-]\s?${NUM})\s?${UNIT})`;
// A Latin run: may open with a number joined to it ("7&8 Albert Hall Mansions", "2-bed"), carries inner spaces,
// digits and name punctuation, and always ends on a letter or digit so trailing sentence punctuation stays outside.
const LATIN_L = String.raw`A-Za-zÀ-ɏ`;
const LATIN = String.raw`(?:\d+(?:[&\-]\d+)?[\s\-]?)?[${LATIN_L}](?:[${LATIN_L}\d&'’.@/:_\-–]|\s(?=[${LATIN_L}\d&]))*[${LATIN_L}\d]|[${LATIN_L}]`;
// An Arabic run (for English context): Arabic letters with inner spaces/no-break spaces, ending on a letter.
const ARABIC = String.raw`[${AR}](?:[${AR}ً-ٰٟ]|[\s ](?=[${AR}]))*`;

const ISO_RE = /[⁦⁧⁨]([^⁩]*)⁩/g;
const AR_CONTEXT_RE = new RegExp(`(${FORMULA})|(${AMOUNT})|(${LATIN})`, "g");
const EN_CONTEXT_RE = new RegExp(`(${ARABIC})`, "g");

function splitPlain(text: string, lang: Lang): Run[] {
  const out: Run[] = [];
  const arabicContext = lang === "ar";
  if (arabicContext ? !hasLatinText(text) && !/\d/.test(text) : !hasArabicText(text)) {
    return text ? [{ text, kind: "text" }] : [];
  }
  const re = arabicContext ? AR_CONTEXT_RE : EN_CONTEXT_RE;
  re.lastIndex = 0;
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(text))) {
    const kind: RunKind = arabicContext ? (m[1] ? "formula" : m[2] ? "amount" : "latin") : "arabic";
    // A bare number in Arabic text needs no isolate; only isolate amounts that carry a unit or a Latin letter.
    if (m.index > last) out.push({ text: text.slice(last, m.index), kind: "text" });
    out.push({ text: m[0], kind });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push({ text: text.slice(last), kind: "text" });
  return out;
}

/** Splits text into plain runs and runs that need an isolate. Joined back, the runs equal the input minus FSI/PDI marks. */
export function splitBidi(text: string, lang: Lang): Run[] {
  if (!text) return [];
  const out: Run[] = [];
  let last = 0;
  ISO_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = ISO_RE.exec(text))) {
    if (m.index > last) out.push(...splitPlain(text.slice(last, m.index), lang));
    if (m[1]) out.push({ text: m[1], kind: m[0][0] === LRI ? "formula" : "isolate" });
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...splitPlain(text.slice(last), lang));
  // merge adjacent plain runs
  return out.reduce<Run[]>((acc, r) => {
    const prev = acc[acc.length - 1];
    if (prev && prev.kind === "text" && r.kind === "text") prev.text += r.text;
    else acc.push({ ...r });
    return acc;
  }, []);
}

/** The `lang` a run should carry when isolated, or undefined to inherit. */
function runLang(r: Run): string | undefined {
  if (r.kind === "latin") return "en";
  if (r.kind === "arabic") return "ar";
  if (r.kind === "isolate") return hasArabicText(r.text) ? undefined : hasLatinText(r.text) ? "en" : undefined;
  return undefined;
}

/**
 * Renders text with each mixed-direction run inside <bdi>. Formulas get dir="ltr"; everything else keeps the
 * <bdi> default (direction from its own first strong character). Plain text with nothing to isolate comes back as
 * the same string, so this is safe to call on every text node.
 */
export function isolate(text: string | null | undefined, lang: Lang): ReactNode {
  if (!text) return text ?? null;
  const runs = splitBidi(text, lang);
  if (runs.length === 1 && runs[0].kind === "text") return runs[0].text;
  return createElement(
    Fragment,
    null,
    ...runs.map((r, i) =>
      r.kind === "text"
        ? r.text
        : createElement("bdi", { key: i, dir: r.kind === "formula" ? "ltr" : undefined, lang: runLang(r) }, r.text),
    ),
  );
}

/** A formula always reads left to right, in any language: render it in an LTR isolate. */
export function formula(text: string | null | undefined): ReactNode {
  if (!text) return null;
  return createElement("bdi", { dir: "ltr", className: "formula" }, text.replace(/[⁦-⁩]/g, ""));
}

/** An amount and its unit as one isolate ("2,000,000 ر.س" never splits or swaps around a neighbouring word). */
export function amount(text: string | null | undefined): ReactNode {
  if (!text) return null;
  return createElement("bdi", null, text);
}

/** lang/dir attributes for a block written in `lang` (answer containers, bubbles, cards). */
export function langDir(lang: Lang): { lang: Lang; dir: "rtl" | "ltr" } {
  return { lang, dir: lang === "ar" ? "rtl" : "ltr" };
}

/** The language a piece of free text is written in: Arabic if it has any Arabic letter, else English. */
export function textLang(text: string | null | undefined, fallback: Lang = "en"): Lang {
  if (!text) return fallback;
  return hasArabicText(text) ? "ar" : hasLatinText(text) ? "en" : fallback;
}

/** Drops FSI/PDI/LRI marks, for places that need plain text (aria-label, title, clipboard). */
export const stripIsolates = (s: string) => s.replace(/[⁦-⁩]/g, "");
