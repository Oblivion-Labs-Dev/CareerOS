"""Per-application Gmail plus-addressing for deterministic reply tracking.

Gmail delivers mail sent to `user+anything@gmail.com` straight to `user@gmail.com`,
and the `+anything` tag survives in the message headers. Tagging each application's
contact-email field with a unique, deterministic suffix lets the inbox tracker match
a recruiter reply back to the exact application it's about, instead of guessing from
subject lines / company names.

Free (no domain/mailbox purchase needed); the tradeoff is that a minority of ATS forms
reject '+' in an email address, in which case autofill should just fall back to the
plain profile email (callers already do this by checking `trackingEmail` truthiness).
"""

from __future__ import annotations

import hashlib
import re

from app.config import settings

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, max_len: int = 20) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return slug[:max_len].strip("-") or "role"


def build_tracking_email(company_name: str | None, stable_id: str) -> str | None:
    """Return `local+company-hash@domain`, or None if Gmail isn't configured.

    `stable_id` should be the application/job id so the tag stays fixed for the
    life of that application even if company_name is later edited.
    """
    gmail_user = (settings.gmail_user or "").strip()
    if "@" not in gmail_user:
        return None
    local_part, _, domain = gmail_user.partition("@")

    company_slug = _slugify(company_name or "role")
    digest = hashlib.sha1(stable_id.encode("utf-8")).hexdigest()[:6]
    tag = f"{company_slug}-{digest}"

    return f"{local_part}+{tag}@{domain}"


def extract_tag_from_address(address: str) -> str | None:
    """Pull the `+tag` out of a `local+tag@domain` address, else None."""
    local_part = address.split("@", 1)[0]
    if "+" not in local_part:
        return None
    return local_part.split("+", 1)[1].strip().lower() or None
