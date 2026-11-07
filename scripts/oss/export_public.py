"""Build the public, open-source snapshot of CareerOS from this private repository.

The private repository keeps the author's own data (resume corpora, outreach
lists, backups, night-batch reports). The public copy is a fresh tree with no
git history, made like this:

1. Take the committed tree at ``--ref`` (default HEAD) with ``git archive``.
2. Drop every path matched by EXCLUDE.
3. Copy the files under ``scripts/oss/public/`` over the tree (neutral
   ranking preset, empty corpora, public AGENTS.md, ...).
4. Rewrite the author's identity to a fictional sample persona (SUBSTITUTIONS,
   plus FILE_SUBSTITUTIONS for the benchmark resume).
5. Scan every file for the author's identity (LEAK_PATTERNS). Any hit, or any
   unreviewed binary document, fails the export and the output is left for
   inspection, never published.
6. Optionally (``--run-tests``) run the API test suite inside the export.

Nothing is pushed or published. ``--init-git`` makes one local commit in the
output folder so a human can review it and push it themselves.

    python scripts/oss/export_public.py --out ../CareerOS-public --run-tests
"""

from __future__ import annotations

import argparse
import fnmatch
import io
import re
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OVERRIDES = Path(__file__).resolve().parent / "public"

# Paths (fnmatch, relative, forward slashes) left out of the public tree.
EXCLUDE = [
    # Private data, reports and the export tooling itself.
    "backups/*", "agent/*", "tasks/*", "scratch/*", "tools/*", "scripts/oss/*",
    ".agents/*", ".evolution/*", ".serena/*",
    "NIGHT_BATCH_DECISIONS.md", "RESUME-GAPS.md", "CLAUDE.md",
    "data/benchmark_results.json", "data/profile/*",
    "docs/screenshots/*", "docs/product-audit-*", "docs/production-readiness-*",
    "docs/resume-corpus-completion-report.md", "docs/resume-match-audit.md",
    "docs/ui-redesign-plan-*", "docs/implementation-prompt.md", "docs/migration-from-arsenal.md",
    "docs/autopilot-hardening-worklist.md", "docs/job-preferences.md",
    "apps/api/scripts/email/*.json",
    # The author's one-off email generators (their Downloads folder and lists).
    "apps/api/scripts/email/generate_csv_recruiter_emails.py",
    "apps/api/scripts/email/generate_personalized_recruiter_emails.py",
    "scripts/nightloop-sentinel.ps1", "scripts/evolution-scheduler.ps1",
    "scripts/backup_encrypted.py", "scripts/seed_user_answers.py",
    # One-off debugging scripts at the top of the repo and of apps/api.
    "*.txt", "dev-watchdog.bat", "restart-dev.bat",
]
# Top-level *.py and apps/api/*.py are ad-hoc scripts, not the product.
EXCLUDE_TOP_LEVEL_SCRIPTS = ("", "apps/api/")

# Ordered: longer tokens first so "Akshay Borse" is not split.
SUBSTITUTIONS: list[tuple[str, str]] = [
    ("amsborse+career@gmail.com", "alex.rivera@example.com"),
    ("amsborse@gmail.com", "alex.rivera@example.com"),
    ("amsborse.github.io", "alexrivera-sample.github.io"),
    ("finance-os-lilac.vercel.app", "portfolio.example.com"),
    ("amsborse", "alexrivera-sample"),
    ("Akshay_Borse", "Alex_Rivera"),
    ("akshay-one-page", "sample-one-page"),
    ("Akshay Borse", "Alex Rivera"),
    ("AKSHAY BORSE", "ALEX RIVERA"),
    ("Akshay", "Alex"), ("AKSHAY", "ALEX"), ("akshay", "alex"),
    ("Borse", "Rivera"), ("BORSE", "RIVERA"), ("borse", "rivera"),
    (r"D:\3 - Resources\Docs\Interview\Resume", r"C:\path\to\your\resume-folder"),
    (r"D:\3 - Resources", r"C:\path\to\your\files"),
]
_PHONE = re.compile(r"(\(?425\)?[\s.\-]?)336([\s.\-]?)9852")

# The benchmark persona carried the author's real resume; keep its structure
# (the benchmark cases stay grounded in it) with fictional employers.
_FICTIONAL_RESUME = [
    ("Microsoft Purview Insider Risk Management", "Northwind Sentinel"),
    ("Agent Adaptive Protection", "Agent Risk Controls"),
    ("Adaptive Protection", "Adaptive Risk Controls"),
    ("Insider Risk Management", "Risk Analytics"),
    ("Microsoft Purview", "Northwind Sentinel"), ("Purview", "Sentinel"),
    ("Microsoft", "Northwind Systems"), ("Amazon", "Contoso Cloud"),
    ("Northeastern University", "Lakeside State University"),
    ("University of Pune", "Riverside Institute of Technology"),
]
FILE_SUBSTITUTIONS: dict[str, list[tuple[str, str]]] = {
    "apps/api/app/services/application_assistant/benchmark_dataset.py": _FICTIONAL_RESUME,
    "apps/api/app/services/application_assistant/resume_diff_service.py": _FICTIONAL_RESUME,
    "apps/extension/scripts/resumeParser.test.js": _FICTIONAL_RESUME,
}

LEAK_PATTERNS = [
    re.compile(r"akshay", re.I),
    re.compile(r"(?<![a-z])borse", re.I),
    re.compile(r"amsborse", re.I),
    re.compile(r"finance-os-lilac", re.I),
    re.compile(r"336[\s.\-]?9852"),
    re.compile(r"D:\\3 - Resources", re.I),
    re.compile(r"Insider Risk Management|Adaptive Protection for", re.I),
]
# Binary documents can hold a real resume and cannot be scanned as text.
DOCUMENT_SUFFIXES = {".pdf", ".docx", ".doc", ".odt", ".rtf"}
BINARY_SUFFIXES = DOCUMENT_SUFFIXES | {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".woff2", ".ttf", ".zip",
}
# Binary documents reviewed by a human and known to hold no personal data.
REVIEWED_DOCUMENTS: set[str] = set()


def excluded(rel: str) -> bool:
    if any(fnmatch.fnmatch(rel, pat) for pat in EXCLUDE):
        return True
    for prefix in EXCLUDE_TOP_LEVEL_SCRIPTS:
        rest = rel[len(prefix):] if rel.startswith(prefix) else None
        if rest is not None and "/" not in rest and rest.endswith(".py"):
            return True
    return False


def rewrite(rel: str, text: str) -> str:
    for old, new in FILE_SUBSTITUTIONS.get(rel, []):
        text = text.replace(old, new)
    for old, new in SUBSTITUTIONS:
        text = text.replace(old, new)
    return _PHONE.sub(lambda m: f"{m.group(1)}555{m.group(2)}0142", text)


def rewrite_path(rel: str) -> str:
    for old, new in SUBSTITUTIONS:
        rel = rel.replace(old, new)
    return rel


def archive(ref: str) -> tarfile.TarFile:
    data = subprocess.run(
        ["git", "-C", str(REPO), "archive", "--format=tar", ref],
        check=True, capture_output=True,
    ).stdout
    return tarfile.open(fileobj=io.BytesIO(data))


def scan(out: Path) -> list[str]:
    problems: list[str] = []
    for path in sorted(p for p in out.rglob("*") if p.is_file()):
        rel = path.relative_to(out).as_posix()
        if rel.startswith(".git/"):
            continue
        for pat in LEAK_PATTERNS:
            if pat.search(rel):
                problems.append(f"{rel}: personal token in the path ({pat.pattern})")
        suffix = path.suffix.lower()
        if suffix in DOCUMENT_SUFFIXES and rel not in REVIEWED_DOCUMENTS:
            problems.append(f"{rel}: unreviewed binary document (add to REVIEWED_DOCUMENTS once checked)")
            continue
        if suffix in BINARY_SUFFIXES:
            continue
        text = path.read_bytes().decode("utf-8", errors="replace")
        for n, line in enumerate(text.splitlines(), 1):
            for pat in LEAK_PATTERNS:
                if pat.search(line):
                    problems.append(f"{rel}:{n}: matches {pat.pattern!r}")
    return problems


def build(ref: str, out: Path) -> dict[str, int]:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty; pass a new or empty folder")
    out.mkdir(parents=True, exist_ok=True)
    kept = dropped = 0
    with archive(ref) as tar:
        for member in tar.getmembers():
            if not member.isfile():
                continue
            if excluded(member.name):
                dropped += 1
                continue
            raw = tar.extractfile(member).read()  # type: ignore[union-attr]
            dest = out / rewrite_path(member.name)
            dest.parent.mkdir(parents=True, exist_ok=True)
            if Path(member.name).suffix.lower() in BINARY_SUFFIXES:
                dest.write_bytes(raw)
            else:
                try:
                    text = raw.decode("utf-8")
                except UnicodeDecodeError:
                    dest.write_bytes(raw)  # scanned below as best-effort text
                else:
                    dest.write_bytes(rewrite(member.name, text).encode("utf-8"))
            kept += 1
    overridden = 0
    for src in (p for p in OVERRIDES.rglob("*") if p.is_file()):
        dest = out / src.relative_to(OVERRIDES)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        overridden += 1
    return {"kept": kept, "dropped": dropped, "overridden": overridden}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="new or empty folder for the public tree")
    ap.add_argument("--ref", default="HEAD", help="git ref to export (committed content only)")
    ap.add_argument("--run-tests", action="store_true", help="run the API test suite in the export")
    ap.add_argument("--init-git", action="store_true", help="make one local commit in the export (never pushed)")
    args = ap.parse_args(argv)

    out = args.out.resolve()
    stats = build(args.ref, out)
    print(f"exported {stats['kept']} files, dropped {stats['dropped']}, overrides {stats['overridden']} -> {out}")

    problems = scan(out)
    if problems:
        print(f"LEAK SCAN FAILED: {len(problems)} problem(s); the export must not be published", file=sys.stderr)
        for p in problems[:200]:
            print("  " + p, file=sys.stderr)
        return 1
    print("leak scan: clean")

    if args.run_tests:
        res = subprocess.run(
            [sys.executable, "-m", "pytest", "tests", "-q", "-m", "not network", "-p", "no:cacheprovider"],
            cwd=out / "apps" / "api",
        )
        if res.returncode != 0:
            print("API tests FAILED in the export", file=sys.stderr)
            return res.returncode
    if args.init_git:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=out, check=True)
        subprocess.run(["git", "add", "."], cwd=out, check=True)
        subprocess.run(["git", "commit", "-q", "-m", "Initial public release"], cwd=out, check=True)
        print("local commit made; review it before pushing anywhere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
