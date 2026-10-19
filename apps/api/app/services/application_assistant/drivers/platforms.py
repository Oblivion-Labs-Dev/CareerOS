"""Per-ATS driver implementations.

All are PREPARATION-ONLY. The generic Playwright fallback in the existing
executor stack stays the path for unknown ATSs; these drivers add deterministic
detection + question discovery + profile mapping on top of the shared scanner.

Per-platform quirks that remain unsupported are stated explicitly via
capabilities/quirks rather than silently attempted:

- Greenhouse: legacy, fully-guarded flow (existing autopilot). Declared here
  so the registry covers it; preparation helpers reuse the same scanner.
- Ashby/Lever/Workable/SmartRecruiters/Personio/Recruitee: public apply pages
  are standard HTML forms — question discovery works off the shared scanner;
  submission is NOT authorized from drivers.
- Workday/iCIMS/Oracle: heavy JS/portal UIs — the scanner cannot reliably read
  their DOM offline; these drivers declare question discovery as heuristic-only
  and route to REVIEW/MANUAL until a permitted browser run captures the page.
"""

from __future__ import annotations

from .base import ApplicationDriver, ApplicationDriverCapabilities

_GREENHOUSE = ApplicationDriverCapabilities(
    detect_ats=True,
    load_job=True,
    discover_questions=True,
    map_profile=True,
    upload_resume=True,
    fill_fields=True,
    validate=True,
    # submit_authorized=False at driver level: actual submission only ever
    # happens through the existing autopilot runner's guarded path.
    submit_authorized=False,
    verify_submission=False,
    browser_fallback=False,
)

# Standard HTML-form ATSs: scanner-based preparation, browser fallback for quirks.
_FORM_ATS = ApplicationDriverCapabilities(
    detect_ats=True,
    load_job=True,
    discover_questions=True,
    map_profile=True,
    upload_resume=True,
    fill_fields=True,
    validate=True,
    submit_authorized=False,
    verify_submission=False,
    browser_fallback=True,
)

# Portal ATSs with heavy JS: detection only until a permitted browser capture.
_PORTAL_ATS = ApplicationDriverCapabilities(
    detect_ats=True,
    load_job=True,
    discover_questions=False,
    map_profile=False,
    upload_resume=True,
    fill_fields=False,
    validate=False,
    submit_authorized=False,
    verify_submission=False,
    browser_fallback=True,
)

FALLBACK = ApplicationDriverCapabilities(
    detect_ats=False,
    load_job=True,
    discover_questions=True,
    map_profile=True,
    upload_resume=True,
    fill_fields=True,
    validate=True,
    submit_authorized=False,
    verify_submission=False,
    browser_fallback=True,
)


class GreenhouseDriver(ApplicationDriver):
    platform = "greenhouse"
    display_name = "Greenhouse"
    capabilities = _GREENHOUSE
    url_host_patterns = ("greenhouse.io", "grnh.se")

    def prepare(self, job, profile, **kwargs):
        prepared = super().prepare(job, profile, **kwargs)
        prepared.warnings.append(
            "Greenhouse submission/confirmation stays on the existing guarded "
            "autopilot path; drivers never click submit."
        )
        return prepared


class AshbyDriver(ApplicationDriver):
    platform = "ashby"
    display_name = "Ashby"
    capabilities = _FORM_ATS
    url_host_patterns = ("ashbyhq.com", "jobs.ashbyhq")


class LeverDriver(ApplicationDriver):
    platform = "lever"
    display_name = "Lever"
    capabilities = _FORM_ATS
    url_host_patterns = ("lever.co", "jobs.lever.co")


class WorkableDriver(ApplicationDriver):
    platform = "workable"
    display_name = "Workable"
    capabilities = _FORM_ATS
    url_host_patterns = ("workable.com", "apply.workable")


class SmartRecruitersDriver(ApplicationDriver):
    platform = "smartrecruiters"
    display_name = "SmartRecruiters"
    capabilities = _FORM_ATS
    url_host_patterns = ("smartrecruiters.com", "careers.smartrecruiters")


class PersonioDriver(ApplicationDriver):
    platform = "personio"
    display_name = "Personio"
    capabilities = _FORM_ATS
    url_host_patterns = ("jobs.personio", "personio.de")


class RecruiteeDriver(ApplicationDriver):
    platform = "recruitee"
    display_name = "Recruitee"
    capabilities = _FORM_ATS
    url_host_patterns = ("recruitee.com",)


class WorkdayDriver(ApplicationDriver):
    platform = "workday"
    display_name = "Workday"
    capabilities = _PORTAL_ATS
    url_host_patterns = ("myworkdayjobs.com", "wd1.myworkdayjobs", "workday")

    def prepare(self, job, profile, **kwargs):
        prepared = super().prepare(job, profile, **kwargs)
        prepared.review_reasons.append(
            "Workday's dynamic portal DOM cannot be read reliably offline; "
            "question discovery requires a permitted browser capture."
        )
        if prepared.mode.name == "AUTO":
            prepared.mode = prepared.mode.__class__.REVIEW
        return prepared


class IcimsDriver(ApplicationDriver):
    platform = "icims"
    display_name = "iCIMS"
    capabilities = _PORTAL_ATS
    url_host_patterns = ("icims.com",)

    def prepare(self, job, profile, **kwargs):
        prepared = super().prepare(job, profile, **kwargs)
        prepared.review_reasons.append(
            "iCIMS portal forms require a permitted browser capture before "
            "fields can be discovered."
        )
        if prepared.mode.name == "AUTO":
            prepared.mode = prepared.mode.__class__.REVIEW
        return prepared


class OracleDriver(ApplicationDriver):
    platform = "oracle"
    display_name = "Oracle Recruiting"
    capabilities = _PORTAL_ATS
    url_host_patterns = ("oraclecloud.com", "taleo.net")

    def prepare(self, job, profile, **kwargs):
        prepared = super().prepare(job, profile, **kwargs)
        prepared.review_reasons.append(
            "Oracle Recruiting (HCM Cloud) forms require a permitted browser "
            "capture before fields can be discovered."
        )
        if prepared.mode.name == "AUTO":
            prepared.mode = prepared.mode.__class__.REVIEW
        return prepared


class GenericDriver(ApplicationDriver):
    """Permitted-Playwright fallback for any other careers page."""

    platform = "generic"
    display_name = "Generic Playwright fallback"
    capabilities = FALLBACK
    url_host_patterns = ()
