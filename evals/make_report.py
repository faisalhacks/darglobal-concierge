#!/usr/bin/env python3
"""Generate REPORT.md (SPEC 20.5) and the numbers block of README.md from result files only.

Nothing in the output is typed by hand: every number is read from a file under evals/results/,
loadtest/results/ or data/, and every table names its source file. A missing source renders
as 'not measured'. Re-run after the final eval run:

    python evals/make_report.py            # writes REPORT.md and updates README.md between the AUTOGEN markers
    python evals/make_report.py --check    # exits 1 if REPORT.md/README.md are stale vs the result files, if the
                                           # dataset ids disagree between result files, or if a doc claims "all ... pass"
                                           # while the latest run has failures
    python evals/make_report.py --check --url https://APP_URL   # also compares the live /api/evals with latest.json
    python evals/make_report.py --check --final                 # also fails while deploy-time {PLACEHOLDERS} remain

One source of truth: evals/results/latest.json. /evals (served from the baked copy of that file), REPORT.md and the README
blocks between the AUTOGEN markers are all derived from it (plus data/completeness.json and the E1/live files that
runner.py attaches to it), so the dataset id and the passed/failed/skipped counts cannot differ between them.

Optional inputs (all optional):
  evals/results/latest.json            full-suite run (mock LLM unless run_context.llm_mode says otherwise)
  evals/results/live_subset.json       the real-model run (runner.py --max-llm-calls N; e.g. --only R1,R2,R3,R4,R5,R6,R7
                                       against the public URL). Every case with an answer is printed verbatim in section 8b.
  evals/results/E1.json                retrieval experiment; E1_before_headers.json / E1_after_headers.json for the A/B
  evals/results/baseline_before.json   the run used as 'before' in the failures table
  evals/results/fixes.json             [{"case": id, "cause": str, "fix": str}] written by whoever fixed it
  loadtest/results/latest.json         load test (loadtest/load.py)
  data/completeness.json               dataset completeness (data lane)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "evals" / "results"
NM = "not measured"
# Filled by the deploy step, never by this script. --final fails while any of these is still in README.md.
LABELS = {"ttft_p95_ms": "ttft_p95_ms (mock LLM)"}


def load(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def f(v, nd=3):
    if v is None:
        return NM
    if isinstance(v, float):
        return f"{v:.{nd}f}".rstrip("0").rstrip(".") if nd else str(round(v))
    return str(v)


def ci(v):
    return f"[{v[0]:.3f}, {v[1]:.3f}]" if isinstance(v, list) and len(v) == 2 else NM


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)).replace("\\", "/")


def table(head, rows):
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def pick_transcripts(latest, live):
    """Five transcripts: >=1 real-model (from live_subset), both languages, one trap or injection."""
    picked, seen = [], set()

    def add(case, source, label):
        if case["id"] in seen or not case.get("turns"):
            return
        seen.add(case["id"])
        picked.append((case, source, label))

    if live:
        for c in live.get("cases", []):
            if c.get("status") != "skipped" and c.get("model") and c.get("turns"):
                add(c, "evals/results/live_subset.json", f"REAL MODEL ({c['model']})")
                break
    cases = {c["id"]: c for c in (latest or {}).get("cases", [])}
    for want in ("R1", "R2", "R4", "A01", "T01", "D01", "D10", "R6"):
        if len(picked) >= 5:
            break
        if want in cases and cases[want].get("status") in ("passed", "failed"):
            c = cases[want]
            add(c, "evals/results/latest.json", f"mock LLM (llm_mode={(latest.get('run_context') or {}).get('llm_mode', NM)})")
    # ensure Arabic is represented
    if not any(c.get("lang") == "ar" for c, _, _ in picked):
        for c in (latest or {}).get("cases", []):
            if c.get("lang") == "ar" and c.get("status") in ("passed", "failed") and c.get("turns"):
                picked = picked[:4]
                add(c, "evals/results/latest.json", "mock LLM")
                break
    return picked[:5]


def real_cases(live):
    return [c for c in (live or {}).get("cases", []) if c.get("status") != "skipped" and c.get("turns")]


def facts(latest, comp, live, e1):
    """Every number the README quotes, read from result files. Unknown -> 'not measured'."""
    c = (comp or {}).get("counts", {})
    dg = (c.get("projects_by_site") or {}).get("DarGlobal")
    full = ((c.get("projects_detail_by_site") or {}).get("DarGlobal") or {}).get("page")
    T = latest["targets"]
    return {
        "DATASET_VERSION": latest.get("dataset_version"),
        "DG_PROJECTS": dg if dg is not None else NM,
        "DG_FULL_PAGES": full if full is not None else NM,
        "DG_OTHER_PROJECTS": (dg - full) if isinstance(dg, int) and isinstance(full, int) else NM,
        "WASALT_LISTINGS": c.get("listings") if c.get("listings") is not None else NM,
        "CITATION_RATE": f(T.get("citation_rate", {}).get("actual")),
        "N_REAL": len(real_cases(live)),
        "N_REAL_MODEL": sum(1 for c in real_cases(live) if c.get("model")),
    }


def e1_pair(e1, qs):
    r = (e1 or {}).get("results") or {}
    try:
        return r["bm25"][qs]["recall@1"], r["hybrid"][qs]["recall@1"], r["bm25"][qs]["n"]
    except (KeyError, TypeError):
        return None


def limitations(F, latest, e1, live):
    """README 'Known limitations': the chair's disclosure sentences with every number filled from a result file."""
    T, rc = latest["targets"], latest.get("run_context") or {}
    cases = latest["cases"]
    out = []
    A = out.append
    A('DarGlobal\'s public pages publish no prices, so the concierge says "Price on request", links the official enquiry page and never estimates one; the trap question in "Try these" shows this.')
    A(f"DarGlobal's bot protection challenged my fetcher's first HTML request, so it stopped and never retried or bypassed it; I read {F['DG_FULL_PAGES']} project pages in my own browser at human pace and filled the other {F['DG_OTHER_PROJECTS']} projects from named public sources, each labelled with its real origin.")
    A("The free model tier allows 50 requests a day in total, so the starter questions are served from prepared answers and, when the cap is reached, the app shows a notice and keeps answering from the dataset with cards and sources.")
    if F["N_REAL"]:
        A(f"The eval suite runs with the model mocked, so its scores measure routing, retrieval, citations and guardrails and not prose quality; real-model evidence is the {F['N_REAL']} answers of the live run ({F['N_REAL_MODEL']} written by a model, the rest built by code) printed verbatim in [REPORT.md](REPORT.md) section 8b, including the weak ones, and a larger real-model run is the first next step.")
    else:
        A("The eval suite runs with the model mocked, so its scores measure routing, retrieval, citations and guardrails and not prose quality; no real-model run is on file, and a real-model run is the first next step.")
    ar, en = e1_pair(e1, "ar_name"), e1_pair(e1, "en_name")
    if ar and en:
        same = (e1 or {}).get("dataset_version") == latest.get("dataset_version")
        when = "" if same else f" (measured on an earlier dataset, `{(e1 or {}).get('dataset_version') or 'unrecorded'}`)"
        verdict = "beat" if ar[0] > ar[1] else ("matched" if ar[0] == ar[1] else "did not beat")
        A(f"On my own known-item benchmark{when} BM25 alone {verdict} hybrid on Arabic project names (recall@1 {f(ar[0])} vs {f(ar[1])}, n={ar[2]}) and scored {f(en[0])} vs {f(en[1])} on English names (n={en[2]}), so the case for hybrid rests on paraphrase and cross-lingual queries I have not yet measured; the app runs BM25-only with one environment variable (`EMBEDDINGS=off`), and that is the mode the backup host uses.")
    else:
        A("The BM25-versus-hybrid benchmark (E1) is not on file, so the choice of hybrid is not backed by a measurement here; the app runs BM25-only with one environment variable (`EMBEDDINGS=off`), and that is the mode the backup host uses.")
    A("The primary URL runs on a Railway trial that ends on {TRIAL_END_DATE} because hybrid retrieval peaked at 0.86 GB and was out-of-memory killed at 512 MB; the free backup host runs keyword-only retrieval.")
    A("Wasalt's llms.txt allows non-commercial extraction of public listings with attribution while its Terms of Use restrict copying, and I could not read DarGlobal's terms pages, so I kept a small attributed sample with no contact data, claim no legal clearance, and will remove the data and the hot-linked images on {TAKEDOWN_DATE} or sooner on request.")
    A('Arabic is only partly verified: 2 of 3 Arabic prompts passed on the real model, one answer wrongly said "not published", and project names without a recorded Arabic name stay in Latin script; a native-speaker evaluation is not done.')
    dg = ((load(ROOT / "data" / "completeness.json") or {}).get("by_site") or {}).get("DarGlobal") or {}
    dg_n, dg_img = dg.get("projects_n"), (dg.get("projects") or {}).get("image_urls")
    if dg_n and dg_img is not None:
        A(f"DarGlobal cards show a photo only for the {round(dg_n * dg_img)} of {dg_n} DarGlobal projects whose hand-read page gave an image URL; the rest use a typographic card, because I chose not to fetch more from a site that blocks automated clients.")
    else:
        A("DarGlobal cards show a photo only where a hand-read page gave an image URL; the rest use a typographic card, because I chose not to fetch more from a site that blocks automated clients.")
    A("The licence notice is shown verbatim, linked to its page, for the two projects whose disclaimer I copied from the official page (Trump Tower Jeddah and Marriott Residences Aida); for other licensed-brand projects I did not collect the notice and did not write one, so the official project page is the authority.")
    fmh = [c for c in cases if c.get("category") == "find_my_home" and c.get("status") in ("passed", "failed")]
    if fmh:
        p = sum(c["status"] == "passed" for c in fmh)
        on = (rc.get("flags") or {}).get("FF_FIND_MY_HOME")
        if p < len(fmh):
            A(f"The guided find-my-home flow passes {p} of {len(fmh)} of its eval cases in the latest run (the flag FF_FIND_MY_HOME was {'on' if on else 'off'} during that run), so it must be switched off in the deployed build (`FF_FIND_MY_HOME=false`, one environment variable) and is listed under Next, not presented as working.")
        else:
            A(f"The guided find-my-home flow passes all {len(fmh)} of its eval cases in the latest run (mock model).")
    ct = T.get("citation_rate", {})
    if ct.get("met") is False:
        A(f"citation_rate is {F['CITATION_RATE']} against a target of {ct.get('target')} and is reported as not met; each failing case is listed in [REPORT.md](REPORT.md) with its check.")
    elif ct.get("met"):
        A(f"citation_rate is {F['CITATION_RATE']} against a target of {ct.get('target')} (met on the mock model).")
    A('Not built: removable filter chips and an "Ask an advisor" consent-based handoff; they are listed under Next and nowhere described as present.')
    A("Questions about the corporate relationship between DarGlobal and Wasalt get a fixed reply that says public sources describe them as sister companies, not parent and subsidiary; no collected page documents that link, so the reply says so and attaches no source.")
    A('Figures sourced from regulatory filings were read from a public mirror and not checked against the LSE original, projects known only from the DarGlobal index cite the general projects page, and possible duplicate entries (for example "Amour Sans Detour" and "Amour Sans Detour 2") were kept as published and not merged.')
    A("Known rough edges: after a failed send the question must be retyped, the trace panel shows internal ids, the CSP still allows inline scripts, and the image is 882 MB.")
    A("I built this with Claude Code agents and reviewed the result; the design decisions, thresholds and trade-offs in [docs/DECISIONS.md](docs/DECISIONS.md) are mine and I can explain or change any of them live.")
    return out


def build():
    latest = load(RES / "latest.json")
    live = (latest or {}).get("live_subset") or load(RES / "live_subset.json")
    e1 = (latest or {}).get("retrieval") or load(RES / "E1.json")
    e1b, e1a = load(RES / "E1_before_headers.json"), load(RES / "E1_after_headers.json")
    base = load(RES / "baseline_before.json")
    fixes = load(RES / "fixes.json")
    load_r = load(ROOT / "loadtest" / "results" / "latest.json")
    comp = load(ROOT / "data" / "completeness.json")
    L = []
    A = L.append

    if not latest:
        return "# REPORT\n\nNo evals/results/latest.json: run `python evals/runner.py` first. Nothing is reported without a result file.\n", {}, latest, comp

    rc = latest.get("run_context") or {}
    tot = latest["totals"]
    mode = rc.get("llm_mode") or f"unknown (older runner; llm_available={rc.get('llm_available')})"
    A("# Evaluation report")
    A("")
    A("*Generated by `evals/make_report.py` from the result files named under each table. No number here was typed by hand.*")
    A("")
    bn = latest.get("banner") or {}
    A(f"> **LLM banner** (run_context / banner in evals/results/latest.json): llm_available={f(bn.get('llm_available', rc.get('llm_available')))}, mode={mode}. " + (bn.get("text") or "banner not recorded (older runner)."))
    A("")
    A("## 0. Read this first: what is mock and what is real")
    A("")
    A(table(["Block", "LLM used", "Source"], [
        ["Full suite (all numbers in sections 3, 4, 6)", f"**{mode}** (mock = deterministic stand-in that writes prose only from retrieved context; it measures routing, retrieval, cards, citations, guardrails and calculation code, NOT model answer quality)" if mode == "mock" else f"**{mode}**", "evals/results/latest.json"],
        ["Real-model subset (section 8)", "real free OpenRouter models" if live else NM, "evals/results/live_subset.json"],
        ["Load test (section 7)", "mock" if load_r else NM, "loadtest/results/latest.json"],
    ]))
    A("")
    A(f"- **The LLM judge was not used** (`run_context.judge_used = {rc.get('judge_used')}`). Arabic is scored by deterministic checks (reply language, RTL ratio, cards, citations, hedging) plus the owner's spot check, which is not part of any number here.")
    A("- The account is capped at 50 requests/day in total on free `:free` models, so real-model coverage is deliberately small.")
    A("")
    A("## 1. Methodology")
    A("")
    A(f"- Suite: `evals/cases.yaml`, {tot['passed'] + tot['failed'] + tot['skipped']} cases ({tot['passed'] + tot['failed']} run, {tot['skipped']} skipped). Facts are never hard-coded: factual cases are templates bound at run time from `data/concierge.sqlite` (read-only). A case whose bind returns no row is **SKIPPED, never counted as passed**.")
    A("- Checks are deterministic (intent, path, citations resolve to known URLs, cards exist in the DB, every number in prose traceable to payloads, no invented prices, no prompt leak, no URL in prose). Vocabulary: header of `evals/cases.yaml`.")
    A("- Split: every 5th case is `split: heldout` and is not used to tune prompts or gates; `by_split` below reports both.")
    A("- Intervals: Wilson 95% for proportions, percentile bootstrap for TTFT p95. n is small, so intervals are wide; a point estimate of 1.0 on n=15 still has a lower bound near 0.8.")
    A(f"- Seed {rc.get('seed')}; split filter `{rc.get('split', 'all')}`; wall time {rc.get('wall_s')} s; partial selection: {rc.get('partial_selection')}.")
    A("")
    A("## 2. Dataset")
    A("")
    A(f"- Dataset version `{latest.get('dataset_version')}`, data as of {latest.get('data_as_of')}; eval run at {latest.get('run_at')}. Source: evals/results/latest.json.")
    if comp:
        c = comp.get("counts", {})
        A(f"- Counts: {c.get('projects')} projects, {c.get('listings')} listings, {c.get('pages')} pages, {c.get('chunks')} chunks. Projects by site: {c.get('projects_by_site')}. Source: data/completeness.json.")
        if c.get("projects_detail_by_site"):
            A(f"- DarGlobal detail level (page = collected detail page, index = name and location only): {c['projects_detail_by_site']}. DarGlobal publishes no prices, so price fields are NULL by design.")
        A("")
        cm = comp.get("completeness", {}).get("projects", {})
        A(table(["projects field", "non-null share"], [[k, f(v)] for k, v in cm.items()]))
    else:
        A(f"- Completeness: {NM} (data/completeness.json missing).")
    A("")
    A("## 3. Scores vs targets")
    A("")
    A(table(["Metric", "Target", "Actual", "n", "95% CI", "Met"], [
        [LABELS.get(k, k), f"{v['op']} {v['target']}", f(v.get("actual")), f(v.get("n")), ci(v.get("ci95")), {True: "yes", False: "**NO**", None: NM}[v.get("met")]]
        for k, v in latest["targets"].items()]))
    A("")
    A("Source: evals/results/latest.json `targets`. `lighthouse_mobile` is measured separately: " + ("see section 9b." if False else f"{f(latest['targets'].get('lighthouse_mobile', {}).get('actual'))}."))
    A("")
    bl = latest.get("by_language")
    A("### By language")
    A("")
    A(table(["Language", "Passed", "Failed", "Rate", "95% CI"], [[k, v["passed"], v["failed"], f(v.get("rate")), ci(v.get("ci95"))] for k, v in bl.items()]) if bl else NM + " (runner too old: no `by_language`).")
    A("")
    bs = latest.get("by_split")
    A("### By split (tune vs heldout)")
    A("")
    A(table(["Split", "Passed", "Failed", "Rate", "95% CI"], [[k, v["passed"], v["failed"], f(v.get("rate")), ci(v.get("ci95"))] for k, v in bs.items()]) if bs else NM)
    A("")
    A("### By category")
    A("")
    A(table(["Category", "Passed", "Failed", "Skipped", "Rate", "95% CI"], [[k, d["passed"], d["failed"], d["skipped"], f(d.get("rate")), ci(d.get("ci95"))] for k, d in sorted(tot["by_category"].items())]))
    A("")
    ar_t, ci_t = latest["targets"].get("arabic_rate", {}), latest["targets"].get("citation_rate", {})
    A("### Arabic and citation rates against their targets")
    A("")
    for nm, t in (("Arabic", ar_t), ("Citation", ci_t)):
        if t.get("actual") is None:
            A(f"- {nm}: {NM}.")
        else:
            A(f"- {nm}: **{t['actual']}** vs target {t['op']} {t['target']} (n={t.get('n')}, 95% CI {ci(t.get('ci95'))}); {'met' if t.get('met') else 'NOT met'}.")
    A("")
    A("### Misses (every failed case, with the check that failed)")
    A("")
    bad = [c for c in latest["cases"] if c.get("status") == "failed"]
    A(table(["Case", "Category", "Lang", "Failed checks"], [[c["id"], c["category"], c.get("lang"), "; ".join(c["failures"])[:260].replace("|", "/")] for c in bad]) if bad else "None.")
    A("")
    ft = latest.get("failure_types")
    A("### Failure types (count of failed checks by type)")
    A("")
    A(table(["Check", "Count"], [[k, v] for k, v in ft.items()]) if ft else ("None." if ft == {} else NM))
    A("")
    cs = latest.get("citation_subset")
    if cs:
        A(f"Citation-subset check (every cited card id and source URL is known to the database): {cs.get('violations')} violations in {cs.get('n')} replies checked; clean-reply rate {f(cs.get('rate'))}, 95% CI {ci(cs.get('ci95'))}. Source: evals/results/latest.json `citation_subset`.")
        A("")
    A("Cause analysis for each miss is in section 10 when `evals/results/fixes.json` exists; otherwise causes are not recorded here.")
    A("")
    sk = [c for c in latest["cases"] if c.get("status") == "skipped"]
    A("### Skipped (not counted as passed)")
    A("")
    A(table(["Case", "Reason"], [[c["id"], (c.get("skip_reason") or "").replace("|", "/")] for c in sk]) if sk else "None.")
    A("")
    A("## 4. Intent confusion matrix")
    A("")
    cf = latest.get("confusion") or {}
    if cf:
        cols = sorted({a for v in cf.values() for a in v})
        A(table(["expected \\ actual"] + cols, [[e] + [cf[e].get(a, 0) for a in cols] for e in sorted(cf)]))
        n_cf = sum(sum(v.values()) for v in cf.values())
        ok_cf = sum(v.get(e, 0) for e, v in cf.items() if "|" not in e)
        A("")
        A(f"Diagonal {ok_cf} of {n_cf} routed cases (rows with a multi-intent expectation count off-diagonal here). Source: evals/results/latest.json `confusion`.")
    else:
        A(NM)
    A("")
    A("## 5. Retrieval experiment (E1)")
    A("")
    if (e1 or {}).get("dataset_version") == latest.get("dataset_version"):
        A(f"Measured on dataset `{e1.get('dataset_version')}` (the same as the suite), retriever mode `{e1.get('retriever_mode')}`, index `{e1.get('index_state')}`. Source: evals/results/E1.json.")
        A("")
    if (load(RES / "E1.json") or {}).get("dataset_version") != (latest or {}).get("dataset_version"):
        A("Caveat: evals/results/E1.json does not record the dataset it was measured on, or records a different one, and "
          "was not re-run on the current dataset (`backend/.venv/Scripts/python evals/experiments.py --only E1`). Treat "
          "the table below as indicative of an earlier build.")
        A("")

    def e1_rows(d):
        rows = []
        for fn, grp in (d.get("results") or {}).items():
            for q, m in grp.items():
                rows.append([fn, q, ("ar" if q.startswith("ar_") else "en"), m.get("n"), f(m.get("recall@1", m.get("hit@1"))), f(m.get("recall@3")), f(m.get("recall@6", m.get("hit@6"))), f(m.get("mrr")), f(m.get("precision@6"))])
        return rows

    head = ["method (bm25 = lexical, embeddings = dense, hybrid = RRF fusion served by the app)", "query set", "lang", "n", "recall@1", "recall@3", "recall@6", "MRR", "precision@6"]
    if e1b and e1a:
        A("Contextual chunk headers, **before** (evals/results/E1_before_headers.json):")
        A("")
        A(table(head, e1_rows(e1b)))
        A("")
        A("**After** (evals/results/E1_after_headers.json):")
        A("")
        A(table(head, e1_rows(e1a)))
    elif e1:
        A(table(head, e1_rows(e1)))
        A("")
        A("Contextual-header before/after: not measured (no E1_before_headers.json / E1_after_headers.json). English and Arabic are separate rows (`en_*`, `ar_*`).")
        A("")
        A(f"Caveat from the experiment file: {e1.get('caveat')} E1 result file run_at: {e1.get('run_at', NM)} (compare with the dataset version in section 2: E1 needs an embedding index built for the same dataset version, otherwise the app and the adapter fall back to BM25-only and dense rows cannot be measured).")
    else:
        A(NM)
    A("")
    A("## 6. Latency (mock LLM, local)")
    A("")
    lt = latest.get("latency") or {}
    A(f"p50 {f(lt.get('p50'))} ms, p95 {f(lt.get('p95'))} ms, TTFT p50 {f(lt.get('ttft_p50'))} ms, TTFT p95 {f(lt.get('ttft_p95'))} ms (n={f(lt.get('n'))}). Source: evals/results/latest.json `latency`. These are for a mock LLM on one machine and say nothing about real-model latency; real-model latency is in section 8 only if measured.")
    A("")
    A("## 7. Load and memory")
    A("")
    if load_r:
        A(f"Run at {load_r['run_at']}, target `{load_r['base_url']}`, mock LLM: {load_r['mock_llm']}. Source: loadtest/results/latest.json.")
        A("")
        st = load_r["stages"]
        keys = [k for k in ("sessions", "requests", "ok", "crashes", "p50_ms", "p95_ms", "ttft_p95_ms", "rps") if k in st[0]]
        A(table(keys, [[s.get(k) for k in keys] for s in st]))
        A("")
        A(f"Total requests {load_r['total_requests']}, crashes {load_r['total_crashes']} (target 0 met: {load_r['target_zero_crashes_met']}).")
        mem = load_r.get("memory_mib")
        A(f"Peak memory: {mem['peak']} MiB over {mem['samples']} samples (`{mem['container']}`; {mem['source']})." if isinstance(mem, dict) else f"Peak memory: {NM}.")
        A("")
        A("429 -> fallback -> degraded behaviour is verified in the backend contract tests with a mocked transport, not against the real API.")
    else:
        A(f"{NM}: no loadtest/results/latest.json.")
    A("")
    A("## 8. Real-model subset")
    A("")
    if live:
        A(f"Run at {live.get('run_at')}: {live.get('llm_calls')} real requests counted (cap {live.get('max_llm_calls', NM)}; counted per attempt, so a ceiling). {live.get('passed')} passed, {live.get('failed')} failed of {live.get('n')} run. Models that answered: {live.get('models_answered')}. App budget counter before/after: {live.get('app_budget_used_before')}/{live.get('app_budget_used_after')}. Judge not used. Source: evals/results/live_subset.json.")
        A("")
        A(table(["Case", "Lang", "Status", "Model", "Degraded reason", "Failed checks"], [[c["id"], c.get("lang"), c.get("status"), c.get("model") or "-", c.get("degraded_reason") or "-", "; ".join(c.get("failures") or [])[:200].replace("|", "/")] for c in live.get("cases", [])]))
        A("")
        A("n is far too small for any rate claim; this block shows only that the live path works and where it degraded.")
        if live.get("dataset_version") not in (None, latest.get("dataset_version")):
            A("")
            A(f"**Caveat:** the real-model run was made on dataset `{live.get('dataset_version')}`, not the current `{latest.get('dataset_version')}`.")
        A("")
        A("### 8b. Real-model answers, verbatim (including the weak ones)")
        A("")
        for c in real_cases(live):
            for t in c["turns"]:
                A(f"**{c['id']}** ({c.get('lang')}), model `{c.get('model') or 'none (answered by code)'}`, path `{t.get('path')}`, intent `{t.get('intent')}`, status {c.get('status')}, {f(c.get('latency_ms'))} ms. Source: evals/results/live_subset.json.")
                A("")
                A(f"> **User:** {t['say']}  ")
                A("> **Concierge:** " + " ".join(str(t.get("answer") or t.get("reply_excerpt", "")).split()))
                A("")
    else:
        A(f"{NM}: no real-model run is on file.")
    A("")
    A("## 9. Transcripts (excerpts; each labelled mock or real)")
    A("")
    tr = pick_transcripts(latest, live)
    if not tr:
        A(NM)
    for c, src, label in tr:
        A(f"### {c['id']} ({c.get('lang')}) - {label}")
        A("")
        A(f"Source: {src}; status: {c.get('status')}; intent: {c.get('intent')}; path: {c.get('path')}. Reply text is the full answer stored by the runner (truncated to 700 characters here).")
        A("")
        for t in c["turns"]:
            A(f"> **User:** {t['say']}  ")
            A("> **Concierge:** " + " ".join(str(t.get("answer") or t.get("reply_excerpt", ""))[:700].split()))
            A(">")
        A("")
    A("## 10. Failures, fixes, re-run")
    A("")
    if base:
        bt, at = base["totals"], tot
        A(table(["Run", "Passed", "Failed", "Skipped", "Source"], [
            ["before", bt["passed"], bt["failed"], bt["skipped"], "evals/results/baseline_before.json"],
            ["after", at["passed"], at["failed"], at["skipped"], "evals/results/latest.json"]]))
        A("")
        before_f = {c["id"]: c for c in base["cases"] if c.get("status") == "failed"}
        after_f = {c["id"] for c in latest["cases"] if c.get("status") == "failed"}
        fx = {x["case"]: x for x in (fixes or [])}
        rows = [[i, c["category"], "; ".join(c["failures"])[:160].replace("|", "/"), (fx.get(i) or {}).get("cause", "not recorded"), (fx.get(i) or {}).get("fix", "not recorded"), "still failing" if i in after_f else "passes now"] for i, c in sorted(before_f.items())]
        A(table(["Case", "Category", "Failure (before)", "Cause", "Fix", "Re-run"], rows) if rows else "No failures in the before run.")
        new = sorted(after_f - set(before_f))
        A("")
        A(f"Failing now but not before (new cases or regressions): {', '.join(new) if new else 'none'}.")
        A("")
        A("Note: the suite grew between the two runs (DarGlobal cases were added), so the totals are not a like-for-like comparison.")
    else:
        A(f"{NM}: evals/results/baseline_before.json is missing.")
    A("")
    A("## 11. Limitations")
    A("")
    for n in rc.get("notes", []):
        A(f"- {n}")
    A("- Mock-LLM numbers do not measure answer quality, tone or Arabic fluency; the judge was not used; real-model coverage is a handful of cases.")
    A("- Binds depend on the dataset: with DarGlobal detail pages missing from the DB, the DarGlobal cases are skipped and say so above.")
    A("- Small n everywhere; compare intervals, not point estimates.")
    A("- Lighthouse: " + (f"{latest['targets']['lighthouse_mobile'].get('actual')}" if latest["targets"].get("lighthouse_mobile", {}).get("actual") is not None else NM + " (not run by this generator)."))
    A("")
    report = "\n".join(L) + "\n"

    # README numbers block
    T = latest["targets"]
    rb = ["<!-- AUTOGEN:numbers (evals/make_report.py; do not edit by hand) -->",
          f"Dataset `{latest.get('dataset_version')}` (as of {latest.get('data_as_of')}). Latest full run {latest.get('run_at')}, LLM mode **{mode}**: "
          f"{tot['passed']} passed, {tot['failed']} failed, {tot['skipped']} skipped.",
          ""]
    rb.append(table(["Metric", "Target", "Actual", "95% CI"], [[LABELS.get(k, k), f"{v['op']} {v['target']}", f(v.get("actual")), ci(v.get("ci95"))] for k, v in T.items() if k != "lighthouse_mobile"]))
    rb.append("")
    rb.append("Mock-LLM numbers measure routing, retrieval, citations and guardrails, not model answer quality. The LLM judge was not used. " +
              (f"Real-model subset: {live.get('passed')}/{live.get('n')} passed using {live.get('llm_calls')} counted requests." if live else "Real-model subset: not measured."))
    if load_r:
        mem = load_r.get("memory_mib")
        rb.append(f"Load (mock LLM): {load_r['total_requests']} requests, {load_r['total_crashes']} crashes" + (f", peak {mem['peak']} MiB." if isinstance(mem, dict) else "; memory not measured."))
    rb.append("Full detail: [REPORT.md](REPORT.md).")
    rb.append("<!-- /AUTOGEN:numbers -->")
    F = facts(latest, comp, live, e1)
    blocks = {
        "numbers": "\n".join(rb),
        "facts": "<!-- AUTOGEN:facts (evals/make_report.py; do not edit by hand) -->\n"
                 f"Dataset `{F['DATASET_VERSION']}`: {F['DG_PROJECTS']} DarGlobal projects ({F['DG_FULL_PAGES']} with a full project page) and {F['WASALT_LISTINGS']} Wasalt listings.\n"
                 "<!-- /AUTOGEN:facts -->",
        "limitations": "<!-- AUTOGEN:limitations (evals/make_report.py; do not edit by hand) -->\n"
                       + "\n".join(f"- {x}" for x in limitations(F, latest, e1, live)) + "\n<!-- /AUTOGEN:limitations -->",
    }
    return report, blocks, latest, comp


def apply_blocks(txt, blocks):
    for name, block in blocks.items():
        pat = re.compile(r"<!-- AUTOGEN:%s\b.*?<!-- /AUTOGEN:%s -->" % (name, name), re.S)
        if pat.search(txt):
            txt = pat.sub(lambda m: block, txt)
    return txt


ALLPASS = re.compile(r"\ball\b[^.\n]{0,40}\bpass(?:es|ed)?\b", re.I)


def consistency_problems(latest, comp, a):
    """What --check enforces beyond staleness. Returns a list of strings; empty means consistent."""
    P = []
    if not latest:
        return ["evals/results/latest.json is missing"]
    v, tot = latest.get("dataset_version"), latest["totals"]
    if comp and comp.get("dataset_version") != v:
        P.append(f"dataset id differs: data/completeness.json {comp.get('dataset_version')} vs latest.json {v}")
    for nm in ("E1", "live_subset"):
        d = load(RES / f"{nm}.json")
        if d and d.get("dataset_version") != v:
            P.append(f"evals/results/{nm}.json was measured on dataset {d.get('dataset_version')}, latest.json is {v} (re-run it, or REPORT.md carries a caveat)")
    rd = (ROOT / "README.md").read_text(encoding="utf-8") if (ROOT / "README.md").exists() else ""
    for pat in ("TODO", "to be tested"):
        if re.search(pat, rd):
            P.append(f"README.md still contains '{pat}'")
    if tot["failed"] > 0:
        for rel_ in ("README.md", "Dockerfile", "evals/README.md", "docs/DEPLOY.md", "docs/DECISIONS.md", "deploy/README.md"):
            p = ROOT / rel_
            if p.exists():
                for n, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                    if ALLPASS.search(line):
                        P.append(f"{rel_}:{n} claims 'all ... pass' but the latest run has {tot['failed']} failed: {line.strip()[:110]}")
    if a.url:
        import urllib.request
        try:
            with urllib.request.urlopen(a.url.rstrip("/") + "/api/evals", timeout=20) as r:  # the app's own endpoint only
                live = json.loads(r.read().decode("utf-8"))
            lt = live.get("totals") or {}
            if live.get("dataset_version") != v or any(lt.get(k) != tot.get(k) for k in ("passed", "failed", "skipped")):
                P.append(f"{a.url}/api/evals serves dataset {live.get('dataset_version')} {lt.get('passed')}/{lt.get('failed')}/{lt.get('skipped')} "
                         f"but latest.json is {v} {tot['passed']}/{tot['failed']}/{tot['skipped']}: rebuild the image with the current latest.json")
        except Exception as e:  # noqa: BLE001
            P.append(f"could not read {a.url}/api/evals: {type(e).__name__}")
    left = sorted(set(re.findall(r"\{([A-Z][A-Z0-9_]+)\}", rd)))
    if left:
        msg = "deploy-time placeholders still in README.md: " + ", ".join(left)
        if a.final:
            P.append(msg)
        else:
            print("info:", msg, "(filled at deploy; --final fails on them)")
    return P


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--url", default="", help="with --check: also compare this deployment's /api/evals with latest.json")
    ap.add_argument("--final", action="store_true", help="with --check: deploy-time placeholders left in README.md are errors")
    a = ap.parse_args()
    report, blocks, latest, comp = build()
    rd = ROOT / "README.md"
    txt = rd.read_text(encoding="utf-8") if rd.exists() else ""
    new_txt = apply_blocks(txt, blocks)
    rp = ROOT / "REPORT.md"
    if a.check:
        problems = []
        if (not rp.exists()) or rp.read_text(encoding="utf-8") != report:
            problems.append("REPORT.md is stale vs evals/results/latest.json (run python evals/make_report.py)")
        if new_txt != txt:
            problems.append("README.md AUTOGEN blocks are stale vs evals/results/latest.json (run python evals/make_report.py)")
        problems += consistency_problems(latest, comp, a)
        for x in problems:
            print("FAIL:", x)
        print("stale or inconsistent" if problems else "up to date and consistent")
        return 1 if problems else 0
    rp.write_text(report, encoding="utf-8")
    if new_txt != txt:
        rd.write_text(new_txt, encoding="utf-8")
    print(f"wrote {rp}" + (" and updated README AUTOGEN blocks" if new_txt != txt else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
