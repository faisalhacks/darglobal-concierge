# Fonts

All fonts are self-hosted through `@fontsource` packages (bundled into `out/_next/static/media`), so no request goes to a font CDN.

| Family | Role | Package | Licence |
|---|---|---|---|
| Cormorant Garamond (500, 600) | Headings, card titles, figures | `@fontsource/cormorant-garamond` 5.3.0 | SIL Open Font License 1.1 |
| Hanken Grotesk (400, 500, 600) | Body, UI | `@fontsource/hanken-grotesk` 5.3.0 | SIL Open Font License 1.1 |
| IBM Plex Sans Arabic (400, 500, 600) | All Arabic text, including headings | `@fontsource/ibm-plex-sans-arabic` 5.3.0 | SIL Open Font License 1.1 |

Licences were checked in each package's `package.json` (`"license": "OFL-1.1"`). OFL permits bundling and self-hosting with the app; the fonts are not sold on their own.
Each CSS file declares `unicode-range` subsets, so browsers download only the subsets a page uses.
