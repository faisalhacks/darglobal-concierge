"use client";
import Link from "next/link";
import { useApp } from "@/components/AppContext";
import { PageShell } from "@/components/PageShell";
import { fmtDate, fmtNumber } from "@/lib/format";

function Box({ x, y, w, h = 56, title, sub, accent }: { x: number; y: number; w: number; h?: number; title: string; sub?: string; accent?: boolean }) {
  return (
    <g>
      <rect x={x} y={y} width={w} height={h} rx="10" className={accent ? "d-box d-box--accent" : "d-box"} />
      <text x={x + 14} y={y + (sub ? 24 : h / 2 + 5)} className="d-title">{title}</text>
      {sub && <text x={x + 14} y={y + 42} className="d-sub">{sub}</text>}
    </g>
  );
}
function Arrow({ d }: { d: string }) {
  return <path d={d} className="d-line" markerEnd="url(#arrow)" />;
}

function Diagram() {
  return (
    <figure className="diagram">
      <svg viewBox="0 0 980 420" role="img" aria-labelledby="dg-title dg-desc">
        <title id="dg-title">System architecture</title>
        <desc id="dg-desc">
          Offline, a single-lane scraper collects public pages, which are extracted, validated and stored in SQLite with BM25 and
          embedding indexes. Online, a question passes input guardrails, then a code planner. Clear intents are answered in code;
          low-confidence ones get one model call that returns validated filters. Retrieval fuses BM25 and embeddings. A free model
          writes the prose, with the next free model and a code fallback if it fails. Cards, tables and sources are built in code and
          streamed before the prose.
        </desc>
        <style>{`
          .d-box{fill:var(--surface-2);stroke:var(--border)}
          .d-box--accent{stroke:var(--gold)}
          .d-title{fill:var(--text);font:600 14px var(--sans)}
          .d-sub{fill:var(--text-muted);font:400 13px var(--sans)}
          .d-lane{fill:var(--text-muted);font:500 13px var(--sans)}
          .d-line{fill:none;stroke:var(--text-muted);stroke-width:1.2}
          .d-sep{stroke:var(--border);stroke-dasharray:4 4}
          .d-arrow{fill:var(--text-muted)}
        `}</style>
        <defs>
          <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0 10 5 0 10z" className="d-arrow" />
          </marker>
        </defs>

        <text x="20" y="28" className="d-lane">Offline, at build time</text>
        <Box x={20} y={44} w={190} title="Scraper" sub="one fetch lane, rate-limited" />
        <Box x={250} y={44} w={200} title="Extract and validate" sub="JSON, HTML, pydantic, PII strip" />
        <Box x={490} y={44} w={210} title="SQLite dataset" sub="projects, listings, pages, chunks" accent />
        <Box x={740} y={44} w={220} title="Indexes" sub="BM25 and multilingual embeddings" />
        <Arrow d="M210 72H246" /><Arrow d="M450 72H486" /><Arrow d="M700 72H736" />

        <line x1="20" y1="132" x2="960" y2="132" className="d-sep" />
        <text x="20" y="160" className="d-lane">Online, per question</text>

        <Box x={20} y={176} w={150} title="Browser" sub="POST, then SSE" />
        <Box x={200} y={176} w={170} title="Input guardrails" sub="length, injection screen" />
        <Box x={400} y={176} w={170} title="Code planner" sub="intent and entities" accent />
        <Box x={600} y={176} w={170} title="Read-only tools" sub="search, compare, calc" />
        <Box x={800} y={176} w={160} title="Hybrid retrieval" sub="BM25 + vectors, RRF" />
        <Arrow d="M170 204H196" /><Arrow d="M370 204H396" /><Arrow d="M570 204H596" /><Arrow d="M770 204H796" />
        <Arrow d="M850 132V172" />

        <Box x={600} y={290} w={360} h={56} title="Free model chain" sub="first free model, next free model, then code" />
        <Arrow d="M880 232V286" />
        <Box x={200} y={290} w={370} h={56} title="Output checks and assembly" sub="prices verified, URLs removed; cards built in code" accent />
        <Arrow d="M600 318H574" />
        <Arrow d="M200 318H95V236" />
        <Arrow d="M485 232V286" />
        <text x="490" y="266" className="d-sub">templates skip the model</text>
        <text x="24" y="380" className="d-sub">Stream: meta, cards, compare, calc, sources, prose tokens, chips, trace, done</text>
      </svg>
      <figcaption>Every number on a card or in a table comes from the dataset, not from the model.</figcaption>
    </figure>
  );
}

const FIELD: Record<string, string> = {
  name_en: "English name", name_ar: "Arabic name", city: "City", country: "Country", source_url: "Source page",
  price_from_amount: "Starting price", price_amount: "Price", status: "Status", handover_year: "Handover year",
  lat: "Map position", lng: "Map position", description_en: "English description", description_ar: "Arabic description",
  image_urls: "Photos", area_m2: "Area", beds: "Bedrooms", baths: "Bathrooms", district: "District",
  property_types: "Property types", unit_types: "Unit types", amenities: "Amenities", developer: "Developer",
  brand_partner: "Brand partner", title: "Title", listing_type: "Sale or rent", project_ref: "Linked project",
  area_min_m2: "Smallest unit area", name_any: "Name (English or Arabic)", property_type: "Property type",
};
const GROUP: Record<string, string> = { projects: "Projects", listings: "Listings", pages: "Pages" };
const POOL_STATE: Record<string, string> = { healthy: "answering", cooling: "paused after a rate limit", removed: "removed for today" };
const LLM_STATE: Record<string, string> = {
  ok: "A model is answering.",
  quota: "Today's free request quota is used up; answers are assembled from the dataset until it resets.",
  cooling: "The free models are paused after a rate limit; answers are assembled from the dataset meanwhile.",
  off: "No model is connected; every answer is assembled from the dataset.",
  maintenance: "Maintenance mode; every answer is assembled from the dataset.",
};

function Completeness({ comp }: { comp: [string, number][] }) {
  const groups = new Map<string, { field: string; r: number }[]>();
  for (const [k, r] of comp) {
    const [g, f] = k.includes(".") ? k.split(".", 2) : ["", k];
    if (g === "by_site" || k.split(".").length > 2) continue; // per-site counts and nested groups, not percentages
    const name = FIELD[f] ?? f.replace(/_/g, " ");
    const list = groups.get(g) ?? [];
    if (!list.some((x) => x.field === name)) list.push({ field: name, r });
    groups.set(g, list);
  }
  return (
    <div className="split">
      {[...groups.entries()].map(([g, rows]) => (
        <div key={g || "all"}>
          {g && <h3>{GROUP[g] ?? g}</h3>}
          <table className="data-table data-table--plain">
            <thead><tr><th>Field</th><th className="num">Published on the page</th></tr></thead>
            <tbody>
              {rows.map(({ field, r }) => (
                <tr key={field}><td>{field}</td><td className="num">{Math.round(r * 100)}%</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

export default function HowItWorks() {
  const { meta, lang, llmState } = useApp();
  const comp = meta ? (Object.entries(meta.completeness ?? {}).filter(([, v]) => typeof v === "number") as [string, number][]) : [];
  const dg = meta?.coverage?.DarGlobal ?? (meta?.counts_by_site?.DarGlobal ? { projects: meta.counts_by_site.DarGlobal.projects, detail_pages: 0, prices_published: false } : undefined);
  const ws = meta?.coverage?.Wasalt ?? meta?.counts_by_site?.Wasalt;
  const hasDg = (dg?.projects ?? 0) > 0;
  const pool = meta?.llm?.pool ?? [];
  const budget = meta?.llm?.budget;
  const mock = meta?.llm?.mode === "mock";
  const cap = budget && budget.cap > 0 && budget.cap < 1000 ? budget.cap : 45; // the mock build reports a 1e9 sentinel
  
  return (
    <PageShell englishOnly>
      <div lang="en" dir="ltr">
        <h1>How the concierge answers</h1>
        <p className="lede">
          It reads only what is published on the public sites and decides in code what kind of question it is. Most answers are
          assembled in code from the dataset; a free language model words the reply and, for messy questions, helps read what was asked; the facts, cards and numbers always come from the dataset.
        </p>

        <section>
          <h2>Known limits</h2>
          <ul>
            {hasDg ? (
              <li>
                <strong>DarGlobal pages were read through the owner&apos;s own browser.</strong> darglobal.co.uk blocks automated clients with a
                challenge page, so the scraper stopped there and no challenge was bypassed. Thirteen DarGlobal pages (12 project pages and the projects index) were opened in the
                owner&apos;s own browser at a human pace; the other DarGlobal facts come from public third-party sources (an LSE filing mirror
                and press reports), each labelled by origin. The dataset holds
                {" "}{fmtNumber(dg?.projects ?? 0, "en")} DarGlobal projects: {fmtNumber(dg?.detail_pages ?? 0, "en")} with a full project page, and the
                rest known only by name and location from the projects page. DarGlobal publishes no prices, so every DarGlobal
                card says &ldquo;Price on request&rdquo;.
              </li>
            ) : (
              <li><strong>No DarGlobal data yet.</strong> darglobal.co.uk answers automated clients with a challenge page, so no DarGlobal project page is in this dataset, and DarGlobal questions get a &ldquo;no verified information&rdquo; answer.</li>
            )}
            <li><strong>A small free model budget.</strong> The free model account allows about 50 requests a day, so the app caps itself at 45 model requests a day. Many answers are assembled in code from the dataset (a template or a quoted passage, plus cards and sources), and common questions are answered from a cache built in advance. At the cap, no model is called and every answer is assembled from the dataset.</li>
            <li><strong>Rent periods.</strong> Wasalt listing pages do not state whether a rent is per month or per year, so rent prices are shown with &ldquo;period not published&rdquo;.</li>
          </ul>
        </section>

        <section>
          <h2>Architecture</h2>
          <Diagram />
        </section>

        <section>
          <h2>What happens to one question</h2>
          <ol className="steps">
            <li><div><strong>Screen.</strong> The message is trimmed, capped at 1,000 characters, normalised (full-width forms, hidden characters, spaced-out letters, leetspeak) and checked for injection patterns in English, Arabic and transliteration. Earlier turns of the conversation go through the same screen. A clear attempt gets a fixed reply and never reaches a model. The pattern list is a tripwire; the structural checks below are what hold when a paraphrase slips past it.</div></li>
            <li><div><strong>Existence check.</strong> If the question names a project or a place that is not in the data, the answer opens with a plain sentence saying it is not in the data. It then pivots to a real DarGlobal spotlight project (closest by city, country or brand) with that project&apos;s own card and source, and ends with a link to the official DarGlobal contact page for an advisor. No number or price is given for the name that does not exist.</div></li>
            <li><div><strong>Plan.</strong> A code planner names the intent (a project, a city, a comparison, a calculation, contact, out of scope) and pulls out entities such as city, budget and bedrooms.</div></li>
            <li><div><strong>Understand (only if needed).</strong> Clear questions skip this step. A low-confidence or messy question (a vague message, an unresolved short follow-up) gets one model call that returns JSON filters such as intent, city, budget, bedrooms and project names. Code validates every field and drops values the dataset does not hold; the model never supplies facts. If the call fails, the code plan is used.</div></li>
            <li><div><strong>Fetch.</strong> The planner, or the validated filters, call a read-only tool directly (project, listing or page search, comparison, calculator). The model does not choose tools on this deployment.</div></li>
            <li><div><strong>Retrieve.</strong> BM25 and multilingual embeddings each rank the passages and reciprocal rank fusion merges them. Measured honestly (experiment E1): on exact project-name lookups BM25 alone did better than the fusion (Arabic hit@1 0.94 vs 0.67, English 1.00 vs 0.92), and city queries scored near zero precision for every method. Those queries were the project names themselves, so E1 shows lexical lookup works; it does not yet show that paraphrases land.</div></li>
            <li><div><strong>Write.</strong> A model drafts the prose from the retrieved passages (marked as untrusted text) or from a code-built summary. A message makes at most 2 model calls: understanding plus prose. Greetings, small talk and off-topic requests also use the model for the wording, grounded in a code-built summary, with a fixed code reply as the fallback. If a model sends no first token within 8 seconds, the next free model is tried. No model is called when a cached answer for the same question and dataset version exists, or when the daily cap is reached.</div></li>
            <li><div><strong>Check.</strong> Every price in the prose must appear in the retrieved context; otherwise it becomes &ldquo;not published&rdquo;. URLs and system-prompt fragments are removed.</div></li>
            <li><div><strong>Assemble.</strong> Cards, comparison tables, calculations and sources are built in code and streamed before the prose, so real content appears while the sentences are still being written. Chips and the trace follow.</div></li>
          </ol>
        </section>

        <section>
          <h2>Reading the trace</h2>
          <p>Answers that use sources have a &ldquo;How I found this&rdquo; panel, collapsed to a line with the number of sources and the time taken. Opening it lists plain-language steps. It shows no model names, cache flags or scores; those diagnostics are kept for the evaluation page.</p>
          <dl className="deflist">
            <dt>What it matched</dt><dd>The project name or names it recognised (up to four), or otherwise how it understood the question, such as one project or homes for sale or rent.</dd>
            <dt>Pages read</dt><dd>How many collected pages the answer draws on.</dd>
            <dt>Tool</dt><dd>The read-only tool used, such as listing search or the comparison table, if any.</dd>
            <dt>How it was worded</dt><dd>One of: a language model worded it from the pages; it was worded from the dataset because the model was unavailable; a fixed reply; or built in code from the fact table.</dd>
            <dt>Time</dt><dd>How long the answer took.</dd>
          </dl>
        </section>

        <section>
          <h2>Model chain</h2>
          <p>Primary: free models via OpenRouter, as the brief asks, in the order below. If one sends no first token within 8 seconds, the next free model is tried; if none answers, the answer is assembled from the dataset with the same sources and cards. The app also caps itself at {fmtNumber(cap, "en")} model requests a day.</p>
          {meta ? (
            <>
              <p>
                {mock ? "Model mocked on this local build. The order below is the configured order when a live key is set." : LLM_STATE[llmState ?? "off"]}
                {!mock && budget && budget.cap > 0 ? ` ${fmtNumber(budget.used, "en")} of the app's ${fmtNumber(budget.cap, "en")} daily model requests are used today.` : ""}
              </p>
              {pool.length > 0 && !mock ? (
                <div className="table-wrap">
                  <table className="data-table">
                    <thead><tr><th>Order</th><th>Model</th><th>State now</th></tr></thead>
                    <tbody>
                      {pool.map((m, i) => (
                        <tr key={m.model}><td className="num">{i + 1}</td><td dir="ltr">{m.model}</td><td>{POOL_STATE[m.state] ?? m.state}</td></tr>
                      ))}
                      <tr><td className="num">{pool.length + 1}</td><td>Answer assembled from the dataset</td><td>always available</td></tr>
                    </tbody>
                  </table>
                </div>
              ) : meta.models?.length ? (
                <ol className="plain-list">
                  {meta.models.map((m) => <li key={m} dir="ltr">{m}</li>)}
                  <li>Answer assembled from the dataset</li>
                </ol>
              ) : null}
            </>
          ) : <p className="muted">Model details load from the server.</p>}
          <p>
            Resilience backup: the same Nemotron model through NVIDIA&apos;s own API. It is used only when OpenRouter&apos;s free daily limit or
            availability fails, never first. When it words an answer, "How I found this" says so. It has its own daily cap, and the code-built
            answer is still the last step. All keys stay on the server and are never sent to your browser.
            {meta?.llm?.backup?.enabled ? ` The backup is switched on (${fmtNumber(meta.llm.backup.used, "en")} of ${fmtNumber(meta.llm.backup.cap, "en")} backup requests used today).` : " The backup is switched off on this build."}
          </p>
        </section>

        <section>
          <h2>Calculations</h2>
          <p>
            The calculator shows its formula and is an estimate, not financial advice. Currency conversion uses the official US dollar pegs for
            AED, SAR, QAR, OMR and BHD, and the European Central Bank daily reference rates for EUR, GBP and INR, shown with the ECB date. If no
            reference rate has been fetched, the answer says so and never guesses one. A USD budget in a search is converted to SAR at the
            official peg of 3.75, and the answer says that it did.
          </p>
        </section>

        <section>
          <h2>Guardrails</h2>
          <dl className="deflist">
            <dt>Input</dt><dd>Length cap, control characters stripped, injection screen in English and Arabic.</dd>
            <dt>Context</dt><dd>Retrieved page text is wrapped as untrusted and stripped of HTML.</dd>
            <dt>Tools</dt><dd>Read-only. Nothing writes, sends or browses.</dd>
            <dt>Output</dt><dd>Price check against context; removal of URLs (including defanged ones), e-mail addresses and phone numbers; a canary token and rule-paraphrase check that stops a recitation of the instructions; banned phrases such as guaranteed returns. The rules themselves are not secret: they are the ones described on this page.</dd>
            <dt>Links</dt><dd>Only official DarGlobal and Wasalt domains are rendered as links.</dd>
            <dt>Advice</dt><dd>No investment advice and no return predictions; facts and official contacts instead.</dd>
          </dl>
        </section>

        <section>
          <h2>Corpus</h2>
          {meta ? (
            <>
              <dl className="deflist">
                <dt>Collected</dt><dd>{fmtDate(meta.data_as_of, lang === "ar" ? "en" : lang)}</dd>
                <dt>Dataset version</dt><dd dir="ltr">{meta.dataset_version}</dd>
                <dt>DarGlobal</dt><dd>{hasDg ? `${fmtNumber(dg?.projects ?? 0, "en")} projects, ${fmtNumber(dg?.detail_pages ?? 0, "en")} with a full project page; no prices published` : "No project pages collected"}</dd>
                <dt>Wasalt</dt><dd>{fmtNumber(ws?.projects ?? 0, "en")} projects and {fmtNumber((ws as { listings?: number } | undefined)?.listings ?? 0, "en")} listings</dd>
                <dt>Pages and passages</dt><dd>{fmtNumber(meta.counts.pages, "en")} pages, split into {fmtNumber(meta.counts.chunks, "en")} searchable passages</dd>
              </dl>
              {comp.length > 0 && (
                <>
                  <h3>How complete each field is</h3>
                  <p className="muted">Share of records where the source page publishes the field. Gaps are shown as &ldquo;Not published&rdquo;, never filled in.</p>
                  <Completeness comp={comp} />
                </>
              )}
            </>
          ) : (
            <p className="muted">Corpus details load from the server.</p>
          )}
          <p><Link href="/evals/">See the evaluation results and the Stress-tested showcase</Link></p>
        </section>
      </div>
    </PageShell>
  );
}
