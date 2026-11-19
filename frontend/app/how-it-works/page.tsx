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
          ambiguous ones use one model tool call. Retrieval fuses BM25 and embeddings. A free model writes prose, with a fallback
          model and a template if both fail. Cards, tables, sources and the trace are built in code and streamed to the browser.
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

        <Box x={600} y={290} w={360} h={56} title="Free model chain" sub="primary, then fallback, then a fixed template" />
        <Arrow d="M880 232V286" />
        <Box x={200} y={290} w={370} h={56} title="Output checks and assembly" sub="prices verified, URLs removed; cards built in code" accent />
        <Arrow d="M600 318H574" />
        <Arrow d="M200 318H95V236" />
        <Arrow d="M485 232V286" />
        <text x="490" y="266" className="d-sub">templates skip the model</text>
        <text x="24" y="380" className="d-sub">Stream: meta, tokens, cards, compare, calc, sources, chips, trace, done</text>
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
    if (g === "by_site") continue; // counts, not percentages
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
  return (
    <PageShell englishOnly>
      <div lang="en" dir="ltr">
        <h1>How the concierge answers</h1>
        <p className="lede">
          It reads only what is published on the public sites and decides in code what kind of question it is. Most answers are
          assembled in code from the dataset; a free language model writes the sentences only for open questions.
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
            <li><strong>A small free model budget.</strong> The free model account allows about 50 requests a day in total. Most answers are therefore assembled in code from the dataset (a template or a quoted passage, plus cards and sources), and common questions are answered from a cache built in advance.</li>
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
            <li><div><strong>Existence check.</strong> If the question names a project or a place that is not in the data, the answer says so and attaches no cards or sources, instead of showing nearby real projects that would read as confirmation.</div></li>
            <li><div><strong>Plan.</strong> A code planner names the intent (a project, a city, a comparison, a calculation, contact, out of scope) and pulls out entities such as city, budget and bedrooms.</div></li>
            <li><div><strong>Fetch.</strong> Clear intents call a read-only tool directly. On this deployment the planner also decides the ambiguous ones, so a message never spends a model call on choosing a tool.</div></li>
            <li><div><strong>Retrieve.</strong> BM25 and multilingual embeddings each rank the passages and reciprocal rank fusion merges them. Measured honestly (experiment E1): on exact project-name lookups BM25 alone did better than the fusion (Arabic hit@1 0.94 vs 0.67, English 1.00 vs 0.92), and city queries scored near zero precision for every method. Those queries were the project names themselves, so E1 shows lexical lookup works; it does not yet show that paraphrases land.</div></li>
            <li><div><strong>Write.</strong> One model call drafts the prose from the retrieved passages, which are marked as untrusted text: one call per message at most, and none when a cached answer for the same question and dataset version exists.</div></li>
            <li><div><strong>Check.</strong> Every price in the prose must appear in the retrieved context; otherwise it becomes &ldquo;not published&rdquo;. URLs and system-prompt fragments are removed.</div></li>
            <li><div><strong>Assemble.</strong> Cards, comparison tables, calculations, sources and the date of the data are built in code and streamed after the prose.</div></li>
          </ol>
        </section>

        <section>
          <h2>Reading the trace</h2>
          <p>Each answer has a &ldquo;How I found this&rdquo; panel. It shows exactly what ran.</p>
          <dl className="deflist">
            <dt>Intent</dt><dd>What the planner decided the question was about.</dd>
            <dt>Path</dt><dd>Answered in code, model chose a tool, or fixed template.</dd>
            <dt>Tool</dt><dd>The read-only tool that was called, if any.</dd>
            <dt>Retrieved passages</dt><dd>The passage IDs and their fused scores, highest first.</dd>
            <dt>Model and calls</dt><dd>Which free model wrote the prose, and how many calls it took (0 or 1 on this deployment).</dd>
            <dt>Time and cache</dt><dd>End-to-end time on the server, and whether a cached answer was reused.</dd>
            <dt>No model used</dt><dd>When the answer was assembled from the dataset alone, the Model line says why: the daily quota, a rate limit, a timeout or maintenance.</dd>
          </dl>
        </section>

        <section>
          <h2>Model chain</h2>
          <p>Only free models on OpenRouter are used. If the first does not answer in time, the next is tried; if none answers, the answer is assembled from the dataset with the same sources and cards.</p>
          {meta ? (
            <>
              <p>{LLM_STATE[llmState ?? "off"]}{budget && budget.cap > 0 ? ` ${fmtNumber(budget.used, "en")} of today's ${fmtNumber(budget.cap, "en")} model requests are used.` : ""}</p>
              {pool.length > 0 ? (
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
          <p><Link href="/evals/">See the evaluation results</Link></p>
        </section>
      </div>
    </PageShell>
  );
}
