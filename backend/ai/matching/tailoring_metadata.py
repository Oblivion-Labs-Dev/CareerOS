"""Source-grounded metadata for resume previews."""

import math


def job_match_score(job):
    value = job.get("matchScore")
    if value is None:
        value = job.get("score")
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return 0.0
    return min(100.0, max(0.0, float(value)))


def authorization_summary(profile):
    auth = profile.get("workAuth") or {}
    authorized = auth.get("authorizedToWorkInUS")
    sponsorship = auth.get("requiresSponsorshipNowOrFuture")
    parts = []
    if authorized is True:
        parts.append("Authorized to work in the United States")
    elif authorized is False:
        parts.append("Not currently authorized to work in the United States")
    else:
        parts.append("Work authorization not provided")
    if sponsorship is True:
        parts.append("requires sponsorship now or in the future")
    elif sponsorship is False:
        parts.append("does not require sponsorship now or in the future")
    else:
        parts.append("sponsorship requirement not provided")
    return "; ".join(parts)
