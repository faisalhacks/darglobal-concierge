# Impeccable detector findings: fixed or justified

Detector: Impeccable 4.10.0. Source scans used the bundled launcher; page scans used `npx --yes impeccable detect`.
Server: mock (`MOCK_LLM_STATE=quota`). Viewports: 390x844 and 1440x900. The full review is in
`DESIGN_REVIEW.md`.

## Source scan: `detect --json frontend/app frontend/components`

0 findings. This scan is regex-only and undercounts.

## Route scans

| Route | Viewport | Finding | Outcome |
|---|---|---|---|
| `/` (empty state) | 390, 1440 | none | clean |
| `/?lang=ar` | 390, 1440 | none; the scan failed on browser connection errors about half the time | clean when it completed |
| `/how-it-works/` | 1440 | `line-length`: about 130 characters per line in the step list and guardrail definitions | **Fixed.** Step text and definition list are capped at 64ch, and `text-wrap: pretty` is applied. Rescan: none. |
| `/how-it-works/` | 1440 | `tiny-text`: 12px diagram labels | **Fixed** to 13px. The 1440 rescan is clean. |
| `/how-it-works/` | 390 | `tiny-text`: 13–14px text inside the architecture SVG | **Justified.** The diagram scrolls sideways at its natural size (min-width 760px) and is not scaled down. Every label is also written out in the SVG `<desc>`, and the steps below say the same thing in 16px text. Making the labels bigger would break the box layout of a fixed diagram. |
| `/how-it-works/` | 390 | `straggler`: single words left on the last line | **Fixed** with `text-wrap: pretty` on paragraphs and list items. `balance` is applied to headings. |
| `/evals/` | 390, 1440 | `straggler` in the intent-routing note (advisory) | **Fixed** with the same `text-wrap: pretty` rule. Rescan: none. |
| `/privacy/` | 390, 1440 | `straggler` in the footer (advisory) | **Fixed** with the same rule. Rescan: none. |
| `/nope/` (404) | both | The detector refuses HTTP 404 pages ("Findings would describe the error page") | Not scannable by design. Checked by screenshot instead (`screenshots/final/desktop-404.png`). |

## Answered-state snapshots

The detector can't send a message, so each answered state was rendered in Playwright, saved as static HTML and
scanned.

| State | Viewport | Finding | Outcome |
|---|---|---|---|
| listings, DarGlobal Oman, one project (AR) | 1440 | `skipped-heading`: the rail `<h1>` was followed directly by the card `<h3>` | **Fixed.** A visually hidden `<h2>` ("Concierge") now heads the conversation log; the empty state already had one. |
| listings (4 cards) | 1440 | `edge-flush-cards`: cards flush with the left edge of the scrolling rail | **Justified.** The rail's edge is the text column. Cards line up with the answer text above them on purpose, and the 4th card peeks at the trailing edge to show the rail scrolls. Padding the start would push the cards out of line with the prose. |
| compare, calc, rentals | 1440 | none | clean |
| all six states | 390 | none (`--json` returned `[]`) | clean |

## Checked by hand (no detector rule for these)

Eyebrow labels above answers: removed. One-sided accent bars on alerts: replaced with a full border.
Repeated labels in one card: the listing title no longer repeats the beds and area, and the calculation card no
longer shows "Down payment" twice. Hero-metric stats: replaced by one sentence. Gold used for brand badges:
removed. Unicode glyph standing in for a control ("ع"): replaced by a labelled toggle. Native Windows scrollbar
arrows: themed out. Measured CLS of 0.04–0.21 on load: now 0–0.003.

## Re-run after the verification fixes (19 Nov, fixer)

Detector: Impeccable 4.10.0 CLI from the local npx cache, against a mock backend on the rebuilt dataset
(20261119-e5604e7e). Raw JSON: `evals/screens/verify/detector-after/`. Each route was tried up to 3 times.

| Route | 390x844 | 1440x900 |
|---|---|---|
| `/` (EN, AR) | EN clean. AR: `cramped-padding` on the two-line status line. **Fixed** after the scan (52px status height, 6px inset on narrow screens); not re-scanned. | clean |
| `/how-it-works/` (EN, AR) | 7 × `tiny-text`: the 13–14px SVG diagram labels. **Justified**, as above. | clean (the earlier AR line-length warnings are gone) |
| `/evals/` (EN, AR) | clean | `line-length`, about 102 characters in the "Why" column of the cases table. **Fixed** after the scan (`td.small` capped at 60ch); not re-scanned. |
| `/privacy/` (EN, AR) | clean | clean (the earlier AR line-length warning is gone) |
| source scan (`frontend/app`, `frontend/components`) | `[]` | |

Line length: content pages now cap paragraphs and list items at 64ch (60ch in Arabic).

Not done in this pass (still open, needs the owner): Impeccable `init` (PRODUCT.md, DESIGN.md), a two-agent critique,
a pass against the real backend with photos loading, and Lighthouse. The answered states (cards, compare, calc,
stop, errors, jump-to-latest, copy) were changed but not re-screenshotted or re-scanned, except one 390px empty-state
screenshot (`evals/screens/verify/after-m-en-empty.png`).
