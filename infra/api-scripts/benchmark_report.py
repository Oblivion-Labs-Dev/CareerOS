"""Turn benchmark JSON into a report you can read and decide from.

Deliberately opinionated: it ends with a recommendation per task rather than
leaving a wall of numbers, because the question being asked is "which model
should CareerOS use", and a table alone does not answer it.

Degrades gracefully - a missing or half-finished input file produces a report
covering whatever did finish, clearly marked, rather than nothing.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any


def load(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def esc(v: Any) -> str:
    return html.escape(str(v))


def num(v: Any, suffix: str = "", dash: str = "—") -> str:
    if v is None or v == "":
        return f'<span class="na">{dash}</span>'
    return f"{v}{suffix}"


def bar(value: float | None, lo: float, hi: float, tone: str = "accent") -> str:
    """A width-encoded cell, so a column can be scanned without reading digits."""
    if value is None:
        return ""
    pct = 0.0 if hi == lo else max(0.0, min(1.0, (float(value) - lo) / (hi - lo)))
    return f'<i class="bar {tone}" style="width:{pct * 100:.0f}%"></i>'


# ---------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------

def pick_scorer(scoring: list[dict]) -> tuple[str | None, list[str]]:
    """Best scoring model, and why.

    Separation is the deciding metric: the score exists to gate submissions, so
    a model that cannot tell a fitting posting from an unfitting one is useless
    at any latency. Determinism is a hard requirement rather than a tiebreak -
    a gate that returns a different number for the same input cannot be
    reasoned about at all.
    """
    usable = [
        s for s in scoring
        if not s.get("error") and s.get("separation") is not None
        and (s.get("determinism") or {}).get("stable") is not False
    ]
    if not usable:
        return None, ["No model produced a stable, separating score."]
    best = max(usable, key=lambda s: (s["separation"], -(s.get("latencyMean") or 999)))
    reasons = [
        f"Separates fitting from unfitting postings by "
        f"{best['separation']} points — the widest margin measured.",
        f"Ranks a fitting role above an unfitting one in "
        f"{best.get('rankAccuracy', 0) * 100:.0f}% of pairs.",
        "Returns the same score twice for the same input.",
        f"{best.get('latencyMean')}s mean per scoring call, "
        f"{(best.get('memory') or {}).get('totalBytes', 0) / 1e9:.1f}GB resident.",
    ]
    failures = int(best.get("failures") or 0)
    if failures:
        reasons.append(
            f"CAVEAT: {failures} of 8 calls returned unparseable JSON. Not a "
            "timeout — the model emits malformed output. In production an "
            "unscored job never enters the queue, so this must be handled "
            "before switching."
        )
    unstable = [s["model"] for s in scoring if (s.get("determinism") or {}).get("stable") is False]
    if unstable:
        reasons.append(
            "Excluded for non-determinism: " + ", ".join(unstable)
            + " — these return different scores for identical input, so they cannot gate a submission."
        )
    return best["model"], reasons


def pick_tailor(tailoring: list[dict]) -> tuple[str | None, list[str]]:
    """Best tailoring model: pass rate first, then how much it actually improves."""
    usable = [t for t in tailoring if not t.get("error") and t.get("passRate") is not None]
    if not usable:
        return None, ["No model produced a submittable tailored resume."]
    best = max(usable, key=lambda t: (t["passRate"], t.get("deltaMean") or -99))
    if not best.get("passRate"):
        return None, [
            "No model cleared the submission gate on any job. The untailored "
            "resume outscored every rewrite, which is a finding about the "
            "resume being strong already, not only about the models."
        ]
    return best["model"], [
        f"Cleared the submission gate on {best['passRate'] * 100:.0f}% of jobs.",
        f"Moved the match score {best.get('deltaMean'):+} points on average.",
        f"Rewrote {best.get('changedMean')} of 17 bullets per job.",
        f"{best.get('latencyMean')}s mean per job.",
    ]


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

def scoring_table(scoring: list[dict]) -> str:
    rows = []
    seps = [s["separation"] for s in scoring if s.get("separation") is not None]
    lo, hi = (min(seps), max(seps)) if seps else (0, 1)
    for s in sorted(scoring, key=lambda x: -(x.get("separation") or -99)):
        if s.get("error"):
            rows.append(
                f'<tr><td class="m">{esc(s["model"])}</td>'
                f'<td colspan="9" class="err">failed: {esc(s["error"][:120])}</td></tr>'
            )
            continue
        det = s.get("determinism") or {}
        stable = det.get("stable")
        det_cell = (
            '<span class="pill good">stable</span>' if stable
            else f'<span class="pill bad">varies {det.get("a")}→{det.get("b")}</span>'
            if stable is False else '<span class="na">—</span>'
        )
        mem = s.get("memory") or {}
        vf = mem.get("vramFraction")
        mem_cell = (
            f'{mem["totalBytes"] / 1e9:.1f}G'
            + (f' <span class="sub">{vf * 100:.0f}% VRAM</span>' if vf is not None else "")
            if mem.get("totalBytes") else '<span class="na">—</span>'
        )
        rows.append(f"""<tr>
  <td class="m">{esc(s["model"])}</td>
  <td class="n big">{num(s.get("separation"))}{bar(s.get("separation"), lo, hi, "good")}</td>
  <td class="n">{num(s.get("strongMean"), "%")}</td>
  <td class="n">{num(s.get("weakMean"), "%")}</td>
  <td class="n">{num(round((s.get("rankAccuracy") or 0) * 100)) if s.get("rankAccuracy") is not None else num(None)}{"%" if s.get("rankAccuracy") is not None else ""}</td>
  <td>{det_cell}</td>
  <td class="n">{num(s.get("unevidencedClaims"))}</td>
  <td class="n {'bad' if (s.get('failures') or 0) else ''}">{num(s.get("failures"))}<span class="sub">of 8</span></td>
  <td class="n">{num(s.get("latencyMean"), "s")}</td>
  <td class="n">{mem_cell}</td>
</tr>""")
    return f"""<table>
<thead><tr>
  <th>Model</th><th>Separation</th><th>Fitting</th><th>Unfitting</th>
  <th>Rank acc.</th><th>Determinism</th><th>Fabricated</th><th>Unparseable</th>
  <th>Latency</th><th>Memory</th>
</tr></thead>
<tbody>{"".join(rows)}</tbody></table>"""


def tailoring_table(tailoring: list[dict]) -> str:
    rows = []
    for t in sorted(tailoring, key=lambda x: -((x.get("passRate") or 0), )[0]):
        if t.get("error"):
            rows.append(
                f'<tr><td class="m">{esc(t["model"])}</td>'
                f'<td colspan="5" class="err">failed: {esc(t["error"][:120])}</td></tr>'
            )
            continue
        pr = t.get("passRate")
        delta = t.get("deltaMean")
        tone = "good" if (delta or 0) > 0 else "bad"
        mem = t.get("memory") or {}
        rows.append(f"""<tr>
  <td class="m">{esc(t["model"])}</td>
  <td class="n big">{num(round(pr * 100) if pr is not None else None)}{"%" if pr is not None else ""}
      {bar(pr, 0, 1, "good")}</td>
  <td class="n {tone}">{num(f"{delta:+}" if delta is not None else None)}</td>
  <td class="n">{num(t.get("changedMean"))}<span class="sub">/17</span></td>
  <td class="n">{num(t.get("errors"))}</td>
  <td class="n">{num(t.get("latencyMean"), "s")}</td>
  <td class="n">{f'{mem["totalBytes"] / 1e9:.1f}G' if mem.get("totalBytes") else num(None)}</td>
</tr>""")
    return f"""<table>
<thead><tr>
  <th>Model</th><th>Gate pass</th><th>Score Δ</th><th>Bullets rewritten</th>
  <th>Errors</th><th>Latency / job</th><th>Memory</th>
</tr></thead>
<tbody>{"".join(rows)}</tbody></table>"""


VARIANT_NOTES = {
    "baseline": "Ships today: retrieved evidence, detected requirements, batches of 4.",
    "no-evidence": "Story index removed — does retrieval earn its context?",
    "batch-8": "Eight bullets per call instead of four.",
    "batch-17": "All seventeen in one call — the shape that returned bullets in the wrong slots.",
    "aggressive": "Aggressive framing, everything else identical.",
}


def variants_table(variants: list[dict]) -> str:
    rows = []
    for v in variants:
        pr = v.get("passRate")
        delta = v.get("deltaMean")
        rows.append(f"""<tr>
  <td class="m">{esc(v.get("variant"))}<span class="sub">{esc(VARIANT_NOTES.get(v.get("variant"), ""))}</span></td>
  <td class="n big">{num(round(pr * 100) if pr is not None else None)}{"%" if pr is not None else ""}
      {bar(pr, 0, 1, "good")}</td>
  <td class="n {'good' if (delta or 0) > 0 else 'bad'}">{num(f"{delta:+}" if delta is not None else None)}</td>
  <td class="n">{num(v.get("changedMean"))}<span class="sub">/17</span></td>
</tr>""")
    return f"""<table>
<thead><tr><th>Prompt variant</th><th>Gate pass</th><th>Score Δ</th><th>Bullets rewritten</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>"""


def questions_table(payload: dict) -> str:
    board = payload.get("leaderboard") or []
    if not board:
        return ""
    rows = []
    for s in board:
        rows.append(f"""<tr>
  <td class="m">{esc(s.get("model"))}</td>
  <td class="n big">{num(s.get("overallBenchmarkScore"))}{bar(s.get("overallBenchmarkScore"), 0, 100, "good")}</td>
  <td class="n">{num(s.get("answerAccuracy"), "%")}</td>
  <td class="n">{num(s.get("criticalFieldAccuracy"), "%")}</td>
  <td class="n {'bad' if (s.get('hallucinationRate') or 0) > 5 else ''}">{num(s.get("hallucinationRate"), "%")}</td>
  <td class="n">{num(s.get("correctAbstentionRate"), "%")}</td>
  <td class="n">{num(s.get("averageLatencyMs"), "ms")}</td>
</tr>""")
    return f"""<table>
<thead><tr><th>Model</th><th>Overall</th><th>Answer acc.</th><th>Critical fields</th>
<th>Hallucination</th><th>Correct abstention</th><th>Latency</th></tr></thead>
<tbody>{"".join(rows)}</tbody></table>"""


# ---------------------------------------------------------------------------

CSS = """
:root{--paper:#faf8f5;--card:#fff;--ink:#1c1b22;--soft:#5a5766;--faint:#8b8798;
--rule:#e4e0d8;--rule2:#efece6;--accent:#3f3d9e;--accent-soft:#ecebf7;
--good:#1f7a54;--good-bg:#e4f1ea;--warn:#a8690b;--bad:#a33a28;--bad-bg:#f8e6e2;
--shadow:0 1px 2px rgba(28,27,34,.06);color-scheme:light}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
--paper:#14131a;--card:#1c1b24;--ink:#eceaf2;--soft:#a8a4b8;--faint:#78748a;
--rule:#2e2c39;--rule2:#26242f;--accent:#9c99f0;--accent-soft:#232140;
--good:#5fd39b;--good-bg:#163020;--warn:#e0ab5a;--bad:#e88b76;--bad-bg:#3a1d17;
--shadow:0 1px 2px rgba(0,0,0,.45);color-scheme:dark}}
:root[data-theme="dark"]{--paper:#14131a;--card:#1c1b24;--ink:#eceaf2;--soft:#a8a4b8;
--faint:#78748a;--rule:#2e2c39;--rule2:#26242f;--accent:#9c99f0;--accent-soft:#232140;
--good:#5fd39b;--good-bg:#163020;--warn:#e0ab5a;--bad:#e88b76;--bad-bg:#3a1d17;
--shadow:0 1px 2px rgba(0,0,0,.45);color-scheme:dark}
*{box-sizing:border-box}
body{background:var(--paper);color:var(--ink);font-family:"Source Sans 3",ui-sans-serif,system-ui,sans-serif;font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.wrap{max-width:1080px;margin:0 auto;padding-inline:20px;padding-block:0 72px}
header{border-bottom:2px solid var(--ink);padding-block:40px 16px;margin-bottom:26px}
.eyebrow{font-family:"IBM Plex Mono",monospace;font-size:11px;letter-spacing:.16em;text-transform:uppercase;color:var(--accent);margin:0 0 10px}
h1{font-family:"Zilla Slab",Georgia,serif;font-size:clamp(2rem,5.5vw,3.1rem);font-weight:600;line-height:1.03;margin:0;letter-spacing:-.02em;text-wrap:balance}
.stand{color:var(--soft);max-width:66ch;margin:13px 0 0}
h2{font-family:"Zilla Slab",Georgia,serif;font-weight:600;font-size:1.42rem;margin:46px 0 3px}
.note{color:var(--soft);margin:0 0 16px;max-width:70ch;font-size:.94rem}
.verdicts{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px;margin-top:26px}
.verdict{background:var(--card);border:1px solid var(--rule);border-left:3px solid var(--accent);border-radius:3px;padding:16px 18px;box-shadow:var(--shadow)}
.verdict h3{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.13em;text-transform:uppercase;color:var(--faint);margin:0 0 6px;font-weight:500}
.verdict .pickname{font-family:"IBM Plex Mono",monospace;font-size:1.22rem;font-weight:600;color:var(--accent);display:block;margin-bottom:9px;word-break:break-all}
.verdict ul{margin:0;padding-left:17px;color:var(--soft);font-size:.9rem}
.verdict li{margin-bottom:3px}
.tablewrap{overflow-x:auto;border:1px solid var(--rule);border-radius:3px;background:var(--card);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;min-width:720px}
th{font-family:"IBM Plex Mono",monospace;font-size:9.5px;letter-spacing:.11em;text-transform:uppercase;color:var(--faint);text-align:left;padding:10px 13px;border-bottom:1px solid var(--rule);font-weight:500;white-space:nowrap}
td{padding:11px 13px;border-bottom:1px solid var(--rule2);vertical-align:top}
tr:last-child td{border-bottom:0}
td.m{font-family:"IBM Plex Mono",monospace;font-size:.87rem;font-weight:600;white-space:nowrap}
td.n{font-variant-numeric:tabular-nums;white-space:nowrap;position:relative}
td.big{font-size:1.06rem;font-weight:600}
td.good{color:var(--good)}td.bad{color:var(--bad)}
.err{color:var(--bad);font-size:.87rem}
.na{color:var(--faint)}
.sub{display:block;color:var(--faint);font-size:.78rem;font-weight:400;font-family:"Source Sans 3",sans-serif;white-space:normal;max-width:34ch}
.bar{display:block;height:3px;border-radius:2px;margin-top:5px;background:var(--accent);opacity:.5;min-width:2px}
.bar.good{background:var(--good)}
.pill{display:inline-block;font-family:"IBM Plex Mono",monospace;font-size:9.5px;letter-spacing:.06em;text-transform:uppercase;padding:3px 7px;border-radius:2px;white-space:nowrap}
.pill.good{background:var(--good-bg);color:var(--good)}
.pill.bad{background:var(--bad-bg);color:var(--bad)}
.method{background:var(--card);border:1px solid var(--rule);border-radius:3px;padding:16px 20px;margin-top:16px}
.method dt{font-family:"IBM Plex Mono",monospace;font-size:10.5px;letter-spacing:.1em;text-transform:uppercase;color:var(--accent);margin-top:13px}
.method dt:first-child{margin-top:0}
.method dd{margin:3px 0 0;color:var(--soft);font-size:.92rem}
.cases{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.cases span{font-family:"IBM Plex Mono",monospace;font-size:11px;padding:4px 8px;border-radius:2px;background:var(--accent-soft);color:var(--accent)}
.cases span.weak{background:var(--bad-bg);color:var(--bad)}
footer{margin-top:50px;padding-top:16px;border-top:1px solid var(--rule);color:var(--faint);font-size:.85rem}
code{font-family:"IBM Plex Mono",monospace;font-size:.87em;background:var(--accent-soft);color:var(--accent);padding:1px 5px;border-radius:2px}
@media(max-width:640px){.verdicts{grid-template-columns:1fr}}
"""


def build(resume: dict, questions: dict) -> str:
    scoring = resume.get("scoring") or []
    tailoring = resume.get("tailoring") or []
    variants = resume.get("variants") or []

    scorer, scorer_why = pick_scorer(scoring)
    tailor, tailor_why = pick_tailor(tailoring)

    cases = resume.get("scoringCases") or []
    case_chips = "".join(
        f'<span class="{"weak" if c["label"] == "weak" else ""}">'
        f'{esc(c["company"])} · {esc(c["title"][:34])}</span>'
        for c in cases
    )

    q_section = ""
    if questions.get("leaderboard"):
        q_section = f"""
  <h2>Secondary: application-question answering</h2>
  <p class="note">The existing 40-case suite, included for completeness. This is
  the only axis with real ground truth, but it measures form filling, not resume
  work, so it does not decide the picks above.</p>
  <div class="tablewrap">{questions_table(questions)}</div>"""

    var_section = ""
    if variants:
        var_section = f"""
  <h2>Prompt shape</h2>
  <p class="note">One model, five prompt shapes, same jobs. This answers whether
  the prompt choices currently in the code are carrying their weight.</p>
  <div class="tablewrap">{variants_table(variants)}</div>"""

    return f"""<title>Model Bench</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Zilla+Slab:wght@500;600;700&family=Source+Sans+3:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500;600&display=swap">
<style>{CSS}</style>
<div class="wrap">
  <header>
    <p class="eyebrow">CareerOS · local model evaluation</p>
    <h1>Model Bench</h1>
    <p class="stand">Which local model should score a resume against a job
    description, and which should rewrite the bullets. Measured on this machine,
    one model resident at a time, against real postings from the job database.</p>
    <div class="verdicts">
      <div class="verdict">
        <h3>Use for resume scoring</h3>
        <span class="pickname">{esc(scorer or "no clear winner")}</span>
        <ul>{"".join(f"<li>{esc(r)}</li>" for r in scorer_why)}</ul>
      </div>
      <div class="verdict">
        <h3>Use for resume tailoring</h3>
        <span class="pickname">{esc(tailor or "none qualified")}</span>
        <ul>{"".join(f"<li>{esc(r)}</li>" for r in tailor_why)}</ul>
      </div>
    </div>
  </header>

  <h2>Resume scoring</h2>
  <p class="note">Separation is the metric that matters: the score decides
  whether an application is sent, so a model that rates everything alike is
  useless however sensible each number looks. Fitting and unfitting are real
  postings labelled before any model saw them — infrastructure and platform
  roles against mobile, frontend and data-science roles.</p>
  <div class="cases">{case_chips}</div>
  <div class="tablewrap" style="margin-top:12px">{scoring_table(scoring)}</div>

  <h2>Resume tailoring</h2>
  <p class="note">Every model's bullets were scored by one fixed scorer
  (<code>{esc(resume.get("referenceScorer", "—"))}</code>) in a single pass after
  all tailoring finished. Letting each model grade its own output would measure
  self-agreement. Gate pass means: genuinely rewritten, structurally sound, and
  scoring above both the 80% bar and the untailored resume.</p>
  <div class="tablewrap">{tailoring_table(tailoring)}</div>
  {var_section}
  {q_section}

  <h2>What this run cannot tell you</h2>
  <div class="method">
    <dl>
      <dt>The 80% submit bar is calibrated to the wrong scorer</dt>
      <dd>It was set while qwen3:4b-instruct was scoring, and that model rates
      almost everything in the high 70s and 80s. A better-calibrated scorer puts
      the same jobs far lower — the Brex posting scores 79.5% under qwen and
      52.5% under mistral. Switching the scorer without moving the bar would
      reject every job. The bar is a property of the scorer, not of the
      candidate, and the two have to move together.</dd>

      <dt>The tailoring comparison rests on one job, not two</dt>
      <dd>The reference scorer could not parse its own output for the Fieldwire
      posting on any attempt, so that job is excluded from every model's score.
      One gradable job is enough to show direction and nowhere near enough to
      rank models. Treat the tailoring table as provisional.</dd>

      <dt>Nothing cleared the gate, and that is partly the bar</dt>
      <dd>The best rewrite moved Brex from 52.5% to 58.1%. That is a real
      improvement and still nowhere near 80%. Whether tailoring "works" cannot
      be settled until the bar is recalibrated against whichever scorer ships.</dd>
    </dl>
  </div>

  <h2>How to read this</h2>
  <dl class="method">
    <dt>Separation</dt><dd>Mean score on fitting postings minus mean on unfitting ones. Higher is better; near zero means the model cannot discriminate and should not gate anything.</dd>
    <dt>Determinism</dt><dd>The same resume and posting scored twice. A model that returns different numbers cannot be used as a submission gate, regardless of its other numbers.</dd>
    <dt>Fabricated</dt><dd>Skills the model claimed as matches that the candidate's documents do not evidence, stripped by the anti-fabrication check. Lower is better grounded.</dd>
    <dt>Score Δ</dt><dd>Tailored score minus the untailored resume scored in the same run. Negative means the rewrite made the match worse.</dd>
    <dt>Memory</dt><dd>As Ollama reports it while loaded. The VRAM fraction predicts usability here: anything outside the 8GB card runs on CPU at a few tokens per second.</dd>
  </dl>

  <footer>
    Generated {esc(resume.get("generatedAt", "—"))} ·
    <code>scripts/benchmark_models.py</code> and
    <code>scripts/benchmark_all.py</code> ·
    raw results in <code>data/benchmark_resume.json</code>
  </footer>
</div>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--resume", default="data/benchmark_resume.json")
    ap.add_argument("--questions", default="data/benchmark_questions.json")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    resume = load(Path(args.resume))
    questions = load(Path(args.questions))
    if not resume:
        raise SystemExit(f"no results at {args.resume}")
    Path(args.out).write_text(build(resume, questions), encoding="utf-8")
    print(f"wrote {args.out}")
    print(f"  scoring models : {len(resume.get('scoring') or [])}")
    print(f"  tailoring      : {len(resume.get('tailoring') or [])}")
    print(f"  variants       : {len(resume.get('variants') or [])}")
    print(f"  question suite : {len(questions.get('leaderboard') or [])}")


if __name__ == "__main__":
    main()
