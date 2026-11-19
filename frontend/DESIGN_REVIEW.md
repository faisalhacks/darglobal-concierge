# Design review: frontend refinement pass (19 Nov 2026)

Scope: a refinement of the existing warm-neutral identity (Cormorant Garamond display, Hanken Grotesk text,
IBM Plex Sans Arabic), not a redesign. Bar: `docs/DESIGN_BAR.md` plus the Impeccable skill (v4.10.0,
`.claude/skills/impeccable`), workflow critique, audit, clarify, harden, polish. Mock API only; zero real model calls.

## How Impeccable was used, and what it could not do

| Step | What ran | Result |
|---|---|---|
| Context | `impeccable context` | Ran. No PRODUCT.md / DESIGN.md in the repo, so this was treated as a scoped refinement of existing code (the skill's own rule). Its interview step was not run: this lane is a subagent with no way to ask the owner, so direction came from the brief alone. |
| Source scan (task 0) | `impeccable detect --json frontend/app frontend/components` | Ran, 19 files, **0 findings**. The tool itself says source scans are regex-only and undercount (no contrast or tiny-text rules), so this proves little on its own. |
| Page scans | `npx --yes impeccable detect --viewport 390x844` and `1440x900` on `/`, `/?lang=ar`, `/how-it-works/`, `/evals/`, `/privacy/`, `/nope/` | Ran. Findings and what was done with each are in `DESIGN_NOTES.md`. |
| Answered states | The detector only sees a fresh page load, so it cannot see cards or tables. Each answered state (listings, rentals, DarGlobal projects in Oman, one project in Arabic, compare, calc) was rendered in Playwright, saved as a static snapshot and scanned. | Ran; findings in `DESIGN_NOTES.md`. |
| Reliability | About one URL scan in three ended with `Protocol error: connection closed` from the detector's own browser on this Windows machine. Each failed scan was retried until it completed; a deliberately bad control page was scanned first to confirm the detector reports real findings. | |
| Craft floor | `reference/craft-floor.md` read before the first edit. | |
| `frontend-design` skill | Loaded. Its guidance matches the brief: no new visual world, cut the template tells. | |

Not done: Impeccable's `critique` subagent and its `shot` command. The critique was done by hand against
the rubric, using Playwright screenshots of every state listed below. `impeccable hooks` is not installed
for this project, so the detector did not run automatically on each edit.

## What changed, by screen

**Chrome (all chat screens).** "Candidate prototype, not an official channel" replaced the
"DarGlobal · Wasalt" subline and the separate strip under the header is gone. The mobile headline strip is
gone. "New conversation" moved into the header (a plus icon below 480 px). The footer is one line on the chat
screen, with Privacy inline. Below 480 px the header shows How it works, the new-conversation icon and the
language toggle; Evals stays one tap away on the How it works page, and stays in the header on wider screens.
Language toggle: a single 44 px button labelled with the other language, "العربية" or "English".

Measured with a message on screen (Playwright, mock degraded mode):

| Viewport | Transcript height | Horizontal page scroll |
|---|---|---|
| 390 x 844 EN | 74% | none |
| 390 x 844 AR | 74% | none |
| 360 x 740 AR | 70% | none |
| 1440 x 900 | 76% | none |

**Status: one line.** The model state appears once, in a fixed-height status line under the header (32 px
desktop, 40 px mobile), built from `meta.llm.state`. It is worded as a fact, e.g. "Answers are assembled from
the dataset; the free model quota is used up for today". The degraded banner, the dash-led labels above each
answer ("Facts only, not advice" and the rest, the eyebrow pattern from the ban list) and the per-answer
degraded line are removed. Per-answer detail now sits only in "How I found this", on the Model line, with the
reason taken from `trace.degraded_reason`. Count checked in the DOM: exactly one status element on every chat
state, zero `.notice` elements.

**CLS on load.** Before: 0.042 to 0.21 (the late banner, then chips and greeting swapping in when
`/api/meta` arrived, then the Arabic swap). After: an inline script sets `lang`/`dir` before first paint, and
the app root stays hidden until the language and `/api/meta` are settled (1.5 s at most). Measured with a
`layout-shift` observer, mock degraded mode, cold load:

| 390 EN | 390 AR | 1440 EN | 1440 AR | 360 AR | 390 EN, no DarGlobal |
|---|---|---|---|---|---|
| 0 | 0.002 | 0 | 0 | 0.003 | 0 |

**Both brands, only numbers that come from the API.** The rail headline and lede switch on
`meta.coverage.DarGlobal.projects`, with `counts_by_site` as the fallback for an older backend. With DarGlobal
rows: "Ask about DarGlobal projects and Wasalt homes." With none, the earlier honest gap copy, and the first
message says "No DarGlobal project pages are in the dataset yet." The three label-over-number stats and the
dataset-hash pill are replaced by one sentence in the first message. Example: "5 DarGlobal projects (3 with a
full project page), 30 Wasalt projects and 1,661 Wasalt listings, collected 19 November 2026." Every number in
it comes from `/api/meta`. The hash moved to How it works. Starter chips come from `meta.starter_chips[lang]`;
the local list is used only when that key is absent, and chips follow the interface language. The last chip
keeps the dashed trap outline.
Rail photograph: the first DarGlobal project with a collected page and an image, from
`/api/projects?site=DarGlobal`. It is hot-linked with no referrer, captioned with the project name and linked
to its DarGlobal page, and falls back to a drawn placeholder.

**Cards.** The DarGlobal badge now matches the neutral Wasalt badge, so gold stays for focus, prices and the
trap chip. DarGlobal cards show city and country, `price_label` or "Price on request", and for
`detail: "index"` the line "Listed on the DarGlobal projects page; no project page collected". Listing titles
no longer repeat the numbers: "Apartment 175.24 SQM with 1 Bedroom" becomes "Apartment in Al-Janadriyah" (the
type is translated in Arabic), and beds and area appear once, in the facts row. "rent, period not published"
has its own muted line. Up to three cards sit in a grid; four or more scroll sideways with snap and a themed
6 px scrollbar with no arrow buttons. Chromium's `scrollbar-width` was overriding the webkit styling, which is
why the arrows showed. Mobile always scrolls sideways at 78% width so the next card peeks.

**Sources.** Two or more Wasalt listing sources collapse into one expandable row, "4 Wasalt listings".
Scrolled to the end, the last source row (y 653 at 1440 x 900) sits clear of the composer (top at y 770).
The transcript has 48 px of bottom padding on desktop and 32 px on mobile.

**Empty state.** One headline, in the rail. "Good to meet you." is gone; the first message says what is in the
corpus. The composer sits directly under the chips until the first message is sent. At 1440 x 900 the gap
between the last chip and the composer is 20 px; the limit was 96 px.

**Composer.** Send has a neutral disabled style (surface-2 fill, muted label, hairline) and a dark filled
enabled style (text colour fill, background-colour label). It is not pale gold any more. States checked:
default, hover, active, focus-visible (2 px ring in `--focus`), disabled, loading (it becomes Stop and the
chips are disabled while streaming, verified in the DOM) and error (Retry in the failed turn, the question
kept in the box on rate limit).

**Trace.** The summary line now carries counts, e.g. "How I found this (4 sources, 0.7 s)". Inside, the intent
and tool show plain names ("Listing search", "Not in the data") instead of identifiers in monospace. Fallback
hops are shown when above zero.

**Arabic.** The rail headline uses weight 500, one step smaller, at line-height 1.5; body text uses 1.8. A
global rule removes letter-spacing and italics under `:lang(ar)`. `<bdi>` wraps prices, areas and bed/bath
facts.

**Alerts.** The one-sided accent bars on rate-limit, error and composer notes are on the ban list, so they are
replaced by a full tinted border.

**/evals.** The page renders every key in `latest.json`, and shows "Not measured" for any key that is absent.
It now has one scores-against-targets table (result, target, 95% interval and n columns appear only when a
value exists, so no column is all dashes, and a Met column), a by-language table, a by-category table, a
separate real-model subset section (`live_subset`), one intent-routing matrix (it replaces ten one-row tables),
the E1 retrieval table (any nesting depth, including before/after) and latency. The cases table opens on
failures and skips; the rest sit behind "Show all N cases". `run_context.db_path` (a local path) is removed
from the raw JSON view.

**/how-it-works.** The architecture diagram and the step sequence stay. The steps are a real ordered process,
so the numerals carry information. Field completeness now uses plain names ("Starting price", "Photos")
grouped by record type (Projects, Listings, Pages). It cannot be grouped by brand because `/api/meta`
completeness is not split by brand. The model pool shows each model's live state and today's budget from
`meta.llm`. The DarGlobal collection method and "no prices published" are stated. Copy now matches the
deployment: one model call per message at most, and tool routing is decided in code.

**/privacy.** The data paragraph is now coverage-aware (EN and AR). It no longer claims there are no DarGlobal
projects when there are, and it names both image hosts.

## Contrast (WCAG 2.x ratios, computed from the tokens)

| Pair | Light | Dark |
|---|---|---|
| Body text on page | 16.56 | 17.28 |
| Body text on surface-2 (user bubble) | 13.76 | 14.87 |
| Muted text on page (rail lede, "Data as of", captions) | 5.51 | 7.63 |
| Muted on surface (cards, status line) | 5.05 | 7.14 |
| Muted on surface-2 (disabled Send label) | 4.57 | 6.57 |
| Gold-strong text (links, trap chip, price accents) on page | 5.66 | 10.30 |
| Gold-strong on surface | 5.18 | 9.64 |
| Focus ring (`--focus`) on page | 5.66 | 8.04 |
| Danger text on page | 5.80 | 4.87 |
| Danger on surface | 5.32 | 4.56 |
| Enabled Send label on its fill | 16.56 | 17.28 |

Raw `--gold` (#c2a36b) is 2.26:1 on the light page, so in light mode it is never used for text or the focus
ring. It appears only on decorative marks (the diamond glyph, list markers, the streaming caret). The focus
ring in light mode uses `--focus` (#7a5f2c).

Targets: buttons, chips, the toggle, the trace summary and the sources group are at least 44 px. Inline text
links in sources and captions are 32 px for a mouse and 44 px under `pointer: coarse`.

## Verification

- `node --test tests/**/*.test.mjs`: 5 of 5 pass. These include the C2 contract checks on the mock: meta
  `coverage`, `llm`, `starter_chips`, `llm_available == (state == 'ok')`, SSE event order, card
  `detail`/`price_label`/`country`, trace keys, `/api/projects?site=` and the `/readyz` keys.
- `tsc --noEmit`: clean. `next build`: succeeds, static export.
- Final screenshots: `frontend/screenshots/final/` (29 files) at 1440 x 900, 390 x 844 and 360 x 740, in EN and
  AR, light and dark. They cover empty, model-ok, no-DarGlobal, DarGlobal cards, a project in Arabic, listings
  with expanded sources, rentals, compare, calc, no-data with the trace open, injection, rate-limited, network
  error, how-it-works, evals, privacy and 404.

## Known gaps (honest list)

- **DarGlobal photographs were not displayed in any screenshot.** The owner's rule is never to fetch
  `darglobal.*` from this machine, so every Playwright run blocked `cdn.darglobal.co.uk` and the DarGlobal card
  and rail images show the placeholder. The code hot-links them for real visitors, and the backend CSP already
  allows `https://*.darglobal.co.uk`. Wasalt photos (imagedelivery.net) load and are visible in the
  screenshots.
- **The backend does not yet emit the C2 keys** (`coverage`, `llm`, `starter_chips`, card `detail` and
  `price_label`, the new trace keys). All screens were checked against `frontend/mock/server.mjs`, which
  implements C2. Against the current backend the frontend falls back to `counts_by_site`, `llm_available` and
  local chips, and has been typechecked for that path, but it was not screenshotted against the real backend in
  this pass.
- **The floor plan as lead image** is picked by the backend (`_first_image` in `store.py`); the card payload
  carries one URL, so the frontend cannot prefer a photograph. This is left to the backend or integrator.
- **No DESIGN.md / PRODUCT.md.** Impeccable recommends `/impeccable init`. Not done, because it needs the
  owner's answers.
- **How it works** still quotes the E1 figures and the 50 requests a day limit as text. Both come from
  recorded facts (E1.json, the owner's account limit), not from `/api/meta`.
