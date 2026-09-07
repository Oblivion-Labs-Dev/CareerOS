"""Greenhouse Email Verification Code Interceptor & Auto-Filler.

Automatically catches Greenhouse 8-character human verification codes delivered to
the candidate's Gmail inbox via IMAP and autofills them into the live Greenhouse form
to complete 100% autonomous submission.
"""

from __future__ import annotations

import asyncio
import email
import email.utils
from email.header import decode_header
import imaplib
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from dotenv import load_dotenv

# Ensure apps/api/.env is loaded
_env_path = Path(__file__).resolve().parents[2] / ".env"
if _env_path.exists():
    load_dotenv(dotenv_path=_env_path, override=False)

from app.config import settings

logger = logging.getLogger("career_os.greenhouse_verification")


def _decode_header(val: str | None) -> str:
    if not val:
        return ""
    text = ""
    for chunk, enc in decode_header(val):
        if isinstance(chunk, bytes):
            text += chunk.decode(enc or "utf-8", errors="replace")
        else:
            text += str(chunk)
    return text


def _extract_code_from_body(body: str) -> str | None:
    """Extract 8-character Greenhouse verification code from email body HTML/text."""
    # Method 1: Inside <h1> or <h2> tag directly after copy-paste prompt
    h_match = re.search(r"<h[1-3][^>]*>\s*([A-Za-z0-9]{8})\s*</h[1-3]>", body, re.IGNORECASE)
    if h_match:
        return h_match.group(1).strip()

    # Method 2: Plain text after "security code field"
    text_match = re.search(r"security code field[^\n]*\s*([A-Za-z0-9]{8})\b", body, re.IGNORECASE)
    if text_match:
        return text_match.group(1).strip()

    # Method 3: Any prominent 8-character alphanumeric string that contains both letters and numbers
    all_codes = re.findall(r"\b[A-Za-z0-9]{8}\b", body)
    stop_words = {"viewport", "intended", "received", "allowpng", "contract", "business", "ironclad", "features", "complete", "interest"}
    for c in all_codes:
        c_low = c.lower()
        if c_low not in stop_words and any(ch.isdigit() for ch in c) and any(ch.isalpha() for ch in c):
            return c

    return None


def _poll_gmail_for_code_once(
    user: str,
    app_pw: str,
    company: str,
    clean_company: str,
    since_timestamp: float,
    log_callback: Callable[[str, str], None] | None = None,
) -> str | None:
    """One synchronous IMAP poll attempt. Runs off the event loop via asyncio.to_thread —
    imaplib has no async API, and calling it directly from an async function would block
    the entire FastAPI event loop (all other requests, health checks included) for as long
    as each login/search/fetch round-trip to Gmail takes. A 10s socket timeout keeps a single
    slow/hung connection attempt from blowing past the caller's overall polling deadline.
    """
    try:
        client = imaplib.IMAP4_SSL("imap.gmail.com", timeout=10)
        try:
            client.login(user, app_pw)
            client.select("INBOX", readonly=True)

            # Search specifically for security code emails
            status, data = client.search(None, '(SUBJECT "Security code")')
            if status == "OK" and data and data[0]:
                uids = data[0].split()
                # Inspect the 5 most recent matching emails
                for uid in reversed(uids[-5:]):
                    s, msg_data = client.fetch(uid, '(RFC822)')
                    if s != "OK" or not msg_data:
                        continue
                    
                    msg = email.message_from_bytes(msg_data[0][1])
                    subject = _decode_header(msg.get("Subject", ""))
                    from_ = _decode_header(msg.get("From", ""))
                    
                    # Ensure this is a security code email
                    sub_low = subject.lower()
                    if "security code" not in sub_low and "verification code" not in sub_low:
                        continue

                    # Extract body
                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() in ("text/plain", "text/html"):
                                pl = part.get_payload(decode=True)
                                if pl:
                                    body += pl.decode(part.get_content_charset() or "utf-8", errors="replace")
                    else:
                        pl = msg.get_payload(decode=True)
                        if pl:
                            body += pl.decode(msg.get_content_charset() or "utf-8", errors="replace")

                    # Parse email date
                    date_str = msg.get("Date")
                    msg_ts = 0.0
                    if date_str:
                        try:
                            msg_ts = email.utils.parsedate_to_datetime(date_str).timestamp()
                        except Exception:
                            pass

                    # Only consider emails received around or after the start of this application
                    if msg_ts > 0 and msg_ts < (since_timestamp - 90):
                        continue

                    # Check if this email is for the target company
                    company_words = [w.lower() for w in clean_company.split() if len(w) > 2]
                    is_for_company = any(w in sub_low or w in body.lower() for w in company_words)
                    
                    # If fresh email arrived after since_timestamp - 15 and from greenhouse, accept it
                    if not is_for_company and (msg_ts >= (since_timestamp - 15) or msg_ts == 0.0) and "greenhouse" in from_.lower():
                        is_for_company = True

                    if not is_for_company:
                        continue

                    if is_for_company:
                        code = _extract_code_from_body(body)
                        if code:
                            logger.info("Found Greenhouse verification code '%s' for %s (Subject: %s)", code, company, subject)
                            if log_callback:
                                log_callback(f"Intercepted security code '{code}' from {from_} ({subject})", "info")
                            client.logout()
                            return code

            client.logout()
        except Exception:
            try:
                client.logout()
            except Exception:
                pass
    except Exception as ex:
        logger.debug("IMAP poll attempt error (will retry): %s", ex)

    return None


async def fetch_latest_greenhouse_verification_code(
    company: str,
    since_timestamp: float,
    timeout_sec: float = 45.0,
    poll_interval: float = 2.5,
    log_callback: Callable[[str, str], None] | None = None,
) -> str | None:
    """Poll Gmail IMAP for an incoming Greenhouse security code email for the target company."""
    user = os.environ.get("GMAIL_USER") or settings.gmail_user
    app_pw = os.environ.get("GMAIL_APP_PASSWORD") or settings.gmail_app_password

    if not user or not app_pw:
        logger.warning("GMAIL_USER/GMAIL_APP_PASSWORD not configured; cannot intercept verification code via IMAP.")
        return None

    deadline = time.time() + timeout_sec
    logger.info("Listening on Gmail (%s) for Greenhouse security code for %s (timeout: %.0fs)...", user, company, timeout_sec)

    clean_company = re.sub(r"[^a-zA-Z0-9 ]", "", company).strip()

    while time.time() < deadline:
        code = await asyncio.to_thread(
            _poll_gmail_for_code_once, user, app_pw, company, clean_company, since_timestamp, log_callback
        )
        if code:
            return code
        await asyncio.sleep(poll_interval)

    logger.warning("Timed out waiting for Greenhouse verification code for %s", company)
    return None


async def handle_greenhouse_verification_flow(
    page: Any,
    target_frame: Any,
    company: str,
    candidate_email: str,
    timeout_sec: float = 45.0,
    log_callback: Callable[[str, str], None] | None = None,
) -> bool:
    """Detect if Greenhouse 8-character verification modal is active, fetch code via Gmail IMAP, and submit."""
    # Check if page has verification code prompt. Greenhouse's application form
    # (and this modal) usually render inside an embedded iframe rather than the
    # top-level document, so the top-level page body alone won't contain the
    # prompt text — check target_frame first, falling back to the page.
    def _has_prompt(text: str) -> bool:
        low = text.lower()
        return (
            "verification code was sent to" in low
            or "enter the 8-character code" in low
            or "security code" in low
        )

    page_text = ""
    has_verification_prompt = False
    for scope_candidate in (target_frame, page):
        if scope_candidate is None:
            continue
        try:
            candidate_text = await scope_candidate.inner_text("body")
        except Exception:
            continue
        if _has_prompt(candidate_text):
            page_text = candidate_text
            has_verification_prompt = True
            break

    if not has_verification_prompt:
        return False

    logger.info("Greenhouse security code prompt detected on page. Initiating automatic email code interception...")
    if log_callback:
        log_callback(f"Greenhouse verification modal detected. Polling {candidate_email} for 8-character security code...", "info")

    start_time = time.time()
    code = await fetch_latest_greenhouse_verification_code(
        company=company,
        since_timestamp=start_time,
        timeout_sec=timeout_sec,
        log_callback=log_callback,
    )

    if not code or len(code) != 8:
        logger.error("Could not obtain valid 8-character code (got: %s)", code)
        if log_callback:
            log_callback(f"Failed to obtain 8-character security code from email for {company}", "error")
        return False

    logger.info("Filling verification code '%s' into Greenhouse form...", code)
    if log_callback:
        log_callback(f"Autofilling 8-character security code [{code}] into Greenhouse form...", "info")

    # Greenhouse renders 8 individual single-character input boxes or 1 main input box
    # Let's check target_frame and page
    scope = target_frame or page
    
    # 1. Try single/multi input matching
    inputs = scope.locator('input[name*="code" i], input[id*="code" i], input[maxlength="1"], input[autocomplete="one-time-code"], .security-code input')
    input_count = await inputs.count()
    
    if input_count == 0:
        # Fallback to page level
        inputs = page.locator('input[name*="code" i], input[id*="code" i], input[maxlength="1"], input[autocomplete="one-time-code"], .security-code input')
        input_count = await inputs.count()

    if input_count >= 8:
        # 8 individual single-character inputs
        for i in range(8):
            el = inputs.nth(i)
            try:
                await el.click(force=True)
                await el.fill(code[i])
                await asyncio.sleep(0.05)
            except Exception as ex:
                logger.warning("Error filling char %d into code input: %s", i, ex)
    elif input_count > 0:
        # Single input field for full code
        first_input = inputs.first
        await first_input.click(force=True)
        await first_input.fill(code)
    else:
        logger.warning("No code input boxes found directly, attempting keyboard typing on focused element")
        await page.keyboard.type(code)

    await asyncio.sleep(0.5)

    # Click Submit / Confirm button on verification prompt
    submit_buttons = [
        'button[data-qa="btn-submit"]',
        'button[type="submit"]:has-text("Submit")',
        'button:has-text("Submit application")',
        'button:has-text("Submit Application")',
        'button:has-text("Confirm")',
        'button:has-text("Verify")',
        'input[type="submit"]',
        '#submit_app',
    ]

    clicked = False
    for sel in submit_buttons:
        btn = scope.locator(sel).first
        if await btn.count() > 0 and await btn.is_visible():
            logger.info("Clicking verification submit button: %s", sel)
            await btn.click()
            clicked = True
            break

    if not clicked:
        for sel in submit_buttons:
            btn = page.locator(sel).first
            if await btn.count() > 0 and await btn.is_visible():
                logger.info("Clicking page-level verification submit button: %s", sel)
                await btn.click()
                clicked = True
                break

    if log_callback:
        log_callback(f"Submitted 8-character verification code for {company}. Waiting for confirmation...", "info")

    await asyncio.sleep(4.0)
    try:
        await page.wait_for_load_state("networkidle", timeout=10000)
    except Exception:
        pass

    return True
