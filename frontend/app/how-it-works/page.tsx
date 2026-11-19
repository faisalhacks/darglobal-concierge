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
          .d-sub{fill:var(--text-muted);font:400 12px var(--sans)}
          .d-lane{fill:var(--text-muted);font:500 12px var(--sans)}
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

export default function HowItWorks() {
  const { meta, lang } = useApp();
  const comp = meta ? Object.entries(meta.completeness ?? {}) : [];
  return (
    <PageShell>
      <div lang="en" dir="ltr">
        <h1>How the concierge answers</h1>
        <p className="lede">
          It reads only what DarGlobal and Wasalt publish, decides in code what kind of question it is, and lets a free language
          model write the sentences. Everything else on screen is assembled from the dataset.
        </p>

        <section>
          <h2>Architecture</h2>
          <Diagram />
        </section>

        <section>
          <h2>What happens to one question</h2>
          <ol className="steps">
            <li><div><strong>Screen.</strong> The message is trimmed, capped at 1,000 characters and checked for injection patterns in English, Arabic and transliteration. A clear attempt gets a fixed reply and never reaches a model.</div></li>
            <li><div><strong>Plan.</strong> A code planner names the intent (a project, a city, a comparison, a calculation, contact, out of scope) and pulls out entities such as city, budget and bedrooms.</div></li>
            <li><div><strong>Fetch.</strong> Clear intents call a read-only tool directly. Only ambiguous ones let the model pick a tool, at most once.</div></li>
            <li><div><strong>Retrieve.</strong> BM25 and multilingual embeddings each rank the passages; reciprocal rank fusion merges them, so exact names and paraphrases both land.</div></li>
            <li><div><strong>Write.</strong> One model call drafts the prose from the retrieved passages, which are marked as untrusted text. Two calls at most per message.</div></li>
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
            <dt>Model and calls</dt><dd>Which free model wrote the prose, and how many calls it took (0, 1 or 2).</dd>
            <dt>Time and cache</dt><dd>End-to-end time on the server, and whether a cached answer was reused.</dd>
            <dt>Degraded</dt><dd>Shown when no model was available and the answer was assembled from the dataset alone.</dd>
          </dl>
        </section>

        <section>
          <h2>Model chain</h2>
          <p>Only free models on OpenRouter are used. If the first does not answer in time, the next is tried; if none answers, a fixed template is sent with the same sources and cards.</p>
          {meta?.models?.length ? (
            <ol className="steps">
              {meta.models.map((m) => <li key={m}><div><code>{m}</code></div></li>)}
              <li><div>Fixed template with sources and cards</div></li>
            </ol>
          ) : (
            <p className="muted">{meta ? "No model is configured on this deployment, so every answer uses the template path." : "Model details load from the server."}</p>
          )}
          {meta && <p className="muted">Language model available now: {meta.llm_available ? "yes" : "no"}.</p>}
        </section>

        <section>
          <h2>Guardrails</h2>
          <dl className="deflist">
            <dt>Input</dt><dd>Length cap, control characters stripped, injection screen in English and Arabic.</dd>
            <dt>Context</dt><dd>Retrieved page text is wrapped as untrusted and stripped of HTML.</dd>
            <dt>Tools</dt><dd>Read-only. Nothing writes, sends or browses.</dd>
            <dt>Output</dt><dd>Price check against context, URL removal, banned phrases such as guaranteed returns.</dd>
            <dt>Links</dt><dd>Only official DarGlobal and Wasalt domains are rendered as links.</dd>
            <dt>Advice</dt><dd>No investment advice and no return predictions; facts and official contacts instead.</dd>
          </dl>
        </section>

        <section>
          <h2>Corpus</h2>
          {meta ? (
            <>
              <dl className="deflist">
                <dt>Dataset</dt><dd><code>{meta.dataset_version}</code>, collected {fmtDate(meta.data_as_of, lang === "ar" ? "en" : lang)}</dd>
                <dt>Projects</dt><dd>{fmtNumber(meta.counts.projects, "en")}</dd>
                <dt>Listings</dt><dd>{fmtNumber(meta.counts.listings, "en")}</dd>
                <dt>Pages</dt><dd>{fmtNumber(meta.counts.pages, "en")}</dd>
                <dt>Passages</dt><dd>{fmtNumber(meta.counts.chunks, "en")}</dd>
              </dl>
              {comp.length > 0 && (
                <>
                  <h3>Field completeness</h3>
                  <p className="muted">Share of records where the field is published on the source page. Gaps are shown as &ldquo;Not published&rdquo;, never filled in.</p>
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead><tr><th>Field</th><th className="num">Published</th></tr></thead>
                      <tbody>
                        {comp.map(([f, r]) => (
                          <tr key={f}>
                            <td><code>{f}</code></td>
                            <td className="num"><span className="meter" style={{ ["--w" as string]: `${Math.round(r * 100)}%` }} aria-hidden="true" />{Math.round(r * 100)}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
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
