# Design bar — anti-slop checklist

Source: Contra Labs Frontier Design Benchmark (leaderboard, rubric, methodology, blog; read Nov 2026).
The rubric's individual criteria are unpublished; the rules below are inferred from its named dimensions
(type hierarchy, spacing, contrast, "renders whole", too many fonts, inconsistent spacing) and from the
measured "AI slop" tells. Benchmark finding: designers prefer **finished, specific** work over generic work.

## Ban list (measured AI tells)
- Small spaced-caps eyebrow label above every heading that repeats the heading (93% of AI pages, 11% human).
- Italic or highlighted word inside a headline; "mini subtexts everywhere".
- Numbered sections 01 / 02 / 03.
- Everything in a card. Cards only for real objects (project, listing, compare, calc).
- Tilted cards, stickers, angled phones.
- Centered heading on every section.
- Arrow glyphs on every link/button (→ is the Claude tell, ↗ the GPT tell). One consistent link treatment, no arrows by default.
- Slogan headings of 2–3 parallel phrases; copy that stops at the benefit without saying how it works.
- Spec-sheet styling (status labels, figure refs) on ordinary copy.

## Must
1. Two type families max (serif display + sans text) + Arabic family. No decorative italics.
2. One spacing scale (4/8/12/16/24/32/48/64), applied everywhere.
3. Contrast checked on every label, incl. gold on dark and text over images.
4. Nothing cut off at 360/390/414 px or at sticky header/composer boundaries; renders whole.
5. Group with whitespace, rules and type, not boxes.
6. One accent (gold), neutral surfaces, real project photography (linked originals).
7. Concrete copy: say what the concierge does and how (sourced answers, data-as-of date), not slogans.
8. The chat is the product: specific first message, specific chips from real corpus (real city/project names), visible loading/error/empty/no-data states.
9. Mobile first, 44 px targets, focus rings, `prefers-reduced-motion`, semantic headings, labelled inputs.
10. Real numbers only on screen (corpus counts from /api/meta), never placeholder stats.
11. Final rubric pass before ship: fonts, spacing, contrast, cut-off, repeated components — fix each finding.

## Impeccable (impeccable.style, pbakaus/impeccable) — adopted rules
Tooling: `npx impeccable detect http://localhost:7860` (62 slop rules) runs in the polish pass; findings are fixed
or justified. Workflow order before release: critique → audit → clarify → harden → polish.

- **No Inter / Geist** (flagged as the default that makes products look alike). Pick a UI sans with character.
- **No italic serif display headline.** Serif display upright; vary size/weight before adding families.
- Body ≥ 16 px, line-height ~1.5 EN / ~1.8 AR, measure 65–75 ch, `text-wrap: pretty` (body) / `balance` (headings), no justified text, no tracking on body, **no letter-spacing ever on Arabic**, no italics on Arabic.
- No gradient text, neon, purple/cyan, radial glow, glassmorphism, decorative grid backgrounds, side-tab accent borders, ghost cards (hairline + wide shadow), nested cards, identical card grids.
- Cream/beige is flagged as an AI default *unless it is the brand's own palette*. Our warm-neutral tokens (SPEC §15.6) are a deliberate DarGlobal-gallery choice — keep them, but make gold rare (CTA, price, focus) and keep surfaces neutral.
- WCAG AA: 4.5:1 body, 3:1 large text and UI borders. Check muted text on surface-2 and gold-on-dark.
- Motion: only for real activity (streaming indicator); no pulsing status dot, no bounce/elastic, settle in 150–250 ms; content visible by default (never stuck at opacity 0); honour `prefers-reduced-motion`.
- Every control has default / hover / focus-visible / active / disabled / loading / error. Visible focus outline. Enter sends, Shift+Enter newline, `aria-live="polite"` on the assistant stream.
- Popovers/menus never clipped by the chat container. No modal abuse.
- Copy (EN + AR): no em-dash overuse, no "world-class / elevate / seamless / supercharge", no forced-contrast lines, no repeated labels in one card. Every error/empty state says what happened and what to do next. Never claim availability or prices not in the data.

## RTL specifics (not covered by Impeccable)
- `lang`/`dir` on `<html>` from the locale toggle; `dir="auto"` on each message bubble for mixed text; `<bdi>` around prices, areas, project codes.
- Logical CSS properties only (`margin-inline`, `inset-inline-start`, `text-align: start`). Mirror directional icons only (send, chevrons); never logos, photos, maps.
- `Intl.NumberFormat` per locale; one numeral system per locale, applied consistently.
