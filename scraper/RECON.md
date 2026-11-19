# RECON — DarGlobal and Wasalt (SPEC §6.1)

Recon date: 2026-11-19 (UTC). Every request went through the single fetch lane (`scraper/fetch.py`):
one request at a time across all hosts, at least 2 s apart, User-Agent
`DarGlobalConciergeCandidatePrototype/1.0 (job-assessment prototype; non-commercial)`, no cookies, no proxies.
Every raw response is in `scraper/snapshots/<host>/`, and every live request is logged in `snapshots/_ledger.jsonl`.

## Verdict summary

| Site | Real domain | robots.txt | Crawl-delay | Verdict |
|---|---|---|---|---|
| DarGlobal | `darglobal.co.uk` (`www.` redirects to the apex) | Allows `/$`, `/projects/`, `/blog/`, `/press/`. Disallows `/sitemap_index.xml`, tracking params, `?s=`, `?post_type=`, `?wc-ajax=` | none declared, so we use 2 s | **BLOCKED for automated clients.** HTML pages return an Imperva/Incapsula JS bot challenge. **Fetching stopped** (SPEC §6.3) |
| Wasalt | `wasalt.sa` (some assets and links use `wasalt.com`) | `User-agent: *` gets `Allow: /` except `/search` and `/cdn-cgi/rum`. The comment says AI access is allowed to most areas | none declared, so we use 2 s | **Allowed.** Public SRP, project and static pages fetched |
| Wasalt auctions | `auction.wasalt.sa` | Allows `/` and `/auction/*`. Disallows `/user/*` | none | Allowed (we fetched the landing page only) |
| Wasalt blog/guides | `blog.wasalt.sa` (WordPress) | Disallows `/wp-admin/`. `GPTBot` is fully disallowed, but our UA is not GPTBot | none | Allowed (we fetched the index plus 6 guides) |

## DarGlobal — details

- `GET https://www.darglobal.co.uk/robots.txt` returned 200 (contents above). `Sitemap: https://darglobal.co.uk/sitemap.xml`.
- `GET https://darglobal.co.uk/sitemap.xml` returned 200, with 482 URLs: 266 `/blog/`, 73 `/press/`, 26 `/insights/`,
  15 `/projects/` (country/type listing pages such as `/projects/properties-in-uae/villas`), 12 `/partners/`,
  9 `/one-of-one/`, plus about 30 top-level project landing pages (e.g. `/w-residences`, `/davinci-tower-by-pagani`,
  `/aida-trump-villas`, `/rayana/trump-mansions`, `/trump-plaza/park-residences`) and static pages (`/about`, `/faq`,
  `/get-in-touch`, `/partners`, `/investor`, `/why-invest`).
- **`GET https://darglobal.co.uk/projects` returned 200 with a 212-byte body**:
  `<META NAME="robots" CONTENT="noindex,nofollow">` plus `<script src="/_Incapsula_Resource?...">`. This is an
  Imperva (Incapsula) JavaScript bot challenge, so the real page content was never served.
- **Action: DarGlobal stopped after that one HTML request** (3 DarGlobal requests in total: robots, sitemap, /projects).
  We did not retry. We did not run a headless browser to solve the challenge, change the UA or add cookies. The fetcher
  now has a persisted block entry (`snapshots/_blocked.json`) and refuses every further DarGlobal request.
- ToS: the terms pages (`/terms-of-uses`, `/terms-conditions`) sit behind the same challenge, so **we could not read them**.
- Page-type probes (`__NEXT_DATA__` / JSON-LD / SSR): **not possible** because of the challenge.
- Site-advertised counts: unknown. The sitemap suggests about 30 to 40 project or landing URLs, but that is a URL count,
  not a project count.
- **Dataset impact (automated pass only; superseded by the manual collection below):** `projects` held **0 DarGlobal rows**. The only DarGlobal row is one `pages` record
  (`darglobal-pg-sitemap`, `page_type=sitemap_index`) that lists the official public URLs from the sitemap and states
  that the content was not collected. No DarGlobal facts are invented.
- **NEEDS-HUMAN options (owner decides):** (a) ask DarGlobal for permission or a feed. (b) The owner saves a handful of
  DarGlobal project pages manually in a normal browser into `scraper/manual/darglobal/` for a DarGlobal extractor
  (not written yet, because no page structure could be observed). (c) Ship as Wasalt-only and state the gap in
  the README.
  We did not take option (b) automatically, because driving a browser to get past a bot challenge is a bypass.
  **Update (same day): the owner chose option (b)** — see "DarGlobal — manual collection" below. The automated
  fetcher still refuses every DarGlobal request.

## DarGlobal — manual collection (owner's own browser)

- **Who / how:** the owner opened the pages in their own, already-running Chrome session, one page at a time at human
  pace. Each extract records its method as `claude-in-chrome, user's own browser session, human pace` (the
  Claude-in-Chrome extension read the page the owner had open; no headless browser, no proxy, no changed UA, no
  challenge solving by the pipeline). Every extract has `blocked: false`. `scraper/fetch.py` was not used, and the
  pipeline never sends a request to `darglobal.*`.
- **When / how many:** 2026-11-19, 09:48 to 09:57 UTC, **7 pages** (log: `scraper/manual/darglobal/extracts/_log.jsonl`):
  `/projects` (index) plus 6 project pages (`/trump-international-hotel-and-tower-dubai`, `/davinci-tower-by-pagani`,
  `/urban-oasis-by-missoni`, `/w-residences`, `/les-vagues`, `/the-astera`). The pages are on the save list in
  `scraper/manual/darglobal/SAVE_LIST.md`, and robots.txt allows them.
- **What an extract holds:** url, title, headings, visible text, image URLs, JSON-LD (FAQ nodes and the site-wide
  Organization node removed), `collected_at`. Person names were replaced with `[name removed]` and phone numbers with
  `[phone]` at collection time.
- **Parser:** `scraper/darglobal_manual.py` (offline). `python -m scraper.build_dataset` merges Wasalt and DarGlobal
  and picks up any new `extracts/*.json` with no code change. Then rebuild the index with
  `backend/.venv/Scripts/python -m backend.app.build_index --data data/concierge.sqlite --out data/index`.
  - `/projects`: the 38 H3 headings are the project names in page order. The location of each project is the text
    between the previous name and that name. Country comes from an explicit token map only (UAE, KSA, Oman, Qatar,
    Spain, United Kingdom/England, plus the page's own location filter). If no token matches, country is NULL and the
    row is listed in `data/build_report.json` -> `darglobal_unresolved` (today only *Trump Mansions*, published as
    "Rayana, Wadi Safar, Riyadh"; the parser still leaves it NULL, and the third-party merge below corrects it).
    These rows are **index-only**: `source_url = https://darglobal.co.uk/projects`, with name, city and country only
    (unless the third-party merge below adds facts).
  - Project pages upgrade the matching index row: source_url, description (first paragraph), property type, status,
    units, amenities (from JSON-LD amenityFeature), area, lat/lng (from JSON-LD GeoCoordinates only), images (the
    page's own JSON-LD images on `cdn.darglobal.co.uk`, max 6), and brand partner (only when it is in the published
    name). Area uses the published sqm (label `Area (SQM)`, otherwise the sqm stated in the text), and otherwise the
    `Area (SQFT)` label × 0.092903. The published area strings are quoted verbatim in the fact chunk, because some
    pages contradict themselves (e.g. Les Vagues label 84–383 sqm vs text 86–389 sqm).
  - **Not ingested:** the whole *WHY INVEST* section (yield, capital-growth and "doubled market price" claims),
    investment / Golden-Visa / register-interest FAQ entries, *OTHER PROJECTS* cross-sell cards, the register-interest
    form and the cookie banner. The list for each page is in `build_report.json` -> `darglobal.detail[].excluded_sections`
    / `faq_excluded`.
  - **No prices:** DarGlobal pages publish none (the JSON-LD `AggregateOffer` has a currency but no price), so every
    `price_*` column is NULL. Answers say "Price on request" / "not published".
- **Contact page:** `pages` row `darglobal-pg-contact` = `https://darglobal.co.uk/get-in-touch`. The URL comes from the
  sitemap fetched earlier, the text is one line, and the page was not fetched. For Wasalt, `wasalt-pg-contact` =
  `https://wasalt.sa/en/corporate`, which was already in the snapshots, so no new request was made.

## DarGlobal data provenance

DarGlobal facts in `data/concierge.sqlite` come from exactly two kinds of source. No Wayback Machine, Google cache,
archive mirror, proxy, headless browser, changed User-Agent, cookie replay or any other workaround was used for
darglobal.co.uk at any point.

1. **DarGlobal's own pages, 7 of them, read in the owner's own browser at human pace.** The automated fetcher made
   3 DarGlobal requests (robots.txt, sitemap.xml, /projects), got the Imperva/Incapsula bot challenge on the HTML page,
   and **stopped** there, as SPEC §6.3 requires. The block entry in `snapshots/_blocked.json` still makes it refuse every
   DarGlobal request. The owner then opened 7 pages (`/projects` plus 6 project pages) in their own Chrome session,
   one at a time, between 09:48 and 09:57 UTC on 2026-11-19. The bot protection was respected: nothing was solved or
   bypassed by the pipeline. The details are in the section above.
2. **Third-party public sources for everything else.** These are in `scraper/manual/darglobal/thirdparty/*.json`,
   collected on 2026-11-19 with no darglobal.* or wasalt.* request. The source list with dates is in
   `scraper/manual/darglobal/thirdparty/_SOURCES.md`. There are 34 distinct source URLs of these kinds:
   - **LSE RNS:** Dar Global PLC Full Year Results, RNS 1301W, 2026-03-11, read from the ticker.app mirror of
     the London Stock Exchange announcement. This is the company's own regulatory filing. Its table values were
     extracted by a summarising fetch tool and **have not yet been spot-checked against the LSE original**.
   - **Press and trade press:** The National, Gulf News, Oman Observer, Arab News, Asharq Al-Awsat, Qatar News
     Agency, The Peninsula, idealista, Gulf Construction, Middle East Construction News, Hospitality Net, London
     Loves Property, plus one law-firm note (Clyde & Co).
   - **Wire-hosted Dar Global releases:** PR Newswire, AAP (Cision) and the Zawya press-release section. They are
     tagged **"company statement"** in every chunk, and so is one developer-bylined Khaleej Times supplement. Zawya
     release pages carry no date, so they are recorded as "undated on page".
   - Broker and listing portals turned up in searches but were **not** used as fact sources.

**How the third-party facts are merged** (`scraper/darglobal_thirdparty.py`, offline, deterministic):
- 20 files. **3 are empty and skipped** (Fairway Villas, La Collina, Sunrise Haven). The other 17 cover 23 DarGlobal
  rows. **14 files enrich an existing index row**, using a reviewed name-match table; a token fuzzy matcher agrees
  wherever it is confident, and it is used on its own only for future files. **3 create a new row**, each with
  `dg-<slug>`, `site='DarGlobal'` and `developer='DarGlobal'`:
  - `dg-rayana`: the masterplan. DarGlobal lists only its component *Trump Mansions*.
  - `dg-trump-plaza-jeddah`: the parent of the listed Trump Executive and Trump Park Residences, in the Amaya
    development.
  - `dg-trump-signature-villas`: AIDA. It is not on the index under this name, and it is unclear whether it is the
    same product as Trump Golf Villas or Fairway Villas.

  A fact that names a component that DarGlobal lists as its own row is also attached to that row: Trump Executive
  and Park Residences, Amaya, The Great Escape 2, Trump Cliff Villas and Trump Mansions.
- **Every fact keeps its own source.** There is one chunk per (project, source), and its `source_url` is that source.
  The chunk text gives the source title, its type, its date and its URL. Each project with third-party facts also
  has a "Public sources" chunk and a `pages` row (`page_type='project_sources'`, id
  `darglobal-pg-sources-<slug>`) that lists every source, so the bot can cite them.
- **Conflicts are kept, not resolved.** A "Figures by source and date" chunk lists every field that two or more
  sources report, with each value's source and date. For example, Trump Tower Jeddah units are given as "about 500
  units (The National, 12 Dec 2024), 500 luxury apartments (Gulf News, 15 Dec 2024) and 561 (Dar Global PLC RNS
  1301W, 11 Mar 2026)". Structured columns are filled only when they are empty, and only from the most recent RNS
  value: `status`, `handover_year` (only from an RNS "Qn YYYY" completion) and `property_types`. A row whose
  structured record now comes from the RNS gets `projects.source_url` set to the RNS URL, so a card or field answer
  never cites darglobal.co.uk for a value DarGlobal did not publish. The DarGlobal URL that the name and location
  came from stays on the row's `#fact-en/#fact-ar` chunks.
- **Prices:** every `price_*` column stays NULL. The only price figures stored are the two Trump Tower Jeddah press
  figures, and they appear in chunk text only, as "Price press-reported on 2024-12-12: average price per unit
  4 million riyals ..." (The National) and "Price press-reported on 2024-12-15: price range priced between SR4
  million to SR50 million ..." (Gulf News), each marked "(not an official DarGlobal price list)". The Mulliner's marketed and sale prices
  are excluded. The price in those two headlines is cut from the stored title, but the URLs stay as published.
  Reported total project values (for example "$1 billion") are kept and labelled "not a unit price".
- **Excluded facts:** the AIDA "3.5 million square kilometre" misprint (the curator note says do not use) and the
  two Mulliner prices. Investment-return claims are filtered as before; none occurred.
- **Rayana (Riyadh) correction:** DarGlobal publishes *Trump Mansions* as "Rayana, Wadi Safar, Riyadh", which has no
  country token, so the parser leaves the country NULL. Third-party sources place Rayana in Wadi Safar, Diriyah,
  Riyadh, Saudi Arabia: the Zawya Dar Global release and Arab News (2026-01-11). The merge therefore sets
  `dg-trump-mansions.country = 'Saudi Arabia'`. It is logged in `build_report.json` under
  `darglobal.thirdparty.corrections` and `darglobal_unresolved[].resolved_by_thirdparty`, and the project's sources
  page and fact chunk state it.
- **Result:** 41 DarGlobal rows. 6 have their own DarGlobal page, 32 come from the index (20 of them now carry
  third-party facts) and 3 come from third-party sources only. That makes 29 of 41 DarGlobal projects with detail
  facts: the 6 page rows plus the 23 rows with third-party facts. The full report is in `data/build_report.json`
  under `darglobal.thirdparty`.

## Wasalt — details

- robots.txt: shown above. `llms.txt` (https://wasalt.sa/llms.txt, updated 2025-07-06) says: `AllowLLMUse: Yes`,
  `AllowSummarization: Yes`, `AllowDataExtraction: Only for public listing content`, `AllowCommercialUse: No`,
  `CrawlRateLimit: Moderate`, ContentScope `/blog/ /for-sale/ /for-rent/ /projects/`, `AttributionRequired: Yes`
  ("Source: Wasalt.sa"). It disallows extracting phone/WhatsApp/contact details, resale/redistribution, scraping
  internal search results or maps, and non-public content. It also says prices change, so we must point users to the live site.
- ToS (`/en/s/terms-of-use`, snapshot saved): the Intellectual Property section says users may not "copy, extract,
  publish ... any content ... except as permitted", and may not republish content on other websites or use it for
  commercial purposes. **This conflicts with llms.txt**, which permits extracting public listing content for
  non-commercial use. Our position: a non-commercial job-assessment prototype, a small sample (about 0.8k listings out of
  60k in the sitemap), attribution and a link to the original on every card, images hot-linked rather than re-hosted, no
  contact data, and every answer points to the live site. **The owner should mention this conflict in the README and
  take the bot down after review** (SPEC §33).
- Sitemaps (from robots): `product_sitemap_en_sa.xml.gz` has 60,000 listing URLs (45,898 `/property/sale/`,
  14,102 `/property/rent/`). `category_sitemap_en_sa.xml.gz` has 8,542 SRP/category URLs.
  `rental_pdp_sitemap_en_sa.xml.gz` has 2,676 daily-rental URLs. `static_sitemap_en_sa.xml.gz` has 9 static URLs.
- Page-type probes (all Next.js with `__NEXT_DATA__`, giving T1 extraction):
  - **SRP / category** (`/en/properties-for-sale-in-riyadh`): `pageProps.searchResult` = `{count, totalPages,
    properties[30-32], unitCount, aucCount}`. Each property has `propertyInfo` (title, city, district, salePrice /
    expectedRent, currencyType, propertySubType, slug), `attributes` (bedrooms, bathrooms, built-up area) and
    `propertyFiles.images`. Some `properties` entries are nested arrays of **project cards**. There are also 29 JSON-LD
    blocks, and `pageProps.para` holds the SEO "area guide" HTML.
    **PII present in the payload** (`leadContactInfo.ownerName`, `propertyOwner.*`, `contactDetails.phoneNumber/whatsappNumber`):
    **never read by the extractor.**
  - **PDP** (`/en/property/sale/<slug>-<id>`): `pageProps.propertyDetailsV3`. Free-text `description`s contain phone
    numbers, so PDP descriptions are not used (only one PDP was probed).
  - **Project** (`/en/project/<City>/<slug>-<id>`): `pageProps.compoundDetails.data.projectInfo` (title, description,
    salePriceMin/Max, currency, labels such as "Under Construction", city, district, completionDate) plus `location`
    (lat/lng, published together with an `isApproxLocation` flag) and `compoundUnitListDetails` (the units in the project).
  - **Static** (`/en/corporate`, `/en/s/*`): Strapi CMS JSON in `pageProps` plus SSR HTML. `/en/s/masterplan` and
    `/en/s/wasalt-business` serve the home page content (duplicates, dropped).
  - `/en/projects` returns **404**. Wasalt has no public project index page. Projects are discovered from `/en/project/`
    links on SRP pages.
- Pagination: SRPs carry `filterQueries.page`. We only fetched page 1 of each category (a sample, by design).
- **Site-advertised counts** (from `searchResult.count` on the fetched SRPs, as of the scrape): Riyadh sale 29,459;
  Jeddah sale 28,735; Riyadh rent 20,759; Jeddah rent 5,099; Dammam sale 3,099; Al Khobar sale 2,780; Makkah sale
  2,097; Madinah sale 1,598; Khamis Mushayt sale 541; Taif sale 518. Project counts ("unitCount"): Jeddah sale 1,146;
  Madinah 214; Riyadh 169. The full table is in `data/build_report.json` -> `srp_site_counts`.
- Excluded by design: `/search` (robots and llms.txt), `business.wasalt.sa/*/login`, `auction.wasalt.sa/user/*`,
  every agent/owner/contact field, and daily-rental booking pages.

## Request budget

Hard cap 450 live requests. **Used: 127 logged requests** (`snapshots/_ledger.jsonl`): DarGlobal 3, Wasalt hosts 124.
In the first pass, before explicit redirect handling was added to `fetch.py`, httpx followed redirects automatically.
That left about 11 redirect hops unlogged (www to apex for DarGlobal robots.txt, and 10 inactive Wasalt project
pages redirecting to `/en/sale/search`). They were still made sequentially. The fetcher now follows redirects
manually, logs each hop and never follows into `/search`. No 403, 429 or CAPTCHA came from any Wasalt host.

Pagination finding: `?page=2` on an SRP returns page 1 again (`filterQueries.page` stays 0), so the sample's breadth
comes from about 50 category/city SRPs, not from paging. `/en/properties-for-sale-in-buraydah` returned 404.
