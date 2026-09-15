"""Deterministic hard filter & AI ranking engine for Autopilot jobs."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.services.application_assistant.domain import AutopilotJobStatus
from app.services.application_assistant.persistence import list_autopilot_jobs
from app.services.application_assistant.qwen_job_match import evaluate_job_match


DEFAULT_MIN_MATCH_SCORE = 75.0
DEFAULT_MAX_POST_AGE_DAYS = 7
DEFAULT_MAX_APPLICATIONS_PER_RUN = 25


def normalize_title(title: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", title.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_company(company: str) -> str:
    cleaned = re.sub(r"(inc|llc|corp|corporation|ltd|co)\b", "", company.lower(), flags=re.I)
    cleaned = re.sub(r"[^\w\s]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def normalize_location(location: str) -> str:
    cleaned = re.sub(r"[^\w\s]", "", (location or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def generate_composite_job_key(
    company: str, title: str, app_url: str = "", external_id: str = "", location: str = "",
) -> str:
    norm_c = normalize_company(company)
    norm_t = normalize_title(title)
    if external_id:
        return f"{norm_c}::{norm_t}::{external_id.lower().strip()}"
    if app_url:
        from urllib.parse import urlparse
        parsed = urlparse(app_url)
        clean_url = f"{parsed.netloc}{parsed.path}".rstrip("/")
        return f"{norm_c}::{norm_t}::{clean_url}"
    # Neither a job id nor a URL to key on — the weakest signal available, so
    # location is folded in here (and only here) as an extra dimension. It is
    # deliberately left out of the id/url branches above: those already
    # identify one specific posting, and a posting stored with location
    # missing on one copy but not the other must not be treated as a
    # different job just because that field is inconsistently populated.
    return f"{norm_c}::{norm_t}::{normalize_location(location)}"


def build_existing_key_index(existing_jobs: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Composite key -> set of statuses, computed once instead of per candidate.

    ``evaluate_hard_filters`` used to recompute every existing job's composite
    key from scratch (two regex substitutions plus a urlparse) on every single
    call, inside a loop over every candidate job — O(candidates x existing).
    With a few hundred candidates against ~2,000 existing jobs that is enough
    string processing to peg a CPU core for tens of seconds per refill cycle
    and stall the whole (single-worker) API process for every other request.
    Building this index once per batch turns the check into an O(1) lookup.
    """
    index: dict[str, set[str]] = {}
    for existing in existing_jobs:
        key = generate_composite_job_key(
            existing.get("company") or "",
            existing.get("title") or "",
            existing.get("applicationUrl") or "",
            existing.get("externalJobId") or "",
            existing.get("location") or "",
        )
        index.setdefault(key, set()).add(existing.get("status") or "")
    return index


def role_location_priority_bonus(job: dict[str, Any]) -> float:
    """Candidate-preference ranking bonus implementing strict 4-tier priority:

    Tier 1 (+120.0): Senior Software Engineer in Washington State (Seattle, Bellevue, Redmond, Kirkland, WA)
    Tier 2 (+90.0):  Related Washington SWE/backend/platform role at any level
    Tier 3 (+60.0):  Senior Software Engineer elsewhere in the United States (Remote US / Nationwide)
    Tier 4 (+25.0):  Rest / other qualifying US software engineering roles (e.g. SWE II, Platform)

    Location outranks seniority inside Washington deliberately: a related
    Washington engineering role is preferred over a Senior title somewhere else
    in the country. The bonus is added to the Mistral resume-match score, so
    within a tier the highest-matching posting still applies first.
    """
    title_l = (job.get("title") or "").lower()
    loc_l = (job.get("location") or "").lower()

    # If location is missing from autopilot job payload, check metadata or raw payload
    if not loc_l and "metadata" in job and isinstance(job["metadata"], dict):
        loc_l = (job["metadata"].get("location") or "").lower()

    # Non-software engineering roles must never receive SWE tier priority
    non_swe_markers = (
        "product manager", "program manager", "project manager", "sales engineer",
        "solution architect", "account executive", "designer", "recruiter", "talent",
        "marketing", "human resources", "counsel", "legal", "business analyst",
        "operations manager", "account manager",
    )
    if any(m in title_l for m in non_swe_markers):
        return 0.0

    # Location classification. "Washington, D.C." / "Washington, District of
    # Columbia" are the opposite side of the country from Washington State and
    # must never earn the top location tier — matching the bare substring
    # "washington" previously put D.C. postings at the head of the queue.
    is_dc = any(k in loc_l for k in (
        "district of columbia", "washington, d.c", "washington d.c",
        "washington, dc", "washington dc",
    ))
    is_wa = not is_dc and any(k in loc_l for k in (
        "seattle", "bellevue", "redmond", "kirkland", "spokane",
        "tacoma", ", wa", "wa,", "wa ", "washington",
    ))
    is_us = is_wa or is_dc or any(k in loc_l for k in (
        "united states", "usa", "u.s.", "remote", "us", "remote - us", "remote, us",
    ))

    # Role level classification
    above_senior_markers = (
        "staff", "principal", "distinguished", "fellow", "architect",
        "director", "head of", "vp", "vice president",
    )
    is_above_senior = any(k in title_l for k in above_senior_markers)

    is_senior = (
        any(k in title_l for k in ("senior", "sr.", "sr ", "sr-", "senior swe"))
        and any(k in title_l for k in (
            "software", "backend", "full stack", "frontend", "platform",
            "infrastructure", "systems", "cloud", "security", "data",
            "engineer", "developer",
        ))
        and not is_above_senior
    )

    is_staff_or_principal = (
        is_above_senior
        and any(k in title_l for k in ("staff", "principal"))
        and not any(k in title_l for k in ("director", "vp", "vice president", "head of"))
    )

    is_other_swe = (
        any(k in title_l for k in (
            "software", "backend", "back end", "full stack", "fullstack", "frontend",
            "front end", "platform", "infrastructure", "systems", "distributed",
            "engineer", "developer",
        ))
        and not is_senior
        and not any(re.search(rf"\b{k}\b", title_l) for k in ("intern", "internship", "co-op", "apprentice"))
    )

    # Tier 1: Senior Software Engineer in Washington State
    if is_senior and is_wa:
        return 120.0

    # Tier 2: Any related Washington engineering role — Staff/Principal, SWE II,
    # backend/platform/infrastructure. Preferred over an out-of-state Senior
    # title because relocation is the harder constraint here, not the level.
    if is_wa and (is_staff_or_principal or is_other_swe):
        return 90.0

    # Tier 3: Senior Software Engineer elsewhere in the United States
    if is_senior and is_us:
        return 60.0

    # Tier 4: Rest / other US engineering roles (Staff/Principal, SWE II, general SWE)
    if is_us and (is_staff_or_principal or is_other_swe):
        return 25.0

    return 0.0


def evaluate_hard_filters(
    job: dict[str, Any],
    profile: dict[str, Any],
    existing_jobs: list[dict[str, Any]] | dict[str, set[str]],
    settings: dict[str, Any] | None = None,
) -> tuple[bool, str]:
    """Perform deterministic pre-checks before executing AI match scoring.

    ``existing_jobs`` accepts either the raw job list (rebuilds the key index
    every call — fine for a one-off check) or a pre-built index from
    ``build_existing_key_index`` (O(1) lookup — required for any caller that
    invokes this per candidate in a loop; see that function's docstring).

    Returns (passed, skip_reason).
    """
    opts = settings or {}
    max_age_days = opts.get("maxPostAgeDays", DEFAULT_MAX_POST_AGE_DAYS)

    company = job.get("company") or ""
    title = job.get("title") or ""
    app_url = job.get("applicationUrl") or job.get("listingUrl") or ""
    external_id = job.get("externalJobId") or ""

    if not company or not title:
        return False, "Missing company or job title"

    # A posting with no URL — or one pointing at a careers *index* rather than a
    # specific job — can never be applied to. Without this the executor opens
    # the listing page, fills nothing, and fails with "Submit button not found",
    # burning a full browser session per attempt.
    if not app_url:
        return False, "Posting has no application URL"
    url_path, _, url_query = app_url.partition("?")
    if re.search(r"/(?:jobs|careers|openings|positions)/?$", url_path, flags=re.I):
        # Many boards keep the index path and identify the posting in the query
        # instead (`/en/jobs/?gh_jid=7849003`), so only a URL that names no job
        # anywhere is an index.
        if not re.search(r"=\d{3,}", url_query):
            return False, f"Application URL '{app_url}' is a careers index, not a specific posting"

    # 1. Duplicate Application Protection
    if not opts.get("allowDuplicates", False):
        existing_key_index = existing_jobs if isinstance(existing_jobs, dict) else build_existing_key_index(existing_jobs)
        location = job.get("location") or ""
        job_key = generate_composite_job_key(company, title, app_url, external_id, location)
        blocking_statuses = existing_key_index.get(job_key) or set()
        for ex_status in blocking_statuses:
            if ex_status in (
                AutopilotJobStatus.SUBMITTED.value,
                AutopilotJobStatus.APPLYING.value,
                AutopilotJobStatus.STAGED.value,
                "NEEDS_REVIEW",
                AutopilotJobStatus.QUEUED.value,
            ):
                return False, f"Duplicate application already in state: {ex_status}"

    # 2. Posting Recency Check
    date_posted_str = job.get("datePosted")
    if date_posted_str:
        try:
            posted_date = datetime.fromisoformat(date_posted_str.replace("Z", "+00:00"))
            if posted_date.tzinfo is None:
                posted_date = posted_date.replace(tzinfo=timezone.utc)
            cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
            if posted_date < cutoff:
                return False, f"Posting age exceeds limit ({max_age_days} days)"
        except Exception:
            pass

    # 3. Role Title Filter (Software Engineering Roles Only)
    title_lower = title.lower()
    swe_keywords = [
        "software engineer",
        "software developer",
        "full stack",
        "fullstack",
        "backend",
        "back end",
        "frontend",
        "front end",
        "platform engineer",
        "systems engineer",
        "infrastructure engineer",
        "distributed systems",
        "devops",
        "site reliability",
        "sre",
        "applications engineer",
        "application engineer",
        "swe",
        # Missing until 2026-09-15, and rejecting real postings in bulk: Esri,
        # Zscaler and others title the role "Software Development Engineer"
        # at every level, and "Full-Stack" is usually hyphenated.
        "software development engineer",
        "software engineer in test",
        "full-stack",
    ]
    # Short role codes and "product engineer" need word boundaries: "sde" must
    # not match inside another word, and "product engineer" must not pull in
    # "product security engineer" or any sales/presales title.
    swe_patterns = (r"\bsde\b", r"\bsdet\b", r"\bproduct engineer\b")
    is_swe_role = any(kw in title_lower for kw in swe_keywords) or any(
        re.search(pattern, title_lower) for pattern in swe_patterns
    )
    if not is_swe_role:
        return False, f"Role '{title}' is not a Software Engineering role"

    # Exclude internship / co-op / apprentice / student postings for experienced candidate
    intern_keywords = ("intern", "internship", "co-op", "apprentice", "working student", "fellowship")
    if any(re.search(rf"\b{kw}\b", title_lower) for kw in intern_keywords):
        return False, f"Role '{title}' is an internship or apprentice position"

    # 4. Location Filter (United States Positions Only)
    job_loc = (job.get("location") or "").lower()
    job_wp = (job.get("workplaceType") or "").lower()
    
    # Check for international non-US countries / locations to exclude
    non_us_indicators = [
        "poland", "warsaw", "krakow", "uk", "united kingdom", "london",
        "canada", "toronto", "vancouver", "germany", "berlin", "munich",
        "india", "bangalore", "hyderabad", "france", "paris", "brazil",
        "australia", "sydney", "singapore", "ireland", "dublin", "japan",
        "tokyo", "china", "emea", "apac", "latam", "mexico", "netherlands",
        "amsterdam", "spain", "madrid", "barcelona", "sweden", "stockholm",
        "chile", "argentina", "colombia", "turkey", "peru", "ecuador",
        "uruguay", "venezuela", "bolivia", "paraguay", "costa rica",
        "panama", "guatemala", "el salvador", "honduras", "nicaragua",
        "dominican republic", "bogota", "buenos aires", "santiago",
        "lima", "istanbul", "ankara", "sao paulo", "rio de janeiro",
        "portugal", "lisbon", "italy", "rome", "milan", "switzerland",
        "zurich", "austria", "vienna", "belgium", "brussels", "denmark",
        "copenhagen", "norway", "oslo", "finland", "helsinki", "israel",
        "tel aviv", "south africa", "philippines", "manila", "vietnam",
        "indonesia", "malaysia", "thailand", "south korea", "seoul",
        "new zealand", "egypt", "nigeria", "kenya", "uae", "dubai",
        "hungary", "budapest", "czech", "prague", "romania", "bucharest",
        "bulgaria", "sofia", "greece", "athens", "ukraine", "kyiv", "kiev",
        "serbia", "belgrade", "croatia", "slovakia", "slovenia", "lithuania",
        "latvia", "estonia", "tallinn", "riga", "vilnius", "pakistan",
        "bangladesh", "sri lanka", "morocco", "tunisia", "ghana", "taiwan",
        "hong kong", "saudi", "qatar", "jordan", "armenia", "georgia (country)",
    ]
    # Strong US evidence: phrases, full state names and major US cities, safe to
    # match as substrings. A location naming one of these is a US-eligible
    # posting even when it also lists other countries ("Remote, Canada; Remote,
    # United States", "Vienna, Virginia, United States", "SF, NY, Portland, or
    # Remote within US/Canada") - those were all rejected as non-US before.
    us_indicators = [
        "united states", "usa", "u.s.", "remote - us", "remote (us", "us remote",
        "remote in us", ", us", ", usa", "nyc", "new york city",
        "alabama", "alaska", "arizona", "arkansas", "california", "colorado",
        "connecticut", "delaware", "florida", "hawaii", "idaho", "illinois",
        "indiana", "iowa", "kansas", "kentucky", "louisiana", "maine", "maryland",
        "massachusetts", "michigan", "minnesota", "mississippi", "missouri",
        "montana", "nebraska", "nevada", "new hampshire", "new jersey",
        "new mexico", "new york", "north carolina", "north dakota", "ohio",
        "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina",
        "south dakota", "tennessee", "texas", "utah", "vermont", "virginia",
        "washington", "wisconsin", "wyoming",
        "seattle", "bellevue", "redmond", "austin", "san francisco", "boston",
        "los angeles", "chicago", "atlanta", "denver", "miami", "dallas",
        "houston", "phoenix", "philadelphia", "san diego", "san jose",
        "palo alto", "mountain view", "menlo park", "portland", "pittsburgh",
        "raleigh", "salt lake city", "minneapolis", "detroit", "nashville",
        "indianapolis",
    ]
    # Weak US evidence: state abbreviations and short city codes, matched as
    # whole tokens only ("Budapest, Hungary" contains "ga", "Poland" contains
    # "la"). Weak evidence alone never outweighs a named non-US place:
    # "Hyderabad, in" is India, not Indiana, and "CA-Ontario-Toronto" is Canada.
    us_state_abbr = {
        "al", "ak", "az", "ar", "ca", "co", "ct", "de", "fl", "ga", "hi", "id",
        "il", "in", "ia", "ks", "ky", "la", "me", "md", "ma", "mi", "mn", "ms",
        "mo", "mt", "ne", "nv", "nh", "nj", "nm", "ny", "nc", "nd", "oh", "ok",
        "or", "pa", "ri", "sc", "sd", "tn", "tx", "ut", "vt", "va", "wa", "wv",
        "wi", "wy", "dc", "us", "usa", "sf", "nyc",
    }
    # Locations that name no country at all. Treated like a bare "remote": the
    # posting is not known to be outside the US, so it is not rejected for it.
    ambiguous_location = re.compile(
        r"^\s*$|hybrid|in[- ]office|on[- ]?site|multiple locations|\b\d+\s+locations?\b|flexible",
        flags=re.I,
    )

    # Opt-in (profile.allowInternationalLocations): postings outside the United
    # States are no longer rejected at all. They still rank below every US
    # posting, because role_location_priority_bonus gives them no location tier.
    allow_international = str(profile.get("allowInternationalLocations", "")).strip().lower() in (
        "yes", "true", "1",
    )

    if job_loc or title_lower:
        strong_us = any(ind in job_loc for ind in us_indicators)
        tokens = {t.strip(" .;|()") for t in re.split(r"[,\s/\-]+", job_loc)} if job_loc else set()
        weak_us = bool(tokens & us_state_abbr)
        # "uk" is the one indicator short enough to hide inside ordinary words
        # ("Milwaukee", "Duke Energy"), so it only counts as a whole token.
        title_tokens = {t.strip(" .;|()") for t in re.split(r"[,\s/\-]+", title_lower)}
        names_non_us = any(
            country in job_loc or country in title_lower
            for country in non_us_indicators if country != "uk"
        ) or "uk" in tokens or "uk" in title_tokens

        if names_non_us and not strong_us and not allow_international:
            return False, f"Location '{job.get('location')}' is outside the United States"

        if job_loc and not names_non_us and not allow_international:
            has_us_marker = strong_us or weak_us or "remote" in job_loc or bool(ambiguous_location.search(job_loc))
            if not has_us_marker:
                return False, f"Location '{job.get('location')}' does not match United States criteria"

    # 5. Employment Type Constraints
    job_emp = (job.get("employmentType") or "").lower()
    pref_emp = (profile.get("preferredEmploymentType") or "").lower()
    if pref_emp and job_emp and pref_emp not in job_emp and "full" in pref_emp and "part" in job_emp:
        return False, f"Employment type mismatch: job is {job_emp}, preferred is {pref_emp}"

    profile_loc = (profile.get("location") or "").lower()
    remote_pref = profile.get("remoteOnly", False)

    if remote_pref and "remote" not in job_wp and "remote" not in job_loc:
        return False, "Job is not Remote, candidate requires Remote Only"

    # 6. US Citizenship & Visa Sponsorship / ITAR Defense Filter
    needs_sponsorship = (
        str(profile.get("sponsorship", "")).strip().lower() in ("yes", "true", "1")
        or str(profile.get("requiresSponsorship", "")).strip().lower() in ("yes", "true", "1")
    )
    is_us_citizen = str(profile.get("usCitizen", "")).strip().lower() in ("yes", "true", "1")

    norm_c = normalize_company(company)
    # Defense / aerospace contractors known to strictly require US citizenship under ITAR / EAR
    known_itar_defense_companies = {
        "anduril",
        "anduril industries",
        "spacex",
        "lockheed",
        "lockheed martin",
        "northrop",
        "northrop grumman",
        "raytheon",
        "rtx",
        "general dynamics",
        "boeing defense",
        "l3harris",
        "bae systems",
        "sierra nevada",
        "palantir defense",
    }
    if any(c in norm_c for c in known_itar_defense_companies):
        return False, f"Company '{company}' is a Defense/ITAR contractor (excluded per user preference)"

    # Exclude boards with hard bot protection that block automated headless runs
    #
    # Live-tested 2026-09-14 rather than trusted as a static guess (see git
    # history for the brief window this was disabled). Two lines of evidence
    # that DISAGREE, both real:
    #  1. CareerOS's own stealth Playwright browser hit an identical,
    #     reproducible `Timeout 60000ms exceeded` on page.goto across 3 real
    #     attempts against 2 queued postings, hanging with no progress until
    #     manually recovered each time - eventually settling on "no
    #     application form on the posting page".
    #  2. A plain manual Chrome session (not Playwright, no stealth args) hit
    #     a genuinely current Roblox posting - found by browsing Roblox's own
    #     live listings, not from the queue - and its real Greenhouse-hosted
    #     apply form (Resume/CV, Cover Letter, Legal Name...) loaded
    #     instantly with zero CAPTCHA/Turnstile/any bot-challenge visible.
    # So "Roblox uses Cloudflare Turnstile" (the original reason this block
    # existed) is likely just wrong - nothing challenged a normal browser.
    # The two automation postings tested were both from days-old discovery
    # batches and may simply have been expired/closed (one confirmed
    # redirecting to the generic careers page on manual navigation), which
    # would also explain a slow/odd load rather than an active bot-wall. This
    # was not re-isolated against a known-fresh posting through CareerOS's
    # own automation before time ran out, so the real cause (stale queue
    # entries vs. a genuine stealth-browser-specific load issue on this
    # board) is still open - see NIGHT_BATCH_DECISIONS.md. Re-enabling the
    # block for now since every real automation attempt failed, but the
    # reason is deliberately about the *symptom*, not a false "bot
    # protection" claim - a future session re-testing against a fresh
    # posting id could resolve this properly.
    # One specific, deliberate exception: job 8127056 (Senior Software
    # Engineer - Desktop) is a known-fresh, known-open posting confirmed by
    # hand to have no bot-challenge - added 2026-09-14 to get one clean,
    # confound-free automation result through CareerOS's own pipeline
    # (the earlier 3 test attempts both used likely-expired postings, so the
    # timeout cause was never actually isolated). Remove this once that
    # result is in - it is not meant to stand as a permanent carve-out.
    _ROBLOX_TEST_EXCEPTION_URLS = ("careers.roblox.com/jobs/8127056",)
    if "roblox" in norm_c and not any(u in app_url for u in _ROBLOX_TEST_EXCEPTION_URLS):
        return False, "Roblox's Greenhouse-hosted apply form reliably times out in CareerOS's automation (verified live 2026-09-14); a manual browser hit no challenge on a current posting, so this is unconfirmed as an actual bot-wall - see NIGHT_BATCH_DECISIONS.md"
    if "okta" in norm_c:
        return False, "Okta uses reCAPTCHA verification"

    if needs_sponsorship and not is_us_citizen:

        # Check job description and title text for ITAR and citizenship restrictions
        full_text = f"{title} {job.get('description', '')} {job.get('requirements', '')}".lower()
        itar_patterns = [
            r"\b(?:itar|ear)\b",
            r"\bu\.?s\.?\s+citizenship\s+required\b",
            r"\bu\.?s\.?\s+citizens?\s+only\b",
            r"\bsecurity clearance\b",
            r"\bclearance eligibility\b",
            r"\bu\.?s\.?\s+person\s+(?:status\s+)?required\b",
            r"\bmust be a (?:u\.s\.\s+)?person\b",
            r"\bexport control(?:led)?\b",
            r"\bno (?:visa )?sponsorship\b",
            r"\bnot (?:able to )?sponsor\b",
            r"\bunable to sponsor\b",
            r"\bwithout (?:visa )?sponsorship\b",
        ]
        for pat in itar_patterns:
            if re.search(pat, full_text, flags=re.I):
                return False, f"Position requires U.S. Citizenship / clearance or does not sponsor visas ({pat})"

    return True, ""


# How much a brand-new posting outranks an otherwise identical old one, and how
# quickly that advantage decays. Freshness is worth less than the
# location/level tier (hundreds of points) but comparable to a few points of
# match score, so it breaks ties between similar jobs without ever promoting a
# poorly-matched posting over a well-matched one.
RECENCY_BONUS_MAX = 12.0
RECENCY_HALF_LIFE_HOURS = 48.0


def posting_recency_bonus(job: dict[str, Any]) -> float:
    """Extra priority for a recently discovered/posted job.

    Stale postings are the single biggest source of wasted attempts: a job
    discovered a day or two ago is frequently already closed by the time
    Autopilot reaches it, which burns a full browser session to learn the link
    now redirects to a careers directory. Ordering the freshest postings first
    means the queue spends its attempts where they can still succeed, and older
    entries are worked through afterwards rather than never.
    """
    from datetime import datetime, timezone

    stamp = (
        job.get("postedAt")
        or job.get("discoveredAt")
        or job.get("queuedAt")
        or job.get("createdAt")
    )
    if not stamp:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0
    if age_hours <= 0:
        return RECENCY_BONUS_MAX
    # Halve the bonus for every half-life the posting has aged.
    return RECENCY_BONUS_MAX * (0.5 ** (age_hours / RECENCY_HALF_LIFE_HOURS))


# A posting genuinely put up by the employer within this window jumps ahead
# of the entire rest of the queue - tier, match score, everything - on the
# theory that a same-day posting has the least competition and the best odds
# if applied to first. Deliberately gated on the real `datePosted` a source
# reported, not on when *we* discovered it: those are different claims (a
# job discovered today could have been posted weeks ago and only just
# surfaced by a scraper's pagination), and only real-posting-date sources
# should get this override. Most sources don't currently populate it, so
# most postings are unaffected and fall through to the normal scoring below.
FRESH_POSTING_WINDOW_HOURS = 24.0
# Comfortably larger than role_location_priority_bonus's documented "hundreds
# of points" ceiling, so this always wins regardless of tier or match score.
FRESH_POSTING_OVERRIDE_BONUS = 100_000.0


def _is_senior_software_engineer_title(job: dict[str, Any]) -> bool:
    """The fresh-posting override is restricted to this one title band by
    explicit request: a same-day posting jumping the entire queue is a
    strong effect, and without a title gate it would apply just as hard to
    a new-grad or unrelated-title posting that merely happened to be fresh.
    Matches "senior software engineer" as a substring so natural variations
    ("Senior Software Engineer II", "Senior Software Engineer, Platform")
    still qualify, but a plain "Software Engineer" or "Staff Software
    Engineer" does not.
    """
    return "senior software engineer" in (job.get("title") or "").lower()


def _real_posting_age_hours(job: dict[str, Any]) -> float | None:
    """Hours since the job's real, source-reported `datePosted` - or None
    when that field is missing/unparseable, meaning this source never told
    us when the posting actually went up and there is nothing honest to act
    on (see the ingest-side fix in queue_preprocessor.py's
    _ingest_scraper_snapshot for why this was reliably blank before)."""
    stamp = job.get("datePosted")
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - parsed).total_seconds() / 3600.0


def queue_priority_score(job: dict[str, Any]) -> float:
    """The single number the persistent queue is ordered by.

    A verified same-day posting overrides everything else first (see
    FRESH_POSTING_OVERRIDE_BONUS). Below that: location/level tier dominates
    (see ``role_location_priority_bonus``), the Mistral resume-match score
    orders postings inside a tier, and a decaying recency bonus puts the
    freshest postings first so the queue does not spend its attempts on
    links that have already closed.
    """
    age_hours = _real_posting_age_hours(job)
    fresh_override = (
        FRESH_POSTING_OVERRIDE_BONUS
        if age_hours is not None
        and 0.0 <= age_hours <= FRESH_POSTING_WINDOW_HOURS
        and _is_senior_software_engineer_title(job)
        else 0.0
    )
    return (
        fresh_override
        + role_location_priority_bonus(job)
        + float(job.get("matchScore") or 0.0)
        + posting_recency_bonus(job)
    )


def filter_and_rank_jobs(
    db: Session | list[dict[str, Any]],
    raw_jobs: list[dict[str, Any]],
    profile: dict[str, Any],
    settings: dict[str, Any] | None = None,
    *,
    precomputed_matches: dict[str, dict[str, Any]] | None = None,
    documents: dict[str, Any] | None = None,
    accomplishments: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Process a list of discovered jobs:

    1. Run hard filters (deterministic)
    2. Attach the Mistral/Ollama resume-vs-JD match (precomputed by the queue
       preprocessor, or scored inline here when the caller has none)
    3. Filter by min match score threshold (with fallback so batch queue never starves)
    4. Sort by location/level tier, then match score, then date posted

    ``maxApplicationsPerRun``/``targetProcessCount`` of 0 (or absent) means *no
    limit* — the persistent queue is deliberately unbounded, and only the E2E
    submission count is capped.
    """
    opts = settings or {}
    min_score = float(opts.get("minMatchScore") or 0.0)
    max_apps = int(opts.get("maxApplicationsPerRun") or opts.get("targetProcessCount") or 0)

    existing_jobs = db if isinstance(db, list) else list_autopilot_jobs(db)
    matches = precomputed_matches or {}
    all_passing: list[dict[str, Any]] = []

    # Built once instead of re-derived from existing_jobs on every candidate
    # (see build_existing_key_index's docstring - that reduced an O(candidates
    # x existing) hot loop to O(candidates + existing)). Updated below as each
    # candidate passes, so two copies of the same posting discovered in this
    # same raw_jobs batch (e.g. scraped twice across different search result
    # pages) are caught against each other too, not only against jobs that
    # already existed before this batch ran - a real gap that let the same
    # posting get queued and submitted twice.
    existing_key_index = build_existing_key_index(existing_jobs)

    # Load resume text / accomplishments for the heuristic-fallback path
    # below (only reached when a posting has no Mistral score) when the
    # caller didn't already supply them and a real DB session is on hand to
    # load them from. Without this, the deterministic fallback - the only
    # scoring path that runs while the local LLM is off - matched purely
    # against structured profile fields, blind to anything only mentioned in
    # the resume's own prose or in recorded accomplishments.
    if documents is None and accomplishments is None and not isinstance(db, list):
        try:
            from app.db.store import get_kv, list_entities
            documents = get_kv(db, "documents") or {}
            accomplishments = list_entities(db, "accomplishment")
        except Exception:
            documents, accomplishments = {}, []

    for job in raw_jobs:
        passed, skip_reason = evaluate_hard_filters(job, profile, existing_key_index, opts)
        manual_reason: tuple[Any, str] | None = None
        if not passed:
            # A hard-filter rejection is not always a dead end. A board behind a
            # CAPTCHA is live and perfectly submittable by hand - the challenge
            # exists to stop automation, and must never be defeated, but the
            # user works these by hand and wants to see them.
            #
            # The runner already routes these to MANUAL_REVIEW once they are in
            # the queue. They were never getting there: selection dropped them
            # first, so the classifier downstream never saw them. 188 real
            # postings were excluded this way.
            from app.services.application_assistant.ineligibility import (
                MANUAL_REASONS,
                classify_ineligibility,
            )

            classified = classify_ineligibility({**job, "skipReason": skip_reason})
            if classified and classified[0] in MANUAL_REASONS:
                manual_reason = classified
            else:
                continue

        match = matches.get(str(job.get("id") or "")) or job.get("mistralMatch")
        if isinstance(match, dict) and match.get("matchScore") is not None:
            score = float(match.get("matchScore") or 0.0)
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": match.get("matchReason", ""),
                "keyMatchingSkills": match.get("keyMatchingSkills") or [],
                "missingSkills": match.get("missingSkills") or [],
                "matchMethod": match.get("matchMethod", "ollama-local"),
                "matchModel": match.get("matchModel", ""),
                # Kept so existing UI/reporting that reads matchReasons still
                # renders something meaningful now that the real explanation is
                # a sentence rather than a bag of keywords.
                "matchReasons": (match.get("keyMatchingSkills") or [])[:8],
                "status": AutopilotJobStatus.SCORED.value,
            }
        else:
            # No Mistral score available (Ollama down, or not preprocessed yet).
            # Fall back to the deterministic heuristic and label it honestly so
            # nothing downstream reports a heuristic number as a model match.
            match_result = evaluate_job_match(
                job=job, profile=profile, documents=documents, accomplishments=accomplishments,
            )
            score = float(match_result.get("overallScore", 0.0))
            ranked_job = {
                **job,
                "matchScore": score,
                "matchReason": match_result.get("explanation", "") or "Heuristic keyword match (Mistral unavailable).",
                "keyMatchingSkills": match_result.get("strongMatches", [])[:8],
                "missingSkills": match_result.get("missingQualifications", [])[:8],
                "matchMethod": "heuristic",
                "matchReasons": match_result.get("strongMatches", []) + match_result.get("potentialConcerns", []),
                "status": AutopilotJobStatus.SCORED.value,
            }

        if manual_reason is not None:
            # Carried in as a real opportunity, flagged so the automation never
            # spends a browser session trying to drive a board it cannot.
            from app.services.application_assistant.ineligibility import apply_ineligibility

            apply_ineligibility(ranked_job, manual_reason[0], manual_reason[1])

        ranked_job["queuePriority"] = queue_priority_score(ranked_job)
        all_passing.append(ranked_job)

        # Mark this candidate as taken immediately, not just on the next call
        # into this function - otherwise the same posting appearing twice in
        # this same raw_jobs batch (a duplicate scrape, not a duplicate DB
        # row) passes the hard filter both times and gets queued twice.
        if not opts.get("allowDuplicates", False):
            dup_key = generate_composite_job_key(
                job.get("company") or "",
                job.get("title") or "",
                job.get("applicationUrl") or job.get("listingUrl") or "",
                job.get("externalJobId") or "",
                job.get("location") or "",
            )
            existing_key_index.setdefault(dup_key, set()).add(AutopilotJobStatus.QUEUED.value)

    # Sort descending by queue priority (tier bonus + match score), then datePosted
    all_passing.sort(key=lambda j: (j.get("queuePriority", 0.0), j.get("datePosted") or ""), reverse=True)

    # minMatchScore orders the queue; it does not remove anything from it.
    #
    # This used to drop every job below the bar whenever at least one job
    # cleared it, which threw away postings for two reasons that are both bad.
    # A job with no score is missing data, not a poor match - when the local
    # model is down or returns unparseable output the score is absent, and
    # filtering on a field that defaults to 0.0 deleted real postings for a
    # reason that had nothing to do with the job. And a genuinely low score is
    # a judgement from a small local model that is often wrong; the user works
    # these lists by hand and may well want to apply anyway.
    #
    # Nothing here weakens the submission bar: a low-scoring job still is not
    # auto-submitted, it just stays visible. Hard eligibility filters above
    # still exclude genuine dead ends.
    if min_score > 0:
        all_passing.sort(
            key=lambda j: (
                float(j.get("matchScore") or 0.0) >= min_score,
                j.get("queuePriority", 0.0),
                j.get("datePosted") or "",
            ),
            reverse=True,
        )

    return all_passing[:max_apps] if max_apps > 0 else all_passing
