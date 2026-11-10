"""A recipient name outside the console code page (e.g. 'Ő') must not crash the
outreach batch when stdout is redirected to a log on Windows (cp1252)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "email" / "send_recruiter_outreach_batch.py"


def test_dry_run_survives_non_cp1252_name(tmp_path: Path) -> None:
    emails = tmp_path / "emails.json"
    results = tmp_path / "campaigns.json"
    emails.write_text(
        json.dumps(
            [
                {
                    "company": "Acme",
                    "recruiterName": "Őrs Kovács",
                    "firstName": "Őrs",
                    "email": "ors@acme.example",
                    "subject": "Hello",
                    "body": "Hi Őrs,",
                }
            ]
        ),
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PYTHONIOENCODING": "cp1252",
        "GMAIL_USER": "dry-run@example.com",
        "GMAIL_APP_PASSWORD": "not-used-in-dry-run",
    }

    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--dry-run", "--emails", str(emails), "--results", str(results)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        timeout=60,
    )

    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    campaign = json.loads(results.read_text(encoding="utf-8"))[0]
    assert [r["status"] for r in campaign["results"]] == ["dry_run"]
