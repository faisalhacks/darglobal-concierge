# UI class and token contract (lane A, `frontend/app/globals.css`)

`globals.css` is one ordered sheet: **1 tokens, 2 base, 3 shell, 4 components, 5 utilities**. Lane A is its only
editor. Other lanes style their own parts in co-located files (`app/shell.css`, `components/*.module.css`,
`components/cards/cards.module.css`, `components/StressTested.css`) and read **only the tokens below**. If you need a
token that is not listed, ask lane A for it by name. Do not hard-code colours, font sizes or radii.

## Breakpoints
Viewport min-width: **600** (tablet), **900** (rail split), **1440**, **1920**. Height: **max-height 820**, **max-height 500**.
Container: `chat` (inline-size, on `.chat`), threshold **760px** (card grid vs carousel, compare min column).
Type never changes at a breakpoint: only `clamp()` inside a token.

## Theme
- `html[data-theme="light" | "dark"]`; no attribute = follow `prefers-color-scheme`. `color-scheme` is set per theme.
- `html[data-text-scale="large"]` or an inline `--text-scale: 1.125` on `<html>` scales the root font size
  (`--fs-root = 100% x --text-scale`). Default 1.

## Colour tokens (both themes, measured)
| Token | Use | Dark | Light |
|---|---|---|---|
| `--bg` | page | #0c0b0a | #fdfcfa |
| `--surface` | cards, popovers, composer box | #1a1816 | #ffffff |
| `--surface-2` | user bubble, hover, differing compare cells | #26231f | #f4f0e8 |
| `--border` | decorative hairline only | #3d3832 | #d9d1c2 |
| `--border-strong` | control boundaries (chips, inputs, toggles) >= 3:1 on bg, surface, surface-2 | #7a7266 | #8c8273 |
| `--text` | body, >= 13:1 | #f3efe8 | #161412 |
| `--text-muted` | secondary text, >= 6.4:1 | #b8b0a3 | #5c554b |
| `--accent` | brand mark, markers, primary button fill | #c2a36b | #7a5f2c |
| `--accent-strong` | links, active states | #d7bb85 | #5f4a20 |
| `--on-accent` | text on `--accent` (>= 6:1) | #15120e | #ffffff |
| `--focus` | focus ring (2px solid, 2px offset) | #d7bb85 | #5f4a20 |
| `--danger`, `--ok` | error / pass text | #f0958a / #9ccf9f | #a3271b / #256b3a |
| `--scrim` | dialog backdrop | rgba(0,0,0,.55) | rgba(22,20,18,.45) |
| `--shadow-card`, `--shadow-pop` | card hairline shadow (light only), popovers | | |

`#c2a36b` exists only in the dark block; light never computes it. Legacy aliases still resolve per theme:
`--gold` = `--accent`, `--gold-strong` = `--accent-strong`, `--on-gold` = `--on-accent`. New code uses the new names.

## Type tokens (resolved per element language: `:lang(en)` / `:lang(ar)`)
Every font-size in every sheet is one of these. An element with `lang="ar"` inside the English UI (or the reverse)
gets its own language's scale and family automatically.

| Role | Size token | Line-height | Weight | EN px | AR px |
|---|---|---|---|---|---|
| timestamps, uppercase eyebrow | `--fs-meta-xs` | `--lh-meta-xs` | 500 | 13 | 14 |
| meta, legal, badge, source meta | `--fs-meta` | `--lh-meta` | 400 | 14 | 15 |
| chip, button, nav, card facts, table cells | `--fs-control` (alias `--fs-ui`) | `--lh-control` | 500 / 400 | 15 | 16 |
| prose, bubble, composer, ledes | `--fs-body` | `--lh-body` | 400 | 17 | 19 |
| listing card title (sans) | `--fs-title-sm` | `--lh-title-sm` | `--fw-title-sm` | 17 | 18 |
| compare caption, section h3 | `--fs-h3` | `--lh-h3` | `--fw-h3` | 20 | 21 |
| project card title, compare name (display face) | `--fs-title` (alias `--fs-card-title`) | `--lh-title` | `--fw-title` | 24 | 24 |
| calc figure, price (display face, tabular) | `--fs-figure` | `--lh-figure` | `--fw-figure` | 28 | 28 |
| wordmark (display face) | `--fs-brand` | `--lh-brand` | `--fw-brand` | 22 | 20 |
| display h1 | `--fs-display` | `--lh-display` | `--fw-display` | clamp 36-64 | clamp 32-52 |

Families: `--font-display` (Cormorant in EN, IBM Plex Sans Arabic in AR) only at 24px and up plus the 22px wordmark;
`--font-text` (Hanken Grotesk in EN, IBM Plex Sans Arabic in AR) everywhere else. Raw families: `--serif`, `--sans`,
`--arabic`, `--mono`. `--measure` is 68ch (EN) / 60ch (AR). Every Arabic line-height token is >= 1.5.
Legacy size names map onto roles (no 11/12px anywhere): `--fs-12`→meta-xs, `--fs-14`→meta, `--fs-15`→control,
`--fs-16`→body, `--fs-20`→h3, `--fs-24`→title, `--fs-28`→figure, `--fs-40`→display.

## Spacing, shape, motion, layout tokens
`--sp-4 8 12 16 24 32 48 64`, `--r-bubble` 10px, `--r-card` 14px, `--r-control` 12px, `--r-chip` 999px,
`--t-fast` 120ms, `--t-med` 200ms, `--ease`, `--gutter` clamp(16px, 2.5vw, 40px), `--header-h` 56px,
`--footer-h` 40px, `--composer-max` 880px, `--rich-max` 1200px, `--rail-w` clamp(280px, 24vw + 40px, 440px)
(lane B overrides it on `<html>` with the stored user width).

## Global classes provided by globals.css
- Frame / hardening: `.app-root[data-ready]`, `.app-shell` (overflow clip), `.page-shell`, `.embed-shell`, `.home > *`
  (min-width 0), `.chat` (size container `chat`), `.skip`, `.status-line` (hidden; remove from DOM).
- Conversation (legacy `Chat.tsx` markup): `.log`, `.turn`, `.turn--user`, `.turn--assistant`, `.turn__mark`,
  `.turn__body`, `.turn__note`, `.turn--collapsed`, `.bubble`, `.prose`, `.prose--streaming`, `.prose__head`,
  `.cite`, `.cite__chip` (`[aria-expanded="true"]` or `[data-active]` highlights), `.cite__pop`, `.cite__site`,
  `.cite__title`, `.cite__date`, `.skeleton`, `.skeleton__label`, `.skeleton__line(--short)`, `.chips`, `.chip`,
  `.alert`, `.alert--error`, `.composer__note`, `.composer__legal`, `.greeting`, `.greeting__msg`, `.greeting__body`.
- Rich blocks (legacy `Parts.tsx` markup): `.rich` / `.cards` (wide, centred, up to 1200px), `.card-rail`
  (carousel below 760px container, grid at and above; `[data-count="1"]`), `.cards__next` (44px chevron),
  `.cards__more`, `.card`, `.card--listing`, `.card__media` (`img[data-portrait]` or `.card__media--contain` letterboxes),
  `.card__body`, `.card__top`, `.card__status`, `.card__title`, `.card__title--sm`, `.card__place`, `.card__brand`,
  `.card__facts`, `.card__price`, `.card__price-label`, `.card__price-none`, `.card__note`, `.card__warn`,
  `.card__source`, `.badge`, `.plist` and `.plist__*`, `.compare` and `.compare__caption/__verdict/__scroll/__name/
  __thumb/__none`, `td[data-diff]`, `.calc` and `.calc__*`, `.handoff` and `.handoff__title/__ctx/__links/__note`,
  `.spotlight`, `.spotlight__scope`, `.sources` (numbered rows; `li[data-active]` or `li:target` highlights),
  `.sources__head`, `.sources__site`, `.sources__body`, `.sources__title`, `.sources__meta`, `.sources__date`,
  `.footnotes`, `.orig` (original-text disclosure), `.trace`, `.trace__steps`.
- Buttons: `.btn-primary` (accent fill; `:disabled` / `[aria-disabled="true"]` = outline + muted label),
  `.btn-quiet`, `.btn-text`, `.linkish`, `.icon-btn` (44x44, `[aria-pressed="true"]`), `.mark`.
- Content pages: `.page`, `.lede`, `.en-only`, `.steps`, `.deflist`, `.split`, `.plain-list`, `.diagram`,
  `.table-wrap`, `.data-table(--wrap|--plain|--stack)`, `.matrix`, `.matrix__hit`, `.matrix__miss`, `.meter`
  (`--w`), `.empty`, `.raw`, `.cta`, `.notfound`, `.demo-host`, `.site-footer` (content pages).
- Utilities: `.sr-only`, `.muted`, `.small`, `.num`, `.pass`, `.fail`, `.warn`, `.ltr` (LTR isolate),
  `.nowrap`, `.wrap-anywhere`, `.icon--dir` (mirrors in RTL), `[hidden]`.

## Owned elsewhere (globals.css deliberately does not style these)
Header, rail, splitter, menus, About sheet, home footer line: `app/shell.css` (lane B). Chat column, composer,
jump-to-latest, welcome, action row: lane C modules. Cards, compare, sources, cite, trace, handoff, spotlight,
footnotes in the new `components/cards/*`: `cards.module.css` (lane D).
