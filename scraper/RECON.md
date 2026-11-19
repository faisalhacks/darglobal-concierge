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
- **Dataset impact:** `projects` holds **0 DarGlobal rows**. The only DarGlobal row is one `pages` record
  (`darglobal-pg-sitemap`, `page_type=sitemap_index`) that lists the official public URLs from the sitemap and states
  that the content was not collected. No DarGlobal facts are invented.
- **NEEDS-HUMAN options (owner decides):** (a) ask DarGlobal for permission or a feed. (b) The owner saves a handful of
  DarGlobal project pages manually in a normal browser into `scraper/manual/darglobal/` for a DarGlobal extractor
  (not written yet, because no page structure could be observed). (c) Ship as Wasalt-only and state the gap in
  the README.
  We did not take option (b) automatically, because driving a browser to get past a bot challenge is a bypass.

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
