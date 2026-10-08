"""Golden resume evals: python -m app.services.career_compiler.evals [--offline] [--only ID ...]

Each fixture in evals/resume/fixtures is a synthetic job description plus what a correct resume must and must not
do. A live run goes JD -> jd.json -> query -> retrieval -> plan -> DeepSeek writing -> validation -> Word page fit ->
DOCX/PDF, then scores the result deterministically. --offline stops after planning (no DeepSeek, no Word).
Results, with model, prompt, retrieval and template versions, go to evals/resume/results/.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[5]
EVALS = REPO / "evals" / "resume"
HARD_GATES = ("factual_precision", "metric_precision", "technology_precision", "traceability")
#: Validator codes that mean a draft asserted something career.json does not support (as opposed to length or form).
FACT_CODES = {"missing_evidence", "unknown_evidence", "evidence_not_allowed", "wrong_company", "unresolved_conflict",
              "unsupported_metric", "unsupported_experience", "unsupported_technology", "unsupported_title",
              "unsupported_scale", "unsupported_ownership", "sparse_detail", "date_mismatch"}


def _said(text: str, term: str) -> bool:
    from app.services.career_compiler.lexicon import mentions_tech
    if re.fullmatch(r"[\w .#+/-]+", term) and not re.search(r"\d", term):
        return mentions_tech(text, term)
    return term.casefold() in text.casefold()


def fixtures(only: list[str] | None = None) -> list[dict[str, Any]]:
    items = [json.loads(p.read_text(encoding="utf-8")) for p in sorted((EVALS / "fixtures").glob("*.json"))]
    return [f for f in items if not only or f["id"] in only]


def _git() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def run_fixture(fixture: dict[str, Any], *, offline: bool) -> dict[str, Any]:
    from app.services.career_compiler.deepseek import DeepSeekClient
    from app.services.career_compiler.models import JobDescription, ResumeDocument, ResumePlan
    from app.services.career_compiler.pipeline import analyze, generate
    from app.services.career_compiler.retrieval import retrieve_evidence
    from app.services.career_compiler.scoring import retrieval_recall
    from app.services.career_compiler.store import load_store

    store = load_store()
    llm = DeepSeekClient(api_key="") if offline else DeepSeekClient()
    started = time.perf_counter()
    analysis = analyze(text=fixture["jd"], llm=llm, refresh=True)
    jd = JobDescription.model_validate(analysis["jd"])
    plan = ResumePlan.model_validate(analysis["plan"])
    retrieval = retrieve_evidence(jd, store)
    texts = [r.original_text.casefold() for r in jd.requirements]
    expected = fixture.get("expected_requirements") or []
    found = [e for e in expected if any(e.casefold() in t for t in texts)]
    disputed = {e.id for e in store.evidence.values() if e.status == "needs_reconciliation"}
    must_not_use = set(fixture.get("must_not_use") or []) | disputed
    planned_projects = [p.project_id for p in plan.selected_projects]
    result: dict[str, Any] = {
        "id": fixture["id"], "category": fixture["category"], "jd_source": jd.source, "requirements": len(jd.requirements),
        "jd_parsing_recall": round(len(found) / len(expected), 4) if expected else None,
        "jd_parsing_missed": [e for e in expected if e not in found],
        **retrieval_recall(retrieval, fixture.get("expected_evidence") or [], fixture.get("expected_projects") or []),
        "plan_project_recall": round(sum(p in planned_projects for p in fixture.get("expected_projects") or [])
                                     / len(fixture["expected_projects"]), 4) if fixture.get("expected_projects") else None,
        "planned_disallowed_evidence": sorted({i for p in plan.selected_projects for i in p.evidence_ids} & must_not_use),
        "analysis_stages": analysis["stages"],
    }
    if offline:
        result["seconds"] = round(time.perf_counter() - started, 1)
        return result
    output = generate(jd=jd, plan=plan, llm=llm, store=store)
    document = ResumeDocument.model_validate(output["document"])
    bullets = ([document.summary] if document.summary else []) + document.bullets()
    text = "\n".join(b.text for b in bullets)
    cited = {i for b in bullets for i in b.evidence_ids}
    on_page = {b.project_id for b in bullets}
    said = [t for t in fixture.get("must_not_say") or [] if _said(text, t)]
    gaps = fixture.get("expected_gaps") or []
    gap_rows = output["evaluation"]["no_supported_evidence"]
    caught: dict[str, int] = {}
    other_rejections: dict[str, int] = {}
    for row in output["debug"]:
        for draft in row.get("rejected") or []:
            for code in draft["issues"]:
                bucket = caught if code in FACT_CODES else other_rejections
                bucket[code] = bucket.get(code, 0) + 1
    evaluation = output["evaluation"]
    version = output.get("resume_version") or {}
    result.update({
        "valid": output["valid"], "pages": output["pages"], "engine": output["layout"]["engine"],
        "lines_used": output["layout"]["lines_used"], "capacity_lines": output["layout"]["capacity_lines"],
        **{k: evaluation[k] for k in ("factual_precision", "metric_precision", "technology_precision", "traceability",
                                      "conflict_leakage", "supported_jd_recall", "top_requirement_coverage",
                                      "evidence_utilization", "redundant_bullet_rate", "page_compliance",
                                      "template_fidelity", "style_score", "unsupported_claims")},
        "project_selection_recall": round(sum(p in on_page for p in fixture.get("expected_projects") or [])
                                          / len(fixture["expected_projects"]), 4) if fixture.get("expected_projects") else None,
        "used_disallowed_evidence": sorted(cited & must_not_use),
        "said_forbidden": said,
        "gaps_not_claimed": [g for g in gaps if not _said(text, g)],
        "gaps_reported": [g for g in gaps if any(_said(r["text"], g) for r in gap_rows)],
        "hallucinations_caught": caught, "length_or_form_rejections": other_rejections,
        "hallucinations_shipped": evaluation["unsupported_claims"] + len(said) + len(cited & must_not_use),
        "supported_but_not_used": [r["id"] for r in evaluation["supported_but_not_used"]],
        "resume_id": version.get("resume_id"), "pdf_checks_passed": (version.get("pdf_checks") or {}).get("passed"),
        "warnings": output["warnings"], "fit_log": output["fit_log"],
        "stages": output["stages"], "bullets": [{"id": b.id, "text": b.text, "evidence": b.evidence_ids,
                                                 "requirements": b.jd_requirement_ids} for b in bullets],
        "seconds": round(time.perf_counter() - started, 1),
    })
    return result


def failures(result: dict[str, Any]) -> list[str]:
    out = []
    if result.get("planned_disallowed_evidence"):
        out.append("plan selected disallowed evidence")
    if "valid" not in result:
        return out
    for key in HARD_GATES:
        if result.get(key) is not None and result[key] < 1:
            out.append(f"{key} {result[key]}")
    for key in ("conflict_leakage", "hallucinations_shipped"):
        if result.get(key):
            out.append(f"{key} {result[key]}")
    if result.get("page_compliance") != 1 or result.get("template_fidelity") != 1:
        out.append("page or template")
    if result.get("pdf_checks_passed") is False:
        out.append("pdf checks")
    if result.get("said_forbidden"):
        out.append("said " + ", ".join(result["said_forbidden"]))
    return out


def _mean(results: list[dict[str, Any]], key: str) -> float | None:
    values = [r[key] for r in results if isinstance(r.get(key), (int, float))]
    return round(sum(values) / len(values), 4) if values else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="JD parsing, retrieval and planning only")
    parser.add_argument("--only", nargs="*", help="fixture ids")
    args = parser.parse_args(argv)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = EVALS / "results" / stamp
    # Each run gets fresh jd.json caches and its own version store, so evals never touch real feedback or resumes.
    os.environ["CAREEROS_JD_CACHE"] = str(run_dir / "jd")
    os.environ["CAREEROS_COMPILER_DATA"] = str(run_dir / "data")
    from app.services.career_compiler import prompts
    from app.services.career_compiler.deepseek import DeepSeekClient
    from app.services.career_compiler.docx_template import load_spec, template_digest
    from app.services.career_compiler.query import QUERY_VERSION
    from app.services.career_compiler.retrieval import RETRIEVAL_VERSION
    from app.services.career_compiler.store import load_store
    from app.services.career_compiler.weights import weights

    offline = args.offline or not DeepSeekClient().configured
    spec = load_spec()
    meta = {"run": stamp, "mode": "offline" if offline else "live", "git": _git(),
            "model": "" if offline else DeepSeekClient().model, "prompt_versions": prompts.PROMPT_VERSIONS,
            "retrieval_version": RETRIEVAL_VERSION, "query_version": QUERY_VERSION,
            "template_version": template_digest(spec), "template_sha256": spec["golden"]["sha256"],
            "career_json_sha256": load_store().digest, "weights": weights()}
    results = []
    for fixture in fixtures(args.only):
        print(f"[{fixture['id']}] {fixture['category']} ...", flush=True)
        try:
            result = run_fixture(fixture, offline=offline)
        except Exception as exc:  # noqa: BLE001 - one broken fixture must not hide the others
            result = {"id": fixture["id"], "category": fixture["category"], "error": f"{type(exc).__name__}: {exc}"}
        result["failures"] = failures(result) + ([result["error"]] if "error" in result else [])
        results.append(result)
        print("   " + ("PASS" if not result["failures"] else "FAIL: " + "; ".join(result["failures"])), flush=True)
    keys = ["jd_parsing_recall", "evidence_retrieval_recall", "project_retrieval_recall", "plan_project_recall"]
    if not offline:
        keys += ["project_selection_recall", "factual_precision", "metric_precision", "technology_precision",
                 "traceability", "supported_jd_recall", "top_requirement_coverage", "evidence_utilization",
                 "redundant_bullet_rate", "style_score", "page_compliance", "template_fidelity"]
    summary = {k: _mean(results, k) for k in keys}
    if not offline:
        summary["hallucinations_shipped"] = sum(r.get("hallucinations_shipped") or 0 for r in results)
        summary["hallucinations_caught"] = sum(sum((r.get("hallucinations_caught") or {}).values()) for r in results)
        summary["length_or_form_rejections"] = sum(sum((r.get("length_or_form_rejections") or {}).values()) for r in results)
        summary["conflict_leakage"] = sum(r.get("conflict_leakage") or 0 for r in results)
    summary["passed"] = sum(1 for r in results if not r["failures"])
    summary["fixtures"] = len(results)
    report = {"meta": meta, "summary": summary, "results": results}
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (EVALS / "results" / "latest.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n" + json.dumps({"meta": {k: meta[k] for k in ("mode", "model", "retrieval_version", "query_version",
                                                           "template_version", "git")}, "summary": summary}, indent=2))
    print(f"\nFull report: {run_dir / 'report.json'}")
    return 0 if summary["passed"] == summary["fixtures"] else 1


if __name__ == "__main__":
    sys.exit(main())
