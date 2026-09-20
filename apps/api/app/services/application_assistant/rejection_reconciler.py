"""Mark one submitted application rejected when its rejection email arrives.

CareerOS already reads the inbox for submission confirmations
(``manual_submission_reconciler``); rejections are the same idea run the other
direction — an employer's "unfortunately, we will not be moving forward"
lands, and the specific job it is about should move out of the "still open"
pool on its own, without the user re-reading their inbox and clicking through
every SUBMITTED card by hand.

The one rule that matters is the same one the submission reconciler already
proved out the hard way: one rejection email must never rewrite more than one
job's status. Most rejection emails name only the employer ("Thank you for
your interest in Acme"), not the specific posting, so an unrestricted match
would reject *every* open Acme application off a single email — the false
positive is worse than leaving the job alone, because it would hide a job
that is genuinely still open behind a rejection that was never sent for it.
So a rejection is only ever applied when it can be pinned to exactly one
submitted job:

* only SUBMITTED jobs are candidates — a job that never went out cannot be
  rejected;
* the email has to be newer than that job's own submission time (with a
  little slack for clock skew), so an old rejection from a previous
  application to the same employer proves nothing about this one;
* the company on the email has to match the company on the job;
* when the email names the specific role, that resolves ambiguity even with
  several open applications at the same employer; otherwise it is only
  applied when exactly one SUBMITTED job at that company is a candidate.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.store import now_iso, session_scope
from app.services.application_assistant.persistence import (
    list_autopilot_jobs,
    save_autopilot_job,
)
logger = logging.getLogger("career_os.rejection_reconciler")

RECONCILABLE_STATUSES = ("SUBMITTED",)


def _normalise(name: str) -> str:
    """Company names as they compare: lowercase, alphanumeric only — boards
    spell the same employer several ways, so punctuation cannot be part of
    the comparison. Mirrors manual_submission_reconciler's own helper."""
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


_TITLE_STOPWORDS = frozenset({
    "the", "and", "for", "at", "of", "to", "a", "an", "in", "on",
    "thank", "thanks", "you", "your", "application", "unfortunately",
    "we", "ve", "have", "interest", "position", "role", "update", "regarding",
})


def _significant_title_words(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {w for w in words if w not in _TITLE_STOPWORDS and len(w) > 1}


def _word_tokens(text: str) -> str:
    """Lowercase, space-joined word tokens — punctuation and casing gone, but
    word boundaries kept.

    ``_normalise`` (company identity comparisons) deliberately strips spaces
    too, which is safe there since both sides of that comparison are single
    company names. It is NOT safe for substring-checking a company name
    against a whole email body: despacing "our application" collapses it to
    "ourapplication", which contains "oura" as a plain substring — a real,
    already-submitted company name. Confirmed live: a genuine Samsara
    rejection got matched to a completely unrelated Oura application this
    way, because "Oura" is a substring of despaced boilerplate text that
    appears in nearly every application email. Keeping single spaces between
    words and requiring the company to appear as its own padded segment
    below closes that off.
    """
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _company_named_in(company: str, haystack: str) -> bool:
    """Whether `company` appears as a whole word/phrase in `haystack`."""
    company_tokens = _word_tokens(company)
    if not company_tokens:
        return False
    return f" {company_tokens} " in f" {_word_tokens(haystack)} "



def _title_named(title: Any, haystack: str) -> bool:
    """Whether the email names this specific role, in the subject or body."""
    title_words = _significant_title_words(str(title or ""))
    if len(title_words) < 2:
        return False
    return title_words.issubset(_significant_title_words(haystack))


def _parse_date(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _spent_rejections(jobs: list[dict[str, Any]]) -> set[str]:
    """Rejection emails already credited to some job, so a later run does not
    re-spend the same email on a second job."""
    spent: set[str] = set()
    for job in jobs:
        if job.get("status") != "REJECTED":
            continue
        uid = str((job.get("rejectionEvidence") or {}).get("uid") or "")
        if uid:
            spent.add(uid)
    return spent


def _rejection_phrases() -> tuple[str, ...]:
    """The same phrase list `classify_text` itself uses for the rejection
    category — one source of truth for what wording counts as a rejection."""
    from app.services.tracker.classification import CATEGORY_RULES

    for key, _label, tokens in CATEGORY_RULES:
        if key == "rejection":
            return tokens
    return ()


# Words that turn a rejection phrase from a real determination ("we have
# decided not to move forward") into ordinary confirmation-email boilerplate
# that merely mentions the possibility ("if you are not selected, keep an
# eye on our careers page"). Confirmed live: a plain Honeycomb "thank you for
# applying" confirmation contains exactly that sentence, and matched "not
# selected" even under a literal contiguous-substring check — the phrase is
# genuinely present, just conditionally, not as an actual decision.
_CONDITIONAL_MARKERS = ("if ", "should you", "in the event", "in case")
_CONDITIONAL_LOOKBEHIND_CHARS = 40

# "unfortunately" alone is too generic to trust — confirmed live: "replies
# will **unfortunately** not be read" (an unattended-mailbox disclaimer on an
# otherwise plain application-received email) matches it with no conditional
# marker anywhere nearby, and is not a rejection at all. Every genuine
# rejection found in this same audit paired it with one of these
# decision-confirming fragments within the same sentence or two; require one
# of them nearby instead of trusting the word on its own. The other phrases
# ("other candidates", "decided not to proceed", "not moving forward", ...)
# are already specific enough on their own — this extra check is scoped to
# "unfortunately" only.
_DECISION_CONFIRMATION_MARKERS = (
    "move forward", "moving forward", "not selected", "not proceed",
    "not to proceed", "decided", "other candidates", "not a match",
    "position has been filled", "pursue other", "unable to", "will not be",
    "no longer", "different direction", "won't be", "not able to move",
    "not the right fit", "candidacy",
)
_DECISION_CONFIRMATION_LOOKAHEAD_CHARS = 200


def _genuine_rejection_positions(text: str) -> list[int]:
    """Start indices of every rejection-phrase occurrence that is a real
    determination, not conditional boilerplate or an incidental use of
    "unfortunately". Checks every occurrence of every phrase — a genuine
    rejection often also contains an unrelated, later "if you have
    questions" sentence, so finding *a* conditional nearby does not
    disqualify the whole email, only the specific occurrence next to it."""
    positions: list[int] = []
    for phrase in _rejection_phrases():
        start = 0
        while True:
            idx = text.find(phrase, start)
            if idx == -1:
                break
            window = text[max(0, idx - _CONDITIONAL_LOOKBEHIND_CHARS):idx]
            if not any(marker in window for marker in _CONDITIONAL_MARKERS):
                if phrase == "unfortunately":
                    ahead = text[idx:idx + _DECISION_CONFIRMATION_LOOKAHEAD_CHARS]
                    if not any(m in ahead for m in _DECISION_CONFIRMATION_MARKERS):
                        start = idx + 1
                        continue
                positions.append(idx)
            start = idx + 1
    return positions


def _has_genuine_rejection_wording(text: str) -> bool:
    return bool(_genuine_rejection_positions(text))


def _fetch_rejection_threads(limit: int, window_days: int) -> list[dict[str, Any]]:
    """Emails whose body or subject contains rejection wording, searched
    across the whole `window_days` mailbox history rather than only the most
    recent `limit` messages.

    A recency-window fetch (this reconciler's first version, and what
    `GmailImapClient.fetch_threads` does generically for the tracker
    dashboard) breaks down here: Autopilot's own verification-code and
    "thank you for applying" traffic runs at high volume while a batch is
    active, so the most-recent-200-ish messages can be entirely today's
    submissions with no rejection anywhere in them — even though real,
    unread rejections from earlier in the same campaign are sitting further
    back in the mailbox. Searching IMAP `TEXT`/`SUBJECT` for the rejection
    phrases directly finds those regardless of how much confirmation traffic
    has piled up more recently. Confirmed live: a recency-window fetch of the
    200 newest recruiter-ish emails was saturated by same-day verification
    (93) and applied (73) mail, missing rejections from earlier in the week
    entirely; a body search for "unfortunately" alone found 336 matches
    mailbox-wide.
    """
    from app.config import settings
    from app.services.gmail_imap import GmailImapClient, _decode_header_value, _parse_address_list

    if not getattr(settings, "gmail_user", "") or not getattr(settings, "gmail_app_password", ""):
        return []

    since = (datetime.now(timezone.utc) - timedelta(days=window_days)).strftime("%d-%b-%Y")

    client = GmailImapClient(settings.gmail_user, settings.gmail_app_password)
    connection = client._connect()  # noqa: SLF001 — reusing the shared helpers, same pattern manual_submission_reconciler uses
    try:
        client._open_mailbox(connection)  # noqa: SLF001
        uids: set[str] = set()
        for phrase in _rejection_phrases():
            try:
                # IMAP `TEXT` search is a *candidate* filter only, not the
                # classifier — see below for why the real phrase check has to
                # happen in Python against the full body.
                status, data = connection.uid("search", None, f'(SINCE {since} TEXT "{phrase}")')
                if status == "OK" and data and data[0]:
                    uids.update(data[0].decode().split())
            except Exception:
                continue
        ordered = sorted(uids, key=int)[-limit:]
        if not ordered:
            return []

        # Fetch full raw messages ourselves rather than through `_fetch_uids`
        # + `_extract_snippet`: that snippet is text/plain-only and capped at
        # 500 chars, built for a quick dashboard preview, not for verifying a
        # specific phrase actually occurs. Two gaps that combined into a real
        # incident (2026-09-16): Gmail's IMAP `TEXT "phrase"` search is a
        # bag-of-words match, not a literal phrase search — a plain "Thank
        # you for applying" confirmation containing "...we will be in touch
        # if you are **selected**..." and, separately, "do **not** reply to
        # this email" matched a `TEXT "not selected"` search even though the
        # phrase "not selected" never actually appears anywhere in it. 110
        # ordinary confirmation emails were nearly marked as rejections this
        # way (118 were, before this fix, on the version that also had the
        # word-boundary bug above). The fix has to check the *real* body text
        # for the *literal* phrase, not trust the IMAP search result as if it
        # already had.
        import email as email_module
        import re as re_module

        threads: list[dict[str, Any]] = []
        uids_str = ",".join(ordered)
        status, data = connection.uid("fetch", uids_str, "(RFC822 UID)")
        if status != "OK" or not data:
            return []
        for item in data:
            if not isinstance(item, tuple) or len(item) < 2:
                continue
            raw = item[1]
            if not isinstance(raw, (bytes, bytearray)):
                continue
            try:
                header_str = item[0].decode(errors="replace") if isinstance(item[0], bytes) else str(item[0])
                uid_match = re_module.search(r"UID\s+(\d+)", header_str)
                item_uid = uid_match.group(1) if uid_match else ""

                msg = email_module.message_from_bytes(raw)
                subject = _decode_header_value(msg.get("Subject")) or ""
                from_name, _from_addr = _parse_address_list(msg.get("From"))
                date_raw = msg.get("Date")
                try:
                    from email.utils import parsedate_to_datetime
                    date_value = parsedate_to_datetime(date_raw).isoformat() if date_raw else ""
                except Exception:
                    date_value = ""

                body = ""
                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/plain", "text/html") and not part.get_filename():
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode(part.get_content_charset() or "utf-8", errors="replace")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        body = payload.decode(msg.get_content_charset() or "utf-8", errors="replace")

                # Strip HTML tags/entities well enough for a literal-phrase
                # check — this does not need to be a real HTML renderer, just
                # avoid a tag swallowing the space between two words that
                # would otherwise glue them together and hide a phrase.
                text_only = re_module.sub(r"<[^>]+>", " ", body)
                full_text = f"{subject} {text_only}"
                full_text_norm = " ".join(full_text.split()).lower()

                if not _has_genuine_rejection_wording(full_text_norm):
                    continue

                threads.append({
                    "uid": item_uid or "",
                    "subject": subject or "No Subject",
                    "fromName": from_name,
                    "date": date_value,
                    # Capped, but generously — this is what the title-naming
                    # check searches, and it is now real body text, not a
                    # truncated-before-the-phrase 500-char snippet.
                    "snippet": full_text_norm[:5000],
                })
            except Exception:  # noqa: BLE001
                logger.debug("skipping unparseable rejection candidate", exc_info=True)
                continue
        return threads
    finally:
        try:
            connection.logout()
        except Exception:
            pass


def reconcile_rejections(
    db: Session | None = None, *, limit: int = 1000, window_days: int = 45, dry_run: bool = False
) -> dict[str, Any]:
    """Mark exactly one SUBMITTED job REJECTED per genuine rejection email found.

    ``dry_run=True`` runs the full matching pass and reports what it would do
    without calling ``save_autopilot_job`` — for validating a change to the
    matching logic against the live inbox before trusting it to write.
    """

    def _run(session: Session) -> dict[str, Any]:
        all_jobs = list_autopilot_jobs(session)
        candidates = [
            job for job in all_jobs
            if job.get("status") in RECONCILABLE_STATUSES and job.get("company")
        ]
        if not candidates:
            return {"success": True, "checked": 0, "marked": 0, "jobs": []}

        already_spent = _spent_rejections(all_jobs)

        try:
            threads = _fetch_rejection_threads(limit, window_days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not read the inbox for rejections: %s", exc)
            return {"success": False, "reason": str(exc), "checked": len(candidates), "marked": 0, "jobs": []}

        cutoff = datetime.now(timezone.utc) - timedelta(days=window_days)
        marked: list[dict[str, str]] = []
        consumed: set[str] = set(already_spent)
        claimed: set[str] = set()

        def _eligible(job: dict[str, Any], company_key: str, sent_at: datetime) -> bool:
            if job["id"] in claimed:
                return False
            if _normalise(job.get("company")) != company_key:
                return False
            # A rejection cannot predate the submission it is rejecting.
            submitted_at = _parse_date(job.get("submittedAt"))
            if submitted_at and sent_at < submitted_at - timedelta(minutes=10):
                return False
            return True

        def _mark(job: dict[str, Any], subject: str, sent_at: datetime, uid: str, matched_on: str) -> None:
            job["previousStatus"] = job.get("status")
            job["status"] = "REJECTED"
            job["rejectedAt"] = sent_at.isoformat()
            job["rejectionEvidence"] = {
                "uid": uid,
                "subject": subject[:200],
                "matchedOn": matched_on,
                "source": "gmail",
            }
            job["updatedAt"] = now_iso()
            if not dry_run:
                save_autopilot_job(session, job)
            if uid:
                consumed.add(uid)
            claimed.add(job["id"])
            marked.append({"id": job["id"], "company": job.get("company", ""), "title": job.get("title", ""), "subject": subject[:90]})
            logger.info(
                "Marked %s (%s) rejected from its rejection email, matched on %s",
                job.get("company"), job.get("title", ""), matched_on,
            )

        usable: list[tuple[str, str, str, datetime, str]] = []
        for thread in threads:
            uid = str(thread.get("uid") or "")
            if uid and uid in consumed:
                continue
            subject = str(thread.get("subject") or "")
            snippet = str(thread.get("snippet") or "")
            # No re-classification here: `_fetch_rejection_threads` already
            # searched IMAP for these exact rejection phrases server-side, so
            # every thread it returned matched one somewhere in the message.
            # Re-running `classify_text` against just the subject and a
            # ~500-char snippet risked missing the very match that got the
            # email fetched in the first place, when the phrase sits later in
            # a longer body than the snippet covers.
            sent_at = _parse_date(thread.get("date"))
            if sent_at is None or sent_at < cutoff:
                continue
            haystack = f"{subject} {thread.get('fromName') or ''} {snippet}"
            usable.append((subject, haystack, thread.get("fromName") or "", sent_at, uid))

        # Title-named matches only — no company-only fallback. Two distinct
        # false-positive mechanisms turned up in the same company-only pass
        # during validation (2026-09-16): a despaced-substring bug ("Oura"
        # inside "our application"), and — after fixing that — a real,
        # long-enough company name ("Future") coincidentally named in an
        # unrelated employer's generic sign-off ("wish you all the best with
        # your future endeavors"), well within any character-distance window
        # short enough to still catch genuine cases in a short email. No
        # window size reliably tells a company's own use of its name apart
        # from an ordinary English word or phrase used incidentally nearby.
        # Requiring the specific role to be named — 2+ significant,
        # non-generic words matched as a set — is a categorically stronger
        # signal that does not share this failure mode, and every genuine
        # rejection found in manual audit during validation already named
        # its role. The cost is real but bounded: a rejection whose email
        # names neither the role nor anything distinctive is left
        # unreconciled rather than guessed, exactly this module's own stated
        # bar for when to stay silent.
        for subject, haystack, from_name, sent_at, uid in usable:
            if uid and uid in consumed:
                continue
            matches = [
                job for job in candidates
                if _eligible(job, _normalise(job.get("company")), sent_at)
                and _company_named_in(job.get("company") or "", haystack)
                and _title_named(job.get("title"), haystack)
            ]
            if len(matches) != 1:
                continue
            _mark(matches[0], subject, sent_at, uid, "title")

        return {"success": True, "checked": len(candidates), "marked": len(marked), "jobs": marked}

    if db is not None:
        return _run(db)
    with session_scope() as owned:
        return _run(owned)
