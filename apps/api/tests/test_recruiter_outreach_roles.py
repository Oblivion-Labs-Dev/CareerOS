import json
import sqlite3

from app.services.recruiter_outreach_roles import load_open_jobs, rank_roles, tailor_emails

BODY = (
    "Hi Steve,\n\nI hope you're doing well.\n"
    "I'm reaching out because I'm starting to look at new opportunities, and Acme is one of the companies I wanted to reach out to.\n"
    "A few examples of the work I've done:\n\n"
    "•  Built enterprise security capabilities protecting more than 237K AI agents across 13K+ tenants.\n"
    "•  Designed distributed systems handling over 100K transactions per second.\n"
    "•  Built internal tooling that reduced service setup from weeks to hours.\n"
    "•  Led infrastructure improvements that reduced operational costs by more than $250K per month.\n"
    "If you think my background could be a fit for any of your teams, I'd really appreciate the chance to talk.\n"
)

BACKEND = (
    "Requirements:\n- 5+ years building distributed systems and microservices in Java\n"
    "- Event-driven architecture with Kafka, NoSQL stores, Redis\n- SQL, API design, AWS\n"
)


def _db(tmp_path, jobs):
    path = tmp_path / "career_os.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE entities (id TEXT, entity_type TEXT, payload TEXT, user_id TEXT)")
    for i, job in enumerate(jobs):
        conn.execute("INSERT INTO entities VALUES (?, 'aa_discovered_job', ?, NULL)", (str(i), json.dumps(job)))
    conn.commit()
    conn.close()
    return path


def test_email_names_best_fit_open_role_and_leads_with_relevant_bullet(tmp_path):
    db = _db(tmp_path, [
        {"company": "Acme", "title": "Senior Software Engineer, Backend", "description": BACKEND,
         "listingUrl": "https://acme.example/jobs/1", "active": "True"},
        {"company": "Acme", "title": "Senior Software Engineer, Backend", "description": BACKEND,
         "listingUrl": "https://acme.example/jobs/old", "active": "False"},
        {"company": "Acme", "title": "Senior Android Engineer", "description": "Kotlin, Android SDK",
         "active": "True"},
    ])
    email = {"company": "Acme", "email": "steve@acme.example", "subject": "old", "body": BODY}

    [out], unmatched = tailor_emails([email], load_open_jobs(db))

    assert unmatched == []
    assert out["roleMatched"] is True
    assert out["subject"] == "Senior Software Engineer at Microsoft | Senior Software Engineer, Backend at Acme"
    assert "I saw the Senior Software Engineer, Backend opening at Acme (https://acme.example/jobs/1)" in out["body"]
    assert "Android" not in out["body"]
    assert "fit for the Senior Software Engineer, Backend role" in out["body"]
    bullets = [line for line in out["body"].split("\n") if line.startswith("•")]
    assert "100K transactions" in bullets[0]
    assert len(bullets) == 4


def test_company_without_fitting_role_keeps_original_email(tmp_path):
    db = _db(tmp_path, [{"company": "Other", "title": "Senior Backend Engineer", "description": BACKEND,
                         "active": "True"}])
    email = {"company": "Acme", "email": "a@acme.example", "subject": "orig", "body": BODY}

    [out], unmatched = tailor_emails([email], load_open_jobs(db))

    assert unmatched == ["Acme"]
    assert out["roleMatched"] is False
    assert out["subject"] == "orig" and out["body"] == BODY


def test_company_name_uses_posting_spelling(tmp_path):
    # Real data: both the recruiter list and the scraped postings say "Doordash";
    # only the hand-written template body has the brand spelling.
    db = _db(tmp_path, [{"company": "Doordash", "title": "Senior Software Engineer, Backend",
                         "description": BACKEND, "active": "True"}])
    body = BODY.replace("If you think", "One of the reasons I'm interested in DoorDash is scale.\nIf you think")
    email = {"company": "Doordash", "email": "r@doordash.example", "subject": "s", "body": body}
    [out], _ = tailor_emails([email], load_open_jobs(db))
    assert out["subject"].endswith("at DoorDash")
    assert "opening at DoorDash" in out["body"] and "Doordash" not in out["body"]


def test_rank_roles_cleans_mojibake_and_dedupes_titles():
    jobs = [{"company": "Acme", "title": "Senior Software Engineer � Backend", "description": BACKEND}] * 2
    roles = rank_roles(jobs, min_score=0)
    assert [r.title for r in roles] == ["Senior Software Engineer - Backend"]
