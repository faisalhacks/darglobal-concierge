// Dev-only mock of the binding API/SSE contract. No dependencies.
// Serves frontend/out (static export) plus canned /api/* responses so the UI can be built and
// screenshotted without the backend. ALL DATA BELOW IS FIXTURE DATA, labelled as such; it is not
// scraped and must never be shipped as real content.
//
//   node mock/server.mjs                 -> http://localhost:8787
//   PORT=8787 MOCK_LLM=0 node mock/server.mjs   (simulate no OpenRouter key => degraded)
//   MOCK_EVALS=empty | sample            (default: empty)
//   MOCK_CANDIDATE=1                     (placeholder footer links, not real details)
//   MOCK_FLAGS=FF_WIDGET_DEMO,FF_MAP     (flags to turn on)
//
// Trigger words in a chat message: oman, dubai, riyadh/apartment, auction, compare, down/%,
// python/2+2, ignore/system prompt, guarantee, reykjavik, rate (429), drop (stream cut), slow.
import { createServer } from "node:http";
import { readFile, stat } from "node:fs/promises";
import { extname, join, normalize, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "out");
const PORT = Number(process.env.PORT || 8787);
const LLM = process.env.MOCK_LLM !== "0";
const FLAGS = new Set((process.env.MOCK_FLAGS || "").split(",").filter(Boolean));
const AS_OF = "2026-11-18T09:00:00Z";
const VERSION = "fixture-v0";

const SRC = (site, title, path) => ({
  site, title: `[fixture] ${title}`,
  url: site === "DarGlobal" ? `https://www.darglobal.co.uk/${path}` : `https://wasalt.sa/${path}`,
  scraped_at: AS_OF,
});

const PROJECTS = [
  { id: "fx-p1", slug: "fixture-coastal-a", name: "Fixture Residence A", site: "DarGlobal", city: "Muscat", country: "Oman", price_from: { amount: 1250000, currency: "OMR" }, status: "Off-plan", image_url: null, source_url: "https://www.darglobal.co.uk/projects/fixture-a" },
  { id: "fx-p2", slug: "fixture-coastal-b", name: "Fixture Residence B", site: "DarGlobal", city: "Muscat", country: "Oman", price_from: null, status: null, image_url: "https://example.invalid/broken.jpg", source_url: "https://www.darglobal.co.uk/projects/fixture-b" },
  { id: "fx-p3", slug: "fixture-tower-c", name: "Fixture Tower C", site: "DarGlobal", city: "Dubai", country: "United Arab Emirates", price_from: { amount: 2400000, currency: "AED" }, status: "Ready", image_url: null, source_url: "https://www.darglobal.co.uk/projects/fixture-c" },
];
const LISTINGS = [
  { id: "fx-l1", title: "Fixture listing: 2-bed apartment", site: "Wasalt", listing_type: "buy", price: { amount: 1180000, currency: "SAR" }, beds: 2, baths: 2, area_m2: 142, district: "Fixture district", city: "Riyadh", image_url: null, source_url: "https://wasalt.sa/listing/fixture-1" },
  { id: "fx-l2", title: "Fixture listing: 3-bed apartment", site: "Wasalt", listing_type: "rent", price: { amount: 85000, currency: "SAR" }, beds: 3, baths: null, area_m2: null, district: null, city: "Riyadh", image_url: null, source_url: "https://wasalt.sa/listing/fixture-2" },
];

const CHIPS_EN = [
  { label: "Payment plans", message: "What payment plans are published?" },
  { label: "Compare two projects", message: "Compare Fixture Residence A and Fixture Tower C" },
  { label: "Contact sales", message: "How do I contact sales?" },
];
const CHIPS_AR = [
  { label: "خطط الدفع", message: "ما هي خطط الدفع المنشورة؟" },
  { label: "قارن بين مشروعين", message: "قارن بين المشروعين" },
  { label: "التواصل مع المبيعات", message: "كيف أتواصل مع المبيعات؟" },
];

const isAr = (s) => /[؀-ۿ]/.test(s);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function plan(msg) {
  const m = msg.toLowerCase();
  const ar = isAr(msg);
  const L = ar ? "ar" : "en";
  const base = { lang: L, chips: ar ? CHIPS_AR : CHIPS_EN, sources: [], intent: "general", path: "code", tool: null };
  if (/ignore|system prompt|تجاهل|موجّه النظام/.test(m)) return { ...base, intent: "injection", path: "template", text: ar ? "لا أستطيع مشاركة تعليماتي الداخلية. يسعدني مساعدتك في أسئلة عن مشاريع دار جلوبال ومنازل وصلت." : "I can't share my internal instructions. I'm glad to help with questions about DarGlobal projects and Wasalt homes." };
  if (/python|2\s*\+\s*2|code/.test(m)) return { ...base, intent: "off_topic", path: "template", text: ar ? "أنا متخصص في عقارات دار جلوبال ووصلت فقط. جرّب أحد الاقتراحات أدناه." : "I only cover DarGlobal and Wasalt property. Try one of the suggestions below." };
  if (/guarantee|return on|ضمان|عائد/.test(m)) return { ...base, intent: "advice", path: "template", text: ar ? "لا أستطيع تقديم نصائح استثمارية أو توقع العوائد. يمكنني مشاركة الحقائق المنشورة وروابط التواصل الرسمية." : "I can't give investment advice or predict returns. I can share published facts and the official sales contacts." };
  if (/reykjavik|ريكيافيك/.test(m)) return { ...base, intent: "no_data", path: "template", text: ar ? "لا توجد لديّ معلومات موثّقة عن هذا المشروع في البيانات المنشورة." : "I have no verified information about that project in the published data. I won't guess a price." };
  if (/compare|قارن/.test(m)) return { ...base, intent: "compare", tool: "compare_projects", text: ar ? "هذه مقارنة بين المشروعين من البيانات المنشورة." : "Here is how the two compare, using only what each page publishes.", compare: {
    columns: [{ id: "fx-p1", name: "Fixture Residence A", site: "DarGlobal" }, { id: "fx-p3", name: "Fixture Tower C", site: "DarGlobal" }],
    rows: [
      { label: ar ? "المدينة" : "City", values: ["Muscat", "Dubai"] },
      { label: ar ? "السعر يبدأ من" : "Price from", values: ["OMR 1,250,000", "AED 2,400,000"] },
      { label: ar ? "التسليم" : "Handover", values: [null, "Ready"] },
      { label: ar ? "خطة الدفع" : "Payment plan", values: ["[fixture] 60/40", null] },
      { label: ar ? "العلامة" : "Brand partner", values: [null, null] },
    ],
    sources: [SRC("DarGlobal", "Fixture Residence A", "projects/fixture-a"), SRC("DarGlobal", "Fixture Tower C", "projects/fixture-c")],
  }, sources: [SRC("DarGlobal", "Fixture Residence A", "projects/fixture-a"), SRC("DarGlobal", "Fixture Tower C", "projects/fixture-c")] };
  if (/down|%|دفعة/.test(m)) return { ...base, intent: "calculate", tool: "calculator", text: ar ? "الحساب أدناه تقديري." : "Here is the arithmetic. It is an estimate.", calc: {
    kind: "down_payment", inputs: { price: "SAR 2,000,000", percent: "20%" }, result: { down_payment: "SAR 400,000", remaining: "SAR 1,600,000" },
    formula: "down_payment = price × percent / 100", disclaimer: ar ? "تقدير وليس نصيحة مالية." : "Estimate, not financial advice." } };
  if (/riyadh|apartment|الرياض|شقق/.test(m)) return { ...base, intent: "search_listings", tool: "search_listings", text: ar ? "وجدت عرضين في الرياض ضمن البيانات التجريبية." : "Two fixture listings in Riyadh match.\n\n- One for sale, one for rent\n- Bathrooms and area are not published for the second", cards: { projects: [], listings: LISTINGS }, sources: [SRC("Wasalt", "Fixture listing 1", "listing/fixture-1"), SRC("Wasalt", "Fixture listing 2", "listing/fixture-2")] };
  if (/oman|muscat|عمان|عُمان|مسقط/.test(m)) return { ...base, intent: "projects_by_location", tool: "search_projects", text: ar ? "لدى دار جلوبال مشروعان تجريبيان في مسقط، عُمان.\n\n- السكن A يبدأ من 1,250,000 ريال عماني\n- السعر غير منشور للسكن B" : "There are two fixture projects in Muscat, Oman.\n\n- Fixture Residence A starts from OMR 1,250,000\n- Fixture Residence B does not publish a price", cards: { projects: PROJECTS.slice(0, 2), listings: [] }, sources: [SRC("DarGlobal", "Fixture Residence A", "projects/fixture-a"), SRC("DarGlobal", "Fixture Residence B", "projects/fixture-b")] };
  if (/dubai|branded|دبي|العلامات/.test(m)) return { ...base, intent: "projects_by_location", tool: "search_projects", text: ar ? "مشروع تجريبي واحد في دبي." : "One fixture project is in Dubai: Fixture Tower C, ready, from AED 2,400,000.", cards: { projects: [PROJECTS[2]], listings: [] }, sources: [SRC("DarGlobal", "Fixture Tower C", "projects/fixture-c")] };
  if (/auction|مزاد/.test(m)) return { ...base, intent: "faq", path: LLM ? "llm_tool" : "template", tool: "search_pages", text: ar ? "هذا نص تجريبي يصف المزادات. ستأتي الإجابة الحقيقية من صفحات وصلت المنشورة." : "This is fixture text standing in for an answer about Wasalt auctions. The real answer will come from Wasalt's published pages, with the steps they describe.", sources: [SRC("Wasalt", "Auctions", "auctions")] };
  return { ...base, intent: "general", tool: "search_pages", text: ar ? "هذه إجابة تجريبية من الخادم الوهمي." : "This is a fixture answer from the mock server. Ask about Oman, Dubai, Riyadh, auctions, a comparison or a down payment to see each component.", sources: [SRC("DarGlobal", "About", "about")] };
}

function send(res, event, data) { res.write(`event: ${event}\ndata: ${JSON.stringify(data)}\n\n`); }

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
  const words = p.text.split(/(?<=\s)/);
  for (let i = 0; i < words.length; i += 2) {
    send(res, "token", { t: words.slice(i, i + 2).join("") });
    await sleep(degraded ? 5 : 40);
    if (/drop/.test(msg) && i > 6) { res.destroy(); return; }
  }
  if (p.cards) send(res, "cards", p.cards);
  if (p.compare) send(res, "compare", p.compare);
  if (p.calc) send(res, "calc", p.calc);
  send(res, "sources", p.sources);
  send(res, "chips", p.chips);
  send(res, "trace", {
    intent: p.intent, path: degraded ? "template" : p.path, tool: p.tool,
    retrieved: p.sources.length ? [{ id: "chunk-fx-0012", score: 0.0328 }, { id: "chunk-fx-0007", score: 0.0311 }, { id: "chunk-fx-0031", score: 0.0164 }] : [],
    llm_calls: p.path === "template" || degraded ? 0 : 1, model: p.path === "template" || degraded ? null : "mock/free-model:free",
    latency_ms: Date.now() - t0, cache_hit: false, degraded,
  });
  send(res, "done", {});
  res.end();
}

const SAMPLE_EVALS = {
  run_id: "fixture-run", generated_at: AS_OF, dataset_version: VERSION, note: "Fixture report from the mock server, not real results.",
  scores: {
    reviewer_set: { score: 1, target: 1, n: 7 }, factual: { score: 0.9, target: 0.9, n: 30 }, citations: { score: 1, target: 1, n: 30 },
    arabic: { score: 0.8, target: 0.85, n: 20 }, injection: { score: 1, target: 1, n: 12 }, false_refusals: { score: 0.04, target: 0.05, n: 8, passed: true },
  },
  failures: [{ id: "ar-07", category: "arabic", reason: "fixture: transliterated city name not resolved" }],
};

function meta() {
  return {
    dataset_version: VERSION, data_as_of: AS_OF,
    counts: { projects: 3, listings: 2, pages: 12, chunks: 64 },
    completeness: { price_from: 0.67, status: 0.67, image_url: 0.33, handover: 0.33 },
    models: LLM ? ["mock/free-model:free", "mock/fallback-model:free"] : [],
    llm_available: LLM,
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
    catch { res.writeHead(404); res.end("Not found (run pnpm build first)"); }
  }
}

createServer(async (req, res) => {
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
    if (p === "/api/evals") return json(res, 200, process.env.MOCK_EVALS === "sample" ? SAMPLE_EVALS : {});
    if (p === "/api/projects") return json(res, 200, PROJECTS);
    if (p.startsWith("/api/projects/")) { const r = PROJECTS.find((x) => x.slug === p.split("/").pop()); return r ? json(res, 200, r) : json(res, 404, { code: "NOT_FOUND" }); }
    if (p === "/api/listings") return json(res, 200, LISTINGS);
    if (p === "/api/compare" && req.method === "POST") return json(res, 200, plan("compare").compare);
    if (p === "/healthz" || p === "/readyz") return json(res, 200, { ok: true });
    return serveStatic(res, p);
  } catch (e) { console.error(e); if (!res.headersSent) json(res, 500, { code: "INTERNAL", message: "mock error" }); }
}).listen(PORT, () => console.log(`mock on http://localhost:${PORT}  (llm=${LLM})`));
