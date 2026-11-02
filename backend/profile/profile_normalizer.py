"""Keep the profile's work-authorization facts consistent across every spelling.

The same fact is stored under several keys that grew up at different times:
a flat ``sponsorship`` string, a flat ``requiresSponsorship`` string, and the
structured ``workAuth.requiresSponsorshipNowOrFuture`` boolean. The answer
resolver reads the structured boolean and treats it as authoritative, so when
the flat keys said one thing and the nested boolean said another, the nested
value silently won.

That is not a cosmetic inconsistency. It was observed live: the candidate does
require visa sponsorship, the profile's nested boolean said ``false``, and
applications went out to employers answering "No" to "Now, or at any time in the
future, will you require sponsorship?" — a false statement of work-authorization
status made in the candidate's name.

This module runs on every profile save and collapses the spellings onto one
another so they cannot drift apart again. An explicit flat answer the user just
typed in the UI wins over a stale nested boolean, because the flat key is the
one the Profile form writes.
"""

from __future__ import annotations

from typing import Any

_TRUE_WORDS = {"yes", "true", "1", "y"}
_FALSE_WORDS = {"no", "false", "0", "n"}


def _tri_state(value: Any) -> bool | None:
    """Read a yes/no answer that may be a bool, a string, or absent.

    Returns None for anything that does not clearly say yes or no, so a blank
    field leaves the existing value alone instead of being read as "no".
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in _TRUE_WORDS:
        return True
    if text in _FALSE_WORDS:
        return False
    return None


def normalize_work_authorization(profile: dict[str, Any]) -> dict[str, Any]:
    """Return ``profile`` with its work-authorization keys agreeing.

    Precedence for "do you require sponsorship":
      1. a flat ``sponsorship`` / ``requiresSponsorship`` answer (what the
         Profile form writes when the user states the fact themselves),
      2. the existing ``workAuth.requiresSponsorshipNowOrFuture`` boolean,
      3. left untouched when neither says anything definite.

    The same treatment is given to "are you authorized to work in the US",
    which is a genuinely independent fact: a candidate can be authorized today
    and still need sponsorship to continue, so neither answer may be derived by
    negating the other.
    """
    updated = dict(profile)
    work_auth = dict(updated.get("workAuth") or {})

    sponsorship = _tri_state(updated.get("sponsorship"))
    if sponsorship is None:
        sponsorship = _tri_state(updated.get("requiresSponsorship"))
    if sponsorship is None:
        sponsorship = _tri_state(work_auth.get("requiresSponsorshipNowOrFuture"))

    if sponsorship is not None:
        work_auth["requiresSponsorshipNowOrFuture"] = sponsorship
        updated["sponsorship"] = "Yes" if sponsorship else "No"
        updated["requiresSponsorship"] = "Yes" if sponsorship else "No"
        # Needing sponsorship at any point and holding permanent authorization
        # are mutually exclusive, and the resolver answers a separate question
        # from this key. Keeping a stale True here would tell an employer the
        # candidate needs no future sponsorship right after telling them they do.
        if sponsorship:
            work_auth["permanentWorkAuthorization"] = False

    authorized = _tri_state(updated.get("workAuthorization"))
    if authorized is None:
        authorized = _tri_state(updated.get("authorizedToWorkInUS"))
    if authorized is None:
        authorized = _tri_state(work_auth.get("authorizedToWorkInUS"))
    if authorized is not None:
        work_auth["authorizedToWorkInUS"] = authorized
        updated["authorizedToWorkInUS"] = "Yes" if authorized else "No"
        updated["workAuthorization"] = "Yes" if authorized else "No"

    citizen = _tri_state(updated.get("usCitizen"))
    if citizen is None:
        citizen = _tri_state(work_auth.get("usCitizen"))
    if citizen is not None:
        work_auth["usCitizen"] = citizen
        updated["usCitizen"] = "Yes" if citizen else "No"

    if work_auth:
        updated["workAuth"] = work_auth

    # Saved screening answers outrank the structured profile in the resolver
    # (resolution_method PROFILE_SCREENING_ANSWER wins over
    # PROFILE_OPTION_MAPPING), so a stale one silently overrides the fact the
    # user just corrected. Observed live: workAuth said sponsorship was
    # required, a saved answer still said "No", and the saved answer is what
    # went onto the form. Keep them in step.
    answers = updated.get("screeningAnswers")
    if isinstance(answers, list):
        synced: list[Any] = []
        for entry in answers:
            if not isinstance(entry, dict):
                synced.append(entry)
                continue
            entry_id = str(entry.get("id") or "")
            if sponsorship is not None and entry_id == "sponsorship_us":
                entry = {**entry, "answer": "Yes" if sponsorship else "No"}
            elif authorized is not None and entry_id == "work_auth_us":
                entry = {**entry, "answer": "Yes" if authorized else "No"}
            synced.append(entry)
        updated["screeningAnswers"] = synced

    return updated
