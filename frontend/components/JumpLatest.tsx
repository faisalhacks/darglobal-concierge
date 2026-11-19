"use client";
import s from "./JumpLatest.module.css";

/** "Jump to latest": a 40px round icon button docked at the inline-end edge directly above the composer, in its own
 * strip outside the scroll area, so it can never sit on top of a link, card text or an alert. */
export function JumpLatest({ label, onJump }: { label: string; onJump: () => void }) {
  return (
    <div className={s.strip}>
      <button type="button" className={`jump-latest ${s.btn}`} onClick={onJump} aria-label={label} title={label}>
        <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
          <path d="M12 5v14M6 13l6 6 6-6" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>
    </div>
  );
}
