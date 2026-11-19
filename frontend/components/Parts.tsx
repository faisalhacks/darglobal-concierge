"use client";
// Barrel kept for existing imports. Cards, compare, sources, cite chips, trace, handoff and spotlight live in
// components/cards/* (lane D); Chips stays here until lane C moves it.
import type { Chip } from "@/lib/types";

export { CardRail, isRich } from "./cards/CardGrid";
export { ProjectCard } from "./cards/ProjectCard";
export { ListingCard } from "./cards/ListingCard";
export { CompareTable } from "./cards/CompareTable";
export { CalcResult } from "./cards/CalcResult";
export { SourceList } from "./cards/Sources";
export { Cite, Cited } from "./cards/Cite";
export { Trace } from "./cards/Trace";
export { HandoffCard } from "./cards/Handoff";
export { SpotlightCard } from "./cards/Spotlight";
export { Footnotes } from "./cards/Footnotes";
export { AnswerBlocks, answerKind, answerNames, answerSources } from "./cards/AnswerBlocks";

export function Chips({ chips, onPick, disabled, trapLabel, label }: { chips: Chip[]; onPick: (c: Chip) => void; disabled?: boolean; trapLabel?: string; label?: string }) {
  if (!chips.length) return null;
  return (
    <div className="chips" role="list" aria-label={label}>
      {chips.map((c) => (
        <button
          role="listitem"
          type="button"
          key={c.label}
          className={`chip${trapLabel && c.label === trapLabel ? " chip--trap" : ""}`}
          onClick={() => onPick(c)}
          disabled={disabled}
        >
          {c.label}
        </button>
      ))}
    </div>
  );
}
