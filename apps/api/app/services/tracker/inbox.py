"""Fetches recruiter threads via GmailImapClient and classifies + caches them as
`email_classification` entities, keyed by IMAP UID so re-fetching is idempotent."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.store import list_entities, upsert_entity
from app.services.gmail_imap import GmailImapClient
from app.services.tracker.classification import classify_thread_async

ENTITY_TYPE = "email_classification"


async def fetch_and_classify_threads(db: Session, client: GmailImapClient, limit: int = 20) -> list[dict[str, Any]]:
    threads = client.fetch_threads(limit=limit, include_body=True)
    cached_by_uid = {entity.get("uid"): entity for entity in list_entities(db, ENTITY_TYPE)}
    results: list[dict[str, Any]] = []
    for thread in threads:
        uid = thread.get("uid")
        cached = cached_by_uid.get(uid)
        # Re-classify if we've never seen this UID, or if previous classification was uncategorized
        if cached and cached.get("subject") == thread.get("subject") and cached.get("category") and cached.get("category") != "uncategorized":
            results.append(
                {
                    **thread,
                    "category": cached.get("category"),
                    "categoryLabel": cached.get("categoryLabel"),
                    "confidence": cached.get("confidence"),
                }
            )
            continue
        classified = await classify_thread_async(thread)
        stored = upsert_entity(
            db,
            ENTITY_TYPE,
            {
                "id": f"emailclass_{uid}",
                "uid": uid,
                "subject": classified.get("subject"),
                "fromName": classified.get("fromName"),
                "fromAddress": classified.get("fromAddress"),
                "date": classified.get("date"),
                "snippet": classified.get("snippet"),
                "category": classified.get("category"),
                "categoryLabel": classified.get("categoryLabel"),
                "confidence": classified.get("confidence"),
            },
        )
        results.append(
            {
                **thread,
                "category": stored.get("category"),
                "categoryLabel": stored.get("categoryLabel"),
                "confidence": stored.get("confidence"),
            }
        )
    results.sort(key=lambda item: item.get("date") or "", reverse=True)
    return results
