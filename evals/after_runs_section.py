"""REPORT.md section 13: the persona set (60 conversations) and the 30-conversation set, before / after / after + the fix
round that re-ran only the failing conversations. Every figure is read from evals/results/conv_*.json (and the archived
pre-merge copies in evals/results/superseded/)."""
from __future__ import annotations

import json

from quality_section import RES, _load, _ok, _turns


def _passed(tmap):
    return sum(_ok(t) for _, t in tmap.values()), len(tmap)


def _degraded(d):
    return sum(1 for c in d["conversations"] for t in c["turns"]
               if (t.get("trace") or {}).get("degraded_reason") in ("all_models_down", "rate_limited", "timeout"))


def _pre_fix(d):
    """The after run as first measured: the archived copy taken before the fix round was merged in."""
    p = RES / "superseded" / f"conv_{d.get('label')}.pre_fixround.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else d


def _pct(p, n):
    return f"{p}/{n} ({p / n:.1%})" if n else "-"


def build_after_runs() -> str:
    pb, pa = _load("personas_before"), _load("personas_after")
    cb, ca = _load("before2"), _load("after2")
    if not (pb and pa):
        return ""
    pa0 = _pre_fix(pa)
    ca0 = _pre_fix(ca) if ca else None
    L = ["", "## 13. Persona set and 30-conversation set: after-runs and one fix round (20 Nov 2026)", ""]
    jm = (pa.get("judge") or {}).get("model")
    L.append(f"Answering model: `{pa.get('model')}` via `{pa.get('provider')}` (eval-only provider override). Judge: `{jm}` on "
             "NVIDIA's API, a different model family from the answering model; it scores helpful, honest, tone and persona fit "
             "1-5 and never overrides a deterministic check. A turn passes only if every applicable check passes. The fix round "
             "re-ran only the conversations with a failing turn, on the fixed code, with the same provider, judge and checks, and "
             "replaced those whole conversations in the after file (the pre-merge file is kept in evals/results/superseded/).")
    L.append("")
    L.append("### Persona set: turns passed per persona")
    L.append("")
    L.append("| Persona | before | after | after + fix round |")
    L.append("|---|---|---|---|")
    sb, s0, s1 = pb["summary"], pa0["summary"], pa["summary"]

    def cell(s, p_):
        v = s["turn_pass_by_persona"].get(p_)
        return _pct(v["passed"], v["n"]) if v else "-"

    for p_ in sorted(s1["turn_pass_by_persona"]):
        L.append(f"| {p_} | {cell(sb, p_)} | {cell(s0, p_)} | {cell(s1, p_)} |")
    tb_, t0_, t1_ = _passed(_turns(pb)), _passed(_turns(pa0)), _passed(_turns(pa))
    L.append(f"| **all** | {_pct(*tb_)} | {_pct(*t0_)} | {_pct(*t1_)} |")
    L.append("")
    if cb and ca:
        L.append("### 30-conversation set (no persona field, so one bucket)")
        L.append("")
        L.append("| Run | Turns passed |")
        L.append("|---|---|")
        for name, d in (("before (before2)", cb), ("after (after2)", ca0), ("after + fix round", ca)):
            L.append(f"| {name} | {_pct(*_passed(_turns(d)))} |")
        L.append("")
    L.append("### Judge means (1-5)")
    L.append("")
    L.append("| Set | Run | helpful | honest | tone | persona fit |")
    L.append("|---|---|---|---|---|---|")
    rows = [("personas", "before", pb), ("personas", "after", pa0), ("personas", "after + fix round", pa)]
    if cb and ca:
        rows += [("30-set", "before", cb), ("30-set", "after", ca0), ("30-set", "after + fix round", ca)]
    for set_, name, d in rows:
        j = d["summary"].get("judge_means") or {}
        L.append(f"| {set_} | {name} | {j.get('helpful')} | {j.get('honest')} | {j.get('tone')} | {j.get('persona_fit')} |")
    L.append("")
    L.append("### Calls per provider")
    L.append("")
    L.append("| Run | NVIDIA answering calls (counted / cap) | NVIDIA judge calls | Gemini judge calls | OpenRouter calls | Stop reason |")
    L.append("|---|---|---|---|---|---|")
    runs = [("personas before", pb), ("personas after", pa0)]
    if cb and ca:
        runs += [("30-set before", cb), ("30-set after", ca0)]
    for name, d in runs:
        jc = (d.get("judge") or {}).get("calls") or {}
        L.append(f"| {name} | {d.get('llm_calls_counted')} / {d.get('max_llm_calls')} | {jc.get('nvidia', 0)} | "
                 f"{jc.get('gemini', 0)} | 0 | {d.get('stop_reason') or 'none'} |")
    for name, d in (("personas", pa), ("30-set", ca)):
        for fr in (d or {}).get("fix_rounds") or []:
            jc = (fr.get("judge") or {}).get("calls") or {}
            L.append(f"| {name} fix round ({len(fr['conversations'])} conversations) | {fr.get('llm_calls_counted')} / "
                     f"{fr.get('max_llm_calls')} | {jc.get('nvidia', 0)} | {jc.get('gemini', 0)} | 0 | {fr.get('stop_reason') or 'none'} |")
    L.append("")
    L.append("### What the error analysis found")
    L.append("")
    n30 = _passed(_turns(ca0))[1] if ca0 else 0
    L.append(f"- The two after-runs ran at the same time against one NVIDIA key. {_degraded(pa0)} of {t0_[1]} persona turns and "
             f"{_degraded(ca0) if ca0 else 0} of {n30} 30-set turns were answered without a model (`all_models_down` or "
             "`rate_limited`); no quota stop fired. Most failures were on those turns, and they exposed real defects in the "
             "no-model fallback:")
    L.append("  - a property request the planner did not classify (\"ok show me something in Riyadh\", Arabizi rent requests, "
             "\"most expensive properties you have\") quoted one field of a retrieved page (\"From the published source: ...\"), "
             "sometimes in the wrong language, instead of showing listings;")
    L.append("  - the off-topic and banter pivot quoted the spotlight project's marketing description verbatim, and a plain insult "
             "got an unrequested \"I can: 2 + 2 = 4\";")
    L.append("  - \"what countries do you cover?\" fell through to the no-answer reply, and Spanish \"España\" / \"proyectos\" "
             "were not recognised;")
    L.append("  - \"relocating to Riyadh, budget around 2 million SAR, what can we get?\" got only the residency reply, no homes.")
    L.append("- Checker false positives fixed in evals/run_conversations.py (the checker was wrong, the answer was right): an "
             "amount the user wrote in words (\"مليون ريال\") is traceable; a context value rounded to a whole number (826.73 m² "
             "stated as 827 m²) is the same figure; the calculator's fixed usage examples in quotes are not data claims. These "
             "changes only make the check more lenient, and only the fix-round turns ran with them; the before runs used the "
             "older checker.")
    L.append("- One Arabic rendering bug surfaced through a checker flag: a listing title such as \"Villa 1189.54 SQM ...\" was "
             "split across two bidi isolates, which can reorder the size in right-to-left text; the size now stays in one isolate.")
    L.append("")
    L.append("### Caveats")
    L.append("")
    L.append("- \"after + fix round\" is optimistic: only conversations with a failing turn were re-run, and passing conversations "
             "were not re-sampled. Run-to-run variance could flip some of those turns either way, so this is not a full re-run.")
    L.append("- The judge and the answering model share one NVIDIA key, and the judge runs in parallel threads. 429s from that "
             "contention put the answering model into cooldown, so turns were still answered without a model in the fix round "
             f"({sum(_degraded({'conversations': [c for c in d['conversations'] if any(t.get('fix_round') for t in c['turns'])]}) for d in (pa, ca) if d)} "
             "fix-round turns). The fallback quality matters for that reason too.")
    L.append("")
    L.append("### Remaining failing turns (after + fix round)")
    L.append("")
    L.append("| Set | Turn | Question | Path (degraded) | Failed checks |")
    L.append("|---|---|---|---|---|")
    for set_, d in (("personas", pa), ("30-set", ca)):
        for c in (d or {}).get("conversations", []):
            for t in c["turns"]:
                bad = [k for k, v in t["checks"].items() if v.get("pass") is False]
                if bad:
                    tr = t.get("trace") or {}
                    q = (t.get("say") or "").replace("|", "/")
                    q = q[:70] + ("..." if len(q) > 70 else "")
                    L.append(f"| {set_} | {c['id']} t{t['n']} | {q} | {tr.get('path')} ({tr.get('degraded_reason') or '-'}) | "
                             f"{', '.join(bad)} |")
    L.append("")
    return "\n".join(L)
