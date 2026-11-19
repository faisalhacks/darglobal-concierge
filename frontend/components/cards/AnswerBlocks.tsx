"use client";
import { STRINGS } from "@/lib/i18n";
import type { CalcEvent, CardsEvent, CompareEvent, HandoffEvent, Lang, Source, SpotlightEvent } from "@/lib/types";
import { CalcResult } from "./CalcResult";
import { CardRail } from "./CardGrid";
import { CompareTable } from "./CompareTable";
import { HandoffCard } from "./Handoff";
import { SourceList } from "./Sources";
import { SpotlightCard } from "./Spotlight";

const HANDOFF = new Set(["contact_sales", "handoff", "advisor", "contact"]);
const GREETING = new Set(["greeting", "smalltalk", "small_talk", "hello"]);
const NO_DATA = new Set(["injection", "calculation", "calculate"]);
const PIVOT = new Set(["off_topic", "spotlight"]);

export interface AnswerData {
  lang: Lang;
  intent?: string | null;
  cards?: CardsEvent | null; compare?: CompareEvent | null; calc?: CalcEvent | null;
  handoff?: HandoffEvent | null; spotlight?: SpotlightEvent | null;
  sources?: Source[] | null;
}

export type AnswerKind = "handoff" | "compare" | "calc" | "spotlight" | "cards" | "none";

/** Which single rich block an answer shows (spec §4: cards OR compare OR calc OR handoff OR spotlight). */
export function answerKind(a: AnswerData): AnswerKind {
  const intent = a.intent ?? "";
  if (a.handoff || HANDOFF.has(intent)) return "handoff";
  if (a.compare) return "compare";
  if (a.calc) return "calc";
  if (intent === "injection" || GREETING.has(intent)) return "none";
  if (a.spotlight?.project) return "spotlight";
  const ps = a.cards?.projects ?? [];
  if (PIVOT.has(intent) && ps.length === 1 && !(a.cards?.listings ?? []).length) return "spotlight";
  if (ps.length || (a.cards?.listings ?? []).length || (a.cards?.index_only ?? []).length) return "cards";
  return "none";
}

/** The sources an answer lists: none for handoff, calc, greeting and refusals (no corpus data was used). */
export function answerSources(a: AnswerData): Source[] {
  const kind = answerKind(a);
  const intent = a.intent ?? "";
  if (kind === "handoff" || kind === "calc" || NO_DATA.has(intent) || GREETING.has(intent)) return [];
  const own = a.sources ?? [];
  return own.length ? own : a.compare?.sources ?? [];
}

/** Project names the answer is about (for the plain-language trace and the handoff context line). */
export function answerNames(a: AnswerData): string[] {
  if (a.compare) return a.compare.columns.map((c) => c.name);
  if (a.spotlight?.project) return [a.spotlight.project.name];
  return (a.cards?.projects ?? []).slice(0, 4).map((p) => p.name);
}

/** Rich block, footnotes (inside the block), then the numbered sources: the fixed answer order of spec §4 after the
 * prose. The action row, trace and follow-up chips are rendered by the conversation (lane C). */
export function AnswerBlocks({ a, asOf }: { a: AnswerData; asOf?: string | null }) {
  const { lang } = a;
  const kind = answerKind(a);
  const sources = answerSources(a);
  return (
    <>
      {kind === "handoff" && <HandoffCard handoff={a.handoff} sources={a.sources ?? []} lang={lang} />}
      {kind === "compare" && a.compare && <CompareTable c={a.compare} lang={lang} />}
      {kind === "calc" && a.calc && <CalcResult c={a.calc} t={STRINGS[lang]} />}
      {kind === "spotlight" && <SpotlightCard p={(a.spotlight?.project ?? a.cards?.projects?.[0])!} lang={lang} />}
      {kind === "cards" && a.cards && (
        <CardRail projects={a.cards.projects ?? []} listings={a.cards.listings ?? []} indexOnly={a.cards.index_only ?? []}
          footnotes={a.cards.footnotes ?? []} lang={lang} />
      )}
      <SourceList sources={sources} lang={lang} asOf={sources.length ? asOf : null} />
    </>
  );
}
