"""REPORT.md section 12: the conversation-quality before/after table, built from evals/results/conv_*.json only.

before = snapshot (HEAD 852840e) and after = the quality-pass tree, both 30 conversations / 90 turns on the same
provider. fix / fix2 = the single fix round, re-running only the affected conversations; "after + fix round" replaces
those conversations' turns with the re-run turns (everything else stays as measured in the after run)."""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

RES = Path(__file__).resolve().parent / "results"


def _load(label):
    p = RES / f"conv_{label}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _ok(t):
    return all(v.get("pass") for v in t["checks"].values() if v.get("pass") is not None)


def _turns(d):
    return {(c["id"], t["n"]): (c, t) for c in d["conversations"] for t in c["turns"]}


def _rate(rows):
    n = len(rows)
    p = sum(1 for r in rows if r)
    return p, n


def build():
    b, a = _load("before"), _load("after")
    if not b or not a:
        return ""
    fixes = [x for x in (_load("fix"), _load("fix2")) if x]
    ta, tb = _turns(a), _turns(b)
    tf = dict(ta)
    for d in fixes:
        for k, v in _turns(d).items():
            tf[k] = v

    def agg(tmap, key):
        out = defaultdict(list)
        for (cid, n), (c, t) in tmap.items():
            ks = [c["category"]] if key == "category" else [t.get("playbook") or c.get("playbook")]
            for k in ks:
                out[k].append(_ok(t))
        return out

    def tot(tmap):
        return sum(_ok(t) for _, t in tmap.values()), len(tmap)

    L = ["", "## 12. Conversation quality pass (before / after)", ""]
    pb, nb = tot(tb)
    pa, na = tot(ta)
    pf, nf = tot(tf)
    L.append(f"Same 30 frozen conversations ({nb} turns), same provider (`{b.get('provider')}`, model `{b.get('model')}`), "
             "every deterministic check on every turn. A turn passes only if all its applicable checks pass. "
             "This is a 30-conversation set (cut from the 60 first planned); it is a regression guide, not a benchmark.")
    L.append("")
    L.append("| Run | Turns passed | Rate | NVIDIA calls (counted) | Judge helpfulness | Judge tone | Share via understanding call |")
    L.append("|---|---|---|---|---|---|---|")
    for name, d, (p, n) in (("before (snapshot 852840e)", b, (pb, nb)), ("after (quality pass)", a, (pa, na))):
        j = d["summary"].get("judge") or {}
        L.append(f"| {name} | {p}/{n} | {p / n:.1%} | {d.get('llm_calls_counted')} | {j.get('helpfulness_mean')} (n={j.get('n')}) | "
                 f"{j.get('tone_mean')} | {d['summary'].get('share_path_llm_understanding'):.1%} |")
    fc = sum(x.get("llm_calls_counted") or 0 for x in fixes)
    L.append(f"| after + one fix round | {pf}/{nf} | {pf / nf:.1%} | {fc} (re-run of {len({k[0] for k in tf if tf[k] is not ta.get(k)})} conversations) | not re-judged | not re-judged | |")
    L.append("")
    for title, key in (("Per category", "category"), ("Per playbook type", "playbook")):
        L.append(f"### {title} (turns passed / turns)")
        L.append("")
        L.append("| " + ("Category" if key == "category" else "Playbook type") + " | before | after | after + fix round | delta (after+fix vs before) |")
        L.append("|---|---|---|---|---|")
        ab, aa, af = agg(tb, key), agg(ta, key), agg(tf, key)
        for k in sorted(set(ab) | set(aa), key=lambda x: str(x)):
            pb_, nb_ = _rate(ab.get(k, []))
            pa_, na_ = _rate(aa.get(k, []))
            pf_, nf_ = _rate(af.get(k, []))
            d_ = pf_ - pb_
            L.append(f"| {k} | {pb_}/{nb_} | {pa_}/{na_} | {pf_}/{nf_} | {d_:+d} |")
        L.append("")
    L.append("### Calls and quota")
    L.append("")
    probes = [b.get("nvidia_probe_before") or {}, (a.get("nvidia_probe_after") or {})]
    hdrs = [p.get("headers") for p in probes if p.get("headers")]
    L.append(f"- NVIDIA completion calls: before {b.get('llm_calls_counted')} (cap 120), after {a.get('llm_calls_counted')} (cap 120), "
             f"fix round {fc} (cap 30); total {b.get('llm_calls_counted', 0) + a.get('llm_calls_counted', 0) + fc}. "
             "Mock suite and unit tests: 0 model calls. OpenRouter: 0 calls in this pass.")
    stops = [d.get("stop_reason") for d in [b, a] + fixes if d.get("stop_reason")]
    L.append("- NVIDIA free limit: " + (f"REACHED, {stops}." if stops else "not reached in any run (no 429, 402 or quota error; no run stopped early)."))
    L.append("- Rate-limit headers: " + (f"recorded {hdrs}" if hdrs else "NVIDIA returned none on GET /v1/models before or after the runs, and the backend does not expose headers of completion calls, so the remaining free credit cannot be read; it is only observable by the stop-on-quota rule firing."))
    L.append("- Stop rule: a quota, credit or 402 error stops a run at once; three consecutive 429s also stop it; the runner records \"NVIDIA free limit reached at N calls\" and keeps what was measured, never retrying in a loop.")
    L.append("")
    L.append("### Caveats")
    L.append("")
    L.append("- The judge is Gemini, rotated across models on 429 (a mix of two models, mostly gemini-3.5-flash-lite), weak on Gulf dialect, and used for helpfulness and tone only; it never overrides a deterministic check. Not re-judged after the fix round. Run-to-run model variance on 90 turns is several points, so a gap of 1 or 2 turns is not a measured change.")
    L.append("- Some remaining failures are checker limits, not wrong answers: `numbers_traceable` flags counts the assistant correctly quotes from its holdings summary (for example 42 projects), and `country_city` flags a not-found reply that lists the countries the data does hold. They count against both runs equally.")
    L.append("- Three playbook types went down by one turn after the pass (vague_opener, identity, investment_advice). Two are `country_city` flags on replies that list the countries the data holds (c20 t2, c24 t2). One is a real open question: c29 t3 (identity, Arabic, \"are your prices up to date\") quotes 1,059,000, which the runner could not find in the turn's context, so it may be an ungrounded number. None of the three was a fix-round target; they are listed as remaining problems.")
    L.append("- 6 turns in the before run and the after run were degraded by `all_models_down` and answered by the code path; none were quota related.")
    L.append("- Playbook ids without a conversation in the set (near_amenity, calculation, currency, unrealistic_budget, injection) are covered only by the mock suite.")
    L.append("")
    return "\n".join(L)
