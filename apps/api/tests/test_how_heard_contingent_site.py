""""Company careers page" never maps to a contractor-only career site.

Found on the 2026-10-30 night loop: a "How did you hear about us?" offers
"Contingent Workers Career Site" and "Website". The saved answer "Company
careers page" went through the generic option match, which paired it with the
contingent-workers site on the shared word "career". The candidate applied as
an employee through the public site, so the answer is "Website".
"""

from app.services.application_assistant.profile_answer_resolver import resolve_answer

OPTIONS = [
    "Agency", "Contingent Workers Career Site", "Direct contact from Acme Recruiter",
    "Events/Conferences", "Other", "Previously Worked for Acme", "Print Ad",
    "Referred by Employee", "Social Network", "University/College/School", "Website",
]
PROFILE = {
    "jobDiscoveryDefault": "Company careers page",
    "screeningAnswers": [
        {
            "id": "how_heard",
            "question": "How did you hear about this job?",
            "answer": "Company careers page",
            "matchPatterns": [r"how\ did\ you\ hear\ about\ us\?"],
        }
    ],
}


def test_gsk_how_heard_picks_website_not_contingent_workers_site():
    assert resolve_answer("How did you hear about us?", PROFILE, options=OPTIONS).answer == "Website"


def test_plain_careers_page_option_still_wins():
    opts = ["LinkedIn", "Acme Careers Page", "Referral", "Other"]
    assert resolve_answer("How did you hear about us?", PROFILE, options=opts).answer == "Acme Careers Page"
