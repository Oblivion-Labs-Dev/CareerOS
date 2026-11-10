"""Top-3 recent roles, company mission and live-board fallback for recruiter outreach."""

from datetime import date

from app.services.recruiter_outreach_roles import (
    board_slug_candidates,
    extract_mission,
    parse_posted,
    tailor_emails,
)

TODAY = date(2026, 11, 10)

BODY = (
    "Hi Steve,\n\nI hope you're doing well.\n"
    "I'm reaching out because I'm starting to look at new opportunities, and Acme is one of the companies I wanted to reach out to.\n"
    "A few examples of the work I've done:\n\n"
    "•  Built enterprise security capabilities protecting more than 237K AI agents across 13K+ tenants.\n"
    "•  Designed distributed systems handling over 100K transactions per second.\n"
    "•  Built internal tooling that reduced service setup from weeks to hours.\n"
    "•  Led infrastructure improvements that reduced operational costs by more than $250K per month.\n"
    "One of the reasons I'm interested in Acme is scale.\n"
    "If you think my background could be a fit for any of your teams, I'd really appreciate the chance to talk.\n"
)
BACKEND = (
    "Requirements:\n- 5+ years building distributed systems and microservices in Java\n"
    "- Event-driven architecture with Kafka, NoSQL stores, Redis\n- SQL, API design, AWS\n"
)
ABOUT = (
    "About us: Acme's mission is to make every package arrive on time, everywhere.\n"
    "Acme is an equal opportunity employer and our mission includes accommodation for all applicants.\n"
)


def _job(title, desc=BACKEND, posted="2026-11-01T00:00:00Z"):
    slug = title.split()[-1].lower()
    return {"company": "Acme", "title": title, "description": desc, "datePosted": posted,
            "listingUrl": f"https://acme.example/{slug}", "active": "True"}


def _email(company="Acme", addr="s@acme.example"):
    return {"company": company, "email": addr, "subject": "s", "body": BODY}


def test_email_lists_top_three_recent_roles_and_quotes_company_mission():
    jobs = {"acme": [
        _job("Senior Software Engineer, Backend", BACKEND + ABOUT),
        _job("Senior Software Engineer, Platform", BACKEND + ABOUT),
        _job("Staff Software Engineer, Payments", BACKEND, posted="October  25, 2026"),
        _job("Senior Software Engineer, Infra", BACKEND + ABOUT),
        _job("Senior Software Engineer, Legacy", BACKEND, posted="2026-08-01"),  # older than 30 days
    ]}

    [out], unmatched = tailor_emails([_email()], jobs, min_score=0, today=TODAY)

    assert unmatched == []
    assert len(out["roles"]) == 3
    assert "Legacy" not in out["body"]
    role_lines = [line for line in out["body"].split("\n") if "(https://acme.example/" in line]
    assert len(role_lines) == 3 and all(line.startswith("•  ") for line in role_lines)
    assert "fit for one of these roles, or another team at Acme" in out["body"]
    assert out["mission"] == "its mission to make every package arrive on time"
    assert "What draws me to Acme is its mission to make every package arrive on time." in out["body"]
    assert "is scale" not in out["body"]
    assert out["subject"] == f"Senior Software Engineer at Microsoft | {out['role']} at Acme"
    # resume highlights stay intact (4 bullets) next to the 3 role bullets
    assert sum(1 for line in out["body"].split("\n") if line.startswith("•")) == 7


def test_resume_highlights_reordered_even_with_role_bullets():
    jobs = {"acme": [_job("Senior Software Engineer, Backend"), _job("Senior Software Engineer, Platform")]}
    [out], _ = tailor_emails([_email()], jobs, min_score=0, today=TODAY)
    highlights = [line for line in out["body"].split("\n")
                  if line.startswith("•") and "(https://acme.example/" not in line]
    assert len(highlights) == 4
    assert "100K transactions" in highlights[0]


def test_no_mission_in_postings_keeps_original_why_line():
    jobs = {"acme": [_job("Senior Software Engineer, Backend")]}
    [out], _ = tailor_emails([_email()], jobs, min_score=0, today=TODAY)
    assert out["mission"] is None
    assert "One of the reasons I'm interested in Acme is scale." in out["body"]


def test_extract_mission_skips_eeo_boilerplate_and_team_missions():
    jobs = [{"description": "We are an equal opportunity employer and our mission is fairness for every candidate. "
                            "The team's mission is to ship faster builds for engineers."}]
    assert extract_mission(jobs, "Acme") is None


def test_extract_mission_prefers_company_mission_then_self_description():
    # Shapes seen in real DoorDash / Airbnb / Samsara postings.
    dd = [{"description": "At DoorDash, our mission to empower local economies shapes how our team members move quickly."}] * 3
    dd += [{"description": "Our mission is to increase the velocity of business impact from GenAI."}]
    assert extract_mission(dd, "DoorDash") == "its mission to empower local economies"
    abnb = [{"description": "Airbnb is a mission-driven company dedicated to helping create a world where anyone can belong anywhere."}]
    assert extract_mission(abnb, "Airbnb") == "its mission to help create a world where anyone can belong anywhere"
    sam = [{"description": "Samsara (NYSE: IOT) is the pioneer of the Connected Operations� Cloud, which is a platform."}]
    assert extract_mission(sam, "Samsara") == "the work itself: Samsara is the pioneer of the Connected Operations Cloud"


def test_parse_posted_formats():
    assert parse_posted("2026-11-01T10:00:00.123+00:00") == date(2026, 11, 1)
    assert parse_posted("October  9, 2026") == date(2026, 10, 9)
    assert parse_posted(1762300800000) == date(2025, 11, 5)
    assert parse_posted("") is None and parse_posted("soon") is None


def test_live_lookup_used_only_when_db_has_no_jobs_and_failure_is_recorded():
    calls = []

    def live(company, email):
        calls.append((company, email))
        if company == "Broken":
            raise RuntimeError("timeout")
        return [_job("Senior Software Engineer, Backend")]

    emails = [_email(), _email("Newco", "n@newco.io"), _email("Broken", "b@broken.io")]
    out, unmatched = tailor_emails(emails, {"acme": [_job("Senior Software Engineer, Backend")]},
                                   min_score=0, live_lookup=live, today=TODAY)

    assert calls == [("Newco", "n@newco.io"), ("Broken", "b@broken.io")]
    assert [e["roleSource"] for e in out] == ["db", "live_board", "live board lookup failed: timeout"]
    assert unmatched == ["Broken"] and out[2]["body"] == BODY


def test_board_slug_candidates_from_name_and_domain():
    assert board_slug_candidates("Zillow Group", "a@zillowgroup.com") == ["zillowgroup", "zillow-group"]
    assert board_slug_candidates("Bitwarden", "x@bitwarden.com") == ["bitwarden"]
    assert board_slug_candidates("Open AI", "x@openai.com") == ["openai", "open-ai"]
