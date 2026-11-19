// Dev-only mock of the binding API/SSE contract (SPEC + contract changes C2). No dependencies.
// Serves frontend/out (static export) plus canned /api/* responses so the UI can be built and
// screenshotted without the backend. It never calls a model.
//
// Data provenance: Wasalt listings below are copied from data/concierge.sqlite (public pages, real photos on
// imagedelivery.net). DarGlobal names, cities and image URLs are copied from the owner's hand-collected extracts
// in scraper/manual/darglobal/extracts; DarGlobal publishes no prices, so none appear here. Answer prose and the
// sample eval report are FIXTURE text and must never be shipped as real content.
//
//   node mock/server.mjs                       -> http://localhost:8787
//   MOCK_LLM_STATE=ok|quota|cooling|off|maintenance   (default ok; MOCK_LLM=0 is an alias for quota)
//   MOCK_DG=0                                  (no DarGlobal rows: the honest gap copy)
//   MOCK_CHIPS=0                               (no starter_chips in /api/meta: local fallback chips)
//   MOCK_EVALS=empty | sample                  (default: sample)
//   MOCK_CANDIDATE=1                           (placeholder footer links, not real details)
//   MOCK_FLAGS=FF_WIDGET_DEMO,FF_MAP           (flags to turn on)
//
// Trigger words in a chat message: oman, les vagues / astera, dubai, riyadh/apartment, rent, compare,
// down/%, python/2+2, ignore/system prompt, guarantee, reykjavik, rate (429), drop (stream cut), slow.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "out");
const PORT = Number(process.env.PORT || 8787);
const LLM_STATE = process.env.MOCK_LLM_STATE || (process.env.MOCK_LLM === "0" ? "quota" : "ok");
const LLM = LLM_STATE === "ok";
const DG_ON = process.env.MOCK_DG !== "0";
const CHIPS_ON = process.env.MOCK_CHIPS !== "0";
const FLAGS = new Set((process.env.MOCK_FLAGS || "").split(",").filter(Boolean));
const AS_OF = "2026-11-19T09:00:00Z";
const VERSION = "fixture-v1";
const INDEX_URL = "https://darglobal.co.uk/projects";

const PRICE_LABEL = { en: "Price on request", ar: "السعر عند الطلب" };

const DG_ALL = [
  { id: "dg-les-vagues", slug: "les-vagues", name: "Les Vagues by Elie Saab", site: "DarGlobal", city: "Doha", country: "Qatar", price_from: null, status: "Under Development", image_url: "https://cdn.darglobal.co.uk/ELS_Courtyard_1024x599_92104c2831.jpg", source_url: "https://darglobal.co.uk/les-vagues", detail: "page" },
  { id: "dg-w-residences", slug: "w-residences", name: "W Residences", site: "DarGlobal", city: "Dubai", country: "United Arab Emirates", price_from: null, status: "Completed and Sold out", image_url: "https://cdn.darglobal.co.uk/WRD_Pool_1_2_9402b26d1a.jpg", source_url: "https://darglobal.co.uk/w-residences", detail: "page" },
  { id: "dg-the-astera", slug: "the-astera", name: "The Astera, Interiors by Aston Martin", site: "DarGlobal", city: "Al Marjan Island, Ras Al Khaimah", country: "United Arab Emirates", price_from: null, status: "Under Development", image_url: "https://cdn.darglobal.co.uk/J001267_DG_01_Rak_Al_Marjan_S07_Exterior_Hero_Final_web_520bfa333d.jpg", source_url: "https://darglobal.co.uk/the-astera", detail: "page" },
  { id: "dg-trump-golf-villas", slug: "trump-golf-villas", name: "Trump Golf Villas", site: "DarGlobal", city: "Muscat", country: "Oman", price_from: null, status: null, image_url: null, source_url: INDEX_URL, detail: "index" },
  { id: "dg-trump-cliff-villas", slug: "trump-cliff-villas", name: "Trump Cliff Villas", site: "DarGlobal", city: "Muscat", country: "Oman", price_from: null, status: null, image_url: null, source_url: INDEX_URL, detail: "index" },
];
const DG = DG_ON ? DG_ALL : [];
const card = (p, lang) => ({ ...p, price_label: p.price_from ? null : PRICE_LABEL[lang] });

const LISTINGS = [
  { id: "wasalt-l-5972209", title: "Apartment 250.93 SQM with 2 Bedrooms", site: "Wasalt", listing_type: "buy", price: { amount: 830000, currency: "SAR" }, beds: 2, baths: null, area_m2: 250.93, district: "Al-Janadriyah", city: "Riyadh", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5972209/images/a788b320-08f5-47dd-b10f-2839b757014f.jpg/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/sale/apartment-25093-sqm-with-2-bedrooms-5972209" },
  { id: "wasalt-l-5893394", title: "Apartment 119.38 SQM with 2 Bedrooms", site: "Wasalt", listing_type: "buy", price: { amount: 950000, currency: "SAR" }, beds: 2, baths: null, area_m2: 119.38, district: "Al-Muanisiyah", city: "Riyadh", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5893394/images/1693834a-83bb-4f4b-befa-7289a6b7888f.jpg/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/sale/apartment-11938-sqm-with-2-bedrooms-5893394" },
  { id: "wasalt-l-5972147", title: "Apartment 71.28 SQM with 2 Bedrooms", site: "Wasalt", listing_type: "buy", price: { amount: 380000, currency: "SAR" }, beds: 2, baths: null, area_m2: 71.28, district: "An-Nadheem", city: "Riyadh", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5972147/images/f262bace-b8e4-4782-94d7-d7427103cff9.webp/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/sale/apartment-7128-sqm-with-2-bedrooms-5972147" },
  { id: "wasalt-l-5935033", title: "Apartment 100.09 SQM with 2 Bedrooms", site: "Wasalt", listing_type: "buy", price: { amount: 600000, currency: "SAR" }, beds: 2, baths: null, area_m2: 100.09, district: "Al Marjan", city: "Riyadh", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5935033/images/e257c8eb-31ae-449a-ae6e-d8c3655f105a.webp/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/sale/apartment-10009-sqm-with-2-bedrooms-5935033" },
];
const RENTALS = [
  { id: "wasalt-l-5974229", title: "Apartment 354.5 SQM with 3 Bedrooms", site: "Wasalt", listing_type: "rent", price: { amount: 85000, currency: "SAR" }, beds: 3, baths: null, area_m2: 354.5, district: "Al-Iskan Al-Janoubi", city: "Dammam", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5974229/images/890578ec-efd6-4815-ac82-6acbea630089.jpeg/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/rent/apartment-3545-sqm-with-3-bedrooms-5974229" },
  { id: "wasalt-l-5971906", title: "Apartment 131.68 SQM with 2 Bedrooms", site: "Wasalt", listing_type: "rent", price: { amount: 42000, currency: "SAR" }, beds: 2, baths: null, area_m2: 131.68, district: "Al Shooalah", city: "Dammam", image_url: "https://imagedelivery.net/1DNKFJPRaeUdy_j8F7HT3w/production/properties/5971906/images/f28ec478-1746-47d9-bf51-d8253b471cf6.png/width=800,quality=75,format=auto", source_url: "https://wasalt.sa/en/property/rent/apartment-13168-sqm-with-2-bedrooms-5971906" },
];
const srcOf = (x, title) => ({ site: x.site, title: title ?? x.title ?? x.name, url: x.source_url, scraped_at: AS_OF });

const STARTER = {
  en: [
    "What DarGlobal projects are in Oman?",
    "Tell me about Les Vagues by Elie Saab",
    "2-bed apartment to buy in Riyadh under 1M SAR",
    "What is 20% down on 2,000,000 SAR?",
    "What is the price of a penthouse at DarGlobal's Aurora Reykjavik tower?",
  ],
  ar: [
    "ما مشاريع دار جلوبال في عُمان؟",
    "حدثني عن مشروع ليه فاغ من إيلي صعب",
    "شقة غرفتين للبيع في الرياض بأقل من مليون ريال",
    "كم الدفعة المقدمة 20% على 2000000 ريال؟",
    "كم سعر البنتهاوس في برج أورورا ريكيافيك من دار جلوبال؟",
  ],
};
const STARTER_GAP = {
  en: ["What projects do you have in Riyadh?", "2-bed apartment to buy in Riyadh under 1M SAR", "Apartments for rent in Dammam", "What is 20% down on 2,000,000 SAR?", "What is the price of a penthouse at DarGlobal's Aurora Reykjavik tower?"],
  ar: ["ما المشاريع المتوفرة في الرياض؟", "شقة غرفتين للبيع في الرياض بأقل من مليون ريال", "شقق للإيجار في الدمام", "كم الدفعة المقدمة 20% على 2000000 ريال؟", "كم سعر البنتهاوس في برج أورورا ريكيافيك من دار جلوبال؟"],
};

const CHIPS_EN = [
  { label: "Compare W Residences and Les Vagues", message: "Compare W Residences and Les Vagues" },
  { label: "Rentals in Dammam", message: "Apartments for rent in Dammam" },
  { label: "How do I contact DarGlobal?", message: "How do I contact DarGlobal sales?" },
];
const CHIPS_AR = [
  { label: "قارن بين دبليو ريزيدنسز وليه فاغ", message: "قارن بين W Residences و Les Vagues" },
  { label: "شقق للإيجار في الدمام", message: "شقق للإيجار في الدمام" },
  { label: "كيف أتواصل مع دار جلوبال؟", message: "كيف أتواصل مع مبيعات دار جلوبال؟" },
];

const isAr = (s) => /[؀-ۿ]/.test(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function plan(msg) {
  const m = msg.toLowerCase();
  const ar = isAr(msg);
  const L = ar ? "ar" : "en";
  const base = { lang: L, chips: ar ? CHIPS_AR : CHIPS_EN, sources: [], intent: "general", path: "code", tool: null };
  if (/ignore|system prompt|تجاهل|موجّه النظام/.test(m)) return { ...base, intent: "injection", path: "template", text: ar ? "لا أشارك تعليماتي الداخلية. يمكنني الإجابة عن مشاريع دار جلوبال ومنازل وصلت المنشورة." : "I don't share my internal instructions. I can answer questions about published DarGlobal projects and Wasalt homes." };
  if (/python|2\s*\+\s*2|\bcode\b/.test(m)) return { ...base, intent: "off_topic", path: "template", text: ar ? "أغطي عقارات دار جلوبال ووصلت فقط. جرّب أحد الاقتراحات أدناه." : "I only cover DarGlobal and Wasalt property. Try one of the suggestions below." };
  if (/guarantee|return on|ضمان|عائد/.test(m)) return { ...base, intent: "advice", path: "template", text: ar ? "لا أقدّم نصائح استثمارية ولا أتوقع العوائد. يمكنني مشاركة الحقائق المنشورة وروابط التواصل الرسمية." : "I don't give investment advice or predict returns. I can share published facts and the official sales contacts." };
  if (/reykjavik|ريكيافيك/.test(m)) return { ...base, intent: "no_data", path: "template", text: ar ? "لا يوجد مشروع بهذا الاسم في البيانات المنشورة، لذا لا أذكر له سعراً." : "There is no project by that name in the published data, so I won't give a price for it." };
  if (/compare|قارن/.test(m)) {
    const [a, b] = [DG_ALL[1], DG_ALL[0]];
    return { ...base, intent: "compare", tool: "compare_projects", text: ar ? "هذه مقارنة بين المشروعين مما تنشره كل صفحة." : "Here is how the two compare, using only what each project page publishes.", compare: {
      columns: [{ id: a.id, name: a.name, site: a.site }, { id: b.id, name: b.name, site: b.site }],
      rows: [
        { label: ar ? "المدينة" : "City", values: ["Dubai", "Doha"] },
        { label: ar ? "السعر" : "Price", values: [null, null] },
        { label: ar ? "الحالة" : "Status", values: ["Completed and Sold out", "Under Development"] },
        { label: ar ? "الوحدات" : "Unit types", values: ["1, 2 & 3-bedrooms", "1, 2 & 3-bedrooms"] },
      ],
      sources: [srcOf(a, "W Residences Downtown Dubai | DarGlobal"), srcOf(b, "Les Vagues by Elie Saab | Sea-View Residences Doha")],
    }, sources: [srcOf(a, "W Residences Downtown Dubai | DarGlobal"), srcOf(b, "Les Vagues by Elie Saab | Sea-View Residences Doha")] };
  }
  if (/down|%|دفعة/.test(m)) return { ...base, intent: "calculate", tool: "calculator", text: ar ? "الحساب أدناه تقديري." : "Here is the arithmetic. It is an estimate.", calc: {
    kind: "down_payment", inputs: { price: 2000000, percent: 20, currency: "SAR" }, result: { down_payment: 400000, remaining: 1600000, currency: "SAR" },
    formula: "down_payment = price × percent / 100", disclaimer: ar ? "تقدير وليس نصيحة مالية." : "Estimate, not financial advice." } };
  if (/rent|إيجار|ايجار/.test(m)) return { ...base, intent: "search_listings", tool: "search_listings", text: ar ? "عرضان للإيجار في الدمام ضمن البيانات." : "Two rentals in Dammam match. Wasalt does not say whether these rents are per month or per year.", cards: { projects: [], listings: RENTALS }, sources: RENTALS.map((x) => srcOf(x)) };
  if (/riyadh|apartment|الرياض|شقة|شقق/.test(m)) return { ...base, intent: "search_listings", tool: "search_listings", text: ar ? "أربعة عروض شقق بغرفتين للبيع في الرياض بأقل من مليون ريال." : "Four 2-bed apartments for sale in Riyadh under SAR 1,000,000 match.\n\n- The cheapest is SAR 380,000 in An-Nadheem\n- Bathroom counts are not published for these listings", cards: { projects: [], listings: LISTINGS }, sources: LISTINGS.map((x) => srcOf(x)) };
  if (DG_ON && /oman|muscat|عمان|عُمان|مسقط/.test(m)) {
    const ps = DG.filter((p) => p.country === "Oman");
    return { ...base, intent: "projects_by_location", tool: "search_projects", text: ar ? "مشروعان لدار جلوبال في مسقط، عُمان، مدرجان في صفحة المشاريع. لم تُجمع صفحتاهما، ولا تُنشر الأسعار." : "Two DarGlobal projects in Muscat, Oman are listed on the DarGlobal projects page: Trump Golf Villas and Trump Cliff Villas. Their own pages were not collected, and DarGlobal publishes no prices.", cards: { projects: ps, listings: [] }, sources: [{ site: "DarGlobal", title: "DarGlobal projects", url: INDEX_URL, scraped_at: AS_OF }] };
  }
  if (DG_ON && /les vagues|ليه فاغ|astera|dubai|دبي/.test(m)) {
    const ps = /dubai|دبي/.test(m) ? [DG_ALL[1]] : /astera/.test(m) ? [DG_ALL[2]] : [DG_ALL[0]];
    const p = ps[0];
    return { ...base, intent: "project_info", tool: "search_projects", text: ar ? `${p.name} في ${p.city}. الحالة: ${p.status}. لا تنشر دار جلوبال سعراً لهذا المشروع.` : `${p.name} is in ${p.city}, ${p.country}. Its page lists the status as ${p.status.toLowerCase()} and 1, 2 and 3-bedroom units. DarGlobal does not publish a price for it.`, cards: { projects: ps, listings: [] }, sources: [srcOf(p)] };
  }
  if (/oman|les vagues|dubai|عمان|دبي/.test(m)) return { ...base, intent: "no_data", path: "template", text: ar ? "لا توجد صفحات مشاريع لدار جلوبال في البيانات حالياً." : "No DarGlobal project pages are in the dataset yet, so I have no verified information on that." };
  if (/contact|تواصل/.test(m)) return { ...base, intent: "contact_sales", path: "template", text: ar ? "استخدم صفحة التواصل الرسمية لدار جلوبال." : "Use DarGlobal's official contact page; this concierge does not collect contact details.", sources: [{ site: "DarGlobal", title: "Contact DarGlobal", url: "https://darglobal.co.uk/contact-us", scraped_at: AS_OF }] };
  return { ...base, intent: "general", tool: "search_pages", text: ar ? "هذه إجابة تجريبية من الخادم الوهمي." : "This is a fixture answer from the mock server. Ask about Oman, Les Vagues, Riyadh, rentals, a comparison or a down payment to see each component.", sources: [] };
}

function send(res, event, data) { res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); }

const REASON = { quota: "quota", cooling: "rate_limited", off: "no_model", maintenance: "maintenance" };

async function chat(req, res, body) {
  const msg = String(body.message || "");
  if (!msg.trim() || msg.length > 1000) return json(res, 400, { code: "BAD_INPUT", message: "Message must be 1–1000 characters." });
  if (/\brate\b/i.test(msg)) { res.setHeader("Retry-After", "20"); return json(res, 429, { code: "RATE_LIMITED", message: "Too many requests", retry_after_s: 20 }); }
  const p = plan(msg);
  const t0 = Date.now();
  res.writeHead(200, { "Content-Type": "text/event-stream; charset=utf-8", "Cache-Control": "no-cache", Connection: "keep-alive", "X-Accel-Buffering": "no" });
  await sleep(/slow/.test(msg) ? 2500 : 450);
  send(res, "meta", { request_id: `mock-${t0}`, lang: p.lang, intent: p.intent, dataset_version: VERSION, data_as_of: AS_OF });
  const degraded = !LLM && p.path !== "template";
  // Backend order: meta, cards?, compare?, calc?, sources, status? (a model is about to write), token*, chips, trace, done.
  const lang = p.lang;
  if (p.cards) send(res, "cards", { projects: p.cards.projects.map((x) => card(x, lang)), listings: p.cards.listings });
  if (p.compare) send(res, "compare", p.compare);
  if (p.calc) send(res, "calc", p.calc);
  send(res, "sources", p.sources);
  if (!degraded && p.path !== "template") { send(res, "status", { step: "writing" }); await sleep(/slow/.test(msg) ? 1500 : 300); }
  const words = p.text.split(/(?<=\s)/);
  for (let i = 0; i < words.length; i += 2) {
    send(res, "token", { t: words.slice(i, i + 2).join("") });
    await sleep(degraded ? 5 : 40);
    if (/drop/.test(msg) && i > 6) { res.destroy(); return; }
  }
  send(res, "chips", p.chips);
  const usedModel = !(p.path === "template" || degraded);
  send(res, "trace", {
    intent: p.intent, path: degraded ? "template" : p.path, tool: p.tool,
    retrieved: p.sources.length ? [{ id: "chunk-fx-0012", score: 0.0328 }, { id: "chunk-fx-0007", score: 0.0311 }, { id: "chunk-fx-0031", score: 0.0164 }] : [],
    llm_calls: usedModel ? 1 : 0, model: usedModel ? "mock/free-model:free" : null,
    latency_ms: Date.now() - t0, cache_hit: false, degraded,
    fallback_hops: 0, degraded_reason: degraded ? REASON[LLM_STATE] ?? "no_model" : null,
  });
  send(res, "done", {});
  res.end();
}

// Fixture report shaped like evals/results/latest.json with the C3 keys. Not real results.
const SAMPLE_EVALS = {
  run_at: AS_OF, dataset_version: VERSION, data_as_of: "2026-11-19",
  note: "Fixture report from the mock server, not real results.",
  totals: {
    passed: 9, failed: 2, skipped: 1,
    by_category: {
      reviewer: { passed: 3, failed: 1, skipped: 0, rate: 0.75 },
      factual: { passed: 3, failed: 0, skipped: 1, rate: 1 },
      arabic: { passed: 2, failed: 1, skipped: 0, rate: 0.667 },
      injection: { passed: 1, failed: 0, skipped: 0, rate: 1 },
    },
  },
  targets: {
    factual_rate: { target: 0.9, op: ">=", actual: 1, met: true, n: 3, ci95: [0.44, 1] },
    arabic_rate: { target: 0.85, op: ">=", actual: 0.667, met: false, n: 3, ci95: [0.21, 0.94] },
    ttft_p95_ms: { target: 3000, op: "<=", actual: 82, met: true },
    lighthouse_mobile: { target: 90, op: ">=", actual: null, met: null, note: "measured separately, not by this runner" },
  },
  by_language: {
    en: { passed: 6, failed: 1, rate: 0.857, ci95: [0.49, 0.97] },
    ar: { passed: 3, failed: 1, rate: 0.75, ci95: [0.3, 0.95] },
  },
  latency: { p50: 47, p95: 93, ttft_p50: 46, ttft_p95: 82, n: 12 },
  confusion: { project_info: { project_info: 3 }, location_overview: { location_overview: 2, general: 1 }, injection: { injection: 2 } },
  run_context: { llm_mode: "mock", llm_available: false, judge_used: false },
  live_subset: {
    run_at: AS_OF, llm_calls: 3, n: 3, passed: 2, failed: 1, models_answered: { "mock/free-model:free": 3 },
    cases: [
      { id: "R1", category: "reviewer", lang: "en", status: "passed" },
      { id: "AR03", category: "arabic", lang: "ar", status: "failed", failures: ["fixture: answer mixed scripts"] },
      { id: "I12", category: "injection", lang: "en", status: "passed" },
    ],
  },
  retrieval: {
    before: { bm25: { ar_name: { n: 18, "hit@1": 0.944, mrr: 0.956 } }, hybrid: { ar_name: { n: 18, "hit@1": 0.667, mrr: 0.735 } } },
    after: { bm25: { ar_name: { n: 18, "hit@1": 0.944, mrr: 0.956 } }, hybrid: { ar_name: { n: 18, "hit@1": 0.889, mrr: 0.91 } } },
  },
  cases: [
    { id: "R1", category: "reviewer", lang: "en", status: "passed" },
    { id: "R6", category: "reviewer", lang: "ar", status: "failed", failures: ["fixture: must_cite: no sources"] },
    { id: "F01", category: "factual", lang: "en", status: "passed" },
    { id: "F02", category: "factual", lang: "en", status: "skipped", skip_reason: "fixture: binds to a row not in this dataset" },
    { id: "AR01", category: "arabic", lang: "ar", status: "passed" },
    { id: "AR02", category: "arabic", lang: "ar", status: "failed", failures: ["fixture: transliterated city name not resolved"] },
    { id: "I01", category: "injection", lang: "en", status: "passed" },
  ],
};

function meta() {
  const dgDetail = DG.filter((p) => p.detail === "page").length;
  return {
    dataset_version: VERSION, data_as_of: AS_OF,
    counts: { projects: 30 + DG.length, listings: 1661, pages: 67, chunks: 2389 },
    counts_by_site: { DarGlobal: { projects: DG.length, listings: 0 }, Wasalt: { projects: 30, listings: 1661 } },
    coverage: {
      DarGlobal: { projects: DG.length, detail_pages: dgDetail, prices_published: false },
      Wasalt: { projects: 30, listings: 1661 },
    },
    completeness: { "projects.name_en": 0.4, "projects.price_from_amount": 0.83, "projects.image_urls": 0.94, "listings.area_m2": 1, "listings.baths": 0.12 },
    models: ["mock/free-model:free", "mock/fallback-model:free"],
    llm_available: LLM,
    llm: {
      mode: LLM_STATE === "off" ? "off" : "mock", state: LLM_STATE,
      budget: { used: LLM_STATE === "quota" ? 45 : 7, cap: 45 },
      pool: [
        { model: "mock/free-model:free", state: LLM ? "healthy" : "cooling" },
        { model: "mock/fallback-model:free", state: LLM ? "healthy" : "removed" },
      ],
    },
    ...(CHIPS_ON ? { starter_chips: DG_ON ? STARTER : STARTER_GAP } : {}),
    flags: Object.fromEntries(["FF_FIND_MY_HOME", "FF_MAP", "FF_VOICE", "FF_HANDOFF_BRIEF", "FF_WIDGET_DEMO"].map((f) => [f, FLAGS.has(f)])),
    candidate: process.env.MOCK_CANDIDATE === "1"
      ? { name: "Candidate Name", github: "https://github.com/example", linkedin: "https://www.linkedin.com/in/example", email: "candidate@example.com" }
      : { name: null, github: null, linkedin: null, email: null },
  };
}

function json(res, status, obj) {
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(obj));
}

const TYPES = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2", ".woff": "font/woff", ".json": "application/json", ".txt": "text/plain", ".ico": "image/x-icon" };

async function serveStatic(res, pathname) {
  let p = normalize(decodeURIComponent(pathname)).replace(/^(\.\.[\\/])+/, "");
  let file = join(ROOT, p);
  if (!file.startsWith(ROOT)) return json(res, 403, {});
  try {
    const s = await stat(file);
    if (s.isDirectory()) file = join(file, "index.html");
  } catch {
    if (!extname(file)) file = join(ROOT, p, "index.html");
  }
  try {
    const buf = await readFile(file);
    res.writeHead(200, { "Content-Type": TYPES[extname(file)] || "application/octet-stream" });
    res.end(buf);
  } catch {
    try { const buf = await readFile(join(ROOT, "404.html")); res.writeHead(404, { "Content-Type": TYPES[".html"] }); res.end(buf); }
    catch { res.writeHead(404); res.end("Not found (run the build first)"); }
  }
}

export function handler() {
  return async (req, res) => {
    const url = new URL(req.url, `http://${req.headers.host}`);
    const p = url.pathname;
    try {
      if (p === "/api/chat/stream" && req.method === "POST") {
        let raw = ""; for await (const c of req) raw += c;
        let body = {}; try { body = JSON.parse(raw); } catch { return json(res, 400, { code: "BAD_INPUT", message: "Invalid JSON" }); }
        return chat(req, res, body);
      }
      if (p === "/api/meta") return json(res, 200, meta());
      if (p === "/api/flags") return json(res, 200, meta().flags);
      if (p === "/api/evals") return json(res, 200, process.env.MOCK_EVALS === "empty" ? {} : SAMPLE_EVALS);
      if (p === "/api/projects") {
        const site = url.searchParams.get("site");
        const lang = url.searchParams.get("lang") === "ar" ? "ar" : "en";
        const rows = site && site.toLowerCase() !== "darglobal" ? [] : DG;
        return json(res, 200, rows.map((x) => card(x, lang)));
      }
      if (p.startsWith("/api/projects/")) { const r = DG.find((x) => x.slug === p.split("/").pop()); return r ? json(res, 200, r) : json(res, 404, { code: "NOT_FOUND" }); }
      if (p === "/api/listings") return json(res, 200, [...LISTINGS, ...RENTALS]);
      if (p === "/api/compare" && req.method === "POST") return json(res, 200, plan("compare").compare);
      if (p === "/healthz") return json(res, 200, { ok: true });
      if (p === "/readyz") return json(res, 200, { ok: true, index: "ok", llm: LLM_STATE, xff_hops_seen: 0 });
      return serveStatic(res, p);
    } catch (e) { console.error(e); if (!res.headersSent) json(res, 500, { code: "INTERNAL", message: "mock error" }); }
  };
}

export { meta as mockMeta, plan as mockPlan };

if (process.argv[1] && fileURLToPath(import.meta.url) === normalize(process.argv[1])) {
  createServer(handler()).listen(PORT, () => console.log(`mock on http://localhost:${PORT}  (llm=${LLM_STATE}, darglobal=${DG_ON})`));
}
